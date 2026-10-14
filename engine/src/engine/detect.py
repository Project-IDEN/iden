"""SCRFD face detection: boxes and five landmarks.

The landmarks are the left eye, right eye, nose tip and the two mouth corners,
in image coordinates — "left" meaning the left of the picture.
"""

from dataclasses import dataclass

import cv2
import numpy as np
import onnxruntime as ort

STRIDES = (8, 16, 32)
ANCHORS_PER_CELL = 2
NMS_IOU = 0.4


@dataclass(frozen=True)
class Face:
    box: np.ndarray  # x1, y1, x2, y2
    score: float
    landmarks: np.ndarray  # (5, 2)

    @property
    def area(self) -> float:
        width, height = self.box[2:] - self.box[:2]
        return float(width * height)


def _letterbox(image: np.ndarray, size: int) -> tuple[np.ndarray, float]:
    height, width = image.shape[:2]
    scale = size / max(height, width)
    resized = cv2.resize(image, (round(width * scale), round(height * scale)))
    canvas = np.zeros((size, size, 3), dtype=np.uint8)
    canvas[: resized.shape[0], : resized.shape[1]] = resized
    return canvas, scale


def _anchor_centres(size: int, stride: int) -> np.ndarray:
    cells = size // stride
    ys, xs = np.mgrid[:cells, :cells]
    centres = np.stack([xs, ys], axis=-1).reshape(-1, 2).astype(np.float32) * stride
    return np.repeat(centres, ANCHORS_PER_CELL, axis=0)


def _candidates(
    session: ort.InferenceSession, image: np.ndarray, size: int, threshold: float
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Boxes, scores and landmarks above `threshold` at one input size, before NMS."""
    canvas, scale = _letterbox(image, size)
    blob = cv2.dnn.blobFromImage(
        canvas, 1 / 128, (size, size), (127.5, 127.5, 127.5), swapRB=True
    )
    outputs = session.run(None, {session.get_inputs()[0].name: blob})

    boxes, scores, landmarks = [], [], []
    count = len(STRIDES)
    for index, stride in enumerate(STRIDES):
        score = np.asarray(outputs[index])[:, 0]
        distances = np.asarray(outputs[index + count]) * stride
        points = np.asarray(outputs[index + 2 * count]) * stride
        centres = _anchor_centres(size, stride)

        keep = score >= threshold
        centres, distances, points = centres[keep], distances[keep], points[keep]
        boxes.append(
            np.hstack([centres - distances[:, :2], centres + distances[:, 2:]])
        )
        landmarks.append(centres[:, None, :] + points.reshape(-1, 5, 2))
        scores.append(score[keep])

    return (
        np.concatenate(boxes) / scale,
        np.concatenate(scores),
        np.concatenate(landmarks) / scale,
    )


def detect(
    session: ort.InferenceSession,
    image: np.ndarray,
    sizes: list[int],
    threshold: float,
) -> list[Face]:
    """Every face above `threshold`, largest first.

    Run at every input size and merged by one NMS. SCRFD finds faces of a
    certain range of sizes in its input: a large size finds a face across the
    room, a small one a face right in front of the camera that fills the
    picture and that the large size misses.
    """
    found = [_candidates(session, image, size, threshold) for size in sizes]
    all_boxes = np.concatenate([boxes for boxes, _, _ in found])
    all_scores = np.concatenate([scores for _, scores, _ in found])
    all_landmarks = np.concatenate([landmarks for _, _, landmarks in found])
    if len(all_scores) == 0:
        return []

    xywh = np.hstack([all_boxes[:, :2], all_boxes[:, 2:] - all_boxes[:, :2]])
    kept = cv2.dnn.NMSBoxes(xywh.tolist(), all_scores.tolist(), threshold, NMS_IOU)
    faces = [
        Face(all_boxes[i], float(all_scores[i]), all_landmarks[i])
        for i in np.asarray(kept).reshape(-1)
    ]
    return sorted(faces, key=lambda face: face.area, reverse=True)
