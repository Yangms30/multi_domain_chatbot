"""Agent Memory API - View/manage what each domain agent has learned about the user."""

from fastapi import APIRouter, Request
from pydantic import BaseModel
from typing import Optional

router = APIRouter()


class MemoryItem(BaseModel):
    id: str
    user_id: str
    domain: str
    memory_type: str
    content: str
    importance: int
    created_at: str
    updated_at: str


class MemoryCreateRequest(BaseModel):
    domain: str
    memory_type: str  # preference | context | feedback | goal | interaction
    content: str
    importance: int = 5


class MemoryUpdateRequest(BaseModel):
    content: Optional[str] = None
    importance: Optional[int] = None


@router.get("/api/memory", response_model=list[MemoryItem])
async def list_memories(domain: str = None, user_id: str = "default"):
    """List agent memories for a user, optionally filtered by domain."""
    from models.database import get_db
    db = get_db()

    query = db.table("agent_memory") \
        .select("*") \
        .eq("user_id", user_id) \
        .order("importance", desc=True) \
        .order("updated_at", desc=True)

    if domain:
        query = query.eq("domain", domain)

    result = query.execute()
    return [MemoryItem(**row) for row in (result.data or [])]


@router.post("/api/memory", response_model=MemoryItem)
async def create_memory(request: MemoryCreateRequest, req: Request):
    """Manually add a memory for the agent."""
    memory_service = req.app.state.chat_service.memory
    memory_service.add_memory(
        user_id="default",
        domain=request.domain,
        memory_type=request.memory_type,
        content=request.content,
        importance=request.importance,
    )
    # Return the most recently created memory
    from models.database import get_db
    db = get_db()
    result = db.table("agent_memory") \
        .select("*") \
        .eq("user_id", "default") \
        .eq("domain", request.domain) \
        .order("created_at", desc=True) \
        .limit(1) \
        .execute()
    return MemoryItem(**result.data[0])


@router.delete("/api/memory/{memory_id}")
async def delete_memory(memory_id: str, req: Request):
    """Delete a specific memory."""
    memory_service = req.app.state.chat_service.memory
    memory_service.delete_memory(memory_id)
    return {"detail": "Memory deleted"}


@router.get("/api/memory/summary")
async def memory_summary(domain: str, user_id: str = "default", req: Request = None):
    """Preview the memory context that will be injected into the agent's prompt."""
    memory_service = req.app.state.chat_service.memory
    prompt = memory_service.build_memory_prompt(user_id, domain)
    return {"domain": domain, "user_id": user_id, "memory_prompt": prompt}
