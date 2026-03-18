# Design: Context Management (슬라이딩 윈도우 + 요약)

> Plan Reference: `docs/01-plan/features/context-management.plan.md`

## 1. Overview

### 1.1 현재 구조 (Before)

```
_build_messages()
  → [system_prompt + memory] + [최근 20개 메시지 원문]
  → 21번째 메시지부터 초반 대화 유실
  → 토큰 관리 없음
```

### 1.2 목표 구조 (After)

```
_build_messages()
  → [system_prompt + memory] + [대화 요약] + [최근 10개 메시지 원문]
  → 전체 대화 맥락 보존
  → 토큰 추정 기반 안전장치
```

### 1.3 LLM에 전달되는 메시지 배열

```
messages = [
  { role: "system",    content: "도메인 시스템 프롬프트 + 에이전트 메모리" },
  { role: "system",    content: "[이전 대화 요약]\n사용자가 무릎 통증에 대해..." },
  { role: "user",      content: "최근 메시지 1" },
  { role: "assistant", content: "최근 응답 1" },
  ...
  { role: "user",      content: "최근 메시지 N (가장 최신)" },
]
```

## 2. DB Schema Changes

### 2.1 chat_sessions 테이블 컬럼 추가

```sql
-- 마이그레이션 SQL (Supabase SQL Editor에서 실행)
ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS context_summary TEXT DEFAULT '';
ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS summary_message_count INTEGER DEFAULT 0;
```

| Column | Type | Default | Description |
|--------|------|---------|-------------|
| `context_summary` | TEXT | `''` | LLM이 생성한 이전 대화 요약문 |
| `summary_message_count` | INTEGER | `0` | 요약에 포함된 메시지 수 (몇 개까지 요약했는지) |

### 2.2 supabase_schema.sql 업데이트

기존 `chat_sessions` CREATE TABLE에 두 컬럼 추가:

```sql
CREATE TABLE IF NOT EXISTS chat_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    domain TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT 'New Chat',
    user_id TEXT DEFAULT 'default',
    context_summary TEXT DEFAULT '',              -- 추가
    summary_message_count INTEGER DEFAULT 0,      -- 추가
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);
```

## 3. New File: `services/context_manager.py`

### 3.1 Class Structure

```python
WINDOW_SIZE = 10          # 최근 원문 유지 개수
SUMMARY_THRESHOLD = 12    # 이 개수 초과 시 요약 시작 (윈도우 + 버퍼 2개)
MAX_SUMMARY_TOKENS = 500  # 요약문 최대 토큰 (추정)

class ContextManager:
    def __init__(self, openrouter: OpenRouterClient):
        self.openrouter = openrouter

    def get_context_messages(self, session_id: str, domain: str, user_id: str) -> list[dict]:
        """세션의 컨텍스트 메시지 배열을 구성하여 반환"""

    async def update_summary_if_needed(self, session_id: str):
        """메시지 수가 threshold를 초과하면 요약 갱신 (비동기)"""

    async def _generate_summary(self, existing_summary: str, new_messages: list[dict]) -> str:
        """기존 요약 + 새 메시지를 합쳐서 LLM으로 요약 생성"""

    def _estimate_tokens(self, text: str) -> int:
        """텍스트의 토큰 수 추정 (한국어: 글자수 * 0.5)"""
```

### 3.2 핵심 메서드 상세

#### `get_context_messages(session_id, domain, user_id)`

```python
def get_context_messages(self, session_id: str, domain: str, user_id: str) -> list[dict]:
    db = get_db()

    # 1. 시스템 프롬프트 + 메모리
    system_prompt = get_system_prompt(domain)
    memory_context = self.memory.build_memory_prompt(user_id, domain)
    if memory_context:
        system_prompt += memory_context
    messages = [{"role": "system", "content": system_prompt}]

    # 2. 세션의 요약 조회
    session = db.table("chat_sessions") \
        .select("context_summary, summary_message_count") \
        .eq("id", session_id).execute()
    session_data = session.data[0] if session.data else {}
    summary = session_data.get("context_summary", "")
    summary_count = session_data.get("summary_message_count", 0)

    # 3. 요약이 있으면 시스템 메시지로 주입
    if summary:
        messages.append({
            "role": "system",
            "content": f"[이전 대화 요약 ({summary_count}개 메시지)]\n{summary}"
        })

    # 4. 요약 이후의 메시지만 원문 로드 (최근 WINDOW_SIZE개)
    all_messages = db.table("chat_messages") \
        .select("role, content") \
        .eq("session_id", session_id) \
        .order("created_at") \
        .execute()
    all_msgs = all_messages.data or []

    # 요약된 부분 이후의 메시지 = 원문 유지 대상
    recent_msgs = all_msgs[summary_count:]

    # 안전장치: WINDOW_SIZE 초과 시 뒤에서부터 자르기
    if len(recent_msgs) > WINDOW_SIZE:
        recent_msgs = recent_msgs[-WINDOW_SIZE:]

    for row in recent_msgs:
        messages.append({"role": row["role"], "content": row["content"]})

    return messages
```

