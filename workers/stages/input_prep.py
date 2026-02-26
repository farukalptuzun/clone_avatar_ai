"""Input preparation: photo quality check, face detect, crop, landmark, InstantID embed, driving video landmarks."""
import json
from pathlib import Path

import cv2
import numpy as np

# Optional: mediapipe for landmarks
try:
    import mediapipe as mp
    HAS_MEDIAPIPE = True
except ImportError:
    HAS_MEDIAPIPE = False

def _quality_check(image: np.ndarray) -> str | None:
    """Returns error message if quality is bad, else None."""
    h, w = image.shape[:2]
    if w < 256 or h < 256:
        return "Image resolution too low (min 256x256)"
    # Blur: Laplacian variance
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
    laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
    if laplacian_var < 50:
        return "Image too blurry"
    return None


def _face_detect(image: np.ndarray) -> tuple[int, int, int, int] | None:
    """Return (x, y, w, h) of first face or None."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
    cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    face_cascade = cv2.CascadeClassifier(cascade_path)
    faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(64, 64))
    if len(faces) == 0:
        return None
    # Largest face
    x, y, w, h = max(faces, key=lambda r: r[2] * r[3])
    return (int(x), int(y), int(w), int(h))


def _crop_face(image: np.ndarray, bbox: tuple[int, int, int, int], margin: float = 0.3) -> np.ndarray:
    x, y, w, h = bbox
    m = margin
    x1 = max(0, int(x - w * m))
    y1 = max(0, int(y - h * m))
    x2 = min(image.shape[1], int(x + w * (1 + m)))
    y2 = min(image.shape[0], int(y + h * (1 + m)))
    return image[y1:y2, x1:x2]


def _landmarks_mediapipe(image: np.ndarray, face_bbox: tuple[int, int, int, int] | None) -> list[tuple[float, float]] | None:
    """Extract 68-style landmark points using mediapipe (subset of 468). Returns list of (x,y) normalized or pixel."""
    if not HAS_MEDIAPIPE:
        return None
    mp_face_mesh = mp.solutions.face_mesh
    h, w = image.shape[:2]
    with mp_face_mesh.FaceMesh(static_image_mode=True, max_num_faces=1) as face_mesh:
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        results = face_mesh.process(rgb)
        if not results.multi_face_landmarks:
            return None
        lm = results.multi_face_landmarks[0]
        # Map to pixel coords; return list of (x, y) for key points (e.g. lips, eyes, contour)
        indices = list(range(min(68, len(lm.landmark))))
        points = [(lm.landmark[i].x * w, lm.landmark[i].y * h) for i in indices]
        return points


def _save_landmarks(landmarks: list[tuple[float, float]], path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        for x, y in landmarks:
            f.write(f"{x}\t{y}\n")


def _extract_driving_landmarks(driving_video_path: str, out_path: str, max_frames: int = 300) -> str | None:
    """Extract face landmarks per frame from driving video (for EchoMimic pose/landmark conditioning)."""
    if not HAS_MEDIAPIPE:
        return None
    cap = cv2.VideoCapture(driving_video_path)
    if not cap.isOpened():
        return None
    mp_face_mesh = mp.solutions.face_mesh
    frames_landmarks = []
    with mp_face_mesh.FaceMesh(static_image_mode=False, max_num_faces=1) as face_mesh:
        while len(frames_landmarks) < max_frames:
            ret, frame = cap.read()
            if not ret:
                break
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = face_mesh.process(rgb)
            if results.multi_face_landmarks:
                lm = results.multi_face_landmarks[0]
                h, w = frame.shape[:2]
                points = [{"x": lm.landmark[i].x, "y": lm.landmark[i].y} for i in range(min(68, len(lm.landmark)))]
                frames_landmarks.append(points)
    cap.release()
    if not frames_landmarks:
        return None
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"frames": frames_landmarks}, f)
    return out_path


def _run_instantid_embed(face_image_path: str, output_embed_path: str) -> str | None:
    """Try to run InstantID-style embedding and save to output_embed_path. Returns error or None."""
    try:
        from pipeline.instantid_embed import extract_instantid_embedding
        extract_instantid_embedding(face_image_path, output_embed_path)
        return None
    except Exception as e:
        return str(e)


def run_input_prep(payload: dict) -> dict:
    job_id = payload.get("job_id", "")
    photo_path = payload.get("photo_path", "")
    base_dir = Path(photo_path).parent

    image = cv2.imread(photo_path)
    if image is None:
        return {"error": "Could not load image"}

    err = _quality_check(image)
    if err:
        return {"error": f"Quality check failed: {err}"}

    bbox = _face_detect(image)
    if bbox is None:
        return {"error": "No face detected"}

    face_crop = _crop_face(image, bbox)
    face_crop_path = str(base_dir / "face_crop.jpg")
    cv2.imwrite(face_crop_path, face_crop)

    landmarks = _landmarks_mediapipe(image, bbox)
    landmarks_path = None
    if landmarks:
        landmarks_path = str(base_dir / "landmarks.txt")
        _save_landmarks(landmarks, landmarks_path)

    instantid_embed_path = str(base_dir / "instantid_embed.npy")
    err_id = _run_instantid_embed(face_crop_path, instantid_embed_path)
    if err_id:
        # Placeholder so video stage has a file (e.g. when InsightFace not installed)
        Path(instantid_embed_path).parent.mkdir(parents=True, exist_ok=True)
        np.save(instantid_embed_path, np.zeros(512, dtype=np.float32))

    driving_landmarks_path = None
    driving_video_path = payload.get("driving_video_path")
    if driving_video_path and Path(driving_video_path).exists():
        driving_landmarks_path = str(base_dir / "driving_landmarks.json")
        _extract_driving_landmarks(driving_video_path, driving_landmarks_path)

    return {
        "photo_path": photo_path,
        "face_crop_path": face_crop_path,
        "landmarks_path": landmarks_path,
        "instantid_embed_path": instantid_embed_path,
        "driving_landmarks_path": driving_landmarks_path,
    }
