from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from models.schemas import ChatRequest, ChatImageRequest, ChatResponse

router = APIRouter()


@router.post("/api/chat", response_model=ChatResponse)
async def send_message(request: ChatRequest, req: Request):
    chat_service = req.app.state.chat_service
    result = await chat_service.process_chat(
        message=request.message,
        domain=request.domain,
        session_id=request.session_id,
        model_override=request.model,
    )
    return result


@router.post("/api/chat/stream")
async def send_message_stream(request: ChatRequest, req: Request):
    chat_service = req.app.state.chat_service
    return StreamingResponse(
        chat_service.stream_chat(
            message=request.message,
            domain=request.domain,
            session_id=request.session_id,
            model_override=request.model,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/api/chat/image", response_model=ChatResponse)
async def send_image_message(request: ChatImageRequest, req: Request):
    chat_service = req.app.state.chat_service
    # For non-streaming image, use process_chat logic with image
    # Simplified: use streaming internally and collect
    result = []
    async for chunk in chat_service.stream_chat_with_image(
        message=request.message,
        domain=request.domain,
        image_data=request.image_data,
        session_id=request.session_id,
        model_override=request.model,
    ):
        result.append(chunk)
    # Parse the last SSE data for session info
    import json
    for r in reversed(result):
        if "done" in r:
            data = json.loads(r.replace("data: ", "").strip())
            return ChatResponse(
                session_id=data["session_id"],
                message_id="",
                content="".join(result),
                domain=request.domain,
            )
    return ChatResponse(session_id="", message_id="", content="", domain=request.domain)


@router.post("/api/chat/image/stream")
async def send_image_message_stream(request: ChatImageRequest, req: Request):
    chat_service = req.app.state.chat_service
    return StreamingResponse(
        chat_service.stream_chat_with_image(
            message=request.message,
            domain=request.domain,
            image_data=request.image_data,
            session_id=request.session_id,
            model_override=request.model,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
