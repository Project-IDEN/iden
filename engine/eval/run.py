"""Measure the engine on your own images, and calibrate its threshold.

    uv run python -m eval.run DATASET [--fmr 1e-4] [--write-threshold]

DATASET is laid out as:

    genuine/<person>/*.jpg   several photos of each consenting person, taken
                             with the cameras the deployment will use
    attacks/<kind>/*.jpg     photos of attacks: prints, phone screens, masks…

It reports the threshold that keeps the false match rate (FMR) at the target,
the false non-match rate (FNMR) that costs, and how the anti-spoofing models do:
APCER, the share of attacks judged live, and BPCER, the share of genuine faces
judged fake. Run it on the same build — GPU or CPU — that serves traffic.
"""

import argparse
import itertools
import json
import re
from datetime import UTC, datetime
from pathlib import Path

import cv2
import numpy as np

from engine import manifest as manifest_module
from engine import pipeline, runtime
from engine.config import settings
from engine.embed import embed
from engine.pad import live_probability

IMAGES = {".jpg", ".jpeg", ".png"}


def _images(folder: Path) -> list[Path]:
    return sorted(p for p in folder.rglob("*") if p.suffix.lower() in IMAGES)


def _describe(models: runtime.Models, path: Path) -> tuple[np.ndarray, float] | None:
    """(embedding, live probability) of the face in one photo, or None."""
    image = cv2.imread(str(path))
    if image is None:
        return None
    frame = pipeline.inspect(models, "center", image)
    if frame.seen is None:
        return None
    vector = embed(
        models.recognizer,
        [frame.seen.aligned],
        models.manifest.recognizer.mean,
        models.manifest.recognizer.std,
    )[0]
    live = live_probability(
        models.anti_spoofing,
        [model.crop_scale for model in models.manifest.anti_spoofing],
        [(image, frame.seen.face)],
    )[0]
    return vector, float(live)


def threshold_at(impostor: np.ndarray, fmr: float) -> float:
    """The lowest similarity at which at most `fmr` of impostor pairs match."""
    return float(np.quantile(impostor, 1 - fmr, method="higher"))


def evaluate(models: runtime.Models, dataset: Path, fmr: float) -> dict:
    people: dict[str, list[np.ndarray]] = {}
    genuine_live: list[float] = []
    skipped: list[str] = []
    for folder in sorted((dataset / "genuine").iterdir()):
        for path in _images(folder):
            described = _describe(models, path)
            if described is None:
                skipped.append(str(path))
                continue
            people.setdefault(folder.name, []).append(described[0])
            genuine_live.append(described[1])

    genuine = [
        float(a @ b)
        for vectors in people.values()
        for a, b in itertools.combinations(vectors, 2)
    ]
    impostor = [
        float(a @ b)
        for (_, first), (_, second) in itertools.combinations(people.items(), 2)
        for a in first
        for b in second
    ]
    if not genuine or not impostor:
        raise SystemExit("Need at least two people with two usable photos each.")

    threshold = threshold_at(np.asarray(impostor), fmr)
    live_threshold = models.manifest.policy.live_threshold

    attacks: dict[str, float] = {}
    attack_root = dataset / "attacks"
    if attack_root.is_dir():
        for folder in sorted(attack_root.iterdir()):
            scores = [
                described[1]
                for path in _images(folder)
                if (described := _describe(models, path)) is not None
            ]
            if scores:
                attacks[folder.name] = float(
                    np.mean(np.asarray(scores) >= live_threshold)
                )

    return {
        "date": datetime.now(UTC).isoformat(),
        "model_version": models.manifest.version,
        "device": models.device,
        "people": len(people),
        "genuine_pairs": len(genuine),
        "impostor_pairs": len(impostor),
        # Below 1/fmr impostor pairs, the threshold rests on too few samples to
        # mean what it says.
        "enough_impostors": len(impostor) >= 1 / fmr,
        "target_fmr": fmr,
        "threshold": threshold,
        "fnmr": float(np.mean(np.asarray(genuine) < threshold)),
        "genuine_mean": float(np.mean(genuine)),
        "impostor_mean": float(np.mean(impostor)),
        "bpcer": float(np.mean(np.asarray(genuine_live) < live_threshold)),
        "apcer": attacks,
        "skipped": skipped,
    }


def write_threshold(manifest_path: Path, threshold: float) -> None:
    text = manifest_path.read_text()
    text = re.sub(
        r"^match_threshold = .*$",
        f"match_threshold = {threshold:.4f}",
        text,
        count=1,
        flags=re.M,
    )
    text = re.sub(r"^calibrated = .*$", "calibrated = true", text, count=1, flags=re.M)
    manifest_path.write_text(text)


def _markdown(report: dict) -> str:
    lines = [
        f"# Engine evaluation — {report['model_version']} on {report['device']}",
        "",
        f"- People: {report['people']}; genuine pairs {report['genuine_pairs']}, "
        f"impostor pairs {report['impostor_pairs']}",
        f"- Threshold at FMR {report['target_fmr']:g}: **{report['threshold']:.4f}**",
        f"- FNMR at that threshold: **{report['fnmr']:.2%}**",
        f"- Mean similarity: genuine {report['genuine_mean']:.3f}, "
        f"impostor {report['impostor_mean']:.3f}",
        f"- BPCER (genuine judged fake): {report['bpcer']:.2%}",
    ]
    for kind, rate in report["apcer"].items():
        lines.append(f"- APCER `{kind}` (attacks judged live): {rate:.2%}")
    if not report["enough_impostors"]:
        lines.append(
            "\n> Too few impostor pairs for this FMR: the threshold is an estimate. "
            "Add more people."
        )
    if report["skipped"]:
        lines.append(f"\n{len(report['skipped'])} photos had no usable face.")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Measure the engine and calibrate its threshold."
    )
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--fmr", type=float, default=1e-4)
    parser.add_argument("--out", type=Path, default=Path("reports"))
    parser.add_argument("--write-threshold", action="store_true")
    args = parser.parse_args()

    manifest = manifest_module.load(settings.engine_manifest)
    models = runtime.load(manifest, settings.engine_model_dir, settings.engine_device)
    report = evaluate(models, args.dataset, args.fmr)

    args.out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    (args.out / f"eval-{stamp}.json").write_text(json.dumps(report, indent=2))
    (args.out / f"eval-{stamp}.md").write_text(markdown := _markdown(report))
    print(markdown)

    if args.write_threshold:
        write_threshold(settings.engine_manifest, report["threshold"])
        print(f"Wrote match_threshold = {report['threshold']:.4f} to the manifest.")


if __name__ == "__main__":
    main()
