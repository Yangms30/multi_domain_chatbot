import json
import httpx
from typing import AsyncGenerator

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


class OpenRouterClient:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.client = httpx.AsyncClient(
            base_url=OPENROUTER_BASE_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=60.0,
        )

    async def chat_completion(
        self,
        messages: list[dict],
        model: str = "openai/gpt-4o-mini",
        temperature: float = 0.7,
        max_tokens: int = 2048,
        stream: bool = False,
    ) -> dict | AsyncGenerator:
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
        }

        if stream:
            return self._stream_response(payload)

        response = await self.client.post("/chat/completions", json=payload)
        response.raise_for_status()
        return response.json()

    async def chat_completion_with_image(
        self,
        messages: list[dict],
        image_base64: str,
        user_text: str,
        model: str = "openai/gpt-4o",
        temperature: float = 0.7,
        max_tokens: int = 2048,
        stream: bool = False,
    ) -> dict | AsyncGenerator:
        # Build vision message
        # image_base64 may already include data URI prefix from frontend
        if image_base64.startswith("data:"):
            image_url = image_base64
        else:
            image_url = f"data:image/jpeg;base64,{image_base64}"

        vision_content = [
            {"type": "text", "text": user_text},
            {
                "type": "image_url",
                "image_url": {"url": image_url},
            },
        ]

        vision_messages = messages.copy()
        # Replace last user message with vision content
        if vision_messages and vision_messages[-1]["role"] == "user":
            vision_messages[-1] = {"role": "user", "content": vision_content}
        else:
            vision_messages.append({"role": "user", "content": vision_content})

        payload = {
            "model": model,
            "messages": vision_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
        }

        if stream:
            return self._stream_response(payload)

        response = await self.client.post("/chat/completions", json=payload)
        response.raise_for_status()
        return response.json()

    async def _stream_response(self, payload: dict) -> AsyncGenerator[str, None]:
        async with self.client.stream(
            "POST", "/chat/completions", json=payload
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = line[6:]
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                    choices = chunk.get("choices", [])
                    if choices:
                        delta = choices[0].get("delta", {})
                        content = delta.get("content")
                        if content:
                            yield content
                except json.JSONDecodeError:
                    continue

    async def close(self):
        await self.client.aclose()
