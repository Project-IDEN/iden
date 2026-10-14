"""`models.toml`: which models run, and the thresholds calibrated for them."""

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class ModelFile:
    file: str
    sha256: str


@dataclass(frozen=True)
class Detector(ModelFile):
    input_sizes: list[int]
    score_threshold: float


@dataclass(frozen=True)
class Recognizer(ModelFile):
    mean: float
    std: float
    match_threshold: float
    calibrated: bool


@dataclass(frozen=True)
class Policy:
    live_threshold: float
    live_fraction: float


@dataclass(frozen=True)
class Quality:
    min_eye_distance: float
    min_sharpness: float
    min_brightness: float
    max_brightness: float
    max_frontal_yaw: float
    max_out_of_frame: float


@dataclass(frozen=True)
class Liveness:
    turn_delta: float
    pitch_delta: float
    consistency_frontal: float
    consistency_turned: float


@dataclass(frozen=True)
class Source:
    url: str
    sha256: str
    file: str | None = None
    extract: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Manifest:
    version: str
    detector: Detector
    recognizer: Recognizer
    anti_spoofing: ModelFile
    policy: Policy
    quality: Quality
    liveness: Liveness
    sources: list[Source]

    def model_files(self) -> list[ModelFile]:
        return [self.detector, self.recognizer, self.anti_spoofing]


def load(path: Path) -> Manifest:
    data = tomllib.loads(path.read_text())
    return Manifest(
        version=data["version"],
        detector=Detector(**data["detector"]),
        recognizer=Recognizer(**data["recognizer"]),
        anti_spoofing=ModelFile(**data["anti_spoofing"]),
        policy=Policy(**data["policy"]),
        quality=Quality(**data["quality"]),
        liveness=Liveness(**data["liveness"]),
        sources=[Source(**entry) for entry in data.get("source", [])],
    )
