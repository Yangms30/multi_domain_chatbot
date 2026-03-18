import json
import uuid
from datetime import datetime, timezone

from models.database import get_db
from services.openrouter import OpenRouterClient
from services.memory_service import MemoryService
from services.context_manager import ContextManager


class ChatService:
    def __init__(self, openrouter: OpenRouterClient):
        self.openrouter = openrouter
        self.memory = MemoryService(openrouter)
        self.context = ContextManager(openrouter, self.memory)

    async def process_chat(self, message: str, domain: str, session_id: str | None = None, user_id: str = "default", model_override: str | None = None):
        db = get_db()
        session_id = self._get_or_create_session(session_id, domain, user_id)

        # Save user message
        user_msg_id = str(uuid.uuid4())
        db.table("chat_messages").insert({
            "id": user_msg_id,
            "session_id": session_id,
            "role": "user",
            "content": message,
        }).execute()

        # Build messages for OpenRouter
        messages = self._build_messages(session_id, domain, user_id)
        config = self._get_config()

        # Call OpenRouter
        result = await self.openrouter.chat_completion(
            messages=messages,
            model=model_override or config["model"],
            temperature=config["temperature"],
            max_tokens=config["max_tokens"],
            stream=False,
        )

        content = result["choices"][0]["message"]["content"]

        # Save assistant message
        assistant_msg_id = str(uuid.uuid4())
        db.table("chat_messages").insert({
            "id": assistant_msg_id,
            "session_id": session_id,
            "role": "assistant",
            "content": content,
        }).execute()

        self._update_session(session_id, message)

        # Background: extract memories and update context summary
        conversation = self._load_conversation(session_id)
        await self.memory.extract_and_store_memories(user_id, domain, conversation)
        await self.context.update_summary_if_needed(session_id)

        return {
            "session_id": session_id,
            "message_id": assistant_msg_id,
            "content": content,
            "domain": domain,
        }

    async def stream_chat(self, message: str, domain: str, session_id: str | None = None, user_id: str = "default", model_override: str | None = None):
        db = get_db()
        session_id = self._get_or_create_session(session_id, domain, user_id)

        # Save user message
        user_msg_id = str(uuid.uuid4())
        db.table("chat_messages").insert({
            "id": user_msg_id,
            "session_id": session_id,
            "role": "user",
            "content": message,
        }).execute()

        messages = self._build_messages(session_id, domain, user_id)
        config = self._get_config()

        full_content = []
        assistant_msg_id = str(uuid.uuid4())

        yield f"data: {json.dumps({'session_id': session_id, 'message_id': assistant_msg_id, 'content': '', 'start': True})}\n\n"

        stream_gen = await self.openrouter.chat_completion(
            messages=messages,
            model=model_override or config["model"],
            temperature=config["temperature"],
            max_tokens=config["max_tokens"],
            stream=True,
        )

        async for chunk in stream_gen:
            full_content.append(chunk)
            yield f"data: {json.dumps({'content': chunk})}\n\n"

        # Save complete assistant message
        complete_content = "".join(full_content)
        db.table("chat_messages").insert({
            "id": assistant_msg_id,
            "session_id": session_id,
            "role": "assistant",
            "content": complete_content,
        }).execute()

        self._update_session(session_id, message)

        yield f"data: {json.dumps({'content': '', 'done': True, 'session_id': session_id})}\n\n"

        # Extract memories and update context summary after stream completes
        conversation = self._load_conversation(session_id)
        await self.memory.extract_and_store_memories(user_id, domain, conversation)
        await self.context.update_summary_if_needed(session_id)

    async def stream_chat_with_image(
        self, message: str, domain: str, image_data: str, session_id: str | None = None, user_id: str = "default", model_override: str | None = None
    ):
        db = get_db()
        session_id = self._get_or_create_session(session_id, domain, user_id)

        # Save user message with image
        user_msg_id = str(uuid.uuid4())
        db.table("chat_messages").insert({
            "id": user_msg_id,
            "session_id": session_id,
            "role": "user",
            "content": message,
            "image_data": image_data,
        }).execute()

        messages = self._build_messages(session_id, domain, user_id)
        config = self._get_config()

        full_content = []
        assistant_msg_id = str(uuid.uuid4())

        yield f"data: {json.dumps({'session_id': session_id, 'message_id': assistant_msg_id, 'content': '', 'start': True})}\n\n"

        stream_gen = await self.openrouter.chat_completion_with_image(
            messages=messages,
            image_base64=image_data,
            user_text=message,
            model=model_override or "openai/gpt-4o",
            temperature=config["temperature"],
            max_tokens=config["max_tokens"],
            stream=True,
        )

        async for chunk in stream_gen:
            full_content.append(chunk)
            yield f"data: {json.dumps({'content': chunk})}\n\n"

        complete_content = "".join(full_content)
        db.table("chat_messages").insert({
            "id": assistant_msg_id,
            "session_id": session_id,
            "role": "assistant",
            "content": complete_content,
        }).execute()

        self._update_session(session_id, message)

        yield f"data: {json.dumps({'content': '', 'done': True, 'session_id': session_id})}\n\n"

        conversation = self._load_conversation(session_id)
        await self.memory.extract_and_store_memories(user_id, domain, conversation)
        await self.context.update_summary_if_needed(session_id)

    def _get_or_create_session(self, session_id: str | None, domain: str, user_id: str) -> str:
        db = get_db()
        if session_id:
            result = db.table("chat_sessions").select("id").eq("id", session_id).execute()
            if result.data:
                return session_id

        new_id = str(uuid.uuid4())
        db.table("chat_sessions").insert({
            "id": new_id,
            "domain": domain,
            "title": "New Chat",
            "user_id": user_id,
        }).execute()
        return new_id

    def _build_messages(self, session_id: str, domain: str, user_id: str) -> list[dict]:
        return self.context.get_context_messages(session_id, domain, user_id)

    def _update_session(self, session_id: str, first_message: str):
        db = get_db()

        result = db.table("chat_messages") \
            .select("id", count="exact") \
            .eq("session_id", session_id) \
            .eq("role", "user") \
            .execute()

        now = datetime.now(timezone.utc).isoformat()

        if result.count and result.count <= 1:
            title = first_message[:30] + ("..." if len(first_message) > 30 else "")
            db.table("chat_sessions").update({
                "title": title,
                "updated_at": now,
            }).eq("id", session_id).execute()
        else:
            db.table("chat_sessions").update({
                "updated_at": now,
            }).eq("id", session_id).execute()

    def _load_conversation(self, session_id: str) -> list[dict]:
        db = get_db()
        result = db.table("chat_messages") \
            .select("role, content") \
            .eq("session_id", session_id) \
            .order("created_at") \
            .execute()
        return result.data or []

    def _get_config(self) -> dict:
        db = get_db()
        result = db.table("llm_config").select("*").eq("id", 1).execute()
        if result.data:
            row = result.data[0]
            return {
                "model": row["model"],
                "temperature": row["temperature"],
                "max_tokens": row["max_tokens"],
                "system_prompt": row["system_prompt"],
                "stream": row["stream"],
            }
        return {
            "model": "openai/gpt-4o-mini",
            "temperature": 0.7,
            "max_tokens": 2048,
            "system_prompt": "",
            "stream": True,
        }
