// Run with `pnpm test`: Node's own test runner, which strips the types itself.
import assert from "node:assert/strict";
import { describe, test } from "node:test";
import {
  blinkPicker,
  isExpression,
  pickFrames,
  smilePicker,
  BLINK_CLOSED,
  SMILE_HOLD_MS,
} from "../src/ui/capture-actions.ts";

/** Readings 40 ms apart, as the capture polls the tracker. */
function readings(values: number[]) {
  return values.map((value, index) => ({ value, at: index * 40 }));
}

describe("blink", () => {
  test("picks open, the most closed frame, and open again", () => {
    const eyes = [0.1, 0.12, 0.3, 0.62, 0.81, 0.93, 0.7, 0.4, 0.15, 0.1];
    assert.deepEqual(pickFrames("blink", readings(eyes)), [0, 5, 8]);
  });

  test("the most closed frame is the deepest one, not the first closed one", () => {
    const eyes = [0.05, 0.6, 0.97, 0.8, 0.05];
    const picked = pickFrames("blink", readings(eyes));
    assert.equal(picked?.[1], 2);
  });

  test("waits for the eyes to be open first", () => {
    const eyes = [0.9, 0.95, 0.05, 0.9, 0.05];
    assert.deepEqual(pickFrames("blink", readings(eyes)), [2, 3, 4]);
  });

  test("no blink, no frames", () => {
    assert.equal(pickFrames("blink", readings([0.1, 0.2, 0.3, 0.2, 0.1])), null);
  });

  test("eyes that close and never open again are not a blink", () => {
    assert.equal(pickFrames("blink", readings([0.1, 0.7, 0.9, 0.95, 0.9])), null);
  });

  test("half closed is not closed", () => {
    const eyes = [0.1, BLINK_CLOSED - 0.05, 0.1];
    assert.equal(pickFrames("blink", readings(eyes)), null);
  });

  test("progress rises as the eyes close and is full once they open", () => {
    const picker = blinkPicker();
    assert.equal(picker.progress(), 0);
    picker.offer(0.1, 0);
    const opened = picker.progress();
    picker.offer(0.9, 40);
    assert.ok(picker.progress() > opened);
    picker.offer(0.1, 80);
    assert.equal(picker.progress(), 1);
    assert.equal(picker.done(), true);
    assert.equal(picker.offer(0.9, 120), null);
  });
});

describe("smile", () => {
  test("picks neutral, the peak, and the smile held", () => {
    const mouth = [0.05, 0.1, 0.4, 0.6, 0.75, 0.9, 0.85, 0.8, 0.82, 0.84, 0.8, 0.8, 0.8, 0.8];
    const picked = pickFrames("smile", readings(mouth));
    assert.ok(picked);
    const [neutral, peak, held] = picked;
    assert.equal(neutral, 0);
    assert.equal(peak, 5);
    // Held: still smiling, at least SMILE_HOLD_MS after the smile began (index 3).
    assert.ok((held - 3) * 40 >= SMILE_HOLD_MS);
    assert.ok((mouth[held] ?? 0) >= 0.55);
  });

  test("the peak is the broadest smile before it was held", () => {
    const mouth = [0.1, 0.6, 0.95, 0.7, 0.65, 0.66, 0.67, 0.68, 0.69, 0.7, 0.7, 0.7, 0.7];
    assert.equal(pickFrames("smile", readings(mouth))?.[1], 2);
  });

  test("waits for a neutral face first", () => {
    const mouth = [0.8, 0.8, 0.1, 0.7, 0.7, 0.7, 0.7, 0.7, 0.7, 0.7, 0.7, 0.7, 0.7, 0.7];
    assert.equal(pickFrames("smile", readings(mouth))?.[0], 2);
  });

  test("a neutral face alone is not a smile", () => {
    assert.equal(pickFrames("smile", readings(Array(40).fill(0.1))), null);
  });

  test("a smile that is not held is not enough", () => {
    // Flickers above the threshold, never for SMILE_HOLD_MS together.
    const mouth = [0.1, 0.7, 0.3, 0.7, 0.3, 0.7, 0.3, 0.7, 0.3, 0.7, 0.3];
    assert.equal(pickFrames("smile", readings(mouth)), null);
  });

  test("progress follows the smile", () => {
    const picker = smilePicker();
    picker.offer(0.1, 0);
    picker.offer(0.3, 40);
    const part = picker.progress();
    assert.ok(part > 0 && part < 1);
  });
});

test("only a blink and a smile are expressions", () => {
  assert.equal(isExpression("blink"), true);
  assert.equal(isExpression("smile"), true);
  for (const step of ["center", "turn_left", "look_up", "frown"]) {
    assert.equal(isExpression(step), false);
  }
});
