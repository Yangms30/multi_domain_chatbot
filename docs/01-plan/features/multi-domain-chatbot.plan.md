# Plan: Multi-Domain Chatbot Website (Prototype)

## Executive Summary

| Perspective | Description |
|-------------|-------------|
| **Problem** | 도메인별 전문 AI 챗봇을 하나의 플랫폼에서 제공하는 통합 인터페이스가 없어, 사용자가 각 도메인(헬스케어, 영화 등)에 맞는 AI 상담을 쉽게 받을 수 없음 |
| **Solution** | OpenRouter LLM 기반의 멀티 도메인 챗봇 마켓플레이스 웹사이트. FastAPI 백엔드 + HTML/CSS/JS 프론트엔드로 프로토타입 구축 |
| **Function UX Effect** | 마켓플레이스에서 도메인 챗봇 선택 → 전용 채팅 인터페이스에서 대화 → 이미지 입력/건강 상담 등 도메인 특화 기능 즉시 사용 |
| **Core Value** | 하나의 플랫폼에서 다양한 전문 도메인 AI를 즉시 활용할 수 있는 통합 경험 제공 |

---

## 1. Project Overview

- **Project Name**: Multi-Domain Chatbot Website
- **Type**: Prototype / MVP
- **Target**: 멀티 도메인 챗봇 마켓플레이스 웹사이트
- **Duration**: 프로토타입 (빠른 개발)
- **Date**: 2026-03-18

## 2. Requirements

### 2.1 Functional Requirements

#### FR-01: Chatbot Marketplace (메인 페이지)
- 도메인별 챗봇 카드 그리드 표시
- 카테고리 필터링 (Healthcare, Movie, All Experts 등)
- 챗봇 검색 기능
- 챗봇 선택 시 채팅 인터페이스로 이동

#### FR-02: Healthcare Domain Chatbot
- 개인 건강 상담 대화
- 사용자 건강 정보 기반 맞춤 답변 (System Prompt 활용)
- 증상 분석 및 건강 조언 제공
- 운동/식단 추천

#### FR-03: Movie Domain Chatbot
- 영화 추천 (장르, 분위기, 배우 기반)
- 영화 이미지 입력 → 영화 식별 (Vision API 활용)
- 영화 정보 제공 (줄거리, 출연진, 평점 등)
- 영화 관련 대화

#### FR-04: Chat Interface
- 실시간 채팅 UI (stitch/chat_interface 디자인 기반)
- 메시지 히스토리 표시
- 이미지 첨부 기능 (영화 도메인용)
- 스트리밍 응답 지원
- New Chat / Back to Marketplace 네비게이션

#### FR-05: Chat History Management
- 대화 기록 목록 표시 (stitch/chat_history_management 디자인 기반)
- 도메인별 필터링
- 대화 검색
- 통계 대시보드 (총 채팅 수, 이번 달 활성 수)

#### FR-06: LLM Configuration
- OpenRouter API를 통한 LLM 모델 선택
- Temperature, Max Output Tokens 파라미터 설정
- System Prompt 커스터마이징
- Streaming 토글

### 2.2 Non-Functional Requirements

| ID | Requirement | Target |
|----|-------------|--------|
| NFR-01 | 프로토타입 수준 성능 | 응답 시간 < 5초 (LLM 응답 제외) |
| NFR-02 | 다크 테마 UI | stitch 디자인 기반 다크 모드 |
| NFR-03 | 로컬 개발 환경 | Docker 없이 단독 실행 가능 |
| NFR-04 | 데이터 저장 | SQLite (프로토타입용 경량 DB) |

## 3. Technical Stack

| Layer | Technology | Rationale |
|-------|------------|-----------|
| **Frontend** | HTML + Tailwind CSS + Vanilla JS | stitch 디자인 활용, 빠른 프로토타이핑 |
| **Backend** | FastAPI (Python) | 사용자 요청, 비동기 처리, OpenRouter 연동 |
| **LLM API** | OpenRouter API | 다양한 LLM 모델 접근 (GPT-4, Claude 등) |
| **Database** | SQLite + aiosqlite | 프로토타입용 경량 DB, 채팅 히스토리 저장 |
| **Styling** | Tailwind CSS (CDN) | stitch HTML에서 이미 사용 중 |
| **Font** | Space Grotesk | stitch 디자인 통일 |

