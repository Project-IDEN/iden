import { KioskError } from "../api";
import { describeCaptureProblems } from "../ui/capture-problems";

interface Retry {
  ticket: string;
  left: number;
}

/** A visit that went wrong: what to tell the person, and whether another capture can help. */
export interface Problem {
  kind: "problem";
  title: string;
  lines: string[];
  retry?: Retry;
}

/** What to tell the person, from IDEN's error code. */
export function explain(error: unknown, retry?: Retry): Problem {
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
    case "consent_required":
      // The wording changed during the visit — a setting changed in IDEN.
      return {
        kind: "problem",
        title: "Please read this again",
        lines: ["What enrolling involves has changed. Start again to read it before you agree."],
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
  actions: "Turn your head the way each arrow shows, and keep going until you hear the chime.",
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
