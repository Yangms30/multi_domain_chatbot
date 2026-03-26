"""Voice service: STT (faster-whisper) + TTS (edge-tts)."""

import io
import logging
import tempfile
import os

logger = logging.getLogger(__name__)

# Lazy-load heavy models
_whisper_model = None


def _get_whisper_model():
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel
        _whisper_model = WhisperModel("small", device="cpu", compute_type="int8")
        logger.info("Whisper model loaded (small, cpu, int8)")
    return _whisper_model


async def speech_to_text(audio_bytes: bytes, filename: str = "audio.webm") -> str:
    """Convert audio bytes to text using faster-whisper."""
    model = _get_whisper_model()

    suffix = os.path.splitext(filename)[1] or ".webm"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(audio_bytes)
        tmp_path = tmp.name

    try:
        segments, info = model.transcribe(tmp_path, language=None)
        text = " ".join(seg.text for seg in segments).strip()
        logger.info("STT result (lang=%s): %s", info.language, text)
        return text
    finally:
        os.unlink(tmp_path)


async def text_to_speech(text: str, lang: str = "ko") -> bytes:
    """Convert text to speech using edge-tts. Returns MP3 bytes."""
    import edge_tts

    # Pick voice based on detected language
    voice = "ko-KR-SunHiNeural" if lang == "ko" else "en-US-AriaNeural"

    communicate = edge_tts.Communicate(text, voice)
    buf = io.BytesIO()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            buf.write(chunk["data"])

    buf.seek(0)
    return buf.read()


def detect_language(text: str) -> str:
    """Simple heuristic: if text contains Korean characters, it's Korean."""
    for ch in text:
        if "\uac00" <= ch <= "\ud7a3":
            return "ko"
    return "en"
