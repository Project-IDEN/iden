import { ArrowDown, ArrowLeft, ArrowRight, ArrowUp, Camera, ScanFace } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { Button } from "./button";
import {
  guidedCapture,
  StepTimeout,
  timedCapture,
  type Guide,
  type Phase,
} from "./capture-sequence";
import { cn } from "./cn";
import type { HeadTracker } from "./head-tracker";

/**
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

type CameraState = "starting" | "denied" | "ready" | "capturing";
// Settled means loaded or failed: a capture started before then would be timed
// for no reason.
type TrackerState = "loading" | "settled";

export function FaceCapture({
  challenge,
  onCaptured,
  trackerFiles,
  startLabel = "Start",
}: {
  challenge: FaceCaptureChallenge;
  onCaptured: (frames: Blob[]) => void;
  /** Where the app serves the head tracker's runtime and model. */
  trackerFiles: string;
  startLabel?: string;
}) {
  const video = useRef<HTMLVideoElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const tracker = useRef<HeadTracker | null>(null);
  const [camera, setCamera] = useState<CameraState>(() =>
    navigator.mediaDevices ? "starting" : "denied",
  );
  const [tracking, setTracking] = useState<TrackerState>("loading");
  const [prompt, setPrompt] = useState<string>("Centre your face in the oval.");
  const [icon, setIcon] = useState<ReactNode>(<ScanFace />);
  const [progress, setProgress] = useState<number | null>(null);

  useEffect(() => {
    let stream: MediaStream | undefined;
    let cancelled = false;
    // Absent outside a secure context: http on anything but localhost.
    if (!navigator.mediaDevices) return;
    navigator.mediaDevices
      .getUserMedia({
        video: { facingMode: "user", width: { ideal: WIDTH }, height: { ideal: HEIGHT } },
        audio: false,
      })
      .then((media) => {
        if (cancelled) return media.getTracks().forEach((track) => track.stop());
        stream = media;
        if (video.current) video.current.srcObject = media;
        setCamera("ready");
      })
      .catch(() => setCamera("denied"));
    return () => {
      cancelled = true;
      stream?.getTracks().forEach((track) => track.stop());
    };
  }, []);

  const cameraReady = camera === "ready" || camera === "capturing";
  useEffect(() => {
    const source = video.current;
    if (!cameraReady || !source) return;
    let cancelled = false;
    // Imported here, not at the top: MediaPipe is most of a megabyte of
    // script, and only the face step needs it.
    import("./head-tracker")
      .then(({ trackHead }) => trackHead(source, trackerFiles))
      .then((started) => {
        if (cancelled) return started.stop();
        tracker.current = started;
      })
      .catch(() => undefined)
      .finally(() => setTracking("settled"));
    return () => {
      cancelled = true;
      tracker.current?.stop();
      tracker.current = null;
    };
  }, [cameraReady, trackerFiles]);

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
  }, []);

  async function run() {
    setCamera("capturing");
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
      setCamera("ready");
      setProgress(null);
      setIcon(<Camera />);
      if (!(error instanceof StepTimeout)) {
        // The camera went away mid-capture: unplugged, or taken by another program.
        setPrompt("The camera stopped. Check it is connected, then start again.");
      } else if (error.step === "center") {
        setPrompt("We couldn't see your face. Centre it in the oval, then start again.");
      } else {
        setPrompt("We didn't see that movement. Start again, and go until the bar fills.");
      }
      return;
    }
    setPrompt("Checking…");
    onCaptured(frames);
  }

  if (camera === "denied") {
    return (
      <p role="alert" className="text-body-sm text-error">
        The camera is unavailable. Allow camera access for this page in your browser, or use another
        way to sign in.
      </p>
    );
  }

  const starting = camera === "starting" || tracking === "loading";
  return (
    <div className="flex flex-col items-center gap-5">
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
            className={cn(
              "stroke-white/70",
              camera === "capturing" && "animate-pulse stroke-primary",
            )}
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

      {progress !== null ? (
        <div
          role="progressbar"
          aria-label="How far you have turned"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round(progress * 100)}
          className="h-2 w-full max-w-xs overflow-hidden rounded-full bg-surface-card"
        >
          <div
            className="h-full rounded-full bg-primary transition-[width] duration-100"
            style={{ width: `${progress * 100}%` }}
          />
        </div>
      ) : null}

      {camera !== "capturing" ? (
        <>
          <p className="text-caption text-muted-foreground">
            A few seconds. You'll be asked to turn or tilt your head twice: go until the bar fills,
            then hold it there.
          </p>
          <Button
            variant="default"
            className="self-stretch"
            disabled={starting}
            onClick={() => void run()}
          >
            {starting ? "Starting the camera…" : startLabel}
          </Button>
        </>
      ) : null}
    </div>
  );
}
