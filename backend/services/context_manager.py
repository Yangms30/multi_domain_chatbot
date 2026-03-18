"""Context Manager - Sliding Window + Summary for long conversations.

Keeps recent N messages as-is and summarizes older messages via LLM.
The summary is stored in chat_sessions.context_summary and injected
into the message array so the model retains full conversation context.
"""

from models.database import get_db
from services.openrouter import OpenRouterClient
from services.domain_manager import get_system_prompt
from services.memory_service import MemoryService

WINDOW_SIZE = 10
SUMMARY_THRESHOLD = 12


class ContextManager:
    def __init__(self, openrouter: OpenRouterClient, memory: MemoryService):
        self.openrouter = openrouter
        self.memory = memory

    def get_context_messages(self, session_id: str, domain: str, user_id: str) -> list[dict]:
        """Build the message array for LLM: system + summary + recent messages."""
        db = get_db()

        # 1. System prompt + agent memory
        system_prompt = get_system_prompt(domain)
        memory_context = self.memory.build_memory_prompt(user_id, domain)
        if memory_context:
            system_prompt += memory_context

        messages = [{"role": "system", "content": system_prompt}]

        # 2. Load session summary
        session = db.table("chat_sessions") \
            .select("context_summary, summary_message_count") \
            .eq("id", session_id).execute()
        session_data = session.data[0] if session.data else {}
        summary = session_data.get("context_summary", "") or ""
        summary_count = session_data.get("summary_message_count", 0) or 0

        if summary:
            messages.append({
                "role": "system",
                "content": f"[Previous Conversation Summary ({summary_count} messages)]\n{summary}",
            })

        # 3. Load all messages and pick recent ones after summary boundary
        all_messages = db.table("chat_messages") \
            .select("role, content") \
            .eq("session_id", session_id) \
            .order("created_at") \
            .execute()
        all_msgs = all_messages.data or []

        recent_msgs = all_msgs[summary_count:]

        # Safety: cap to WINDOW_SIZE from the end
        if len(recent_msgs) > WINDOW_SIZE:
            recent_msgs = recent_msgs[-WINDOW_SIZE:]

        for row in recent_msgs:
            messages.append({"role": row["role"], "content": row["content"]})

        return messages

    async def update_summary_if_needed(self, session_id: str):
        """Check if summary needs updating and generate incrementally."""
        db = get_db()

        # Total message count
        count_result = db.table("chat_messages") \
            .select("id", count="exact") \
            .eq("session_id", session_id).execute()
        total_count = count_result.count or 0

        if total_count < SUMMARY_THRESHOLD:
            return

        # Current summary state
        session = db.table("chat_sessions") \
            .select("context_summary, summary_message_count") \
            .eq("id", session_id).execute()
        session_data = session.data[0] if session.data else {}
        current_summary = session_data.get("context_summary", "") or ""
        summary_count = session_data.get("summary_message_count", 0) or 0

        # How many messages should be outside the window (= summarized)
        messages_to_summarize = total_count - WINDOW_SIZE

        if messages_to_summarize <= summary_count:
            return  # Already up to date

        # Load messages that need to be newly summarized
        all_messages = db.table("chat_messages") \
            .select("role, content") \
            .eq("session_id", session_id) \
            .order("created_at") \
            .execute()
        all_msgs = all_messages.data or []

        new_to_summarize = all_msgs[summary_count:messages_to_summarize]
        if not new_to_summarize:
            return

        # Generate summary via LLM
        new_summary = await self._generate_summary(current_summary, new_to_summarize)

        # Update DB
        db.table("chat_sessions").update({
            "context_summary": new_summary,
            "summary_message_count": messages_to_summarize,
        }).eq("id", session_id).execute()

    async def _generate_summary(self, existing_summary: str, new_messages: list[dict]) -> str:
        """Merge existing summary with new messages into a single summary."""
        new_text = "\n".join(
            f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content'][:300]}"
            for m in new_messages
        )

        if existing_summary:
            prompt = (
                "Combine the existing conversation summary with new conversation content into a single unified summary.\n\n"
                f"Existing summary:\n{existing_summary}\n\n"
                f"New conversation content:\n{new_text}\n\n"
                "Rules:\n"
                "- Summarize within 300 words\n"
                "- Must include the user's key questions, intentions, preferences, and important facts\n"
                "- Include conversation conclusions or agreed-upon content\n"
                "- Arrange chronologically"
            )
        else:
            prompt = (
                "Summarize the following conversation.\n\n"
                f"Conversation:\n{new_text}\n\n"
                "Rules:\n"
                "- Summarize within 300 words\n"
                "- Must include the user's key questions, intentions, preferences, and important facts\n"
                "- Include conversation conclusions or agreed-upon content"
            )

        try:
            result = await self.openrouter.chat_completion(
                messages=[
                    {"role": "system", "content": "You are a conversation summarizer. Return only the summary text, no formatting."},
                    {"role": "user", "content": prompt},
                ],
                model="openai/gpt-4o-mini",
                temperature=0.1,
                max_tokens=400,
                stream=False,
            )
            return result["choices"][0]["message"]["content"].strip()
        except Exception:
            return existing_summary  # Keep existing on failure
