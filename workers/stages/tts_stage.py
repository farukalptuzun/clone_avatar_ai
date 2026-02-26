"""TTS: text -> Turkish speech wav + word/sentence timing for subtitles and lip-sync."""
import asyncio
import json
from pathlib import Path

# Turkish voice (Edge TTS)
DEFAULT_TR_VOICE = "tr-TR-EmelNeural"


def _ensure_event_loop():
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())


def run_tts(payload: dict) -> dict:
    text = (payload.get("text") or "").strip()
    if not text:
        return {"error": "Empty text"}
    base_dir = Path(payload.get("photo_path", "")).parent
    base_dir.mkdir(parents=True, exist_ok=True)
    audio_path = str(base_dir / "tts_audio.mp3")
    timing_path = str(base_dir / "tts_timing.json")

    async def _generate():
        import edge_tts
        # WordBoundary for word-level timing (required for SubMaker)
        communicate = edge_tts.Communicate(
            text, DEFAULT_TR_VOICE, boundary="WordBoundary"
        )
        sub_maker = edge_tts.SubMaker()
        with open(audio_path, "wb") as audio_file:
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio_file.write(chunk["data"])
                elif chunk["type"] == "WordBoundary":
                    sub_maker.feed(chunk)
        # Export timing: list of {start_ms, end_ms, text}
        cues = []
        for cue in sub_maker.cues:
            start_ms = cue.start.total_seconds() * 1000
            end_ms = cue.end.total_seconds() * 1000
            cues.append({"start_ms": start_ms, "end_ms": end_ms, "text": cue.content})
        with open(timing_path, "w", encoding="utf-8") as f:
            json.dump({"words": cues, "full_text": text}, f, ensure_ascii=False)
        return audio_path, timing_path

    _ensure_event_loop()
    try:
        loop = asyncio.get_event_loop()
        audio_path, timing_path = loop.run_until_complete(_generate())
    except Exception as e:
        return {"error": f"TTS failed: {e}"}

    return {
        "audio_path": audio_path,
        "timing_path": timing_path,
    }