#### `update_summary_if_needed(session_id)`

```python
async def update_summary_if_needed(self, session_id: str):
    db = get_db()

    # 전체 메시지 수 조회
    count_result = db.table("chat_messages") \
        .select("id", count="exact") \
        .eq("session_id", session_id).execute()
    total_count = count_result.count or 0

    # 세션의 현재 요약 상태
    session = db.table("chat_sessions") \
        .select("context_summary, summary_message_count") \
        .eq("id", session_id).execute()
    session_data = session.data[0] if session.data else {}
    current_summary = session_data.get("context_summary", "")
    summary_count = session_data.get("summary_message_count", 0)

    # 요약 대상 = 전체 - 윈도우
    messages_outside_window = total_count - WINDOW_SIZE

    # 요약이 필요한 조건: 윈도우 밖 메시지가 있고, 아직 요약 안 된 게 있을 때
    if messages_outside_window <= 0 or messages_outside_window <= summary_count:
        return  # 요약 불필요

    # 새로 요약에 포함할 메시지 로드 (summary_count ~ messages_outside_window)
    all_messages = db.table("chat_messages") \
        .select("role, content") \
        .eq("session_id", session_id) \
        .order("created_at") \
        .execute()
    all_msgs = all_messages.data or []

    new_to_summarize = all_msgs[summary_count:messages_outside_window]
    if not new_to_summarize:
        return

    # LLM으로 요약 생성
    new_summary = await self._generate_summary(current_summary, new_to_summarize)

    # DB 업데이트
    db.table("chat_sessions").update({
        "context_summary": new_summary,
        "summary_message_count": messages_outside_window,
    }).eq("id", session_id).execute()
```

#### `_generate_summary(existing_summary, new_messages)`

```python
async def _generate_summary(self, existing_summary: str, new_messages: list[dict]) -> str:
    new_text = "\n".join(
        f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content'][:300]}"
        for m in new_messages
    )

    if existing_summary:
        prompt = f"""기존 대화 요약과 새로운 대화 내용을 합쳐서 하나의 통합 요약을 작성하세요.

기존 요약:
{existing_summary}

새 대화 내용:
{new_text}

규칙:
- 300자 이내로 요약
- 사용자의 핵심 질문, 의도, 선호도, 중요한 사실을 반드시 포함
- 대화의 결론이나 합의된 내용 포함
- 시간순으로 정리
- 한국어로 작성"""
    else:
        prompt = f"""다음 대화 내용을 요약하세요.

대화 내용:
{new_text}

규칙:
- 300자 이내로 요약
- 사용자의 핵심 질문, 의도, 선호도, 중요한 사실을 반드시 포함
- 대화의 결론이나 합의된 내용 포함
- 한국어로 작성"""

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
        return existing_summary  # 실패 시 기존 요약 유지
```

#### `_estimate_tokens(text)`

```python
def _estimate_tokens(self, text: str) -> int:
    # 한국어: 약 1.5~2 characters per token
    # 영어: 약 4 characters per token
    # 혼합 평균: 글자수 * 0.5로 추정
    return int(len(text) * 0.5)
```

## 4. Modified File: `services/chat_service.py`

### 4.1 변경 사항

| Method | Change |
|--------|--------|
| `__init__` | `ContextManager` 인스턴스 추가 |
| `_build_messages` | `ContextManager.get_context_messages()` 호출로 교체 |
| `process_chat` | 응답 후 `update_summary_if_needed()` 비동기 호출 추가 |
| `stream_chat` | 스트림 완료 후 `update_summary_if_needed()` 비동기 호출 추가 |
| `stream_chat_with_image` | 동일하게 요약 갱신 호출 추가 |

### 4.2 변경 코드

```python
# __init__
from services.context_manager import ContextManager

class ChatService:
    def __init__(self, openrouter: OpenRouterClient):
        self.openrouter = openrouter
        self.memory = MemoryService(openrouter)
        self.context = ContextManager(openrouter)  # 추가

    # _build_messages → 단순화
    def _build_messages(self, session_id: str, domain: str, user_id: str) -> list[dict]:
        return self.context.get_context_messages(session_id, domain, user_id)

    # process_chat에서 요약 갱신 추가 (메모리 추출 옆에)
    async def process_chat(self, ...):
        ...
        # 기존: await self.memory.extract_and_store_memories(...)
        await self.memory.extract_and_store_memories(user_id, domain, conversation)
        await self.context.update_summary_if_needed(session_id)  # 추가
        ...

    # stream_chat에서도 동일
    async def stream_chat(self, ...):
        ...
        await self.memory.extract_and_store_memories(user_id, domain, conversation)
        await self.context.update_summary_if_needed(session_id)  # 추가
```

