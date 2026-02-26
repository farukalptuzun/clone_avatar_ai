"""UGC packaging: TR altyazı, product card/CTA overlay, mp4 export, watermark. Çıktı yerel diske kaydedilir."""
import json
import shutil
from pathlib import Path

from shared.config import settings
from shared.storage import get_result_local_path


def _timing_to_srt(timing_path: str) -> str:
    """Build SRT content from tts_timing.json (word-level). Merge to sentence-level for readability."""
    if not timing_path or not Path(timing_path).exists():
        return ""
    with open(timing_path, encoding="utf-8") as f:
        data = json.load(f)
    words = data.get("words", [])
    if not words:
        return ""
    srt_lines = []
    # One subtitle per 3-5 words for readability
    chunk_size = 4
    for i in range(0, len(words), chunk_size):
        chunk = words[i : i + chunk_size]
        start_ms = chunk[0]["start_ms"]
        end_ms = chunk[-1]["end_ms"]
        text = " ".join(c["text"] for c in chunk)
        srt_lines.append(f"{len(srt_lines)+1}")
        srt_lines.append(_ms_to_srt_time(start_ms) + " --> " + _ms_to_srt_time(end_ms))
        srt_lines.append(text)
        srt_lines.append("")
    return "\n".join(srt_lines)


def _ms_to_srt_time(ms: float) -> str:
    s = int(ms) // 1000
    m, s = s // 60, s % 60
    h, m = m // 60, m % 60
    frac = int(ms % 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{frac:03d}"


def _add_subtitles_and_watermark(
    video_path: str,
    output_path: str,
    timing_path: str | None,
    job_id: str,
) -> None:
    """Burn subtitles (if timing) and watermark into video. Uses OpenCV when ffmpeg not available."""
    import cv2
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError("Cannot open video")
    fps = cap.get(cv2.CAP_PROP_FPS) or 25
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(output_path, fourcc, fps, (w, h))

    cues = []
    if timing_path and Path(timing_path).exists():
        with open(timing_path, encoding="utf-8") as f:
            data = json.load(f)
        cues = data.get("words", [])

    frame_idx = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        t_ms = frame_idx * 1000.0 / fps
        # Subtitle: find current word(s)
        for cue in cues:
            if cue["start_ms"] <= t_ms <= cue["end_ms"]:
                cv2.putText(
                    frame, cue["text"], (w // 2 - 100, h - 80),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2
                )
                cv2.putText(
                    frame, cue["text"], (w // 2 - 100, h - 80),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 1
                )
                break
        # Watermark
        cv2.putText(
            frame, f"CloneAvatar #{job_id[:8]}", (20, h - 20),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1
        )
        out.write(frame)
        frame_idx += 1
    cap.release()
    out.release()


def _overlay_product_image(video_path: str, product_image_path: str, output_path: str) -> str:
    """Overlay product image at bottom-right; return output_path."""
    import cv2
    cap = cv2.VideoCapture(video_path)
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 25
    product = cv2.imread(product_image_path)
    if product is None:
        return video_path
    # Scale product to ~20% height, bottom-right
    ph, pw = product.shape[:2]
    max_h = int(h * 0.2)
    scale = min(1.0, max_h / ph)
    pw, ph = int(pw * scale), int(ph * scale)
    product = cv2.resize(product, (pw, ph))
    x1, y1 = w - pw - 40, h - ph - 80
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(output_path, fourcc, fps, (w, h))
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if 0 <= x1 < w and 0 <= y1 < h:
            roi = frame[y1 : y1 + ph, x1 : x1 + pw]
            if roi.shape[:2] == product.shape[:2]:
                mask = product[:, :, 2] if len(product.shape) == 3 else None
                cv2.addWeighted(product, 0.9, roi, 0.1, 0, roi)
                frame[y1 : y1 + ph, x1 : x1 + pw] = roi
        out.write(frame)
    cap.release()
    out.release()
    return output_path


def run_ugc_pack(payload: dict) -> dict:
    job_id = payload.get("job_id", "")
    video_path = payload.get("video_path")
    if not video_path or not Path(video_path).exists():
        return {"error": "Missing or invalid video_path"}

    base_dir = Path(video_path).parent
    # Çıktı yerel dizine: storage/outputs/{job_id}/output.mp4
    out_dir = get_result_local_path(job_id).parent
    out_dir.mkdir(parents=True, exist_ok=True)
    final_path = str(get_result_local_path(job_id, "output.mp4"))

    timing_path = payload.get("timing_path")
    product_image_path = payload.get("product_image_path")

    try:
        # 1) Altyazı + watermark
        with_subs_path = str(base_dir / "with_subs.mp4")
        _add_subtitles_and_watermark(video_path, with_subs_path, timing_path, job_id)

        # 2) Ürün görseli varsa overlay
        if product_image_path and Path(product_image_path).exists():
            _overlay_product_image(with_subs_path, product_image_path, final_path)
        else:
            shutil.move(with_subs_path, final_path)

        return {"result_key": "output.mp4"}
    except Exception as e:
        return {"error": f"UGC pack failed: {e}"}
