import { ArrowDown, ArrowLeft, ArrowRight, ArrowUp, Camera, ScanFace } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import {
  guidedCapture,
  StepTimeout,
  timedCapture,
  type Guide,
  type Phase,
} from "./capture-sequence";
import { cn } from "./cn";
import type { HeadTracker } from "./head-tracker";
import { useCamera } from "./use-camera";

/**
 * A copy of web/shared/ui/face-capture.tsx, which auth-ui uses for sign-in, with
 * a kiosk-sized button, a camera chosen by name, and kiosk wording. Both follow
 * the provider's challenge format; change them together.
 *
 * A face capture that follows the provider's challenge, frame by frame.
 *
 * The provider sends one step per frame: `center` (look straight ahead) or a
 * head movement. The movements are drawn at random for every attempt, which is
 * what makes a recording made earlier useless — so the order here is the order
 * sent, never a fixed script.
 *
 * Frames are captured from the camera as it sees, unmirrored; only the preview
 * is mirrored, because people expect a mirror. "Turn to your left" therefore
 * means the person's own left, and the provider measures it that way.
 */

export interface FaceCaptureChallenge {
  faceChallengeId: string;
  steps: string[];
}

const WIDTH = 640;
const HEIGHT = 480;
// Built into the image beside the page by scripts/fetch-tracker.mjs.
const TRACKER_FILES = `${import.meta.env.BASE_URL}tracker`;

const MOVES: Record<string, { label: string; icon: ReactNode }> = {
  turn_left: { label: "Slowly turn your head to your left", icon: <ArrowLeft /> },
  turn_right: { label: "Slowly turn your head to your right", icon: <ArrowRight /> },
  look_up: { label: "Tilt your head up", icon: <ArrowUp /> },
  look_down: { label: "Tilt your head down", icon: <ArrowDown /> },
};

function describe({ name, step }: Phase): { prompt: string; icon: ReactNode } {
  const move = MOVES[step];
  if (name === "recentre") return { prompt: "Face the camera again.", icon: <ScanFace /> };
  if (name === "hold" && move) return { prompt: "Hold it there.", icon: move.icon };
  if (move) return { prompt: `${move.label}.`, icon: move.icon };
  return { prompt: "Look straight at the camera.", icon: <ScanFace /> };
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
  const tracker = useRef<HeadTracker | null>(null);
  // Settled means loaded or failed: a capture started before then would be
  // timed for no reason.
  const [trackerSettled, setTrackerSettled] = useState(false);
  const [capturing, setCapturing] = useState(false);
  const [prompt, setPrompt] = useState<string>("Centre your face in the oval.");
  const [icon, setIcon] = useState<ReactNode>(<ScanFace />);
  const [progress, setProgress] = useState<number | null>(null);

  useEffect(() => {
    const source = video.current;
    if (status !== "ready" || !source) return;
    let cancelled = false;
    // Imported here, not at the top: MediaPipe is most of a megabyte of
    // script, and only a capture needs it.
    import("./head-tracker")
      .then(({ trackHead }) => trackHead(source, TRACKER_FILES))
      .then((started) => {
        if (cancelled) return started.stop();
        tracker.current = started;
      })
      .catch(() => undefined)
      .finally(() => setTrackerSettled(true));
    return () => {
      cancelled = true;
      tracker.current?.stop();
      tracker.current = null;
    };
  }, [status, video]);

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
    const frames: Blob[] = [];
    const guide: Guide = {
      phase: (phase) => {
        const shown = describe(phase);
        setPrompt(shown.prompt);
        setIcon(shown.icon);
      },
      progress: setProgress,
      take: async () => {
        frames.push(await frame());
      },
    };
    try {
      if (tracker.current) await guidedCapture(challenge.steps, tracker.current, guide);
      else await timedCapture(challenge.steps, guide);
    } catch (error) {
      setCapturing(false);
      setProgress(null);
      setIcon(<Camera />);
      if (!(error instanceof StepTimeout)) {
        // The camera went away mid-capture: unplugged, or taken by another program.
        setPrompt("The camera stopped. Check it is connected, then start again.");
      } else if (error.step === "center") {
        setPrompt("We couldn't see your face. Stand in the oval, then start again.");
      } else {
        setPrompt("We didn't see that movement. Start again, and go until the bar fills.");
      }
      return;
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
          progress !== null ? (
            <div
              role="progressbar"
              aria-label="How far you have turned"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={Math.round(progress * 100)}
              className="h-3 w-full max-w-sm overflow-hidden rounded-full bg-surface-card"
            >
              <div
                className="h-full rounded-full bg-primary transition-[width] duration-100"
                style={{ width: `${progress * 100}%` }}
              />
            </div>
          ) : null
        ) : (
          <p className="max-w-md text-title-md text-body short:text-body-md">
            Stand about an arm's length away. You'll be asked to turn or tilt your head twice: go
            until the bar fills, then hold it there.
          </p>
        )}

        <div className="flex flex-wrap gap-4 short:gap-3 portrait:justify-center">
          {!capturing ? (
            <button
              type="button"
              className={cn(buttonClass, "bg-primary text-on-primary active:bg-primary-active")}
              disabled={status !== "ready" || !trackerSettled}
              onClick={() => void run()}
            >
              {status === "ready" && trackerSettled ? startLabel : "Starting the camera…"}
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
