import { Camera, ScanFace } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Button } from "./button";
import { cn } from "./cn";

/**
 * The face step of sign-in: a few frames looking straight at the camera.
 *
 * Sign-in asks for no head movements — the provider's challenge for it is all
 * `center` — so its liveness is the passive anti-spoofing model alone. The
 * movements are for enrolment at a kiosk, which happens once.
 */

export interface FaceCaptureChallenge {
  faceChallengeId: string;
  steps: string[];
}

const WIDTH = 640;
const HEIGHT = 480;
// Time to settle in front of the camera, then between frames.
const SETTLE_MS = 900;
const FRAME_GAP_MS = 220;

type CameraState = "starting" | "denied" | "ready" | "capturing";

const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

export function FaceCapture({
  challenge,
  onCaptured,
  startLabel = "Start",
}: {
  challenge: FaceCaptureChallenge;
  onCaptured: (frames: Blob[]) => void;
  startLabel?: string;
}) {
  const video = useRef<HTMLVideoElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const [camera, setCamera] = useState<CameraState>(() =>
    navigator.mediaDevices ? "starting" : "denied",
  );
  const [failed, setFailed] = useState(false);

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

  function frame(): Promise<Blob> {
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
  }

  async function run() {
    setCamera("capturing");
    setFailed(false);
    const frames: Blob[] = [];
    try {
      await wait(SETTLE_MS);
      for (let i = 0; i < challenge.steps.length; i += 1) {
        frames.push(await frame());
        await wait(FRAME_GAP_MS);
      }
    } catch {
      // The camera went away mid-capture: unplugged, or taken by another program.
      setCamera("ready");
      setFailed(true);
      return;
    }
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

  const capturing = camera === "capturing";
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
            className={cn("stroke-white/70", capturing && "animate-pulse stroke-primary")}
          />
        </svg>
        <canvas ref={canvas} className="hidden" />
      </div>

      <p
        aria-live="assertive"
        className="flex min-h-6 items-center gap-2 text-body-md text-ink [&_svg]:h-5 [&_svg]:w-5"
      >
        {failed ? <Camera /> : <ScanFace />}
        {failed
          ? "The camera stopped. Check it is connected, then start again."
          : capturing
            ? "Hold still and look at the camera."
            : "Centre your face in the oval."}
      </p>

      {!capturing ? (
        <>
          <p className="text-caption text-muted-foreground">
            Takes about two seconds. Look straight at the camera and keep still.
          </p>
          <Button
            variant="default"
            className="self-stretch"
            disabled={camera === "starting"}
            onClick={() => void run()}
          >
            {camera === "starting" ? "Starting the camera…" : startLabel}
          </Button>
        </>
      ) : null}
    </div>
  );
}
