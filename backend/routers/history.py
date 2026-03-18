from fastapi import APIRouter
from models.database import get_db
from models.schemas import SessionListItem, MessageItem, StatsResponse

router = APIRouter()


@router.get("/api/history", response_model=list[SessionListItem])
async def list_sessions(domain: str = None, page: int = 1, limit: int = 10):
    db = get_db()
    offset = (page - 1) * limit

    query = db.table("chat_sessions").select("*").order("updated_at", desc=True).range(offset, offset + limit - 1)

    if domain:
        query = query.eq("domain", domain)

    result = query.execute()
    sessions = result.data or []

    items = []
    for s in sessions:
        # Get last message
        msg_result = db.table("chat_messages") \
            .select("content") \
            .eq("session_id", s["id"]) \
            .order("created_at", desc=True) \
            .limit(1) \
            .execute()
        last_msg = msg_result.data[0]["content"][:100] if msg_result.data else ""

        items.append(SessionListItem(
            id=s["id"],
            domain=s["domain"],
            title=s["title"],
            last_message=last_msg,
            created_at=s["created_at"],
            updated_at=s["updated_at"],
        ))

    return items


@router.get("/api/history/stats", response_model=StatsResponse)
async def get_stats():
    db = get_db()

    total_result = db.table("chat_sessions").select("id", count="exact").execute()
    total = total_result.count or 0

    # Active this month
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
    active_result = db.table("chat_sessions") \
        .select("id", count="exact") \
        .gte("updated_at", month_start) \
        .execute()
    active = active_result.count or 0

    msg_result = db.table("chat_messages").select("id", count="exact").execute()
    messages = msg_result.count or 0

    return StatsResponse(total_chats=total, active_this_month=active, total_messages=messages)


@router.get("/api/history/{session_id}", response_model=list[MessageItem])
async def get_session_messages(session_id: str):
    db = get_db()
    result = db.table("chat_messages") \
        .select("id, role, content, image_data, created_at") \
        .eq("session_id", session_id) \
        .order("created_at") \
        .execute()

    return [
        MessageItem(
            id=row["id"],
            role=row["role"],
            content=row["content"],
            image_data=row.get("image_data"),
            created_at=row["created_at"],
        )
        for row in (result.data or [])
    ]


@router.delete("/api/history/{session_id}")
async def delete_session(session_id: str):
    db = get_db()
    # Messages cascade-delete via FK
    db.table("chat_messages").delete().eq("session_id", session_id).execute()
    db.table("chat_sessions").delete().eq("id", session_id).execute()
    return {"detail": "Session deleted"}
