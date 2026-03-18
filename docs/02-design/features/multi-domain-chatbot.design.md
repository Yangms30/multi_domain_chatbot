# Design: Multi-Domain Chatbot Website (Prototype)

> Plan Reference: `docs/01-plan/features/multi-domain-chatbot.plan.md`

---

## 1. System Architecture

### 1.1 Overall Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Browser (Client)                          │
│                                                              │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────────────┐│
│  │  index.html   │ │  chat.html   │ │   history.html       ││
│  │ (Marketplace) │ │ (Chat UI)    │ │ (History Mgmt)       ││
│  │               │ │              │ │                      ││
│  │ marketplace.js│ │ chat.js      │ │ history.js           ││
│  └──────┬───────┘ └──────┬───────┘ └──────────┬───────────┘│
│         │                │                     │            │
│         └────────────────┼─────────────────────┘            │
│                          │                                   │
│                     api.js (공통 API 클라이언트)              │
└──────────────────────────┬───────────────────────────────────┘
                           │ HTTP (REST + SSE)
                           │ Port: 8000
┌──────────────────────────▼───────────────────────────────────┐
│                    FastAPI Application                        │
│                                                              │
│  main.py                                                     │
│  ├── StaticFiles("/", frontend/)     # 프론트엔드 서빙       │
│  ├── Router("/api/chatbots")         # 챗봇 목록             │
│  ├── Router("/api/chat")             # 채팅 처리             │
│  ├── Router("/api/history")          # 히스토리 관리          │
│  └── Router("/api/config")           # LLM 설정              │
│                                                              │
│  services/                                                   │
│  ├── openrouter.py                   # OpenRouter API 호출    │
│  ├── domain_manager.py               # 도메인 챗봇 정의/관리  │
│  └── chat_service.py                 # 채팅 비즈니스 로직     │
│                                                              │
│  models/                                                     │
│  ├── schemas.py                      # Pydantic 스키마        │
│  └── database.py                     # SQLite + aiosqlite    │
└──────────────────────────┬───────────────────────────────────┘
                           │
              ┌────────────┼────────────┐
              ▼                         ▼
    ┌──────────────┐          ┌──────────────────┐
    │  SQLite DB   │          │  OpenRouter API   │
    │  chatbot.db  │          │  (External)       │
    │              │          │                   │
    │  - sessions  │          │  - Chat Completion│
    │  - messages  │          │  - Vision (image) │
    │  - configs   │          │  - Streaming      │
    └──────────────┘          └──────────────────┘
```

### 1.2 Request Flow

```
[사용자] → chat.html → api.js → POST /api/chat
                                       │
                              chat_service.py
                                       │
                              ┌────────▼────────┐
                              │ 1. 세션 확인/생성 │
                              │ 2. 메시지 DB 저장 │
                              │ 3. 도메인 시스템   │
                              │    프롬프트 조합   │
                              │ 4. OpenRouter 호출 │
                              │ 5. 응답 DB 저장    │
                              │ 6. 응답 반환       │
                              └──────────────────┘
```

### 1.3 SSE Streaming Flow

```
[사용자] → POST /api/chat (stream=true)
                  │
                  ▼
        StreamingResponse (text/event-stream)
                  │
        ┌─────────▼──────────┐
        │ OpenRouter API     │
        │ (stream=true)      │
        │                    │
        │ chunk 1 → SSE data │──→ chat.js (EventSource)
        │ chunk 2 → SSE data │──→ 실시간 텍스트 추가
        │ chunk N → SSE data │──→ ...
        │ [DONE]  → SSE done │──→ 완료 처리
        └────────────────────┘
