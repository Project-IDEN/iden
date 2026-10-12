import numpy as np

from eval.run import threshold_at, write_threshold


def test_threshold_admits_at_most_the_target_share_of_impostors():
    impostor = np.linspace(-0.2, 0.5, 10_000)
    threshold = threshold_at(impostor, 1e-3)
    assert np.mean(impostor > threshold) <= 1e-3
    assert np.mean(impostor >= threshold) > 0


def test_writing_the_threshold_marks_the_manifest_calibrated(tmp_path):
    manifest = tmp_path / "models.toml"
    manifest.write_text("[recognizer]\nmatch_threshold = 0.40\ncalibrated = false\n")
    write_threshold(manifest, 0.3172)
    assert manifest.read_text() == (
        "[recognizer]\nmatch_threshold = 0.3172\ncalibrated = true\n"
    )
