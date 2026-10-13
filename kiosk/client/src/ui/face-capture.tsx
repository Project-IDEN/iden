import { ArrowDown, ArrowLeft, ArrowRight, ArrowUp, Camera, ScanFace } from "lucide-react";
import { useCallback, useRef, useState, type ReactNode } from "react";
import { cn } from "./cn";
import { useCamera } from "./use-camera";

/**
 * A copy of web/shared/ui/face-capture.tsx, which auth-ui uses for sign-in, with
 * a kiosk-sized button. Both follow the provider's challenge format; change
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
  className,
}: {
  challenge: FaceCaptureChallenge;
  onCaptured: (frames: Blob[]) => void;
  startLabel?: string;
  /** Part of the camera's name, to choose one of several. */
  camera?: string | null;
  className?: string;
}) {
  const { video, status } = useCamera(prefer);
  const canvas = useRef<HTMLCanvasElement>(null);
  const [capturing, setCapturing] = useState(false);
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
    const frames: Blob[] = [];
    try {
      for (const { step, count } of groups(challenge.steps)) {
        if (step.startsWith("flash:")) {
          setPrompt("Keep still while the screen changes colour.");
          setIcon(<Camera />);
          setFlash(FLASH[step.slice("flash:".length)] ?? null);
          // Exposed under the colour, captured before the camera's white balance
          // has time to cancel it out.
          await wait(challenge.flashSlotMs * 0.6);
          frames.push(await frame());
          await wait(challenge.flashSlotMs * 0.4);
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
          await wait(FRAME_GAP_MS[kind]);
        }
      }
    } finally {
      setFlash(null);
    }
    setPrompt("Checking…");
    onCaptured(frames);
  }

  if (status === "denied") {
    return (
      <p role="alert" className="text-body-sm text-error">
        The camera is unavailable. Allow camera access for this page in your browser, or use another
        way to sign in.
      </p>
    );
  }

  return (
    <div className={cn("flex flex-col items-center gap-5", className)}>
      {flash ? (
        <div aria-hidden="true" className="fixed inset-0 z-50" style={{ backgroundColor: flash }} />
      ) : null}

      <div className="relative aspect-[4/3] w-full overflow-hidden rounded-lg bg-surface-dark">
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
            strokeWidth="2"
            className={cn("stroke-white/70", capturing && "animate-pulse stroke-primary")}
          />
        </svg>
        <canvas ref={canvas} className="hidden" />
      </div>

      <p
        aria-live="assertive"
        className="flex min-h-6 items-center gap-2 text-body-md text-ink [&_svg]:h-5 [&_svg]:w-5"
      >
        {icon}
        {prompt}
      </p>

      {!capturing ? (
        <>
          <p className="text-caption text-muted-foreground">
            About ten seconds. You'll be asked to move your head, and the screen will change colour
            a few times.
          </p>
          <button
            type="button"
            className="min-h-16 self-stretch rounded-lg bg-primary px-8 text-title-lg text-on-primary active:bg-primary-active disabled:opacity-50"
            disabled={status !== "ready"}
            onClick={() => void run()}
          >
            {status === "starting" ? "Starting the camera…" : startLabel}
          </button>
        </>
      ) : null}
    </div>
  );
}
