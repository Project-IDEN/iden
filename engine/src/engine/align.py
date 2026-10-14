import cv2
import numpy as np

SIZE = 112

# Where ArcFace-family recognisers expect the five landmarks in a 112×112 crop.
# Every recogniser in the manifest was trained on faces placed exactly here.
TEMPLATE = np.array(
    [
        [38.2946, 51.6963],
        [73.5318, 51.5014],
        [56.0252, 71.7366],
        [41.5493, 92.3655],
        [70.7299, 92.2041],
    ],
    dtype=np.float32,
)


def similarity(source: np.ndarray, target: np.ndarray) -> np.ndarray:
    """The 2×3 rotation, uniform scale and shift that best maps `source` onto
    `target` in the least-squares sense (Umeyama).

    Every point counts, as in the alignment the models were trained with: a
    robust fit that drops a landmark places the face somewhere they never saw.
    """
    source = source.astype(np.float64)
    target = target.astype(np.float64)
    source_mean, target_mean = source.mean(axis=0), target.mean(axis=0)
    source_centred, target_centred = source - source_mean, target - target_mean

    u, singular, vt = np.linalg.svd(target_centred.T @ source_centred / len(source))
    sign = np.eye(2)
    if np.linalg.det(u) * np.linalg.det(vt) < 0:
        sign[1, 1] = -1
    rotation = u @ sign @ vt
    variance = source_centred.var(axis=0).sum()
    scale = (singular * np.diag(sign)).sum() / variance if variance else 1.0

    shift = target_mean - scale * rotation @ source_mean
    return np.hstack([scale * rotation, shift[:, None]])


def align(image: np.ndarray, landmarks: np.ndarray) -> np.ndarray:
    """The face rotated, scaled and cropped onto the template."""
    matrix = similarity(landmarks, TEMPLATE)
    return cv2.warpAffine(image, matrix, (SIZE, SIZE), borderValue=(0, 0, 0))
