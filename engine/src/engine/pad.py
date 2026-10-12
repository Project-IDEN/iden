"""Passive presentation-attack detection: does this frame show a live face?

MiniFASNet classifies a crop around the face as print attack (0), live (1) or
replay (2). Two models looking at different amounts of context are averaged, as
Silent-Face does.
"""

import cv2
import numpy as np
import onnxruntime as ort

from engine.detect import Face

LIVE = 1


def _crop(image: np.ndarray, box: np.ndarray, scale: float, size: int) -> np.ndarray:
    height, width = image.shape[:2]
    x1, y1, x2, y2 = box
    box_w, box_h = x2 - x1, y2 - y1
    scale = min((height - 1) / box_h, (width - 1) / box_w, scale)
    cx, cy = x1 + box_w / 2, y1 + box_h / 2
    half_w, half_h = box_w * scale / 2, box_h * scale / 2

    left, top = max(0, int(cx - half_w)), max(0, int(cy - half_h))
    right, bottom = min(width - 1, int(cx + half_w)), min(height - 1, int(cy + half_h))
    return cv2.resize(image[top : bottom + 1, left : right + 1], (size, size))


def _softmax(logits: np.ndarray) -> np.ndarray:
    shifted = np.exp(logits - logits.max(axis=1, keepdims=True))
    return shifted / shifted.sum(axis=1, keepdims=True)


def live_probability(
    sessions: list[ort.InferenceSession],
    scales: list[float],
    frames: list[tuple[np.ndarray, Face]],
) -> np.ndarray:
    """The mean live probability of each (image, face) pair, as one batch per model."""
    totals = np.zeros(len(frames))
    for session, scale in zip(sessions, scales, strict=True):
        model_input = session.get_inputs()[0]
        size = int(model_input.shape[-1])
        # BGR, unnormalised 0–255: how MiniFASNet was trained.
        batch = np.stack(
            [
                _crop(image, face.box, scale, size)
                .astype(np.float32)
                .transpose(2, 0, 1)
                for image, face in frames
            ]
        )
        logits = np.asarray(session.run(None, {model_input.name: batch})[0])
        totals += _softmax(logits)[:, LIVE]
    return totals / len(sessions)
