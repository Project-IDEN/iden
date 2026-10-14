import numpy as np

from engine.align import TEMPLATE, align, similarity


def test_similarity_recovers_a_rotation_scale_and_shift():
    angle, scale, shift = 0.3, 2.5, np.array([120.0, 80.0])
    rotation = np.array(
        [[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]]
    )
    landmarks = (TEMPLATE @ rotation.T) * scale + shift
    matrix = similarity(landmarks, TEMPLATE)
    mapped = landmarks @ matrix[:, :2].T + matrix[:, 2]
    assert np.allclose(mapped, TEMPLATE, atol=1e-4)


def test_every_landmark_counts():
    # One landmark off: a least-squares fit spreads the error over all five
    # rather than fitting four exactly and abandoning the fifth.
    landmarks = TEMPLATE * 2 + 50
    landmarks[2] += [12, 0]
    matrix = similarity(landmarks, TEMPLATE)
    mapped = landmarks @ matrix[:, :2].T + matrix[:, 2]
    errors = np.linalg.norm(mapped - TEMPLATE, axis=1)
    assert errors[[0, 1, 3, 4]].max() > 0.1


def test_align_crops_to_112():
    image = np.zeros((480, 640, 3), dtype=np.uint8)
    assert align(image, TEMPLATE * 2 + 100).shape == (112, 112, 3)
