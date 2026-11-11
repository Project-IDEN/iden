import { isExpression, pickerFor, type Expression } from "./capture-actions";
import type { HeadTracker, Pose } from "./head-tracker";

/**
 * When a face capture takes each frame. The frames and steps are exactly the
 * challenge's either way, so the provider and the engine see the same capture,
 * and the engine judges it alone.
 *
 * Each movement has a rhythm the person can follow without reading: two
 * seconds to read what comes next, a tone to start, a chime once the frames
 * are taken. A movement lasts at least five seconds, so nobody is rushed into
 * the next, and fails after eight.
 *
 * With a head tracker, straight-ahead frames wait until the face is frontal
 * and a movement's frames until the head has gone far enough. A blink or a
 * smile follows the same rhythm, and its frames are chosen from the tracker's
 * blendshapes as it happens (`capture-actions.ts`). Without a tracker — it
 * failed to load — every frame is taken on a timer.
 */

export type Phase =
  | { name: "look"; index: number }
  | { name: "prepare"; index: number; step: string; seconds: number }
  | { name: "move"; index: number; step: string }
  | { name: "done"; index: number; step: string };

export interface Guide {
  phase: (phase: Phase) => void;
  /** How far the current movement has gone, 0 to 1; null outside a movement. */
  progress: (value: number | null) => void;
  /** Take the camera's current picture as the capture's next frame. */
  take: () => Promise<void>;
  /** The camera's current picture, not yet part of the capture. */
  snap: () => Promise<Blob>;
  /** Add a picture from `snap` as the capture's next frame. */
  keep: (frame: Blob) => void;
  cue: (sound: "go" | "done") => void;
}

/** The person did not do what was asked within the window. */
export class StepTimeout extends Error {
  constructor(readonly step: string) {
    super(step === "center" ? "No face looking at the camera." : `No ${step} seen.`);
  }
}

const MOVES: Record<string, { axis: keyof Pose; sign: number }> = {
  turn_left: { axis: "yaw", sign: 1 },
  turn_right: { axis: "yaw", sign: -1 },
  look_up: { axis: "pitch", sign: -1 },
  look_down: { axis: "pitch", sign: 1 },
};
// About 25° of turn and 20° of tilt, measured on MediaPipe's canonical face.
// Well past the engine's bar (turn_delta and pitch_delta in engine/models.toml,
// about 16° and 13°), because its landmarks come from another model and can
// read a turn up to a third smaller.
const TRIGGER: Record<keyof Pose, number> = { yaw: 0.37, pitch: 0.22 };
const FRONTAL_YAW = 0.12;
// Readings in a row a condition must hold for: one frame of tracker jitter is
// not a movement.
const STEADY = 2;
const POLL_MS = 40;
const LOOK_WINDOW_MS = 8000;
const PREPARE_SECONDS = 2;
const ACTION_MIN_MS = 5000;
const ACTION_MAX_MS = 8000;
const CENTRE_GAP_MS = 220;
const HOLD_GAP_MS = 150;
// The timed capture: time to read the prompt, and to turn once the tone sounds.
const TIMED_SETTLE_MS = 1200;
const TIMED_TURN_MS = 2500;
const TIMED_HOLD_GAP_MS = 400;

const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/** Consecutive identical steps, so each is asked for once. */
export function groups(steps: string[]): { step: string; count: number }[] {
  return steps.reduce<{ step: string; count: number }[]>((out, step) => {
    const last = out.at(-1);
    if (last && last.step === step) last.count += 1;
    else out.push({ step, count: 1 });
    return out;
  }, []);
}

async function until(check: () => boolean, ms: number): Promise<boolean> {
  const deadline = performance.now() + ms;
  let streak = 0;
  while (performance.now() < deadline) {
    streak = check() ? streak + 1 : 0;
    if (streak >= STEADY) return true;
    await wait(POLL_MS);
  }
  return false;
}

function median(values: number[]): number {
  const sorted = [...values].sort((a, b) => a - b);
  const upper = sorted[sorted.length >> 1] ?? 0;
  const lower = sorted[(sorted.length - 1) >> 1] ?? upper;
  return (lower + upper) / 2;
}

/** How far `pose` has gone towards `step` from `baseline`, where 1 is enough. */
function reach(step: string, pose: Pose | null, baseline: Pose): number {
  const move = MOVES[step];
  if (!pose || !move) return 0;
  return (move.sign * (pose[move.axis] - baseline[move.axis])) / TRIGGER[move.axis];
}

