"""Capture your own face doing every action, for the real-image tests.

    uv run python -m scripts.capture_actions [--camera 0] [--out tests/data/actions]

For a consenting team member only: the photos are of your face. The folder is
git-ignored; delete it when you are done with it.

The terminal guides you through each step — straight ahead, a blink, a smile,
then the four head movements. For each, it counts down, rings the bell, and
records a few seconds from the webcam. From that recording it keeps three
frames, as the kiosk would: three looking ahead; for a blink, open, the most
closed, open again; for a smile, neutral, the peak, the smile held; for a head
movement, the three that went furthest. It then runs the engine's own check on
them and says whether they pass, so a step can be done again.

The frames are written as `<step>_<n>.jpg`, 640×480 and unmirrored, as a kiosk
sends them, and read by engine/tests/test_actions_real.py and the provider's
real-engine integration test. The engine needs no window for this: the
OpenCV it ships with cannot open one, so the guidance is all in the terminal.
"""

import argparse
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from engine import expression, liveness, manifest, pipeline, runtime
from engine.config import settings
from engine.expression import Expression
from engine.pose import Pose

WIDTH, HEIGHT = 640, 480
FRAMES = 3

STEPS: list[tuple[str, str, float]] = [
    ("center", "Look straight at the camera, and keep still.", 2.0),
    ("blink", "Blink slowly, once.", 3.0),
    ("smile", "Start with a straight face, then smile, and hold it.", 3.5),
    ("turn_left", "Turn your head to your left.", 3.0),
    ("turn_right", "Turn your head to your right.", 3.0),
    ("look_up", "Tilt your head up.", 3.0),
    ("look_down", "Tilt your head down.", 3.0),
]


@dataclass
class Shot:
    at: float
    image: np.ndarray
    pose: Pose | None = None
    expression: Expression | None = None


def record(camera: cv2.VideoCapture, seconds: float) -> list[Shot]:
    shots, started = [], time.monotonic()
    while (now := time.monotonic()) - started < seconds:
        ok, image = camera.read()
        if ok:
            shots.append(Shot(now - started, cv2.resize(image, (WIDTH, HEIGHT))))
    return shots


def read(models: runtime.Models, shots: list[Shot]) -> list[Shot]:
    """Each shot's pose and expression; shots without exactly one face dropped."""
    found = []
    for shot in shots:
        frame = pipeline.inspect(models, "center", shot.image)
        if frame.seen is None:
            continue
        (points,) = pipeline.landmarks(
            models.landmarker, [(shot.image, frame.seen.face.box)]
        )
        shot.pose, shot.expression = frame.seen.pose, expression.measure(points)
        found.append(shot)
    return found


def evenly(shots: list[Shot]) -> list[Shot]:
    picks = np.linspace(0, len(shots) - 1, FRAMES).round().astype(int)
    return [shots[i] for i in picks]


def pick_blink(shots: list[Shot]) -> list[Shot]:
    """Open, the most closed, open again: the widest-open frame either side of
    the deepest dip."""
    openness = [s.expression.eye_openness if s.expression else 0.0 for s in shots]
    dip = int(np.argmin(openness))
    if dip in (0, len(shots) - 1):
        return evenly(shots)
    before = int(np.argmax(openness[:dip]))
    after = dip + 1 + int(np.argmax(openness[dip + 1 :]))
    return [shots[before], shots[dip], shots[after]]


def smile_gain(shot: Shot, neutral: Expression) -> float:
    e = shot.expression
    if e is None:
        return 0.0
    return (e.mouth_width - neutral.mouth_width) + (e.mouth_lift - neutral.mouth_lift)


def pick_smile(shots: list[Shot], neutral: Expression) -> list[Shot]:
    """Neutral, the peak, and the smile held: the first frame at least 0.3 s
    after the peak still at four fifths of it, or the last frame."""
    gains = [smile_gain(s, neutral) for s in shots]
    peak = int(np.argmax(gains))
    calm = int(np.argmin(gains[: peak + 1]))
    held = next(
        (
            i
            for i in range(peak + 1, len(shots))
            if shots[i].at - shots[peak].at >= 0.3 and gains[i] >= 0.8 * gains[peak]
        ),
        len(shots) - 1,
    )
    return [shots[calm], shots[peak], shots[held]]


