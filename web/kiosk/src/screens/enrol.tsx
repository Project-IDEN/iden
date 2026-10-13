import { FaceCapture, describeCaptureProblems, useCamera } from "@iden/shared";
import { CircleCheck } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
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
import { BigButton, Lede, Screen, Title } from "./layout";

type Phase =
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
 * One person's visit: show the QR code from the dashboard, confirm the name,
 * follow the capture, hear the result. Every way out — a result, Not me, or
 * nobody touching the screen — returns to the welcome screen with nothing of
 * the person kept.
 */
export function Enrolment({ state }: { state: KioskState }) {
  const [phase, setPhase] = useState<Phase>({ kind: "welcome" });
  const reset = useCallback(() => setPhase({ kind: "welcome" }), []);
  const settings = state.settings;

  useIdle(phase.kind !== "welcome" && phase.kind !== "checking", settings.idleSeconds ?? 90, reset);

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
    case "welcome":
    case "starting":
      return (
        <Welcome
          name={state.name}
          footer={footer}
          camera={settings.cameraLabel}
          busy={phase.kind === "starting"}
          onTicket={(ticket) => void begin(ticket, true)}
        />
      );

    case "confirm":
      return (
        <Screen name={state.name} footer={footer}>
          <Lede>Enrolling the face of</Lede>
          <Title>{phase.challenge.displayName}</Title>
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
        <Screen name={state.name}>
          <Lede>
            Stand about an arm's length away, follow the instructions, and keep your face in the
            oval.
          </Lede>
          <FaceCapture
            className="w-full max-w-xl [&_p]:text-title-md"
            challenge={phase.challenge}
            camera={settings.cameraLabel}
            onCaptured={(frames) => void submit(phase.ticket, phase.challenge, frames)}
          />
          <BigButton variant="quiet" onClick={reset}>
            Cancel
          </BigButton>
        </Screen>
      );

    case "checking":
      return (
        <Screen name={state.name}>
          <Title>Checking…</Title>
          <Lede>This takes a few seconds.</Lede>
        </Screen>
      );

    case "done":
      return (
        <Screen name={state.name}>
          <CircleCheck aria-hidden="true" className="h-20 w-20 text-success" />
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
          <Title>{phase.title}</Title>
          {phase.lines.map((line) => (
            <Lede key={line}>{line}</Lede>
          ))}
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
}: {
  name: string | null;
  footer: string | null | undefined;
  camera: string | null | undefined;
  busy: boolean;
  onTicket: (ticket: string) => void;
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
    <Screen name={name} footer={footer}>
      <Title>Enrol your face</Title>
      <Lede>
        Sign in to IDEN on your phone, open Security, choose <strong>Enrol at a kiosk</strong>, and
        hold the QR code up to the camera.
      </Lede>
      <CameraView video={video} status={status} />
      <p className="min-h-8 text-title-md text-muted-foreground" aria-live="polite">
        {busy ? "Reading your code…" : null}
      </p>
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
    case "invalid_frames":
      return {
        kind: "problem",
        title: "That didn't work",
        lines: [
          "Look at the screen, follow each instruction, and keep still while it changes colour.",
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
