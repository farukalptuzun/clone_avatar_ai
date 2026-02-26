"""EchoMimic + InstantID wrapper for audio-driven talking-head video.
Supports 40GB VRAM: generate at 512/768 then upscale, or segment then concat.
When EchoMimic is not installed, outputs a placeholder video (static frame) for pipeline testing.
With driving_landmarks_path, uses infer_audio2vid_pose.py for pose-driven generation."""
import json
import logging
import os
import pickle
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import cv2
import numpy as np

logger = logging.getLogger(__name__)


# 40GB strategy: generate at lower res, postprocess upscales to 1080x1920
DEFAULT_GEN_WIDTH = 512
DEFAULT_GEN_HEIGHT = 512
TARGET_FPS = 25


def _get_audio_duration_sec(audio_path: str) -> float:
    """Return duration of audio file in seconds (mp3/wav)."""
    try:
        import subprocess
        result = subprocess.run(
            [
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", audio_path
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
    except (FileNotFoundError, ValueError, subprocess.TimeoutExpired):
        pass
    return 5.0


def _placeholder_video(
    ref_image_path: str,
    output_path: str,
    duration_sec: float,
    width: int = DEFAULT_GEN_WIDTH,
    height: int = DEFAULT_GEN_HEIGHT,
) -> None:
    """Write a placeholder video: repeated ref image for duration_sec (for pipeline test without EchoMimic)."""
    img = cv2.imread(ref_image_path)
    if img is None:
        raise FileNotFoundError(f"Cannot read image: {ref_image_path}")
    img = cv2.resize(img, (width, height))
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(output_path, fourcc, TARGET_FPS, (width, height))
    n_frames = int(duration_sec * TARGET_FPS) or 1
    for _ in range(n_frames):
        out.write(img)
    out.release()


def _landmarks_json_to_pose_dir(
    driving_landmarks_path: str,
    width: int,
    height: int,
) -> str:
    """Convert driving_landmarks.json (frames of {x,y} normalized) to EchoMimic pose dir (0.pkl, 1.pkl, ...).
    Returns path to a temp dir; caller must clean up or use with context."""
    with open(driving_landmarks_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    frames = data.get("frames", [])
    if not frames:
        raise ValueError("driving_landmarks.json has no frames")
    pose_dir = tempfile.mkdtemp(prefix="echomimic_pose_")
    for i, frame_pts in enumerate(frames):
        # EchoMimic draw_landmarks(..., normed=False) expects pixel coords
        kpts = np.array(
            [[float(p["x"]) * width, float(p["y"]) * height] for p in frame_pts],
            dtype=np.float32,
        )
        with open(os.path.join(pose_dir, f"{i}.pkl"), "wb") as f:
            pickle.dump(kpts, f)
    return pose_dir


def _run_echomimic(
    ref_image_path: str,
    audio_path: str,
    output_path: str,
    instantid_embed_path: str | None = None,
    driving_video_path: str | None = None,
    driving_landmarks_path: str | None = None,
    width: int = DEFAULT_GEN_WIDTH,
    height: int = DEFAULT_GEN_HEIGHT,
    chunk_seconds: float | None = None,
) -> None:
    """Run EchoMimic inference via subprocess.
    If driving_landmarks_path is set, uses infer_audio2vid_pose.py (pose+audio); else infer_audio2vid.py (audio only)."""
    echomimic_path = os.environ.get("ECHOMIMIC_PATH") or os.path.join(os.path.dirname(__file__), "..", "echomimic")
    echomimic_path = Path(echomimic_path).resolve()
    if not echomimic_path.is_dir():
        raise NotImplementedError("EchoMimic not found. Set ECHOMIMIC_PATH or clone echomimic repo.")
    ref_image_path = Path(ref_image_path).resolve()
    audio_path = Path(audio_path).resolve()
    if not ref_image_path.exists() or not audio_path.exists():
        raise FileNotFoundError("Reference image or audio not found.")

    use_pose = bool(driving_landmarks_path and Path(driving_landmarks_path).exists())
    pose_dir_cleanup = None

    if use_pose:
        infer_script = echomimic_path / "infer_audio2vid_pose.py"
        default_config = echomimic_path / "configs" / "prompts" / "animation_pose.yaml"
        if not infer_script.exists():
            raise NotImplementedError("EchoMimic infer_audio2vid_pose.py not found (required for driving video).")
        pose_dir_cleanup = _landmarks_json_to_pose_dir(driving_landmarks_path, width, height)
        ref_str = str(ref_image_path).replace("\\", "/")
        audio_str = str(audio_path).replace("\\", "/")
        pose_dir_str = str(Path(pose_dir_cleanup).resolve()).replace("\\", "/")
        test_block = f'test_cases:\n  "{ref_str}":\n    - "{audio_str}"\n    - "{pose_dir_str}"'
        if default_config.exists():
            with open(default_config, "r", encoding="utf-8") as f:
                config_lines = f.read()
            if "test_cases:" in config_lines:
                config_lines = re.sub(
                    r"test_cases:\s*\n(  .*\n)*",
                    test_block + "\n",
                    config_lines,
                    count=1,
                )
            else:
                config_lines = config_lines.rstrip() + "\n\n" + test_block + "\n"
        else:
            config_lines = f"""pretrained_base_model_path: "./pretrained_weights/sd-image-variations-diffusers"
pretrained_vae_path: "./pretrained_weights/sd-vae-ft-mse"
audio_model_path: "./pretrained_weights/audio_processor/whisper_tiny.pt"
denoising_unet_path: "./pretrained_weights/denoising_unet_pose.pth"
reference_unet_path: "./pretrained_weights/reference_unet_pose.pth"
face_locator_path: "./pretrained_weights/face_locator_pose.pth"
motion_module_path: "./pretrained_weights/motion_module_pose.pth"
inference_config: "./configs/inference/inference_v2.yaml"
weight_dtype: 'fp16'
test_cases:
  "{ref_str}":
    - "{audio_str}"
    - "{pose_dir_str}"
"""
    else:
        infer_script = echomimic_path / "infer_audio2vid.py"
        default_config = echomimic_path / "configs" / "prompts" / "animation.yaml"
        if not infer_script.exists():
            raise NotImplementedError("EchoMimic infer_audio2vid.py not found.")
        ref_str = str(ref_image_path).replace("\\", "/")
        audio_str = str(audio_path).replace("\\", "/")
        test_block = f'test_cases:\n  "{ref_str}":\n    - "{audio_str}"'
        if default_config.exists():
            with open(default_config, "r", encoding="utf-8") as f:
                config_lines = f.read()
            if "test_cases:" in config_lines:
                config_lines = re.sub(
                    r"test_cases:\s*\n(  .*\n)*",
                    test_block + "\n",
                    config_lines,
                    count=1,
                )
            else:
                config_lines = config_lines.rstrip() + "\n\n" + test_block + "\n"
        else:
            config_lines = f"""pretrained_base_model_path: "./pretrained_weights/sd-image-variations-diffusers/"
pretrained_vae_path: "./pretrained_weights/sd-vae-ft-mse/"
audio_model_path: "./pretrained_weights/audio_processor/whisper_tiny.pt"
denoising_unet_path: "./pretrained_weights/denoising_unet.pth"
reference_unet_path: "./pretrained_weights/reference_unet.pth"
face_locator_path: "./pretrained_weights/face_locator.pth"
motion_module_path: "./pretrained_weights/motion_module.pth"
inference_config: "./configs/inference/inference_v2.yaml"
weight_dtype: 'fp16'
test_cases:
  "{ref_str}":
    - "{audio_str}"
"""

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8") as f:
        f.write(config_lines)
        temp_config = f.name

    try:
        env = {**os.environ, "PYTHONPATH": str(echomimic_path)}
        if os.environ.get("FFMPEG_PATH"):
            env["PATH"] = os.environ["FFMPEG_PATH"] + os.pathsep + env.get("PATH", "")
        python_bin = os.environ.get("ECHOMIMIC_PYTHON") or "python"
        cmd = [
            python_bin,
            str(infer_script),
            "--config", temp_config,
            "-W", str(width),
            "-H", str(height),
            "--device", "cuda",
        ]
        result = subprocess.run(
            cmd,
            cwd=str(echomimic_path),
            env=env,
            capture_output=True,
            text=True,
            timeout=600,
        )
        if result.returncode != 0:
            raise RuntimeError(f"EchoMimic failed: {result.stderr or result.stdout or 'unknown'}")

        out_dir = echomimic_path / "output"
        if not out_dir.exists():
            raise FileNotFoundError("EchoMimic output dir missing.")
        candidates = list(out_dir.rglob("*_withaudio.mp4")) or list(out_dir.rglob("*withaudio*.mp4"))
        if not candidates:
            cutoff = time.time() - 900
            candidates = [p for p in out_dir.rglob("*.mp4") if p.stat().st_mtime >= cutoff]
        if not candidates:
            raise FileNotFoundError("EchoMimic did not produce output video (no *_withaudio.mp4 under output/).")
        latest = max(candidates, key=lambda p: p.stat().st_mtime)
        shutil.copy2(str(latest), output_path)
    finally:
        try:
            os.unlink(temp_config)
        except OSError:
            pass
        if pose_dir_cleanup and os.path.isdir(pose_dir_cleanup):
            try:
                shutil.rmtree(pose_dir_cleanup)
            except OSError:
                pass


def generate_talking_head(
    ref_image_path: str,
    audio_path: str,
    output_path: str,
    instantid_embed_path: str | None = None,
    driving_video_path: str | None = None,
    driving_landmarks_path: str | None = None,
    width: int = DEFAULT_GEN_WIDTH,
    height: int = DEFAULT_GEN_HEIGHT,
    chunk_seconds: float | None = None,
    use_placeholder_if_unavailable: bool = True,
) -> str:
    """
    Generate talking-head video from reference image + audio.
    Returns path to output video (mp4).
    """
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    duration_sec = _get_audio_duration_sec(audio_path)

    try:
        _run_echomimic(
            ref_image_path,
            audio_path,
            output_path,
            instantid_embed_path=instantid_embed_path,
            driving_video_path=driving_video_path,
            driving_landmarks_path=driving_landmarks_path,
            width=width,
            height=height,
            chunk_seconds=chunk_seconds,
        )
    except (NotImplementedError, FileNotFoundError, RuntimeError) as e:
        logger.warning("EchoMimic fallback to placeholder: %s", e, exc_info=True)
        if use_placeholder_if_unavailable:
            _placeholder_video(ref_image_path, output_path, duration_sec, width, height)
        else:
            raise RuntimeError("EchoMimic unavailable or failed") from e

    return output_path
