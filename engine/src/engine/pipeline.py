"""From a set of frames to a decision."""

from collections import Counter
from dataclasses import dataclass, field

import numpy as np

from engine import liveness, quality
from engine.align import align
from engine.detect import Face, detect
from engine.embed import embed, normalise
from engine.log import logger
from engine.pad import live_probability
from engine.pose import Pose, estimate
from engine.runtime import Models
from engine.schemas import Checks, EmbedResult, EnrollResult, VerifyResult
from engine.steps import CENTRE, flash_colour, is_frontal

# Fewer than this many good frontal frames and nothing is decided.
MIN_FRONTAL = 2
MAX_TEMPLATES = 5


@dataclass
class Seen:
    """A frame in which exactly one face was found."""

    face: Face
    pose: Pose
    aligned: np.ndarray
    embedding: np.ndarray = field(default_factory=lambda: np.zeros(0))


@dataclass
class Frame:
    step: str
    image: np.ndarray
    seen: Seen | None
    reasons: list[quality.Reason]

    @property
    def good(self) -> bool:
        return self.seen is not None and not self.reasons


@dataclass
class Analysis:
    frames: list[Frame]
    reasons: list[quality.Reason]
    checks: Checks | None = None
    reference: np.ndarray | None = None

    @property
    def live(self) -> bool:
        return self.checks is not None and self.checks.live


def inspect(models: Models, step: str, image: np.ndarray) -> Frame:
    manifest = models.manifest
    faces = detect(
        models.detector,
        image,
        manifest.detector.input_sizes,
        manifest.detector.score_threshold,
    )
    if reason := quality.face_count_reason(faces):
        return Frame(step, image, None, [reason])

    face = faces[0]
    pose = estimate(face.landmarks)
    aligned = align(image, face.landmarks)
    reasons = quality.assess(
        image, face, aligned, pose, manifest.quality, frontal=is_frontal(step)
    )
    return Frame(step, image, Seen(face, pose, aligned), reasons)


def _reasons(frames: list[Frame]) -> list[quality.Reason]:
    counts: Counter[quality.Reason] = Counter(
        reason for frame in frames for reason in frame.reasons
    )
    return [reason for reason, _ in counts.most_common()]


def _centre(frames: list[Frame]) -> list[tuple[Frame, Seen]]:
    """Good frontal frames: the ones identity and anti-spoofing are judged on."""
    return [(f, f.seen) for f in frames if f.step == CENTRE and f.good and f.seen]


def _complete(frames: list[Frame]) -> bool:
    # Movement and flash frames are judged on landmarks and colour, so any
    # detected face will do; a turned head is supposed to fail frontal checks.
    others_seen = all(f.seen is not None for f in frames if f.step != CENTRE)
    return len(_centre(frames)) >= MIN_FRONTAL and others_seen


