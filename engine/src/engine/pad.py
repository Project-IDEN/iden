"""Passive presentation-attack detection: does this frame show a live face?

InsightFace's liveness model judges an 80×80 crop aligned on the five landmarks,
with the face at under half the crop's width so the edges of a print or a
screen are in view. It outputs the live probability directly.
"""

import cv2
import numpy as np
import onnxruntime as ort

from engine.align import similarity

SIZE = 80

# Where the model expects the five landmarks in its crop.
TEMPLATE = np.array(
    [[32.03, 38.06], [47.89, 37.98], [40.01, 47.08], [33.50, 56.36], [46.63, 56.29]],
    dtype=np.float32,
)


def out_of_frame(image: np.ndarray, landmarks: np.ndarray) -> float:
    """Share of the crop that would fall outside the picture.

    The model judges the context around the face; a face at the edge of the
    picture, or too close to the camera, leaves too little of it to judge.
    """
    inside = cv2.warpAffine(
        np.ones(image.shape[:2], dtype=np.float32),
        similarity(landmarks, TEMPLATE),
        (SIZE, SIZE),
        borderValue=0,
    )
    return float(1 - inside.mean())


def _crop(image: np.ndarray, landmarks: np.ndarray) -> np.ndarray:
    return cv2.warpAffine(
        image,
        similarity(landmarks, TEMPLATE),
        (SIZE, SIZE),
        borderMode=cv2.BORDER_REPLICATE,
    )


def live_probability(
    session: ort.InferenceSession, frames: list[tuple[np.ndarray, np.ndarray]]
) -> np.ndarray:
    """The live probability of each (image, landmarks) pair, as one batch."""
    # RGB scaled to 0–1: how the model was trained.
    batch = (
        np.stack(
            [
                _crop(image, landmarks)[:, :, ::-1].transpose(2, 0, 1)
                for image, landmarks in frames
            ]
        ).astype(np.float32)
        / 255
    )
    return np.asarray(session.run(None, {session.get_inputs()[0].name: batch})[0])
