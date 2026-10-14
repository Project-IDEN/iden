import type { HeadTracker, Pose } from "./head-tracker";

/**
 * When a face capture takes each frame. The frames and steps are exactly the
 * challenge's either way, so the provider and the engine see the same capture,
 * and the engine judges it alone.
 *
 * With a head tracker the capture waits for the person: straight-ahead frames
 * once the face is frontal, a movement's frames once the head has gone far
 * enough, while it is held there. A slow mover gets as long as they need, up
 * to a window, and a quick one is not kept waiting. Without one — the tracker
 * failed to load — frames are taken on a timer.
 */

export type Phase =
  | { name: "look"; step: string }
  | { name: "move"; step: string }
  | { name: "hold"; step: string }
  | { name: "recentre"; step: string };

export interface Guide {
  phase: (phase: Phase) => void;
  /** How far the current movement has gone, 0 to 1; null outside a movement. */
  progress: (value: number | null) => void;
  take: () => Promise<void>;
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
// Past the engine's bar (turn_delta 0.15 and pitch_delta 0.08 in
// engine/models.toml), because its landmarks come from another model and land a
// little differently. Not yet calibrated on real faces: compare the movement
// the engine logs for captures this accepts, and move these until every capture
// it accepts is one the engine accepts.
const TRIGGER: Record<keyof Pose, number> = { yaw: 0.22, pitch: 0.12 };
const FRONTAL_YAW = 0.12;
// Readings in a row a condition must hold for: one frame of tracker jitter is
// not a movement.
const STEADY = 2;
const POLL_MS = 40;
const WINDOW_MS = 8000;
const RECENTRE_WINDOW_MS = 3000;
const CENTRE_GAP_MS = 220;
const HOLD_GAP_MS = 150;

// The timed capture: time to read a prompt and move, between frames, and
// between two movements. A movement's frames are spread over a second while
// the person holds the pose; the engine counts the furthest of them.
const SETTLE_MS = { look: 900, move: 1200 };
const FRAME_GAP_MS = { look: 220, move: 500 };
const RECENTRE_MS = 900;

const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/** Consecutive identical steps, so each is asked for once. */
function groups(steps: string[]): { step: string; count: number }[] {
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

export async function guidedCapture(steps: string[], tracker: HeadTracker, guide: Guide) {
  const { latest } = tracker;
  const frontal = () => {
    const pose = latest();
    return pose !== null && Math.abs(pose.yaw) < FRONTAL_YAW;
  };
  let baseline: Pose = { yaw: 0, pitch: 0 };
  let previous: string | null = null;

  for (const { step, count } of groups(steps)) {
    if (!MOVES[step]) {
      guide.phase({ name: "look", step });
      // Every frame waits, not just the first: these set the baseline each
      // movement is measured from, and identity and anti-spoofing are judged
      // on them.
      const poses: Pose[] = [];
      for (let i = 0; i < count; i += 1) {
        if (!(await until(frontal, WINDOW_MS))) throw new StepTimeout(step);
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
      previous = step;
      continue;
    }

    const last = previous;
    if (last && MOVES[last]) {
      guide.phase({ name: "recentre", step });
      await until(() => Math.abs(reach(last, latest(), baseline)) < 0.3, RECENTRE_WINDOW_MS);
    }
    previous = step;

    guide.phase({ name: "move", step });
    const moved = await until(() => {
      const value = reach(step, latest(), baseline);
      guide.progress(Math.max(0, Math.min(1, value)));
      return value >= 1;
    }, WINDOW_MS);
    guide.progress(null);
    if (!moved) throw new StepTimeout(step);

    guide.phase({ name: "hold", step });
    for (let i = 0; i < count; i += 1) {
      await guide.take();
      await wait(HOLD_GAP_MS);
    }
  }
}

export async function timedCapture(steps: string[], guide: Guide) {
  let previous: string | null = null;
  for (const { step, count } of groups(steps)) {
    const kind = MOVES[step] ? "move" : "look";
    if (kind === "move" && previous && MOVES[previous]) {
      guide.phase({ name: "recentre", step });
      await wait(RECENTRE_MS);
    }
    previous = step;
    guide.phase({ name: kind, step });
    await wait(SETTLE_MS[kind]);
    if (kind === "move") guide.phase({ name: "hold", step });
    for (let i = 0; i < count; i += 1) {
      await guide.take();
      await wait(FRAME_GAP_MS[kind]);
    }
  }
}
