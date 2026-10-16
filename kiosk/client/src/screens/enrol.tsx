import { FaceCapture } from "../ui/face-capture";
import { useCamera } from "../ui/use-camera";
import { ArrowLeft, CircleAlert, CircleCheck, LoaderCircle, QrCode } from "lucide-react";
import { useCallback, useEffect, useState, type ReactNode } from "react";
import {
  enrol,
  reportCamera,
  startEnrolment,
  type EnrolmentChallenge,
  type KioskState,
} from "../api";
import { useIdle } from "../hooks/use-idle";
import { useQrScanner } from "../hooks/use-qr-scanner";
import { CameraView } from "./camera-view";
import { Consent } from "./consent";
import { explain, type Problem } from "./enrol-problems";
import { Idle } from "./idle";
import { BigButton, Lede, Screen, Title } from "./layout";

type Phase =
  | { kind: "idle" }
  | { kind: "consent" }
  | { kind: "welcome" }
  | { kind: "starting" }
  | { kind: "confirm"; ticket: string; challenge: EnrolmentChallenge }
  | { kind: "capture"; ticket: string; challenge: EnrolmentChallenge }
  | { kind: "checking"; name: string }
  | { kind: "done"; name: string }
  | Problem;

const DONE_SECONDS = 8;
const MAX_TICKET = 512;

/**
 * One person's visit: touch the idle screen, agree to what enrolling does, show
 * the QR code from the dashboard, confirm the name, follow the capture, hear the
 * result. Every way out — a result, No thanks, Not me, Back, or nobody touching
 * the screen for the kiosk's idle time — returns to the idle screen, with the
 * camera off and nothing of the person kept, their agreement included.
 */
export function Enrolment({ state }: { state: KioskState }) {
  const [phase, setPhase] = useState<Phase>({ kind: "idle" });
  // The consent version this person agreed to, sent with their capture.
  const [agreed, setAgreed] = useState<string | null>(null);
  const reset = useCallback(() => {
    setAgreed(null);
    setPhase({ kind: "idle" });
  }, []);
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
      await enrol(ticket, challenge.faceChallengeId, agreed ?? "", frames);
      setPhase({ kind: "done", name: challenge.displayName });
    } catch (error) {
      setPhase(explain(error, { ticket, left: challenge.attemptsLeft }));
    }
  }

  const footer = settings.notice || state.location;

  switch (phase.kind) {
    case "idle":
      return <Idle state={state} onStart={() => setPhase({ kind: "consent" })} />;

    case "consent": {
      const consent = state.consent;
      if (!consent) {
        return (
          <Screen name={state.name} footer={footer}>
            <Title>Not ready yet</Title>
            <Lede>This kiosk is still connecting to IDEN. Try again in a minute.</Lede>
            <BigButton onClick={reset}>Finish</BigButton>
          </Screen>
        );
      }
      return (
        <Consent
          name={state.name}
          footer={footer}
          consent={consent}
          onAgree={() => {
            setAgreed(consent.version);
            setPhase({ kind: "welcome" });
          }}
          onDecline={reset}
        />
      );
    }

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