def analyse(models: Models, images: list[np.ndarray], steps: list[str]) -> Analysis:
    frames = [
        inspect(models, step, image) for step, image in zip(steps, images, strict=True)
    ]
    if not _complete(frames):
        return Analysis(frames, _reasons(frames) or ["no_face"])

    manifest = models.manifest
    seen = [(f, f.seen) for f in frames if f.seen is not None]
    vectors = embed(
        models.recognizer,
        [s.aligned for _, s in seen],
        manifest.recognizer.mean,
        manifest.recognizer.std,
    )
    for (_, s), vector in zip(seen, vectors, strict=True):
        s.embedding = vector

    centre = _centre(frames)
    reference = normalise(np.mean([s.embedding for _, s in centre], axis=0))

    probabilities = live_probability(
        models.anti_spoofing, [(f.image, s.face.landmarks) for f, s in centre]
    ).tolist()
    spoofing = liveness.anti_spoofing(probabilities, manifest.policy)

    baseline = Pose(
        yaw=float(np.median([s.pose.yaw for _, s in centre])),
        pitch=float(np.median([s.pose.pitch for _, s in centre])),
        eye_distance=0.0,
    )
    performed: dict[str, list[Pose]] = {}
    for f, s in seen:
        if not is_frontal(f.step):
            performed.setdefault(f.step, []).append(s.pose)
    moved = liveness.actions(baseline, performed, manifest.liveness)

    reflected = liveness.flash(
        [
            (colour, liveness.face_chroma(f.image, s.face))
            for f, s in seen
            if (colour := flash_colour(f.step))
        ],
        manifest.liveness,
    )

    same = liveness.consistency(
        reference,
        [s.embedding for f, s in seen if is_frontal(f.step)],
        [s.embedding for f, s in seen if not is_frontal(f.step)],
        manifest.liveness,
    )

    checks = Checks(
        anti_spoofing=spoofing.passed,
        anti_spoofing_score=spoofing.score,
        actions=moved.passed,
        actions_score=moved.score,
        flash=reflected.passed,
        flash_score=reflected.score,
        flash_spread=reflected.spread,
        consistent=same.passed,
        consistency_score=same.score,
    )
    # Numbers only, never a picture or an identity: what an operator tuning a
    # kiosk's camera and light needs to see, and what tells the checks apart.
    logger.info(
        "Liveness",
        live=checks.live,
        **checks.model_dump(
            exclude={"anti_spoofing", "actions", "flash", "consistent"}
        ),
        live_per_frame=[round(p, 3) for p in probabilities],
        movement={
            step: [
                round(pose.yaw - baseline.yaw, 3)
                if "turn" in step
                else round(pose.pitch - baseline.pitch, 3)
                for pose in poses
            ]
            for step, poses in performed.items()
        },
    )
    return Analysis(frames, _reasons(frames), checks, reference)


def enroll(models: Models, images: list[np.ndarray], steps: list[str]) -> EnrollResult:
    analysis = analyse(models, images, steps)
    result = EnrollResult(
        usable=analysis.checks is not None,
        reasons=analysis.reasons,
        checks=analysis.checks,
        live=analysis.live,
        model_version=models.manifest.version,
    )
    if not analysis.live:
        return result

    index = {id(frame): i for i, frame in enumerate(analysis.frames)}
    best = sorted(
        (
            (quality.score(s.aligned, s.pose), s.embedding, index[id(f)])
            for f, s in _centre(analysis.frames)
        ),
        key=lambda entry: entry[0],
        reverse=True,
    )[:MAX_TEMPLATES]
    result.embeddings = [vector.tolist() for _, vector, _ in best]
    result.qualities = [score for score, _, _ in best]
    result.sources = [source for _, _, source in best]
    return result


def embed_stills(models: Models, images: list[np.ndarray]) -> EmbedResult:
    """Embeddings of photos already accepted at enrolment, for a new model.

    No liveness: these are the provider's own stored enrolment photos, which
    passed it when they were taken. Never reachable with a fresh capture.
    """
    manifest = models.manifest
    frames = [inspect(models, CENTRE, image) for image in images]
    seen = [f.seen for f in frames if f.seen is not None]
    vectors = (
        embed(
            models.recognizer,
            [s.aligned for s in seen],
            manifest.recognizer.mean,
            manifest.recognizer.std,
        )
        if seen
        else []
    )
    found = iter(vectors)
    return EmbedResult(
        model_version=manifest.version,
        embeddings=[
            next(found).tolist() if f.seen is not None else None for f in frames
        ],
    )


def similarity(probe: np.ndarray, templates: np.ndarray) -> float:
    """Best of: the closest single template, and the templates' centroid."""
    templates = templates / np.linalg.norm(templates, axis=1, keepdims=True)
    centroid = normalise(templates.mean(axis=0))
    return float(max((templates @ probe).max(), centroid @ probe))


def verify(
    models: Models,
    images: list[np.ndarray],
    steps: list[str],
    templates: list[list[float]],
) -> VerifyResult:
    analysis = analyse(models, images, steps)
    version = models.manifest.version
    if analysis.reference is None:
        return VerifyResult(
            usable=False, reasons=analysis.reasons, model_version=version
        )

    score = similarity(analysis.reference, np.asarray(templates, dtype=np.float32))
    return VerifyResult(
        usable=True,
        reasons=analysis.reasons,
        checks=analysis.checks,
        live=analysis.live,
        model_version=version,
        matched=score >= models.manifest.recognizer.match_threshold,
        similarity=score,
    )
