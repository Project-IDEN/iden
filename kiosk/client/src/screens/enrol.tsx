import { describeCaptureProblems } from "../ui/capture-problems";
import { FaceCapture } from "../ui/face-capture";
import { useCamera } from "../ui/use-camera";
import { ArrowLeft, CircleAlert, CircleCheck, LoaderCircle, QrCode } from "lucide-react";
import { useCallback, useEffect, useState, type ReactNode } from "react";
import {
  KioskError,
  enrol,
  reportCamera,
  startEnrolment,
  type EnrolmentChallenge,
  type KioskState,
} from "../api";
import { useIdle } from "../hooks/use-idle";
import { useQrScanner } from "../hooks/use-qr-scanner";
import { CameraView } from "./camera-view";
import { Idle } from "./idle";
import { BigButton, Lede, Screen, Title } from "./layout";

type Phase =
  | { kind: "idle" }
  | { kind: "welcome" }
  | { kind: "starting" }
  | { kind: "confirm"; ticket: string; challenge: EnrolmentChallenge }
  | { kind: "capture"; ticket: string; challenge: EnrolmentChallenge }
  | { kind: "checking"; name: string }
  | { kind: "done"; name: string }
  | { kind: "problem"; title: string; lines: string[]; retry?: { ticket: string; left: number } };

const DONE_SECONDS = 8;
const MAX_TICKET = 512;

/**
 * One person's visit: touch the idle screen, show the QR code from the
 * dashboard, confirm the name, follow the capture, hear the result. Every way
 * out — a result, Not me, Back, or nobody touching the screen for the kiosk's
 * idle time — returns to the idle screen, with the camera off and nothing of
 * the person kept.
 */
export function Enrolment({ state }: { state: KioskState }) {
  const [phase, setPhase] = useState<Phase>({ kind: "idle" });
  const reset = useCallback(() => setPhase({ kind: "idle" }), []);
  const settings = state.settings;

  useIdle(phase.kind !== "idle" && phase.kind !== "checking", settings.idleSeconds ?? 90, reset);

  useEffect(() => {
    if (phase.kind !== "done") return;
    const timer = setTimeout(reset, DONE_SECONDS * 1000);
    return () => clearTimeout(timer);
  }, [phase, reset]);

  async function begin(ticket: string, confirm: boolean) {
    setPhase({ kind: "starting" });
    try {
      const challenge = await startEnrolment(ticket);
      setPhase({ kind: confirm ? "confirm" : "capture", ticket, challenge });
    } catch (error) {
      setPhase(explain(error));
    }
  }

  async function submit(ticket: string, challenge: EnrolmentChallenge, frames: Blob[]) {
    setPhase({ kind: "checking", name: challenge.displayName });
    try {
      await enrol(ticket, challenge.faceChallengeId, frames);
      setPhase({ kind: "done", name: challenge.displayName });
    } catch (error) {
      setPhase(explain(error, { ticket, left: challenge.attemptsLeft }));
    }
  }

  const footer = settings.notice || state.location;

  switch (phase.kind) {
    case "idle":
      return <Idle state={state} onStart={() => setPhase({ kind: "welcome" })} />;

    case "welcome":
    case "starting":
      return (
        <Welcome
          name={state.name}
          footer={footer}
          camera={settings.cameraLabel}
          busy={phase.kind === "starting"}
          onTicket={(ticket) => void begin(ticket, true)}
          onBack={reset}
        />
      );

    case "confirm":
      return (
        <Screen name={state.name} footer={footer}>
          <Lede>Enrolling the face of</Lede>
          <p className="font-display text-display-xl text-ink short:text-display-lg">
            {phase.challenge.displayName}
          </p>
          <Lede>Is this you?</Lede>
          <div className="flex gap-4">
            <BigButton onClick={() => setPhase({ ...phase, kind: "capture" })}>
              Yes, start
            </BigButton>
            <BigButton variant="quiet" onClick={reset}>
              No, that's not me
            </BigButton>
          </div>
        </Screen>
      );

    case "capture":
      return (
        <Screen name={state.name} className="gap-4 short:gap-2">
          <FaceCapture
            className="w-full"
            challenge={phase.challenge}
            camera={settings.cameraLabel}
            onCaptured={(frames) => void submit(phase.ticket, phase.challenge, frames)}
            onCancel={reset}
          />
        </Screen>
      );

    case "checking":
      return (
        <Screen name={state.name}>
          <LoaderCircle aria-hidden="true" className="h-16 w-16 animate-spin text-primary" />
          <Title>Checking your capture</Title>
          <Lede>This takes a few seconds. Please stay here.</Lede>
        </Screen>
      );

    case "done":
      return (
        <Screen name={state.name}>
          <CircleCheck
            aria-hidden="true"
            className="h-20 w-20 text-success short:h-14 short:w-14"
          />
          <Title>You're enrolled, {phase.name}</Title>
          <Lede>
            You can now use your face as a second step when you sign in. We've emailed you to
            confirm.
          </Lede>
          <BigButton onClick={reset}>Finish</BigButton>
        </Screen>
      );

    case "problem":
      return (
        <Screen name={state.name} footer={footer}>
          <CircleAlert
            aria-hidden="true"
            className="h-16 w-16 text-accent-amber short:h-12 short:w-12"
          />
          <Title>{phase.title}</Title>
          <div className="flex flex-col gap-2">
            {phase.lines.map((line) => (
              <Lede key={line}>{line}</Lede>
            ))}
          </div>
          <div className="flex gap-4">
            {phase.retry && phase.retry.left > 0 ? (
              <BigButton onClick={() => void begin(phase.retry?.ticket ?? "", false)}>
                Try again ({phase.retry.left} left)
              </BigButton>
            ) : null}
            <BigButton variant="quiet" onClick={reset}>
              Finish
            </BigButton>
          </div>
        </Screen>
      );
  }
}

