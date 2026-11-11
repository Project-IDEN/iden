/**
 * Which three frames a blink or a smile sends.
 *
 * MediaPipe's blendshapes (`eyeBlinkLeft/Right`, `mouthSmileLeft/Right`, each
 * 0 to 1) say from moment to moment how closed the eyes are and how much the
 * person smiles. A picker is fed those readings one at a time and answers which
 * of the step's three frames the camera's current picture should be — or none:
 *
 * - blink: eyes open; the most closed frame, replaced while they close
 *   further; eyes open again.
 * - smile: a neutral face; the peak of the smile, replaced while it grows;
 *   the smile still held a moment after it began.
 *
 * These numbers only decide when to take a frame. The engine judges the frames
 * themselves against the person's own face, and never trusts the kiosk.
 *
 * No DOM and no imports, so the tests run it in Node directly.
 */

export type Slot = 0 | 1 | 2;

export interface Reading {
  /** How closed the eyes are: 0 wide open, 1 shut. Mean of both eyes. */
  blink: number;
  /** How much the person smiles: 0 not at all, 1 fully. Mean of both sides. */
  smile: number;
}

export interface Picker {
  /** The frame the current picture fills, replacing any earlier one there, or null. */
  offer: (value: number, at: number) => Slot | null;
  /** All three frames are chosen. */
  done: () => boolean;
  /** 0 to 1, for the progress bar. */
  progress: () => number;
}

export const EXPRESSIONS = ["blink", "smile"] as const;
export type Expression = (typeof EXPRESSIONS)[number];

export function isExpression(step: string): step is Expression {
  return (EXPRESSIONS as readonly string[]).includes(step);
}

// Blendshape scores. Open is well below closed, so one jittery reading cannot
// count as both.
export const BLINK_OPEN = 0.3;
export const BLINK_CLOSED = 0.55;
export const SMILE_NEUTRAL = 0.25;
export const SMILE_SMILING = 0.55;
// How long a smile must last before its "held" frame is taken.
export const SMILE_HOLD_MS = 400;

export function blinkPicker(): Picker {
  let opened = false;
  let deepest = 0;
  let finished = false;
  return {
    offer(value) {
      if (finished) return null;
      if (!opened) {
        // The eyes must be seen open first: frames that start closed could
        // be a photo of closed eyes, then one of open eyes.
        if (value > BLINK_OPEN) return null;
        opened = true;
        return 0;
      }
      if (value >= BLINK_CLOSED && value > deepest) {
        deepest = value;
        return 1;
      }
      if (deepest >= BLINK_CLOSED && value <= BLINK_OPEN) {
        finished = true;
        return 2;
      }
      return null;
    },
    done: () => finished,
    progress: () => (finished ? 1 : opened ? 0.1 + 0.6 * Math.min(1, deepest / BLINK_CLOSED) : 0),
  };
}

export function smilePicker(): Picker {
  let neutral = false;
  let peak = 0;
  let since: number | null = null;
  let finished = false;
  let latest = 0;
  return {
    offer(value, at) {
      if (finished) return null;
      latest = value;
      if (!neutral) {
        if (value > SMILE_NEUTRAL) return null;
        neutral = true;
        return 0;
      }
      if (value < SMILE_SMILING) {
        // A smile that faded before it was held starts its hold again.
        since = null;
        return null;
      }
      since ??= at;
      if (at - since >= SMILE_HOLD_MS && peak > 0) {
        finished = true;
        return 2;
      }
      if (value > peak) {
        peak = value;
        return 1;
      }
      return null;
    },
    done: () => finished,
    progress: () => (finished ? 1 : neutral ? Math.min(0.9, latest / SMILE_SMILING) : 0),
  };
}

export function pickerFor(step: Expression): Picker {
  return step === "blink" ? blinkPicker() : smilePicker();
}

/**
 * The readings each of the three frames would be taken at, by index into
 * `readings`, or null if the action never completed. What a capture does
 * live, replayed over a recording: for tests, and for tuning the numbers above.
 */
export function pickFrames(
  step: Expression,
  readings: { value: number; at: number }[],
): [number, number, number] | null {
  const picker = pickerFor(step);
  const slots: number[] = [];
  readings.forEach(({ value, at }, index) => {
    const slot = picker.offer(value, at);
    if (slot !== null) slots[slot] = index;
  });
  const [first, second, third] = slots;
  return picker.done() && first !== undefined && second !== undefined && third !== undefined
    ? [first, second, third]
    : null;
}
