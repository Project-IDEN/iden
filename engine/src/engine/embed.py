import numpy as np
import onnxruntime as ort


def embed(
    session: ort.InferenceSession, faces: list[np.ndarray], mean: float, std: float
) -> np.ndarray:
    """L2-normalised embeddings of aligned BGR faces, one row each."""
    batch = (
        np.stack([face[:, :, ::-1].transpose(2, 0, 1) for face in faces]).astype(
            np.float32
        )
        - mean
    ) / std
    vectors = np.asarray(session.run(None, {session.get_inputs()[0].name: batch})[0])
    return vectors / np.linalg.norm(vectors, axis=1, keepdims=True)


def normalise(vector: np.ndarray) -> np.ndarray:
    return vector / np.linalg.norm(vector)