```

---

## 2. Database Design

### 2.1 ERD (Supabase PostgreSQL)

```
┌──────────────────────┐       ┌──────────────────────┐
│    chat_sessions     │       │    chat_messages      │
├──────────────────────┤       ├──────────────────────┤
│ id       UUID PK     │──┐    │ id       UUID PK     │
│ domain   TEXT        │  │    │ session_id UUID FK    │──┐
│ title    TEXT        │  │    │ role     TEXT         │  │
│ user_id  TEXT        │  └───>│ content  TEXT         │  │
│ created_at TIMESTAMPTZ│      │ image_data TEXT NULL  │  │
│ updated_at TIMESTAMPTZ│      │ created_at TIMESTAMPTZ│  │
└──────────────────────┘       └──────────────────────┘  │
                                                          │
┌──────────────────────┐       ┌──────────────────────┐  │
│    llm_config        │       │    agent_memory       │  │
├──────────────────────┤       ├──────────────────────┤  │
│ id       INTEGER PK  │       │ id       UUID PK     │  │
│ model    TEXT         │       │ user_id  TEXT         │  │
│ temperature REAL      │       │ domain   TEXT         │  │
│ max_tokens INTEGER    │       │ memory_type TEXT      │  │
│ system_prompt TEXT    │       │ content  TEXT         │  │
│ stream   BOOLEAN      │       │ importance INTEGER   │  │
│ updated_at TIMESTAMPTZ│       │ created_at TIMESTAMPTZ│  │
└──────────────────────┘       │ updated_at TIMESTAMPTZ│  │
                               └──────────────────────┘  │
  memory_type: preference | context | feedback | goal | interaction
  Agent Self-Improvement: 대화 후 LLM이 사용자 정보를 자동 추출 → memory 저장
                          다음 대화 시 memory를 system prompt에 주입 → 개인화