## 4. Architecture

```
┌─────────────────────────────────────────────────────┐
│                   Frontend (Static)                  │
│  ┌─────────┐  ┌──────────┐  ┌───────────────────┐  │
│  │Marketplace│ │Chat UI   │  │Chat History/Config│  │
│  │(index)   │ │(chat)    │  │(history/config)   │  │
│  └─────────┘  └──────────┘  └───────────────────┘  │
└──────────────────────┬──────────────────────────────┘
                       │ REST API + SSE (Streaming)
┌──────────────────────▼──────────────────────────────┐
│                 FastAPI Backend                       │
│  ┌──────────┐  ┌──────────┐  ┌────────────────┐    │
│  │Chat API  │  │Domain    │  │OpenRouter      │    │
│  │Router    │  │Manager   │  │Client          │    │
│  └──────────┘  └──────────┘  └────────────────┘    │
│  ┌──────────┐  ┌──────────┐                         │
│  │History   │  │Config    │                         │
│  │Manager   │  │Manager   │                         │
│  └──────────┘  └──────────┘                         │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│              Data Layer                              │
│  ┌──────────┐  ┌──────────────────────────────┐    │
│  │SQLite DB │  │OpenRouter API (External)      │    │
│  │(local)   │  │                               │    │
│  └──────────┘  └──────────────────────────────┘    │
└─────────────────────────────────────────────────────┘
```

## 5. Domain Chatbot Specifications

