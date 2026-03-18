"""Agent Memory Service - enables per-domain self-improvement.

Each domain agent builds a memory of user preferences, context, and feedback.
This memory is injected into the system prompt to personalize responses.

Memory types:
  - preference: User likes/dislikes (e.g., "Favorite genres: Action, Sci-Fi")
  - context: Background info (e.g., "Has knee injury, cannot run")
  - feedback: Interaction quality signals (e.g., "Prefers detailed explanations")
  - goal: User objectives (e.g., "Goal to lose 5kg")
  - interaction: Key conversation summaries
"""

from models.database import get_db


class MemoryService:
    def __init__(self, openrouter=None):
        self.openrouter = openrouter

    def get_memories(self, user_id: str, domain: str, limit: int = 20) -> list[dict]:
        """Retrieve agent memories for a user+domain, ordered by importance."""
        db = get_db()
        result = db.table("agent_memory") \
            .select("*") \
            .eq("user_id", user_id) \
            .eq("domain", domain) \
            .order("importance", desc=True) \
            .order("updated_at", desc=True) \
            .limit(limit) \
            .execute()
        return result.data or []

    def add_memory(self, user_id: str, domain: str, memory_type: str, content: str, importance: int = 5):
        """Store a new memory entry."""
        db = get_db()
        db.table("agent_memory").insert({
            "user_id": user_id,
            "domain": domain,
            "memory_type": memory_type,
            "content": content,
            "importance": min(max(importance, 1), 10),
        }).execute()

    def update_memory(self, memory_id: str, content: str = None, importance: int = None):
        """Update an existing memory."""
        db = get_db()
        updates = {"updated_at": "now()"}
        if content is not None:
            updates["content"] = content
        if importance is not None:
            updates["importance"] = min(max(importance, 1), 10)
        db.table("agent_memory").update(updates).eq("id", memory_id).execute()

    def delete_memory(self, memory_id: str):
        """Delete a specific memory."""
        db = get_db()
        db.table("agent_memory").delete().eq("id", memory_id).execute()

    def build_memory_prompt(self, user_id: str, domain: str) -> str:
        """Build a memory context string to inject into the system prompt.

        This is the core of agent self-improvement: past learnings about the user
        are summarized and prepended to the system prompt so the agent adapts.
        """
        memories = self.get_memories(user_id, domain, limit=15)
        if not memories:
            return ""

        sections = {
            "preference": [],
            "context": [],
            "feedback": [],
            "goal": [],
            "interaction": [],
        }

        for mem in memories:
            mtype = mem.get("memory_type", "context")
            if mtype in sections:
                sections[mtype].append(mem["content"])

        lines = ["\n\n--- User Memory (learned from previous conversations) ---"]

        if sections["goal"]:
            lines.append(f"\n[Goals] {' | '.join(sections['goal'])}")
        if sections["context"]:
            lines.append(f"\n[Background] {' | '.join(sections['context'])}")
        if sections["preference"]:
            lines.append(f"\n[Preferences] {' | '.join(sections['preference'])}")
        if sections["feedback"]:
            lines.append(f"\n[Feedback] {' | '.join(sections['feedback'])}")
        if sections["interaction"]:
            lines.append(f"\n[Recent Conversation Summary] {sections['interaction'][0]}")

        lines.append("\nUse the above information to provide optimized responses for this user.")
        lines.append("--- End of Memory ---")

        return "\n".join(lines)

    async def extract_and_store_memories(
        self, user_id: str, domain: str, conversation: list[dict]
    ):
        """Analyze a conversation and extract memorable facts.

        Called after a chat session to learn from the interaction.
        Uses the LLM to extract key user information.
        """
        if not self.openrouter or len(conversation) < 3:
            return

        # Build extraction prompt
        conv_text = "\n".join(
            f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content'][:200]}"
            for m in conversation[-10:]  # Last 10 messages
        )

        extraction_prompt = f"""Extract memorable information about the user from the following conversation.
Return each item as a JSON array.

Conversation:
{conv_text}

Return in the following format:
[
  {{"type": "preference|context|goal|feedback", "content": "description", "importance": 1-10}}
]

Rules:
- Extract only information useful for personalization (health status, preferences, goals, etc.)
- Ignore general greetings or meaningless conversation
- Maximum 5 items
- Only new information not already known
- Return empty array [] if no information to extract"""

        try:
            result = await self.openrouter.chat_completion(
                messages=[
                    {"role": "system", "content": "You are a memory extraction assistant. Return only valid JSON."},
                    {"role": "user", "content": extraction_prompt},
                ],
                model="openai/gpt-4o-mini",
                temperature=0.1,
                max_tokens=500,
                stream=False,
            )

            import json
            content = result["choices"][0]["message"]["content"]
            # Extract JSON from response
            content = content.strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[1].rsplit("```", 1)[0]

            items = json.loads(content)
            if not isinstance(items, list):
                return

            for item in items[:5]:
                if "type" in item and "content" in item:
                    self.add_memory(
                        user_id=user_id,
                        domain=domain,
                        memory_type=item["type"],
                        content=item["content"],
                        importance=item.get("importance", 5),
                    )
        except Exception:
            pass  # Memory extraction is best-effort