def pick_movement(shots: list[Shot], step: str, baseline: Pose) -> list[Shot]:
    """The three frames that went furthest, in the order they were taken."""
    axis, sign = liveness.EXPECTED[step]
    reach = [
        sign * (getattr(s.pose, axis) - getattr(baseline, axis)) if s.pose else -9.0
        for s in shots
    ]
    best = sorted(np.argsort(reach)[-FRAMES:])
    return [shots[i] for i in best]


def judge(
    models: runtime.Models, centre: list[Shot], step: str, picked: list[Shot]
) -> tuple[bool, str]:
    """The engine's own verdict on the step, as an enrolment would judge it."""
    steps = ["center"] * FRAMES + [step] * FRAMES
    result = pipeline.enroll(models, [s.image for s in centre + picked], steps)
    if not result.usable or result.checks is None:
        return False, f"not usable: {', '.join(result.reasons)}"
    checks = result.checks
    return checks.actions, (
        f"action score {checks.actions_score:.2f} (1.00 passes), "
        f"anti-spoofing {checks.anti_spoofing_score:.2f}, "
        f"consistency {checks.consistency_score:.2f}"
    )


def countdown(text: str) -> None:
    print(f"\n{text}")
    for n in (3, 2, 1):
        print(f"  {n}...", flush=True)
        time.sleep(1)
    # The bell: the moment to start, for someone not looking at the screen.
    print("  \a* now", flush=True)


def ask(question: str) -> bool:
    return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Capture your own face doing every action, for the tests."
    )
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--out", type=Path, default=Path("tests") / "data" / "actions")
    args = parser.parse_args()

    print(
        f"This saves photos of your face to {args.out}, for the engine's tests. "
        "Consenting team members only; the folder is git-ignored."
    )
    if not ask("Is this your own face, and do you agree to it being saved here?"):
        sys.exit("Nothing captured.")

    models = runtime.load(
        manifest.load(settings.engine_manifest), settings.engine_model_dir, "auto"
    )
    camera = cv2.VideoCapture(args.camera)
    camera.set(cv2.CAP_PROP_FRAME_WIDTH, WIDTH)
    camera.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)
    if not camera.isOpened():
        sys.exit(f"Camera {args.camera} would not open.")
    args.out.mkdir(parents=True, exist_ok=True)

    centre: list[Shot] = []
    neutral = Expression(0.0, 0.0, 0.0)
    baseline = Pose(0.0, 0.0, 0.0)
    try:
        for step, prompt, seconds in STEPS:
            while True:
                countdown(prompt)
                shots = read(models, record(camera, seconds))
                print("  done.")
                if len(shots) < FRAMES:
                    print("  Your face was not found in enough frames.")
                    continue

                if step == "center":
                    picked = evenly(shots)
                    found = [s.expression for s in picked if s.expression]
                    neutral = expression.neutral(found)
                    baseline = Pose(
                        yaw=float(np.median([s.pose.yaw for s in picked if s.pose])),
                        pitch=float(
                            np.median([s.pose.pitch for s in picked if s.pose])
                        ),
                        eye_distance=0.0,
                    )
                    passed, said = True, "three frames looking ahead"
                elif step == "blink":
                    picked = pick_blink(shots)
                    passed, said = judge(models, centre, step, picked)
                elif step == "smile":
                    picked = pick_smile(shots, neutral)
                    passed, said = judge(models, centre, step, picked)
                else:
                    picked = pick_movement(shots, step, baseline)
                    passed, said = judge(models, centre, step, picked)

                print(f"  {'pass' if passed else 'FAIL'}: {said}")
                if passed or not ask("  Try this step again?"):
                    break

            if step == "center":
                centre = picked
            for n, shot in enumerate(picked):
                cv2.imwrite(
                    str(args.out / f"{step}_{n}.jpg"),
                    shot.image,
                    [cv2.IMWRITE_JPEG_QUALITY, 90],
                )
    finally:
        camera.release()
    print(f"\nWrote {len(STEPS) * FRAMES} frames to {args.out}.")


if __name__ == "__main__":
    main()