```

### 2.2 SQL Schema

```sql
CREATE TABLE IF NOT EXISTS chat_sessions (
    id TEXT PRIMARY KEY,
    domain TEXT NOT NULL,          -- 'healthcare' | 'movie'
    title TEXT NOT NULL DEFAULT 'New Chat',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,             -- 'user' | 'assistant'
    content TEXT NOT NULL,
    image_data TEXT,               -- base64 이미지 (영화 도메인용)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS llm_config (
    id INTEGER PRIMARY KEY DEFAULT 1,
    model TEXT NOT NULL DEFAULT 'openai/gpt-4o-mini',
    temperature REAL NOT NULL DEFAULT 0.7,
    max_tokens INTEGER NOT NULL DEFAULT 2048,
    system_prompt TEXT DEFAULT '',
    stream INTEGER NOT NULL DEFAULT 1,  -- SQLite boolean
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_messages_session ON chat_messages(session_id);
CREATE INDEX idx_sessions_domain ON chat_sessions(domain);
CREATE INDEX idx_sessions_updated ON chat_sessions(updated_at DESC);
```

---

## 3. Backend Design (FastAPI)

### 3.1 Pydantic Schemas (`models/schemas.py`)

```python
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional

# --- Request Schemas ---

class ChatRequest(BaseModel):
    message: str
    domain: str                           # "healthcare" | "movie"
    session_id: Optional[str] = None      # None이면 새 세션 생성
    stream: bool = True

class ChatImageRequest(BaseModel):
    message: str
    domain: str = "movie"
    session_id: Optional[str] = None
    image_data: str                       # base64 encoded image
    stream: bool = True

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
    created_at: datetime
    updated_at: datetime

class MessageItem(BaseModel):
    id: str
    role: str
    content: str
    image_data: Optional[str] = None
    created_at: datetime

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
```

### 3.2 Router: Chatbots (`routers/chatbots.py`)

```python
@router.get("/api/chatbots", response_model=list[ChatbotInfo])
async def list_chatbots(category: str = "all"):
    """도메인별 챗봇 목록 반환. category 필터 지원."""

@router.get("/api/chatbots/{domain}", response_model=ChatbotInfo)
async def get_chatbot(domain: str):
    """특정 도메인 챗봇 정보 반환."""
```

### 3.3 Router: Chat (`routers/chat.py`)

```python
@router.post("/api/chat", response_model=ChatResponse)
async def send_message(request: ChatRequest):
    """텍스트 메시지 전송. stream=false일 때 사용."""

@router.post("/api/chat/stream")
async def send_message_stream(request: ChatRequest):
    """스트리밍 메시지 전송. SSE로 응답."""
    return StreamingResponse(
        chat_service.stream_chat(request),
        media_type="text/event-stream"
    )

@router.post("/api/chat/image", response_model=ChatResponse)
async def send_image_message(request: ChatImageRequest):
    """이미지 포함 메시지 전송 (영화 도메인). Vision API 사용."""

@router.post("/api/chat/image/stream")
async def send_image_message_stream(request: ChatImageRequest):
    """이미지 포함 스트리밍 메시지 전송."""
    return StreamingResponse(
        chat_service.stream_chat_with_image(request),
        media_type="text/event-stream"
    )
```

### 3.4 Router: History (`routers/history.py`)

```python
@router.get("/api/history", response_model=list[SessionListItem])
async def list_sessions(domain: str = None, page: int = 1, limit: int = 10):
    """채팅 세션 목록 조회. 도메인 필터, 페이지네이션 지원."""

@router.get("/api/history/{session_id}", response_model=list[MessageItem])
async def get_session_messages(session_id: str):
    """특정 세션의 메시지 목록 조회."""

@router.delete("/api/history/{session_id}")
async def delete_session(session_id: str):
    """세션 및 관련 메시지 삭제."""

@router.get("/api/history/stats", response_model=StatsResponse)
async def get_stats():
    """채팅 통계 조회."""
```

### 3.5 Router: Config (`routers/config.py`)

```python
@router.get("/api/config", response_model=ConfigResponse)
async def get_config():
    """현재 LLM 설정 조회."""

@router.put("/api/config", response_model=ConfigResponse)
async def update_config(request: ConfigUpdateRequest):
    """LLM 설정 업데이트. 부분 업데이트 지원."""
```

### 3.6 Service: OpenRouter Client (`services/openrouter.py`)

```python
import httpx

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
        """OpenRouter chat completion API 호출.

        stream=True이면 AsyncGenerator로 chunk 반환.
        stream=False이면 전체 응답 dict 반환.
        """
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
        }

        if stream:
            return self._stream_response(payload)
        else:
            response = await self.client.post("/chat/completions", json=payload)
            response.raise_for_status()
            return response.json()

    async def chat_completion_with_image(
        self,
        messages: list[dict],
        image_base64: str,
        model: str = "openai/gpt-4o",  # Vision 지원 모델
        **kwargs,
    ) -> dict | AsyncGenerator:
        """이미지 포함 chat completion.

        messages의 마지막 user 메시지에 image_url 추가.
        OpenRouter는 OpenAI 호환 형식 사용:
        content: [
            {"type": "text", "text": "..."},
            {"type": "image_url", "image_url": {"url": "data:image/...;base64,..."}}
        ]
        """

    async def _stream_response(self, payload: dict) -> AsyncGenerator:
        """SSE 스트림 파싱. data: [DONE] 시 종료."""
        async with self.client.stream("POST", "/chat/completions", json=payload) as response:
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    chunk = json.loads(data)
                    delta = chunk["choices"][0]["delta"]
                    if "content" in delta:
                        yield delta["content"]
```

### 3.7 Service: Domain Manager (`services/domain_manager.py`)

```python
DOMAIN_CHATBOTS = {
    "healthcare": {
        "domain": "healthcare",
        "name": "Health Coach",
        "description": "개인 맞춤 건강 상담, 증상 분석, 운동/식단 추천을 제공하는 AI 건강 코치입니다.",
        "icon": "health_and_safety",
        "color": "#10b981",
        "rating": 4.8,
        "uses": "3.2k",
        "supports_image": False,
        "system_prompt": """당신은 전문 건강 상담 AI 코치입니다.

역할:
- 사용자의 건강 상태, 증상, 생활 습관에 대해 친절하고 전문적으로 상담합니다
- 증상 분석 및 일반적인 건강 조언을 제공합니다
- 맞춤형 운동 루틴과 식단을 추천합니다
- 건강 습관 개선을 위한 구체적 조언을 제공합니다

주의사항:
- 의학적 진단은 하지 않습니다. 심각한 증상은 반드시 병원 방문을 권장합니다
- 모든 답변은 한국어로 제공합니다
- 답변은 구체적이고 실행 가능한 조언 위주로 합니다"""
    },
    "movie": {
        "domain": "movie",
        "name": "Movie Expert",
        "description": "영화 추천, 이미지로 영화 식별, 상세 영화 정보를 제공하는 AI 영화 전문가입니다.",
        "icon": "movie",
        "color": "#8b5cf6",
        "rating": 4.7,
        "uses": "2.8k",
        "supports_image": True,
        "system_prompt": """당신은 영화 전문가 AI입니다.

역할:
- 사용자의 취향(장르, 분위기, 배우 등)에 맞는 영화를 추천합니다
- 영화 정보(줄거리, 출연진, 감독, 평점, 개봉일 등)를 상세히 제공합니다
- 사용자가 이미지를 보내면 해당 이미지의 영화를 식별하고 정보를 제공합니다
- 영화 관련 대화(리뷰, 비교, 트리비아 등)를 나눕니다

주의사항:
- 스포일러는 경고 후 제공합니다
- 모든 답변은 한국어로 제공합니다
- 추천 시 이유와 함께 3~5개 영화를 제안합니다"""
    },
}

def get_all_chatbots() -> list[dict]:
    """모든 도메인 챗봇 목록 반환"""

def get_chatbot(domain: str) -> dict:
    """특정 도메인 챗봇 반환. 없으면 404."""

def get_system_prompt(domain: str) -> str:
    """도메인별 시스템 프롬프트 반환."""
```

### 3.8 Service: Chat Service (`services/chat_service.py`)

```python
class ChatService:
    def __init__(self, db, openrouter: OpenRouterClient, domain_manager):
        self.db = db
        self.openrouter = openrouter
        self.domain_manager = domain_manager

    async def process_chat(self, request: ChatRequest) -> ChatResponse:
        """비스트리밍 채팅 처리.

        1. 세션 확인/생성
        2. 사용자 메시지 DB 저장
        3. 대화 히스토리 로드 (최근 20개)
        4. 시스템 프롬프트 + 히스토리 + 새 메시지 조합
        5. OpenRouter 호출
        6. 어시스턴트 응답 DB 저장
        7. 세션 타이틀 업데이트 (첫 메시지일 때)
        8. 응답 반환
        """

    async def stream_chat(self, request: ChatRequest) -> AsyncGenerator:
        """스트리밍 채팅 처리.

        SSE 형식으로 chunk 반환:
        data: {"content": "chunk text", "session_id": "..."}
        data: {"content": "", "done": true, "session_id": "..."}
        """

    async def process_image_chat(self, request: ChatImageRequest) -> ChatResponse:
        """이미지 포함 채팅 처리. Vision 모델 사용."""

    async def stream_chat_with_image(self, request: ChatImageRequest) -> AsyncGenerator:
        """이미지 포함 스트리밍 채팅."""

    async def _get_or_create_session(self, session_id: str | None, domain: str) -> str:
        """세션 ID 반환. None이면 새로 생성."""

    async def _load_history(self, session_id: str, limit: int = 20) -> list[dict]:
        """최근 N개 메시지를 OpenRouter messages 형식으로 변환."""

    async def _auto_title(self, session_id: str, first_message: str):
        """첫 메시지 기반 세션 제목 자동 생성 (앞 30자)."""
```

### 3.9 Database Module (`models/database.py`)

```python
import aiosqlite

DB_PATH = "chatbot.db"

async def get_db() -> aiosqlite.Connection:
    """DB 연결 반환. FastAPI Depends로 사용."""

async def init_db():
    """테이블 생성 및 초기 데이터 설정. startup 이벤트에서 호출."""

async def close_db():
    """DB 연결 종료. shutdown 이벤트에서 호출."""
```

### 3.10 Main Application (`main.py`)

```python
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield
    await close_db()

app = FastAPI(title="Multi-Domain Chatbot", lifespan=lifespan)

app.add_middleware(CORSMiddleware, allow_origins=["*"], ...)

app.include_router(chatbots_router)
app.include_router(chat_router)
app.include_router(history_router)
app.include_router(config_router)

# 프론트엔드 정적 파일 서빙 (마지막에 마운트)
app.mount("/", StaticFiles(directory="../frontend", html=True), name="frontend")
```

---

## 4. Frontend Design

### 4.1 Page: Marketplace (`index.html`)

**Source**: `stitch/chatbot_marketplace/code.html` 기반 변환

**변경 사항**:
- 챗봇 카드 데이터를 API(`GET /api/chatbots`)에서 동적 로딩
- 카테고리 필터 버튼: "All Experts", "Healthcare", "Movie" (프로토타입은 2개 도메인)
- "Select" 버튼 클릭 → `chat.html?domain={domain}` 으로 이동
- 검색 입력 → 클라이언트 사이드 필터링

**UI 구조** (stitch 디자인 유지):
```
┌─────────────────────────────────────────────────┐
│ Header: BotNexus 로고 | Nav | 검색바 | 프로필    │
├─────────────────────────────────────────────────┤
│ Hero: "Discover specialized AI agents."          │
├─────────────────────────────────────────────────┤
│ Category Pills: [All] [Healthcare] [Movie]       │
├─────────────────────────────────────────────────┤
│ Card Grid (2~4 columns):                         │
│ ┌──────────┐ ┌──────────┐                       │
│ │ Health   │ │ Movie    │  ← API에서 동적 로드   │
│ │ Coach    │ │ Expert   │                        │
│ │ ★ 4.8   │ │ ★ 4.7   │                        │
│ │ [Select] │ │ [Select] │                        │
│ └──────────┘ └──────────┘                       │
├─────────────────────────────────────────────────┤
│ Footer                                           │
└─────────────────────────────────────────────────┘
```

### 4.2 Page: Chat Interface (`chat.html`)

**Source**: `stitch/chat_interface/code.html` 기반 변환

**변경 사항**:
- URL 파라미터(`?domain=healthcare`)로 도메인 결정
- 사이드바: 해당 도메인의 세션 목록 API 로드
- 채팅 영역: 실시간 메시지 표시 + SSE 스트리밍
- 이미지 첨부 버튼: 영화 도메인일 때만 활성화
- LLM 모델 탭 → Config 모달 열기로 변경
- "Back to Marketplace" → `index.html`로 이동

**UI 구조**:
```
┌────────────────┬────────────────────────────────┐
│   Sidebar      │      Main Chat Area             │
│   (280px)      │                                  │
│ ┌────────────┐ │ ┌──────────────────────────────┐│
│ │ 챗봇 아이콘 │ │ │ Header: 챗봇이름 | ⚙설정     ││
│ │ 챗봇 이름   │ │ ├──────────────────────────────┤│
│ ├────────────┤ │ │                               ││
│ │ + New Chat │ │ │  Chat Messages (scrollable)   ││
│ │ ← Back     │ │ │                               ││
│ ├────────────┤ │ │  [Bot] 안녕하세요!             ││
│ │ HISTORY    │ │ │                               ││
│ │ ● 세션 1   │ │ │  [User] 건강 상담...    [You] ││
│ │ ○ 세션 2   │ │ │                               ││
│ │ ○ 세션 3   │ │ │  [Bot] 답변 스트리밍...        ││
│ │            │ │ │                               ││
│ ├────────────┤ │ ├──────────────────────────────┤│
│ │ 사용자 정보 │ │ │ Input: [첨부][이미지][마이크] ││
│ └────────────┘ │ │         [메시지 입력...] [전송]││
│                │ └──────────────────────────────┘│
└────────────────┴────────────────────────────────┘
```

**이미지 첨부 처리 (영화 도메인)**:
```
1. 사용자가 이미지 버튼 클릭
2. FileReader로 이미지 → base64 변환
3. 미리보기 표시 (입력창 위)
4. 전송 시 POST /api/chat/image/stream (image_data 포함)
5. Vision 모델이 이미지 분석 → 영화 식별 응답
```

### 4.3 Page: Chat History (`history.html`)

**Source**: `stitch/chat_history_management/code.html` 기반 변환

**변경 사항**:
- 사이드바 네비게이션 유지 (Dashboard, Chat History, Settings 등)
- 히스토리 테이블을 API(`GET /api/history`)에서 동적 로딩
- 도메인 필터 버튼: "All Domains", "Healthcare", "Movie"
- 행 클릭 → `chat.html?domain={domain}&session={id}` 으로 이동
- 삭제 버튼 → `DELETE /api/history/{session_id}`
- 하단 통계 카드 → `GET /api/history/stats`
- 페이지네이션 → page/limit 파라미터

### 4.4 Modal: LLM Configuration

**Source**: `stitch/llm_configuration/code.html` 기반

**구현 방식**: chat.html 내 모달로 삽입 (별도 페이지 아님)

**동작**:
```
1. 채팅 헤더의 ⚙ 버튼 클릭 → 모달 오픈
2. GET /api/config → 현재 설정 로드
3. 모델 선택 탭, Temperature 슬라이더, Max Tokens 슬라이더
4. System Prompt textarea (도메인 기본값 표시)
5. Streaming 토글
6. "Save Configuration" → PUT /api/config
7. 모달 닫기
```

### 4.5 공통 API Client (`static/js/api.js`)

```javascript
const API_BASE = '';  // 같은 origin (FastAPI 서빙)

const api = {
    // Chatbots
    async getChatbots(category = 'all') { ... },
    async getChatbot(domain) { ... },

    // Chat (non-streaming)
    async sendMessage(message, domain, sessionId = null) { ... },
    async sendImageMessage(message, domain, imageData, sessionId = null) { ... },

    // Chat (streaming) - returns EventSource-like reader
    async streamMessage(message, domain, sessionId = null) {
        const response = await fetch('/api/chat/stream', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message, domain, session_id: sessionId, stream: true }),
        });
        return response.body.getReader();
        // ReadableStream으로 SSE 파싱
    },

    // History
    async getHistory(domain = null, page = 1) { ... },
    async getSessionMessages(sessionId) { ... },
    async deleteSession(sessionId) { ... },
    async getStats() { ... },

    // Config
    async getConfig() { ... },
    async updateConfig(config) { ... },
};
```

---

## 5. Styling Design

### 5.1 Design Tokens (stitch 기반)

```css
/* Colors */
--primary: #256af4;
--bg-dark: #101622;
--bg-light: #f5f6f8;

