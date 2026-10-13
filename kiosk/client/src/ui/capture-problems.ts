/** A copy of web/shared/ui/capture-problems.ts: the provider's `poor_capture` reasons. */
const REASONS: Record<string, string> = {
  no_face: "We couldn't find your face. Keep it inside the oval.",
  multiple_faces: "Only you should be in view.",
  too_small: "Move closer to the camera.",
  blurred: "Hold still — the picture was blurred.",
  too_dark: "It's too dark. Face a lamp or a window.",
  too_bright: "There's too much light. Move away from the light behind or on you.",
  off_angle: "Look straight at the camera when asked.",
};

/** What to tell a person about a `poor_capture`, most useful first. */
export function describeCaptureProblems(reasons: unknown): string[] {
  if (!Array.isArray(reasons)) return [];
  return reasons.flatMap((reason) =>
    typeof reason === "string" && REASONS[reason] ? [REASONS[reason]] : [],
  );
}
