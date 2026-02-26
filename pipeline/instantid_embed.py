"""InstantID-style identity embedding from a single face image.
Uses a lightweight path when full InstantID is not available (placeholder embedding)."""
from pathlib import Path

import numpy as np


def extract_instantid_embedding(face_image_path: str, output_embed_path: str) -> None:
    """Extract identity embedding from face image and save as .npy.
    When InstantID/InsightFace is not installed, saves a placeholder embedding
    so the pipeline can still run; video stage will use reference image only.
    """
    try:
        from insightface.app import FaceAnalysis
        import cv2
        app = FaceAnalysis(providers=["CPUExecutionProvider"])
        app.prepare(ctx_id=0, det_size=(640, 640))
        img = cv2.imread(face_image_path)
        if img is None:
            raise ValueError("Could not load face image")
        faces = app.get(img)
        if not faces:
            raise ValueError("No face in image")
        face = faces[0]
        embedding = face.embedding
        Path(output_embed_path).parent.mkdir(parents=True, exist_ok=True)
        np.save(output_embed_path, embedding.astype(np.float32))
        return
    except ImportError:
        pass
    # Placeholder: save a fixed-size zero embedding so downstream expects same shape
    # Video stage can check for all zeros and fall back to reference image conditioning only
    Path(output_embed_path).parent.mkdir(parents=True, exist_ok=True)
    placeholder = np.zeros(512, dtype=np.float32)
    np.save(output_embed_path, placeholder)