async function takeEach(guide: Guide, count: number, gap: number) {
  for (let i = 0; i < count; i += 1) {
    await guide.take();
    await wait(gap);
  }
}

/** One action, start to finish; `perform` resolves once it was done and its
 * frames taken, or false when it never was. */
async function action(index: number, step: string, guide: Guide, perform: () => Promise<boolean>) {
  for (let seconds = PREPARE_SECONDS; seconds > 0; seconds -= 1) {
    guide.phase({ name: "prepare", index, step, seconds });
    await wait(1000);
  }
  const started = performance.now();
  guide.phase({ name: "move", index, step });
  guide.cue("go");
  if (!(await perform())) throw new StepTimeout(step);
  guide.cue("done");
  guide.phase({ name: "done", index, step });
  await wait(ACTION_MIN_MS - (performance.now() - started));
}

/** A blink or a smile: its frames, chosen as it happens, kept in order once
 * it is complete. False if it never was. */
async function expressed(
  step: Expression,
  count: number,
  tracker: HeadTracker,
  guide: Guide,
): Promise<boolean> {
  const picker = pickerFor(step);
  const frames: Blob[] = [];
  const deadline = performance.now() + ACTION_MAX_MS;
  while (performance.now() < deadline && !picker.done()) {
    const reading = tracker.expression();
    if (reading) {
      const slot = picker.offer(reading[step], performance.now());
      guide.progress(picker.progress());
      if (slot !== null) frames[slot] = await guide.snap();
    }
    await wait(POLL_MS);
  }
  guide.progress(null);
  if (!picker.done()) return false;
  // The provider asks for three frames per action, one per slot; should it
  // ever ask for another number, the extra frames are the expression held.
  frames.slice(0, count).forEach((frame) => guide.keep(frame));
  await takeEach(guide, count - Math.min(count, frames.length), HOLD_GAP_MS);
  return true;
}

export async function guidedCapture(steps: string[], tracker: HeadTracker, guide: Guide) {
  const { latest } = tracker;
  const frontal = () => {
    const pose = latest();
    return pose !== null && Math.abs(pose.yaw) < FRONTAL_YAW;
  };
  let baseline: Pose = { yaw: 0, pitch: 0 };

  for (const [index, { step, count }] of groups(steps).entries()) {
    if (isExpression(step)) {
      await action(index, step, guide, () => expressed(step, count, tracker, guide));
      continue;
    }
    if (MOVES[step]) {
      const moved = async () => {
        const done = await until(() => {
          const value = reach(step, latest(), baseline);
          guide.progress(Math.max(0, Math.min(1, value)));
          return value >= 1;
        }, ACTION_MAX_MS);
        guide.progress(null);
        if (done) await takeEach(guide, count, HOLD_GAP_MS);
        return done;
      };
      await action(index, step, guide, moved);
      continue;
    }

    guide.phase({ name: "look", index });
    // Every frame waits, not just the first: these set the baseline each
    // movement is measured from, and identity and anti-spoofing are judged on
    // them.
    const poses: Pose[] = [];
    for (let i = 0; i < count; i += 1) {
      if (!(await until(frontal, LOOK_WINDOW_MS))) throw new StepTimeout(step);
      const pose = latest();
      await guide.take();
      if (pose) poses.push(pose);
      await wait(CENTRE_GAP_MS);
    }
    if (poses.length) {
      baseline = {
        yaw: median(poses.map((p) => p.yaw)),
        pitch: median(poses.map((p) => p.pitch)),
      };
    }
  }
}

export async function timedCapture(steps: string[], guide: Guide) {
  for (const [index, { step, count }] of groups(steps).entries()) {
    // Without a tracker, a blink or a smile is timed like a movement: the
    // frames are spread over the moment it should happen, and the engine
    // judges whether they caught it.
    if (MOVES[step] || isExpression(step)) {
      const timed = async () => {
        await wait(TIMED_TURN_MS);
        await takeEach(guide, count, TIMED_HOLD_GAP_MS);
        return true;
      };
      await action(index, step, guide, timed);
      continue;
    }
    guide.phase({ name: "look", index });
    await wait(TIMED_SETTLE_MS);
    for (let i = 0; i < count; i += 1) {
      await guide.take();
      await wait(CENTRE_GAP_MS);
    }
  }
}
