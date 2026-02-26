"""Video generation: EchoMimic + InstantID conditioning. 40GB: gen at 512/768 then upscale."""
from pathlib import Path

# Optional: override via env for 40GB tuning
GEN_WIDTH = 512
GEN_HEIGHT = 512


def run_video_gen(payload: dict) -> dict:
    photo_path = payload.get("photo_path") or payload.get("face_crop_path")
    audio_path = payload.get("audio_path")
    if not photo_path or not Path(photo_path).exists():
        return {"error": "Missing or invalid face_crop/photo path"}
    if not audio_path or not Path(audio_path).exists():
        return {"error": "Missing or invalid audio path from TTS"}

    base_dir = Path(photo_path).parent
    output_path = str(base_dir / "raw_video.mp4")

    try:
        from pipeline.echomimic_wrapper import generate_talking_head
        generate_talking_head(
            ref_image_path=payload.get("face_crop_path") or photo_path,
            audio_path=audio_path,
            output_path=output_path,
            instantid_embed_path=payload.get("instantid_embed_path"),
            driving_video_path=payload.get("driving_video_path"),
            driving_landmarks_path=payload.get("driving_landmarks_path"),
            width=GEN_WIDTH,
            height=GEN_HEIGHT,
            use_placeholder_if_unavailable=True,
        )
    except Exception as e:
        return {"error": f"Video gen failed: {e}"}

    return {"video_path": output_path}
