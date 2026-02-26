"""Postprocess: temporal smoothing, face enhancement, 9:16 crop to 1080x1920."""
from pathlib import Path

import cv2
import numpy as np

TARGET_W = 1080
TARGET_H = 1920
SMOOTH_RADIUS = 1  # frames each side for temporal smoothing


def run_postprocess(payload: dict) -> dict:
    video_path = payload.get("video_path")
    if not video_path or not Path(video_path).exists():
        return {"error": "Missing or invalid video_path"}

    base_dir = Path(video_path).parent
    out_path = str(base_dir / "postprocessed.mp4")

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return {"error": "Could not open video"}

    fps = cap.get(cv2.CAP_PROP_FPS) or 25
    n_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if n_frames == 0:
        cap.release()
        return {"error": "Video has no frames"}

    # Read all frames
    frames = []
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        frames.append(frame)
    cap.release()

    # Temporal smoothing: moving average over 2*SMOOTH_RADIUS+1 frames
    if len(frames) > 2 * SMOOTH_RADIUS + 1:
        smoothed = []
        for i in range(len(frames)):
            lo = max(0, i - SMOOTH_RADIUS)
            hi = min(len(frames), i + SMOOTH_RADIUS + 1)
            window = np.stack(frames[lo:hi], axis=0)
            smoothed.append(window.mean(axis=0).astype(np.uint8))
        frames = smoothed

    # Resize/crop to 9:16 1080x1920
    h, w = frames[0].shape[:2]
    target_ratio = TARGET_W / TARGET_H
    current_ratio = w / h
    if current_ratio > target_ratio:
        # Crop width
        new_w = int(h * target_ratio)
        x0 = (w - new_w) // 2
        frames = [f[:, x0 : x0 + new_w] for f in frames]
    else:
        # Crop height
        new_h = int(w / target_ratio)
        y0 = (h - new_h) // 2
        frames = [f[y0 : y0 + new_h, :] for f in frames]
    frames = [cv2.resize(f, (TARGET_W, TARGET_H)) for f in frames]

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(out_path, fourcc, fps, (TARGET_W, TARGET_H))
    for f in frames:
        out.write(f)
    out.release()

    return {"video_path": out_path}
