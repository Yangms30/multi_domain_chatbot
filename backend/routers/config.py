from fastapi import APIRouter
from models.database import get_db
from models.schemas import ConfigResponse, ConfigUpdateRequest
from datetime import datetime, timezone

router = APIRouter()


@router.get("/api/config", response_model=ConfigResponse)
async def get_config():
    db = get_db()
    result = db.table("llm_config").select("*").eq("id", 1).execute()

    if result.data:
        row = result.data[0]
        return ConfigResponse(
            model=row["model"],
            temperature=row["temperature"],
            max_tokens=row["max_tokens"],
            system_prompt=row["system_prompt"],
            stream=row["stream"],
        )
    return ConfigResponse(
        model="openai/gpt-4o-mini",
        temperature=0.7,
        max_tokens=2048,
        system_prompt="",
        stream=True,
    )


@router.put("/api/config", response_model=ConfigResponse)
async def update_config(request: ConfigUpdateRequest):
    db = get_db()

    updates = {"updated_at": datetime.now(timezone.utc).isoformat()}
    if request.model is not None:
        updates["model"] = request.model
    if request.temperature is not None:
        updates["temperature"] = request.temperature
    if request.max_tokens is not None:
        updates["max_tokens"] = request.max_tokens
    if request.system_prompt is not None:
        updates["system_prompt"] = request.system_prompt
    if request.stream is not None:
        updates["stream"] = request.stream

    if len(updates) > 1:  # more than just updated_at
        db.table("llm_config").update(updates).eq("id", 1).execute()

    return await get_config()
