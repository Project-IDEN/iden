"""How long the engine takes over a capture, stage by stage, with no HTTP.

What to compare a CPU with a GPU on, or one model with another, before the
network and the provider are in the way:

    uv run python -m scripts.bench
    uv run python -m scripts.bench --runs 50 --image me.jpg --json bench.json

The capture is nine frames of one photo at the kiosk's 640×480, the shape of a
real enrolment. A photo cannot pass the movement checks, so the timing is of
the work, not of a successful enrolment.
"""

import argparse
import json
import logging
import os
import platform
import statistics
import time
from collections.abc import Callable
from pathlib import Path

import cv2
import structlog

from engine import manifest as manifest_module
from engine import pad, pipeline, runtime
from engine.align import align
from engine.config import settings
from engine.detect import detect
from engine.embed import embed
from engine.imaging import decode

STEPS = ["center"] * 5 + ["turn_left", "turn_right", "look_up", "look_down"]


def _capture(path: Path) -> list[bytes]:
    image = cv2.imread(str(path))
    if image is None:
        raise SystemExit(f"{path} is not an image.")
    frame = cv2.imencode(".jpg", cv2.resize(image, (640, 480)))[1].tobytes()
    return [frame] * len(STEPS)


def _time(run: Callable[[], object], runs: int) -> dict[str, float]:
    run()
    samples = []
    for _ in range(runs):
        started = time.perf_counter()
        run()
        samples.append((time.perf_counter() - started) * 1000)
    samples.sort()
    return {
        "mean": statistics.fmean(samples),
        "p50": samples[len(samples) // 2],
        "p95": samples[min(len(samples) - 1, round(len(samples) * 0.95))],
        "min": samples[0],
    }


def measure(models: runtime.Models, frames: list[bytes], runs: int) -> dict:
    found = models.manifest.detector
    recognizer = models.manifest.recognizer
    images = [decode(frame, settings.engine_max_pixels) for frame in frames]
    faces = [
        detect(models.detector, image, found.input_sizes, found.score_threshold)
        for image in images
    ]
    if not all(faces):
        raise SystemExit("No face found in the photo; try another with --image.")
    landmarks = [found_faces[0].landmarks for found_faces in faces]
    aligned = [
        align(image, points) for image, points in zip(images, landmarks, strict=True)
    ]
    templates = embed(
        models.recognizer, aligned[:3], recognizer.mean, recognizer.std
    ).tolist()

    def detect_all() -> None:
        for image in images:
            detect(models.detector, image, found.input_sizes, found.score_threshold)

    stages = {
        "decode (9 frames)": lambda: [
            decode(frame, settings.engine_max_pixels) for frame in frames
        ],
        "detect (9 frames, one by one)": detect_all,
        "embed (batch of 9)": lambda: embed(
            models.recognizer, aligned, recognizer.mean, recognizer.std
        ),
        "anti-spoofing (batch of 5)": lambda: pad.live_probability(
            models.anti_spoofing, list(zip(images[:5], landmarks[:5], strict=True))
        ),
        "enrol, end to end": lambda: pipeline.enroll(models, images, STEPS),
        "verify, end to end": lambda: pipeline.verify(
            models, images[:5], STEPS[:5], templates
        ),
    }
    return {name: _time(run, runs) for name, run in stages.items()}


def _table(results: dict[str, dict[str, float]]) -> str:
    lines = [
        "| Stage | mean ms | p50 ms | p95 ms | min ms |",
        "|---|---:|---:|---:|---:|",
    ]
    for name, t in results.items():
        lines.append(
            f"| {name} | {t['mean']:.1f} | {t['p50']:.1f} | {t['p95']:.1f} | "
            f"{t['min']:.1f} |"
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Time the engine over a capture, stage by stage."
    )
    parser.add_argument("--runs", type=int, default=20, help="Timed runs per stage.")
    parser.add_argument("--image", type=Path, default=Path("tests/data/astronaut.jpg"))
    parser.add_argument("--device", choices=["auto", "cuda", "cpu"], default="auto")
    parser.add_argument("--json", type=Path, help="Also write the results here.")
    args = parser.parse_args()

    # Every enrolment logs its liveness scores; a benchmark makes hundreds.
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING)
    )
    manifest = manifest_module.load(settings.engine_manifest)
    models = runtime.load(manifest, settings.engine_model_dir, args.device)
    results = measure(models, _capture(args.image), args.runs)

    machine = f"{platform.system()} {platform.machine()}, {os.cpu_count()} cores"
    print(
        f"Model {manifest.version} on {models.device} ({machine}), {args.runs} runs\n"
    )
    print(_table(results))
    if args.json:
        args.json.write_text(
            json.dumps(
                {
                    "model_version": manifest.version,
                    "device": models.device,
                    "providers": models.providers,
                    "machine": machine,
                    "runs": args.runs,
                    "stages_ms": results,
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
