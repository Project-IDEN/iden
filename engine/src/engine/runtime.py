"""Loading the models onto the device they will run on."""

import hashlib
from dataclasses import dataclass
from pathlib import Path

import onnxruntime as ort

from engine.manifest import Manifest, ModelFile

CUDA = "CUDAExecutionProvider"
CPU = "CPUExecutionProvider"


class ModelError(RuntimeError):
    pass


def execution_providers(device: str, available: list[str]) -> list[str]:
    """CUDA first when asked for and present, the CPU always last.

    `cuda` without a visible GPU is an error rather than a fallback: a GPU host
    whose driver broke should not keep serving at a twentieth of the speed while
    nobody notices.
    """
    if device == "cpu":
        return [CPU]
    if CUDA in available:
        return [CUDA, CPU]
    if device == "cuda":
        raise ModelError(
            "ENGINE_DEVICE=cuda but onnxruntime cannot see a GPU. Install the "
            "`gpu` extra and check the NVIDIA driver and container runtime."
        )
    return [CPU]


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _session(
    model_dir: Path, model: ModelFile, providers: list[str]
) -> ort.InferenceSession:
    path = model_dir / model.file
    if not path.is_file():
        raise ModelError(
            f"{path} is missing. Run: uv run python -m scripts.fetch_models"
        )
    # A model file is code the engine executes on every face it sees, so one
    # that is not byte-for-byte the reviewed file does not run.
    if sha256_of(path) != model.sha256:
        raise ModelError(f"{path} does not match the sha256 in the manifest.")

    options = ort.SessionOptions()
    # The recogniser declares a batch of one and accepts any; at the default
    # level every batched call logs a warning about it.
    options.log_severity_level = 3
    return ort.InferenceSession(str(path), options, providers=providers)


@dataclass
class Models:
    manifest: Manifest
    providers: list[str]
    detector: ort.InferenceSession
    recognizer: ort.InferenceSession
    anti_spoofing: list[ort.InferenceSession]

    @property
    def device(self) -> str:
        return "cuda" if self.detector.get_providers()[0] == CUDA else "cpu"


def load(manifest: Manifest, model_dir: Path, device: str) -> Models:
    providers = execution_providers(device, ort.get_available_providers())
    return Models(
        manifest=manifest,
        providers=providers,
        detector=_session(model_dir, manifest.detector, providers),
        recognizer=_session(model_dir, manifest.recognizer, providers),
        anti_spoofing=[
            _session(model_dir, model, providers) for model in manifest.anti_spoofing
        ],
    )
