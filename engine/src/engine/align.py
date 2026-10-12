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


def align(image: np.ndarray, landmarks: np.ndarray) -> np.ndarray:
    """The face rotated, scaled and cropped onto the template."""
    matrix, _ = cv2.estimateAffinePartial2D(
        landmarks.astype(np.float32), TEMPLATE, method=cv2.LMEDS
    )
    if matrix is None:
        # Collinear landmarks admit no similarity transform; an exact affine
        # fit through three of them still yields a crop to judge quality on.
        matrix = cv2.getAffineTransform(landmarks[:3].astype(np.float32), TEMPLATE[:3])
    return cv2.warpAffine(image, matrix, (SIZE, SIZE), borderValue=(0, 0, 0))