/* Domain Colors */
--healthcare: #10b981;  /* emerald */
--movie: #8b5cf6;       /* purple */

/* Glass Effect */
.glass {
    background: rgba(255, 255, 255, 0.03);
    backdrop-filter: blur(12px);
    border: 1px solid rgba(255, 255, 255, 0.05);
}

/* Font */
font-family: 'Space Grotesk', sans-serif;

/* Border Radius */
--radius: 0.25rem;
--radius-lg: 0.5rem;
--radius-xl: 0.75rem;
```

### 5.2 Tailwind Config (공통)

```javascript
tailwind.config = {
    darkMode: "class",
    theme: {
        extend: {
            colors: {
                "primary": "#256af4",
                "background-light": "#f5f6f8",
                "background-dark": "#101622",
                "healthcare": "#10b981",
                "movie": "#8b5cf6",
            },
            fontFamily: {
                "display": ["Space Grotesk", "sans-serif"]
            },
        },
    },
}
```

---

## 6. Implementation Order

| Step | Task | Files | Depends On |
|------|------|-------|------------|
| 1 | 프로젝트 구조 생성 + requirements.txt | `backend/`, `frontend/` | - |
| 2 | DB 모듈 + 스키마 초기화 | `models/database.py`, `models/schemas.py` | Step 1 |
| 3 | 도메인 매니저 | `services/domain_manager.py` | Step 1 |
| 4 | OpenRouter 클라이언트 | `services/openrouter.py`, `.env` | Step 1 |
| 5 | 챗봇 목록 라우터 | `routers/chatbots.py` | Step 3 |
| 6 | 채팅 서비스 + 라우터 | `services/chat_service.py`, `routers/chat.py` | Step 2,3,4 |
| 7 | 히스토리 라우터 | `routers/history.py` | Step 2 |
| 8 | Config 라우터 | `routers/config.py` | Step 2 |
| 9 | FastAPI main.py 조합 | `main.py` | Step 5,6,7,8 |
| 10 | Frontend: api.js | `static/js/api.js` | Step 9 |
| 11 | Frontend: Marketplace | `index.html`, `static/js/marketplace.js` | Step 10 |
| 12 | Frontend: Chat Interface | `chat.html`, `static/js/chat.js` | Step 10 |
| 13 | Frontend: 이미지 업로드 (영화) | `chat.js` 확장 | Step 12 |
| 14 | Frontend: SSE 스트리밍 | `chat.js` 확장 | Step 12 |
| 15 | Frontend: History 페이지 | `history.html`, `static/js/history.js` | Step 10 |
| 16 | Frontend: LLM Config 모달 | `chat.html` 내 모달 | Step 12 |

---

## 7. Dependencies

### 7.1 `requirements.txt`

```
fastapi==0.115.*
uvicorn[standard]==0.34.*
aiosqlite==0.21.*
httpx==0.28.*
python-dotenv==1.1.*
pydantic==2.*
```

### 7.2 `.env`

```
OPENROUTER_API_KEY=sk-or-v1-xxxxxxxxxxxxx
```

### 7.3 `.gitignore`

```
.env
__pycache__/
*.pyc
chatbot.db
```

---

## 8. Error Handling

| Error Case | HTTP Status | Handling |
|------------|-------------|----------|
| 존재하지 않는 도메인 | 404 | `{"detail": "Domain not found: {domain}"}` |
| 세션 없음 | 404 | `{"detail": "Session not found"}` |
| OpenRouter API 오류 | 502 | `{"detail": "LLM service error"}` + 로깅 |
| OpenRouter 타임아웃 | 504 | `{"detail": "LLM service timeout"}` |
| 이미지 크기 초과 (>5MB) | 413 | `{"detail": "Image too large. Max 5MB"}` |
| 잘못된 설정 값 | 422 | Pydantic 자동 validation |
| DB 오류 | 500 | `{"detail": "Internal server error"}` + 로깅 |

---

## 9. Startup Commands

```bash
# 1. 가상환경 생성 및 활성화
cd backend
python -m venv venv
source venv/Scripts/activate  # Windows Git Bash

# 2. 의존성 설치
pip install -r requirements.txt

# 3. 환경변수 설정
cp .env.example .env
# .env 파일에 OPENROUTER_API_KEY 입력

# 4. 서버 실행
uvicorn main:app --reload --port 8000

# 5. 브라우저에서 접속
# http://localhost:8000
```