function Welcome({
  name,
  footer,
  camera,
  busy,
  onTicket,
  onBack,
}: {
  name: string | null;
  footer: ReactNode;
  camera: string | null | undefined;
  busy: boolean;
  onTicket: (ticket: string) => void;
  onBack: () => void;
}) {
  const { video, status, label } = useCamera(camera);

  // So the dashboard can say which camera this kiosk is using, or that it has none.
  useEffect(() => {
    if (status === "ready") void reportCamera(label).catch(() => undefined);
    if (status === "denied") void reportCamera(null).catch(() => undefined);
  }, [status, label]);

  useQrScanner(video, !busy && status === "ready", (text) => {
    if (!text.startsWith("iden-kiosk-pair:") && text.length <= MAX_TICKET) onTicket(text);
  });

  return (
    <Screen
      name={name}
      footer={footer}
      className="grid grid-cols-[minmax(0,1fr)_auto] content-center items-center gap-10 text-left portrait:grid-cols-1 portrait:justify-items-center portrait:text-center short:gap-6"
    >
      <div className="flex flex-col gap-6 short:gap-4 portrait:items-center">
        <Title>Show your QR code</Title>
        <Lede>
          Hold your phone up to the camera, with the code from{" "}
          <strong className="font-medium text-ink">Enrol at a kiosk</strong> inside the corners.
        </Lede>
        <p
          aria-live="polite"
          className="flex min-h-8 items-center gap-3 text-title-md text-muted-foreground short:text-body-md"
        >
          {busy ? (
            <LoaderCircle aria-hidden="true" className="h-6 w-6 animate-spin text-primary" />
          ) : (
            <QrCode aria-hidden="true" className="h-6 w-6" />
          )}
          {busy ? "Reading your code…" : "Looking for a code…"}
        </p>
        <div className="portrait:self-center">
          <BigButton variant="quiet" onClick={onBack}>
            <ArrowLeft aria-hidden="true" className="h-6 w-6" />
            Back
          </BigButton>
        </div>
      </div>
      <CameraView video={video} status={status} />
    </Screen>
  );
}

/** What to tell the person, from IDEN's error code. */
function explain(error: unknown, retry?: { ticket: string; left: number }): Phase {
  const code = error instanceof KioskError ? error.code : "error";
  switch (code) {
    case "poor_capture":
      return {
        kind: "problem",
        title: "We couldn't see your face clearly",
        lines: describeCaptureProblems(
          error instanceof KioskError ? error.details.reasons : undefined,
        ),
        retry,
      };
    case "not_live":
      return {
        kind: "problem",
        title: "That didn't work",
        lines: describeFailedChecks(error instanceof KioskError ? error.details.failed : undefined),
        retry,
      };
    case "invalid_frames":
      return {
        kind: "problem",
        title: "That didn't work",
        lines: [
          "Look at the screen, follow each instruction, and hold each position until the next one.",
        ],
        retry,
      };
    case "face_challenge_invalid":
      return {
        kind: "problem",
        title: "That took too long",
        lines: ["Start again when you're ready."],
        retry,
      };
    case "enrolment_ticket_invalid":
      return {
        kind: "problem",
        title: "This code can't be used",
        lines: [
          "It has expired, was already used, or has run out of attempts.",
          "Create a new one in IDEN under Security.",
        ],
      };
    case "rate_limited":
      return {
        kind: "problem",
        title: "Too many attempts",
        lines: ["Wait a few minutes and try again."],
      };
    default:
      return {
        kind: "problem",
        title: "Enrolment is unavailable",
        lines: ["Something went wrong on our side. Try again later, or ask staff for help."],
      };
  }
}

// The kiosk is supervised, so IDEN says which liveness checks failed. Each line
// is what the person can do about it.
const CHECK_ADVICE: Record<string, string> = {
  actions:
    "Turn your head the way each arrow shows, all the way, and hold it there until the next instruction.",
  anti_spoofing: "Make sure your face is evenly lit, with nothing covering it, and try again.",
  consistent: "Only one person should be in front of the camera during the capture.",
};

function describeFailedChecks(failed: unknown): string[] {
  const lines = Array.isArray(failed)
    ? failed.map((check) => CHECK_ADVICE[String(check)]).filter((line) => line !== undefined)
    : [];
  return lines.length > 0
    ? lines
    : ["Look at the screen, follow each instruction, and hold each position until the next one."];
}
