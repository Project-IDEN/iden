from pathlib import Path

import pytest

from engine.manifest import ModelFile
from engine.runtime import CPU, CUDA, ModelError, _session, execution_providers


def test_auto_uses_the_gpu_when_there_is_one():
    assert execution_providers("auto", [CUDA, CPU]) == [CUDA, CPU]
    assert execution_providers("auto", [CPU]) == [CPU]


def test_cpu_never_touches_the_gpu():
    assert execution_providers("cpu", [CUDA, CPU]) == [CPU]


def test_cuda_without_a_gpu_refuses_to_start():
    with pytest.raises(ModelError):
        execution_providers("cuda", [CPU])


def test_a_model_that_is_not_the_reviewed_file_does_not_load(tmp_path: Path):
    (tmp_path / "model.onnx").write_bytes(b"not the model")
    with pytest.raises(ModelError, match="sha256"):
        _session(tmp_path, ModelFile("model.onnx", "0" * 64), [CPU])


def test_a_missing_model_says_how_to_fetch_it(tmp_path: Path):
    with pytest.raises(ModelError, match="fetch_models"):
        _session(tmp_path, ModelFile("model.onnx", "0" * 64), [CPU])
