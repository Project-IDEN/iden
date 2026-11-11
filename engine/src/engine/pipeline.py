"""From a set of frames to a decision."""

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import numpy as np

from engine import expression, liveness, quality
from engine.align import align
from engine.detect import Face, detect
from engine.embed import embed, normalise
from engine.expression import Expression
from engine.landmarks import landmarks
from engine.log import logger
from engine.manifest import Policy
from engine.pad import live_probability
from engine.pose import Pose, estimate
from engine.runtime import Models
from engine.schemas import Checks, EmbedResult, EnrollResult, VerifyResult
from engine.steps import CENTRE, EXPRESSIONS

# Fewer than this many good frontal frames and nothing is decided.
MIN_FRONTAL = 2
MAX_TEMPLATES = 5

# One detector run does not keep every core busy, so frames are inspected a few
# at a time: measured, a 9-frame capture spends about a quarter less in detection.
_inspectors = ThreadPoolExecutor(max_workers=4, thread_name_prefix="inspect")


@dataclass
class Seen:
    """A frame in which exactly one face was found."""

    face: Face
    pose: Pose
    aligned: np.ndarray
    embedding: np.ndarray = field(default_factory=lambda: np.zeros(0))
    # From the 106 landmarks; measured at enrolment only.
    expression: Expression | None = None


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
    # The good frontal frames anti-spoofing judged, and templates are made from:
    # at enrolment, only those with the eyes open.
    judged: list[tuple[Frame, Seen]] = field(default_factory=list)

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
        image, face, aligned, pose, manifest.quality, frontal=step == CENTRE
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
    # Movement frames are judged on landmarks, so any detected face will do; a
    # turned head is supposed to fail frontal checks. One frame per movement is
    # enough: a head turned far may lose the detector in the others.
    movements = {f.step for f in frames if f.step != CENTRE}
    seen = {f.step for f in frames if f.step != CENTRE and f.seen is not None}
    return len(_centre(frames)) >= MIN_FRONTAL and seen == movements


def _measure(models: Models, seen: list[tuple[Frame, Seen]]) -> None:
    """Each face's eyes and mouth, from the 106 landmarks, as one batch."""
    points = landmarks(models.landmarker, [(f.image, s.face.box) for f, s in seen])
    for (_, s), found in zip(seen, points, strict=True):
        s.expression = expression.measure(found)


def open_eyed(
    centre: list[tuple[Frame, Seen]], neutral: Expression, rules: Policy
) -> list[tuple[Frame, Seen]]:
    """The frontal frames with the eyes open. A closed eye can read as a print
    to the anti-spoofing model, and makes a poor template."""
    return [
        (f, s)
        for f, s in centre
        if s.expression is not None
        and liveness.eyes_open(s.expression.eye_openness, neutral.eye_openness, rules)
    ]


def _expressions(
    seen: list[tuple[Frame, Seen]],
    steps: list[str],
    neutral: Expression,
    models: Models,
) -> dict[str, liveness.Verdict]:
    """A verdict for each blink and smile step asked for, on that step's frames
    in the order they were captured."""
    rules = models.manifest.policy
    verdicts: dict[str, liveness.Verdict] = {}
    for step in EXPRESSIONS:
        if step not in steps:
            continue
        found = [s.expression for f, s in seen if f.step == step and s.expression]
        verdicts[step] = (
            liveness.blink(neutral.eye_openness, [e.eye_openness for e in found], rules)
            if step == "blink"
            else liveness.smile(neutral, found, rules)
        )
    return verdicts


def analyse(
    models: Models,
    images: list[np.ndarray],
    steps: list[str],
    *,
    expressions: bool = False,
) -> Analysis:
    """Every check on one capture.

    With `expressions`, which enrolment asks for, the 106 landmarks are read
    too: a blink or smile step is judged on them, and anti-spoofing and the
    templates use only frontal frames with the eyes open. A capture with a
    blink or smile step always reads them. Without, which is every sign-in, the
    checks are the head-pose ones alone.
    """
    expressions = expressions or any(step in EXPRESSIONS for step in steps)
    frames = list(
        _inspectors.map(lambda step, image: inspect(models, step, image), steps, images)
    )
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

    judged = centre
    neutral: Expression | None = None
    if expressions:
        _measure(models, seen)
        neutral = expression.neutral(
            [s.expression for _, s in centre if s.expression is not None]
        )
        judged = open_eyed(centre, neutral, manifest.policy)

    probabilities = (
        live_probability(
            models.anti_spoofing, [(f.image, s.face.landmarks) for f, s in judged]
        ).tolist()
        if judged
        else []
    )
    spoofing = liveness.anti_spoofing(probabilities, manifest.policy)

    baseline = Pose(
        yaw=float(np.median([s.pose.yaw for _, s in centre])),
        pitch=float(np.median([s.pose.pitch for _, s in centre])),
        eye_distance=0.0,
    )
    performed: dict[str, list[Pose]] = {}
    for f, s in seen:
        if f.step in liveness.EXPECTED:
            performed.setdefault(f.step, []).append(s.pose)
    expressed = (
        _expressions(seen, steps, neutral, models) if neutral is not None else {}
    )
    moved = liveness.combined(
        (
            [liveness.actions(baseline, performed, manifest.liveness)]
            if performed
            else []
        )
        + list(expressed.values())
    )

    same = liveness.consistency(
        reference,
        [s.embedding for f, s in seen if f.step == CENTRE],
        [s.embedding for f, s in seen if f.step != CENTRE],
        manifest.liveness,
    )

    checks = Checks(
        anti_spoofing=spoofing.passed,
        anti_spoofing_score=spoofing.score,
        actions=moved.passed,
        actions_score=moved.score,
        consistent=same.passed,
        consistency_score=same.score,
    )
    # Numbers only, never a picture or an identity: what an operator tuning a
    # kiosk's camera and light needs to see, and what tells the checks apart.
    logger.info(
        "Liveness",
        live=checks.live,
        **checks.model_dump(exclude={"anti_spoofing", "actions", "consistent"}),
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
        **(
            {
                "expression": {
                    step: round(verdict.score, 3) for step, verdict in expressed.items()
                },
                "eyes_open_frontal": f"{len(judged)}/{len(centre)}",
            }
            if expressions
            else {}
        ),
    )
    return Analysis(frames, _reasons(frames), checks, reference, judged)


def enroll(models: Models, images: list[np.ndarray], steps: list[str]) -> EnrollResult:
    analysis = analyse(models, images, steps, expressions=True)
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
            for f, s in analysis.judged
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
    frames = list(_inspectors.map(lambda image: inspect(models, CENTRE, image), images))
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
