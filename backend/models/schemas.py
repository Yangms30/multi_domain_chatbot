from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional


# --- Request Schemas ---

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=10000)
    domain: str = Field(..., min_length=1, max_length=50)
    session_id: Optional[str] = None
    stream: bool = True
    model: Optional[str] = None


class ChatImageRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=10000)
    domain: str = Field("movie", min_length=1, max_length=50)
    session_id: Optional[str] = None
    image_data: str = Field(..., max_length=10_000_000)  # ~7.5MB base64
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
