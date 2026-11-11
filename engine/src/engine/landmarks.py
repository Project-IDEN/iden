"""InsightFace's 106-point landmarks (`2d106det.onnx`), for blink and smile.

The detector's five points place a face; they cannot tell an open eye from a
closed one or a smile from a straight mouth. This model outlines the eyes and
the lips, which is what an enrolment's `blink` and `smile` steps are judged on.

The model sees a 192×192 crop centred on the detector's box, with the face at
two thirds of its width — the crop InsightFace's own `Landmark` class makes —
and its graph normalises the pixels itself, so it takes them as they are.
"""

import cv2
import numpy as np
import onnxruntime as ort

SIZE = 192
# The face's box at two thirds of the crop: room for the chin and the brow.
MARGIN = 1.5

# Point indices, by what they outline, in the picture as taken (unmirrored):
# "image-left" is the person's right. Read off the model's output on the test
# photos (engine/tests/data); the order within each group does not matter, as
# every measure below uses the group's extent, not its sequence.
IMAGE_LEFT_EYE = (33, 34, 35, 36, 37, 39, 40, 41, 42)
IMAGE_RIGHT_EYE = (87, 88, 89, 90, 91, 93, 94, 95, 96)
MOUTH = tuple(range(52, 72))
# The lips' inner outline: where a mouth's centre is.
INNER_LIPS = (54, 57, 60, 62, 65, 66, 69, 70)


def _crop_matrix(box: np.ndarray) -> np.ndarray:
    """The 2×3 shift and scale that puts `box`'s centre in the middle of the crop."""
    x1, y1, x2, y2 = box.astype(np.float64)
    scale = SIZE / (max(x2 - x1, y2 - y1) * MARGIN)
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    return np.array(
        [[scale, 0, SIZE / 2 - cx * scale], [0, scale, SIZE / 2 - cy * scale]]
    )


def landmarks(
    session: ort.InferenceSession, faces: list[tuple[np.ndarray, np.ndarray]]
) -> list[np.ndarray]:
    """The 106 points of each (image, box) pair's face, in that image's
    coordinates, as one batch."""
    if not faces:
        return []
    matrices = [_crop_matrix(box) for _, box in faces]
    crops = [
        cv2.warpAffine(image, matrix, (SIZE, SIZE), borderValue=(0, 0, 0))
        for (image, _), matrix in zip(faces, matrices, strict=True)
    ]
    # BGR to RGB, channels first; no scaling — the graph does it.
    batch = np.stack([crop[:, :, ::-1].transpose(2, 0, 1) for crop in crops]).astype(
        np.float32
    )
    output = np.asarray(session.run(None, {session.get_inputs()[0].name: batch})[0])

    points = []
    for row, matrix in zip(output, matrices, strict=True):
        # The model answers in [-1, 1] across the crop.
        crop_points = (row.reshape(-1, 2) + 1) * (SIZE / 2)
        inverse = cv2.invertAffineTransform(matrix)
        homogeneous = np.hstack([crop_points, np.ones((len(crop_points), 1))])
        points.append(homogeneous @ inverse.T)
    return points
