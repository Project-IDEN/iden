import type { IdenError } from "@iden/shared";
import { Button, cn, describeCaptureProblems } from "@iden/shared";
import {
  Clock,
  RotateCw,
  ScanFace,
  ShieldAlert,
  TimerOff,
  WifiOff,
  type LucideIcon,
} from "lucide-react";
import type { ReactNode } from "react";
import { duration } from "../duration";

/** What the provider allows: three faces that do not match in fifteen minutes. */
const TRIES = 3;

type Tone = "error" | "caution" | "info";

interface Outcome {
  tone: Tone;
  glyph: LucideIcon;
  title: string;
  body: ReactNode;
  tips?: string[];
  /** Present after a face that did not match: how many tries remain. */
  triesLeft?: number;
  /** Whether trying again can help. */
  retry: boolean;
}

function paused(seconds: number): Outcome {
  return {
    tone: "info",
    glyph: Clock,
    title: "Face sign-in is paused",
    body: `After ${TRIES} tries that didn't match, it's paused for ${duration(seconds)} to protect your account.`,
    retry: false,
  };
}

function outcomeOf(problem: IdenError): Outcome {
  const left = problem.details.attemptsLeft;
  const resumesIn = problem.details.retryAfter;

  if (problem.code === "poor_capture") {
    return {
      tone: "caution",
      glyph: ScanFace,
      title: "We couldn't see you clearly",
      body: "That didn't use one of your tries.",
      tips: describeCaptureProblems(problem.details.reasons),
      retry: true,
    };
  }
  if (problem.code === "face_rejected") {
    if (left === 0) return paused(typeof resumesIn === "number" ? resumesIn : 900);
    return {
      tone: "error",
      glyph: ShieldAlert,
      title: "That didn't match",
      body: "Look straight at the camera in even light, with nothing covering your face.",
      triesLeft: typeof left === "number" ? left : undefined,
      retry: true,
    };
  }
  if (problem.status === 429) return paused(problem.retryAfter ?? 900);
  if (problem.code === "face_enrolment_outdated") {
    return {
      tone: "info",
      glyph: ScanFace,
      title: "Your face needs enrolling again",
      body: "Face sign-in was upgraded since you enrolled. Enrol again at a kiosk, and use another method for now.",
      retry: false,
    };
  }
  if (problem.code === "engine_unavailable") {
    return {
      tone: "caution",
      glyph: WifiOff,
      title: "Face checks are unavailable",
      body: "This is on our side and usually brief. Try again in a minute, or use another method.",
      retry: true,
    };
  }
  if (problem.code === "face_challenge_invalid") {
    return {
      tone: "caution",
      glyph: TimerOff,
      title: "That took too long",
      body: "Start again when you're ready.",
      retry: true,
    };
  }
  if (problem.status === 401 || problem.status === 404) {
    return {
      tone: "info",
      glyph: TimerOff,
      title: "Your sign-in timed out",
      body: "Return to the application and start again.",
      retry: false,
    };
  }
  return { tone: "error", glyph: ShieldAlert, title: problem.message, body: null, retry: true };
}

const TONE_TEXT: Record<Tone, string> = {
  error: "text-error",
  caution: "text-warning",
  info: "text-muted-foreground",
};

/** The capture's own oval, so the result reads as the answer to it. */
function OvalBadge({ tone, glyph: Glyph }: { tone: Tone; glyph: LucideIcon }) {
  return (
    <span
      className={cn("relative flex h-[4.5rem] w-14 items-center justify-center", TONE_TEXT[tone])}
    >
      <svg aria-hidden="true" viewBox="0 0 56 72" className="absolute inset-0 h-full w-full">
        <ellipse
          cx="28"
          cy="36"
          rx="26"
          ry="34"
          className="fill-current stroke-current opacity-90"
          fillOpacity="0.08"
          strokeWidth="1.5"
        />
      </svg>
      <Glyph aria-hidden="true" className="relative h-6 w-6" />
    </span>
  );
}

/** One small oval per try, filled while it is still yours to use. */
function Tries({ left }: { left: number }) {
  return (
    <p className="flex items-center justify-center gap-3 text-caption text-muted-foreground">
      <span aria-hidden="true" className="flex gap-1.5">
        {Array.from({ length: TRIES }, (_, index) => (
          <svg key={index} viewBox="0 0 10 13" className="h-[13px] w-2.5">
            <ellipse
              cx="5"
              cy="6.5"
              rx="4.25"
              ry="5.75"
              strokeWidth="1.5"
              className={index < left ? "fill-primary stroke-primary" : "fill-none stroke-hairline"}
            />
          </svg>
        ))}
      </span>
      {left === 1 ? "1 try left" : `${left} tries left`}
    </p>
  );
}

/**
 * What came of a face capture that did not sign the person in: what happened,
 * what to do about it, and — after a face that did not match — how many tries
 * remain before face sign-in pauses.
 */
export function FaceOutcome({
  problem,
  onRetry,
  onSwitch,
}: {
  problem: IdenError;
  onRetry: () => void;
  onSwitch?: () => void;
}) {
  const outcome = outcomeOf(problem);

  return (
    <div role="alert" className="flex flex-col items-center gap-5 text-center">
      <OvalBadge tone={outcome.tone} glyph={outcome.glyph} />
      <div>
        <p className="font-display text-title-lg text-ink">{outcome.title}</p>
        {outcome.body ? <p className="mt-2 text-body-sm text-body">{outcome.body}</p> : null}
      </div>

      {outcome.tips?.length ? (
        <ul className="flex w-full flex-col gap-2 rounded-lg bg-surface-soft px-4 py-3 text-left text-body-sm text-body">
          {outcome.tips.map((tip) => (
            <li key={tip} className="flex gap-2.5">
              <span aria-hidden="true" className="mt-2 h-1 w-1 shrink-0 rounded-full bg-primary" />
              {tip}
            </li>
          ))}
        </ul>
      ) : null}

      {outcome.triesLeft !== undefined ? <Tries left={outcome.triesLeft} /> : null}

      {outcome.retry ? (
        <Button variant="default" className="self-stretch" onClick={onRetry}>
          <RotateCw aria-hidden="true" />
          Try again
        </Button>
      ) : onSwitch ? (
        <Button variant="default" className="self-stretch" onClick={onSwitch}>
          Use another method
        </Button>
      ) : null}
    </div>
  );
}
