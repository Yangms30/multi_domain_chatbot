from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional


# --- Request Schemas ---

class ChatRequest(BaseModel):
    message: str
    domain: str
    session_id: Optional[str] = None
    stream: bool = True
    model: Optional[str] = None


class ChatImageRequest(BaseModel):
    message: str
    domain: str = "movie"
    session_id: Optional[str] = None
    image_data: str
    stream: bool = True
    model: Optional[str] = None


class ConfigUpdateRequest(BaseModel):
    model: Optional[str] = None
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(None, ge=1, le=16384)
    system_prompt: Optional[str] = None
    stream: Optional[bool] = None


# --- Response Schemas ---

class ChatResponse(BaseModel):
    session_id: str
    message_id: str
    content: str
    domain: str


class ChatbotInfo(BaseModel):
    domain: str
    name: str
    description: str
    icon: str
    color: str
    rating: float
    uses: str
    supports_image: bool


class SessionListItem(BaseModel):
    id: str
    domain: str
    title: str
    last_message: str
    created_at: str
    updated_at: str


class MessageItem(BaseModel):
    id: str
    role: str
    content: str
    image_data: Optional[str] = None
    created_at: str


class ConfigResponse(BaseModel):
    model: str
    temperature: float
    max_tokens: int
    system_prompt: str
    stream: bool


class StatsResponse(BaseModel):
    total_chats: int
    active_this_month: int
    total_messages: int
