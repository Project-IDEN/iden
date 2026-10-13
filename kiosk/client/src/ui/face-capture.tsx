import { ArrowDown, ArrowLeft, ArrowRight, ArrowUp, Camera, ScanFace } from "lucide-react";
import { useCallback, useRef, useState, type ReactNode } from "react";
import { cn } from "./cn";
import { useCamera } from "./use-camera";

/**
 * A copy of web/shared/ui/face-capture.tsx, which auth-ui uses for sign-in, with
 * a kiosk-sized button, a camera chosen by name, and kiosk wording. Both follow the provider's challenge format; change
 * them together.
 *
 * A face capture that follows the provider's challenge, frame by frame.
 *
 * The provider sends one step per frame: `center` (look straight ahead), a head
 * movement, or `flash:<colour>` (fill the screen with that colour). Movements and
 * colours are drawn at random for every attempt, which is what makes a
 * recording made earlier useless — so the order here is the order sent, never
 * a fixed script.
 *
 * Frames are captured from the camera as it sees, unmirrored; only the preview
 * is mirrored, because people expect a mirror. "Turn to your left" therefore
 * means the person's own left, and the provider measures it that way.
 */

export interface FaceCaptureChallenge {
  faceChallengeId: string;
  steps: string[];
  flashSlotMs: number;
}

const WIDTH = 640;
const HEIGHT = 480;
// Time to read a prompt and move before frames are taken, and between frames.
const SETTLE_MS = { center: 900, action: 1300 } as const;
const FRAME_GAP_MS = { center: 220, action: 260 } as const;

const FLASH: Record<string, string> = { red: "#ff0000", green: "#00ff00", blue: "#0000ff" };

const ACTIONS: Record<string, { label: string; icon: ReactNode }> = {
  turn_left: { label: "Slowly turn your head to your left", icon: <ArrowLeft /> },
  turn_right: { label: "Slowly turn your head to your right", icon: <ArrowRight /> },
  look_up: { label: "Tilt your head up", icon: <ArrowUp /> },
  look_down: { label: "Tilt your head down", icon: <ArrowDown /> },
};

const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

// A flash frame must have been *taken* while the colour was on screen. A fixed
// delay is not enough: through Chromium a USB webcam can run a quarter of a
// second or more behind the screen, and a frame still showing the previous
// colour fails the check every time — the colours never repeat back to back.
// So the capture waits for the first frame the camera exposed after the colour
// was painted, by the capture time Chromium reports for each frame.
const EXPOSURE_MARGIN_MS = 40;
// When the browser reports no capture time, how far the camera is assumed to lag.
const FALLBACK_LAG_MS = 300;
const FRAME_TIMEOUT_MS = 2000;

/** The time the screen has shown whatever was just rendered. */
const painted = () =>
  new Promise<number>((resolve) =>
    requestAnimationFrame(() => requestAnimationFrame(() => resolve(performance.now()))),
  );

/** Resolves once the video shows a frame the camera took at or after `since`. */
function frameTakenAfter(video: HTMLVideoElement, since: number): Promise<void> {
  return new Promise((resolve) => {
    const timeout = setTimeout(resolve, FRAME_TIMEOUT_MS);
    const check: VideoFrameRequestCallback = (now, metadata) => {
      const reported = metadata.captureTime;
      const taken =
        reported !== undefined && Math.abs(now - reported) < 1000
          ? reported
          : now - FALLBACK_LAG_MS;
      if (taken >= since) {
        clearTimeout(timeout);
        resolve();
      } else {
        video.requestVideoFrameCallback(check);
      }
    };
    video.requestVideoFrameCallback(check);
  });
}

/** Consecutive identical steps, so a prompt is shown once for its frames. */
function groups(steps: string[]): { step: string; count: number }[] {
  return steps.reduce<{ step: string; count: number }[]>((out, step) => {
    const last = out.at(-1);
    if (last && last.step === step && !step.startsWith("flash:")) last.count += 1;
    else out.push({ step, count: 1 });
    return out;
  }, []);
}