### 5.1 Healthcare Chatbot
- **System Prompt**: "당신은 전문 건강 상담 AI입니다. 사용자의 건강 상태, 증상, 생활 습관에 대해 친절하고 전문적으로 상담합니다. 의학적 진단은 하지 않으며, 일반적인 건강 조언을 제공합니다."
- **Features**: 증상 분석, 운동 추천, 식단 조언, 건강 습관 개선
- **Icon**: health_and_safety (Material Symbols)
- **Color**: Emerald (#10b981)

### 5.2 Movie Chatbot
- **System Prompt**: "당신은 영화 전문가 AI입니다. 영화 추천, 영화 정보 제공, 영화 이미지 분석을 수행합니다. 사용자의 취향에 맞는 영화를 추천하고 상세한 영화 정보를 제공합니다."
- **Features**: 영화 추천, 이미지로 영화 식별 (Vision), 영화 정보 검색
- **Icon**: movie (Material Symbols)
- **Color**: Purple (#8b5cf6)
- **Special**: 이미지 업로드 → OpenRouter Vision 모델로 영화 식별

## 6. API Design (FastAPI)

### 6.1 Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/chatbots` | 챗봇 목록 조회 |
| GET | `/api/chatbots/{domain}` | 특정 도메인 챗봇 정보 |
| POST | `/api/chat` | 채팅 메시지 전송 (텍스트) |
| POST | `/api/chat/image` | 이미지 포함 채팅 (영화 도메인) |
| GET | `/api/chat/stream` | SSE 스트리밍 응답 |
| GET | `/api/history` | 채팅 히스토리 목록 |
| GET | `/api/history/{chat_id}` | 특정 채팅 히스토리 |
| DELETE | `/api/history/{chat_id}` | 채팅 삭제 |
| GET | `/api/config` | LLM 설정 조회 |
| PUT | `/api/config` | LLM 설정 변경 |

### 6.2 Data Models

```python
# Chat Message
class ChatMessage:
    id: str
    chat_id: str
    role: str  # "user" | "assistant"
    content: str
    image_url: str | None  # 이미지 첨부 시
    domain: str  # "healthcare" | "movie"
    created_at: datetime

# Chat Session
class ChatSession:
    id: str
    domain: str
    title: str
    last_message: str
    created_at: datetime
    updated_at: datetime

# LLM Config
class LLMConfig:
    model: str  # OpenRouter 모델 ID
    temperature: float  # 0.0 ~ 2.0
    max_tokens: int
    system_prompt: str
    stream: bool

# Domain Chatbot
class DomainChatbot:
    domain: str
    name: str
    description: str
    icon: str
    color: str
    system_prompt: str
    supports_image: bool
```

## 7. Frontend Pages (stitch 기반)

| Page | Source | Route | Description |
|------|--------|-------|-------------|
| Marketplace | `stitch/chatbot_marketplace` | `/` | 챗봇 선택 메인 페이지 |
| Chat | `stitch/chat_interface` | `/chat/{domain}` | 도메인 챗봇 채팅 |
| History | `stitch/chat_history_management` | `/history` | 대화 기록 관리 |
| Config | `stitch/llm_configuration` | Modal (in chat) | LLM 설정 모달 |

## 8. Project Structure

```
chatbot/
├── backend/
│   ├── main.py                 # FastAPI 엔트리포인트
│   ├── routers/
│   │   ├── chat.py             # 채팅 API
│   │   ├── chatbots.py         # 챗봇 목록 API
│   │   ├── history.py          # 히스토리 API
│   │   └── config.py           # LLM 설정 API
│   ├── services/
│   │   ├── openrouter.py       # OpenRouter API 클라이언트
│   │   ├── domain_manager.py   # 도메인별 챗봇 관리
│   │   └── chat_service.py     # 채팅 비즈니스 로직
│   ├── models/
│   │   ├── schemas.py          # Pydantic 모델
│   │   └── database.py         # SQLite 설정
│   ├── requirements.txt
│   └── .env                    # OPENROUTER_API_KEY
├── frontend/
│   ├── index.html              # Marketplace (stitch 기반)
│   ├── chat.html               # Chat Interface (stitch 기반)
│   ├── history.html            # Chat History (stitch 기반)
│   ├── static/
│   │   ├── css/
│   │   │   └── styles.css      # 공통 스타일
│   │   └── js/
│   │       ├── marketplace.js  # 마켓플레이스 로직
│   │       ├── chat.js         # 채팅 로직 + 스트리밍
│   │       ├── history.js      # 히스토리 로직
│   │       └── api.js          # API 클라이언트
│   └── assets/
├── stitch/                     # 디자인 레퍼런스 (원본 유지)
├── docs/
└── README.md
```

## 9. Implementation Order

| Phase | Task | Priority |
|-------|------|----------|
| 1 | Backend 기본 구조 + FastAPI 설정 | P0 |
| 2 | OpenRouter API 클라이언트 구현 | P0 |
| 3 | 도메인 챗봇 관리 (Healthcare, Movie) | P0 |
| 4 | 채팅 API + SQLite DB | P0 |
| 5 | Frontend Marketplace (stitch 기반 변환) | P0 |
| 6 | Frontend Chat Interface (stitch 기반 변환) | P0 |
| 7 | 이미지 업로드 + Vision API (영화 도메인) | P1 |
| 8 | 스트리밍 응답 (SSE) | P1 |
| 9 | Chat History 페이지 | P1 |
| 10 | LLM Configuration 모달 | P2 |

## 10. Key Decisions

| Decision | Choice | Reason |
|----------|--------|--------|
| Frontend framework | Vanilla HTML/JS | stitch 디자인이 이미 HTML, 프로토타입이므로 프레임워크 불필요 |
| DB | SQLite | 프로토타입용, 설치 없이 사용 가능 |
| LLM Provider | OpenRouter | 다양한 모델 접근, 단일 API로 여러 LLM 사용 가능 |
| Streaming | SSE (Server-Sent Events) | WebSocket보다 구현 간단, 프로토타입에 적합 |
| Image handling | Base64 encoding | 프로토타입용, 파일 서버 불필요 |
| Frontend serving | FastAPI StaticFiles | 별도 웹서버 불필요, 단일 서버 구동 |

## 11. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| OpenRouter API 키 노출 | High | .env 파일 분리, .gitignore 추가 |
| Vision API 모델 비용 | Medium | 이미지 크기 제한, 사용량 모니터링 |
| 프로토타입 범위 확대 | Medium | P0 기능만 우선 구현, P1/P2는 후순위 |
| 한국어 응답 품질 | Low | System Prompt에 한국어 응답 명시 |
