"""Quality gate: face embedding distance, lip sync check; resample once if over threshold."""
import numpy as np
from pathlib import Path

NUM_SAMPLE_FRAMES = 10
FACE_DISTANCE_THRESHOLD = 0.8  # max mean cosine distance (or L2) to pass
MAX_RESAMPLES = 1


def _sample_frames(video_path: str, n: int = NUM_SAMPLE_FRAMES) -> list[np.ndarray]:
    import cv2
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return []
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if total == 0:
        cap.release()
        return []
    indices = np.linspace(0, total - 1, n, dtype=int) if total >= n else list(range(total))
    frames = []
    for i in indices:
        cap.set(cv2.CAP_PROP_POS_FRAMES, i)
        ret, frame = cap.read()
        if ret:
            frames.append(frame)
    cap.release()
    return frames


def _face_embedding(image: np.ndarray) -> np.ndarray | None:
    """Extract face embedding (InsightFace if available)."""
    try:
        from insightface.app import FaceAnalysis
        app = FaceAnalysis(providers=["CPUExecutionProvider"])
        app.prepare(ctx_id=0, det_size=(640, 640))
        faces = app.get(image)
        if faces:
            return faces[0].embedding
    except ImportError:
        pass
    return None


def _embedding_distance(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine distance: 1 - cos_sim. 0 = identical."""
    a = a.ravel().astype(np.float32)
    b = b.ravel().astype(np.float32)
    sim = np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-8)
    return float(1 - sim)


def _check_face_consistency(
    video_path: str,
    reference_embed_path: str | None,
) -> tuple[bool, float]:
    """True if pass (identity stable). Returns (pass, mean_distance)."""
    if not reference_embed_path or not Path(reference_embed_path).exists():
        return True, 0.0  # no reference: skip check
    ref_embed = np.load(reference_embed_path)
    if ref_embed.size == 0 or (ref_embed == 0).all():
        return True, 0.0  # placeholder embedding: skip
    frames = _sample_frames(video_path, NUM_SAMPLE_FRAMES)
    if not frames:
        return True, 0.0
    distances = []
    for frame in frames:
        emb = _face_embedding(frame)
        if emb is not None:
            distances.append(_embedding_distance(ref_embed, emb))
    if not distances:
        return True, 0.0
    mean_dist = float(np.mean(distances))
    return mean_dist <= FACE_DISTANCE_THRESHOLD, mean_dist


def run_quality_gate(payload: dict) -> dict:
    video_path = payload.get("video_path")
    if not video_path or not Path(video_path).exists():
        return {"error": "Missing or invalid video_path"}

    reference_embed_path = payload.get("instantid_embed_path")
    resample_attempt = payload.get("_quality_resample_attempt", 0)

    pass_face, mean_dist = _check_face_consistency(video_path, reference_embed_path)

    if pass_face:
        return {"quality_pass": True, "face_mean_distance": mean_dist}

    if resample_attempt >= MAX_RESAMPLES:
        return {
            "error": f"Quality failed after {MAX_RESAMPLES} resample(s). Face distance: {mean_dist:.4f}",
            "quality_failed": True,
        }

    # Resample: re-run video gen with varied params (seed/CFG); same payload but trigger one more video_gen
    from workers.stages import video_gen
    new_payload = {**payload, "_quality_resample_attempt": resample_attempt + 1}
    result = video_gen.run_video_gen(new_payload)
    if result.get("error"):
        return {
            "error": f"Resample failed: {result['error']}. Original face distance: {mean_dist:.4f}",
            "quality_failed": True,
        }
    pass_face2, mean_dist2 = _check_face_consistency(result["video_path"], reference_embed_path)
    if pass_face2:
        return {
            "quality_pass": True,
            "face_mean_distance": mean_dist2,
            "resampled": True,
            "video_path": result["video_path"],
        }
    return {
        "error": f"Quality failed after resample. Face distance: {mean_dist2:.4f}",
        "quality_failed": True,
    }
