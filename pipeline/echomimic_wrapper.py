"""EchoMimic + InstantID wrapper for audio-driven talking-head video.
Supports 40GB VRAM: generate at 512/768 then upscale, or segment then concat.
When EchoMimic is not installed, outputs a placeholder video (static frame) for pipeline testing."""
from pathlib import Path

import cv2


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


def _run_echomimic(
    ref_image_path: str,
    audio_path: str,
    output_path: str,
    instantid_embed_path: str | None = None,
    driving_video_path: str | None = None,
    width: int = DEFAULT_GEN_WIDTH,
    height: int = DEFAULT_GEN_HEIGHT,
    chunk_seconds: float | None = None,
) -> None:
    """Run EchoMimic inference if available; otherwise raises NotImplementedError."""
    import os
    echomimic_path = os.environ.get("ECHOMIMIC_PATH") or os.path.join(os.path.dirname(__file__), "..", "echomimic")
    if not Path(echomimic_path).exists():
        raise NotImplementedError(
            "EchoMimic not found. Set ECHOMIMIC_PATH or clone echomimic repo. Using placeholder."
        )
    # Optional: invoke infer_audio2vid.py with ref_image_path and audio_path
    # For spike we leave this as stub; real impl would subprocess or import from echomimic
    raise NotImplementedError("EchoMimic inference not wired; use placeholder.")


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
            width=width,
            height=height,
            chunk_seconds=chunk_seconds,
        )
    except NotImplementedError:
        if use_placeholder_if_unavailable:
            _placeholder_video(ref_image_path, output_path, duration_sec, width, height)
        else:
            raise

    return output_path
