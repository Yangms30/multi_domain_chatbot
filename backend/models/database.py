import os
from supabase import create_client, Client

_supabase: Client | None = None


def get_db() -> Client:
    global _supabase
    if _supabase is None:
        url = os.getenv("SUPABASE_URL", "")
        key = os.getenv("SUPABASE_KEY", "")
        _supabase = create_client(url, key)
    return _supabase


async def init_db():
    """Verify Supabase connection. Tables must be created via Supabase Dashboard/SQL Editor."""
    db = get_db()
    # Quick connectivity check
    try:
        db.table("llm_config").select("id").limit(1).execute()
    except Exception:
        pass  # Tables may not exist yet; user needs to run migration SQL

    # Check context_summary column exists (migration)
    try:
        db.table("chat_sessions").select("context_summary").limit(1).execute()
    except Exception:
        pass  # Column doesn't exist yet; user needs to run migration SQL

    # Ensure default config exists
    try:
        result = db.table("llm_config").select("id").eq("id", 1).execute()
        if not result.data:
            db.table("llm_config").insert({
                "id": 1,
                "model": "openai/gpt-4o-mini",
                "temperature": 0.7,
                "max_tokens": 2048,
                "system_prompt": "",
                "stream": True,
            }).execute()
    except Exception:
        pass


async def close_db():
    global _supabase
    _supabase = None
