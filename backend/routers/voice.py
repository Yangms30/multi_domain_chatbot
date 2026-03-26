"""Voice API: audio in → STT → LLM → TTS → audio out."""

from fastapi import APIRouter, Request, UploadFile, File, Form
from fastapi.responses import Response

from services.voice_service import speech_to_text, text_to_speech, detect_language

router = APIRouter()


@router.post("/api/voice")
async def voice_chat(
    req: Request,
    audio: UploadFile = File(...),
    domain: str = Form("assistant"),
    session_id: str = Form(None),
):
    """
    Accept audio, run STT → LLM chat → TTS.
    Returns MP3 audio with transcript/reply in headers.
    """
    audio_bytes = await audio.read()

    # 1) STT
    transcript = await speech_to_text(audio_bytes, audio.filename or "audio.webm")
    if not transcript:
        return Response(
            content=b"",
            media_type="audio/mpeg",
            headers={"X-Transcript": "", "X-Reply": "음성을 인식하지 못했습니다."},
        )

    # 2) LLM chat
    chat_service = req.app.state.chat_service
    result = await chat_service.process_chat(
        message=transcript,
        domain=domain,
        session_id=session_id,
    )
    reply = result["content"]
    new_session_id = result["session_id"]

    # 3) TTS
    lang = detect_language(reply)
    audio_out = await text_to_speech(reply, lang)

    return Response(
        content=audio_out,
        media_type="audio/mpeg",
        headers={
            "X-Transcript": transcript,
            "X-Reply": reply,
            "X-Session-Id": new_session_id,
            "Access-Control-Expose-Headers": "X-Transcript, X-Reply, X-Session-Id",
        },
    )