export function FaceCapture({
  challenge,
  onCaptured,
  startLabel = "Start",
  camera: prefer,
  onCancel,
  className,
}: {
  challenge: FaceCaptureChallenge;
  onCaptured: (frames: Blob[]) => void;
  startLabel?: string;
  /** Part of the camera's name, to choose one of several. */
  camera?: string | null;
  onCancel?: () => void;
  className?: string;
}) {
  const { video, status } = useCamera(prefer);
  const canvas = useRef<HTMLCanvasElement>(null);
  const [capturing, setCapturing] = useState(false);
  const [taken, setTaken] = useState(0);
  const [prompt, setPrompt] = useState<string>("Centre your face in the oval.");
  const [icon, setIcon] = useState<ReactNode>(<ScanFace />);
  const [flash, setFlash] = useState<string | null>(null);

  const frame = useCallback(async (): Promise<Blob> => {
    const source = video.current;
    const target = canvas.current;
    if (!source || !target) throw new Error("The camera is not ready.");
    target.width = source.videoWidth || WIDTH;
    target.height = source.videoHeight || HEIGHT;
    target.getContext("2d")?.drawImage(source, 0, 0, target.width, target.height);
    return new Promise((resolve, reject) =>
      target.toBlob(
        (blob) => (blob ? resolve(blob) : reject(new Error("Could not capture a frame."))),
        "image/jpeg",
        0.85,
      ),
    );
  }, [video]);

  async function run() {
    setCapturing(true);
    setTaken(0);
    const frames: Blob[] = [];
    try {
      for (const { step, count } of groups(challenge.steps)) {
        if (step.startsWith("flash:")) {
          setPrompt("Keep still while the screen changes colour.");
          setIcon(<Camera />);
          setFlash(FLASH[step.slice("flash:".length)] ?? null);
          const shown = await painted();
          const source = video.current;
          if (!source) throw new Error("The camera is not ready.");
          // Under the colour, and soon after it appeared: before the camera's
          // automatic white balance, if any, has time to cancel it out.
          await Promise.all([
            frameTakenAfter(source, shown + EXPOSURE_MARGIN_MS),
            wait(challenge.flashSlotMs * 0.6),
          ]);
          frames.push(await frame());
          setTaken(frames.length);
          continue;
        }

        setFlash(null);
        const action = ACTIONS[step];
        const kind = action ? "action" : "center";
        setPrompt(action?.label ?? "Look straight at the camera.");
        setIcon(action?.icon ?? <ScanFace />);
        await wait(SETTLE_MS[kind]);
        for (let i = 0; i < count; i += 1) {
          frames.push(await frame());
          setTaken(frames.length);
          await wait(FRAME_GAP_MS[kind]);
        }
      }
    } catch {
      // The camera went away mid-capture: unplugged, or taken by another program.
      setCapturing(false);
      setPrompt("The camera stopped. Check it is connected, then start again.");
      setIcon(<Camera />);
      return;
    } finally {
      setFlash(null);
    }
    setPrompt("Checking…");
    onCaptured(frames);
  }

  const buttonClass =
    "inline-flex min-h-16 min-w-36 items-center justify-center rounded-lg px-8 text-title-lg transition-colors disabled:opacity-50 short:min-h-14 short:min-w-32 short:px-6 short:text-title-md";

  return (
    <div
      className={cn(
        "grid grid-cols-[minmax(0,1fr)_auto] content-center items-center gap-10 text-left portrait:grid-cols-1 portrait:justify-items-center portrait:text-center short:gap-6",
        className,
      )}
    >
      {flash ? (
        <div aria-hidden="true" className="fixed inset-0 z-50" style={{ backgroundColor: flash }} />
      ) : null}

      <div className="flex flex-col gap-6 short:gap-3 portrait:items-center">
        {status === "denied" ? (
          <p role="alert" className="font-display text-display-sm text-error">
            The camera is not working. Ask staff for help.
          </p>
        ) : (
          <p
            aria-live="assertive"
            className="flex items-center gap-4 font-display text-display-md text-ink short:text-display-sm [&_svg]:h-9 [&_svg]:w-9 [&_svg]:shrink-0 [&_svg]:text-primary short:[&_svg]:h-7 short:[&_svg]:w-7"
          >
            {icon}
            {prompt}
          </p>
        )}

        {capturing ? (
          <div
            role="progressbar"
            aria-label="Capture progress"
            aria-valuemin={0}
            aria-valuemax={challenge.steps.length}
            aria-valuenow={taken}
            className="h-2 w-full max-w-sm overflow-hidden rounded-full bg-surface-card"
          >
            <div
              className="h-full rounded-full bg-primary transition-[width] duration-300"
              style={{ width: `${(taken / challenge.steps.length) * 100}%` }}
            />
          </div>
        ) : (
          <p className="max-w-md text-title-md text-body short:text-body-md">
            Stand about an arm's length away. It takes about ten seconds: you'll be asked to move
            your head, and the screen will change colour a few times.
          </p>
        )}

        <div className="flex flex-wrap gap-4 short:gap-3 portrait:justify-center">
          {!capturing ? (
            <button
              type="button"
              className={cn(buttonClass, "bg-primary text-on-primary active:bg-primary-active")}
              disabled={status !== "ready"}
              onClick={() => void run()}
            >
              {status === "starting" ? "Starting the camera…" : startLabel}
            </button>
          ) : null}
          {onCancel ? (
            <button
              type="button"
              className={cn(buttonClass, "bg-surface-card text-ink active:bg-surface-cream-strong")}
              onClick={onCancel}
            >
              Cancel
            </button>
          ) : null}
        </div>
      </div>

      <div className="relative aspect-[4/3] h-[min(62dvh,30rem)] max-w-full overflow-hidden rounded-xl bg-surface-dark portrait:order-first portrait:h-auto portrait:w-full">
        <video
          ref={video}
          autoPlay
          playsInline
          muted
          className="h-full w-full -scale-x-100 object-cover"
        />
        <svg
          aria-hidden="true"
          viewBox="0 0 400 300"
          className="pointer-events-none absolute inset-0 h-full w-full"
        >
          <defs>
            <mask id="face-oval">
              <rect width="400" height="300" fill="white" />
              <ellipse cx="200" cy="145" rx="88" ry="115" fill="black" />
            </mask>
          </defs>
          <rect width="400" height="300" fill="rgba(20,20,19,0.55)" mask="url(#face-oval)" />
          <ellipse
            cx="200"
            cy="145"
            rx="88"
            ry="115"
            fill="none"
            strokeWidth="2.5"
            className={cn(capturing ? "animate-pulse stroke-primary" : "stroke-white/70")}
          />
        </svg>
        <canvas ref={canvas} className="hidden" />
      </div>
    </div>
  );
}