## 5. Modified File: `models/database.py`

### 5.1 init_db 마이그레이션 추가

```python
async def init_db():
    db = get_db()

    # 기존 연결 확인 코드 유지...

    # 컬럼 마이그레이션 (context_summary)
    try:
        db.rpc("exec_sql", {
            "query": "ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS context_summary TEXT DEFAULT ''"
        }).execute()
        db.rpc("exec_sql", {
            "query": "ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS summary_message_count INTEGER DEFAULT 0"
        }).execute()
    except Exception:
        pass  # 이미 존재하거나 RPC 미지원 시 무시 (수동 마이그레이션 필요)
```

> **Note**: Supabase는 RPC로 DDL 실행이 제한될 수 있으므로, SQL Editor에서 수동 실행하는 마이그레이션 SQL도 제공합니다.

## 6. Modified File: `supabase_schema.sql`

기존 파일 하단에 마이그레이션 섹션 추가:

```sql
-- ============================================
-- Migration: Context Management
-- ============================================
ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS context_summary TEXT DEFAULT '';
ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS summary_message_count INTEGER DEFAULT 0;
```

## 7. Data Flow Diagram

```
사용자 메시지 도착
       │
       ▼
┌─────────────────────┐
│  1. 메시지 DB 저장    │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────────────────────────────┐
│  2. _build_messages (ContextManager)          │
│  ┌─────────────────────────────────────────┐ │
│  │ system_prompt + agent_memory            │ │
│  ├─────────────────────────────────────────┤ │
│  │ context_summary (이전 대화 요약)         │ │
│  ├─────────────────────────────────────────┤ │
│  │ 최근 10개 메시지 원문                    │ │
│  └─────────────────────────────────────────┘ │
└──────────┬──────────────────────────────────┘
           │
           ▼
┌─────────────────────┐
│  3. LLM API 호출     │
│  (OpenRouter)        │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  4. 응답 DB 저장     │
└──────────┬──────────┘
           │
           ▼ (비동기, 병렬)
    ┌──────┴──────┐
    ▼             ▼
┌────────┐  ┌─────────────┐
│메모리   │  │요약 갱신      │
│추출     │  │(threshold    │
│        │  │ 초과 시만)    │
└────────┘  └─────────────┘
```

## 8. 요약 갱신 시나리오

### 시나리오 1: 메시지 8개 (요약 불필요)

```
total=8, WINDOW_SIZE=10, SUMMARY_THRESHOLD=12
→ 8 < 12, 요약 생성 안 함
→ messages = [system] + [msg 1~8 원문]
```

### 시나리오 2: 메시지 15개 (첫 요약 생성)

```
total=15, WINDOW_SIZE=10
→ messages_outside_window = 15 - 10 = 5
→ summary_count = 0 (아직 요약 없음)
→ msg 1~5를 LLM으로 요약 생성
→ DB: context_summary = "...", summary_message_count = 5
→ messages = [system] + [요약(1~5)] + [msg 6~15 원문]
```

### 시나리오 3: 메시지 25개 (점진적 요약 갱신)

```
total=25, WINDOW_SIZE=10
→ messages_outside_window = 25 - 10 = 15
→ summary_count = 5 (이전에 5개까지 요약됨)
→ msg 6~15를 기존 요약과 합쳐서 재요약
→ DB: context_summary = "...(통합)", summary_message_count = 15
→ messages = [system] + [요약(1~15)] + [msg 16~25 원문]
```

## 9. Implementation Order

| Step | File | Action | Dependency |
|------|------|--------|------------|
| 1 | `supabase_schema.sql` | 마이그레이션 SQL 추가 + Supabase에서 실행 | 없음 |
| 2 | `services/context_manager.py` | 신규 파일 생성 | Step 1 |
| 3 | `services/chat_service.py` | ContextManager 통합 | Step 2 |
| 4 | `models/database.py` | init_db 마이그레이션 시도 추가 | Step 1 |

## 10. Testing Checklist

- [ ] 메시지 10개 이하: 요약 없이 전체 원문 전달 확인
- [ ] 메시지 15개: 첫 요약 생성 확인 (DB에 context_summary 저장)
- [ ] 메시지 25개: 점진적 요약 갱신 확인
- [ ] 요약 API 실패 시: 기존 요약 유지, 에러 무시 확인
- [ ] 새 세션: context_summary가 빈 문자열로 시작 확인
- [ ] 기존 세션 (마이그레이션 후): 정상 동작 확인
