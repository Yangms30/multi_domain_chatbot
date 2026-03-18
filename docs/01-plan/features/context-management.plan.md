# Plan: Context Management (슬라이딩 윈도우 + 요약)

## Executive Summary

| Perspective | Description |
|-------------|-------------|
| **Problem** | 현재 세션 내 최근 20개 메시지만 고정 로드하여, 긴 대화 시 초반 맥락이 유실되고 토큰 한도 초과 위험이 있음 |
| **Solution** | 슬라이딩 윈도우 + LLM 요약 방식으로 오래된 메시지를 자동 요약 압축하고, 최근 N개 원문은 유지하여 전체 대화 맥락을 보존 |
| **Function UX Effect** | 사용자가 1시간 전 얘기한 내용도 챗봇이 기억하고 참조하여 답변 → "이 챗봇 나를 진짜 알아" 느낌 |
| **Core Value** | 대화가 길어져도 맥락이 끊기지 않는 연속적인 대화 경험 제공 |

---

## 1. Project Overview

- **Feature Name**: Context Management (Sliding Window + Summary)
- **Type**: 기존 기능 개선
- **Target**: chat_service.py의 `_build_messages` 메서드 개선
- **Date**: 2026-03-18
- **Parent Plan**: multi-domain-chatbot.plan.md

## 2. Requirements

### 2.1 Functional Requirements

#### FR-01: 대화 요약 자동 생성
- 세션 내 메시지가 설정된 윈도우 크기(기본 10개)를 초과하면 오래된 메시지를 LLM으로 요약
- 요약은 `chat_sessions` 테이블의 새 컬럼 `context_summary`에 저장
- 요약은 한국어로 생성, 핵심 맥락과 사용자 의도를 보존

#### FR-02: 슬라이딩 윈도우 메시지 로드
- 최근 N개(기본 10개) 메시지는 원문 그대로 유지
- 그 이전 메시지는 요약문으로 대체
- LLM에 전달되는 형태: `[시스템 프롬프트] + [메모리] + [대화 요약] + [최근 10개 원문]`

#### FR-03: 점진적 요약 업데이트
- 새 메시지가 추가될 때마다 윈도우가 밀리면서 요약 대상이 늘어남
- 기존 요약 + 새로 밀려난 메시지를 합쳐서 요약 갱신 (매번 전체 재요약 X)
- 요약 갱신은 비동기로 처리하여 응답 속도에 영향 없음

#### FR-04: 토큰 안전장치
- 전체 메시지(시스템 프롬프트 + 요약 + 원문)의 추정 토큰 수 계산
- 모델별 토큰 한도의 80%를 초과하면 윈도우 크기를 자동 축소
- 토큰 추정: 한국어 기준 글자 수 × 0.5 (대략적 추정)

### 2.2 Non-Functional Requirements

| ID | Requirement | Target |
|----|-------------|--------|
| NFR-01 | 요약 생성 지연 | 응답 후 비동기 처리, 사용자 체감 지연 0 |
| NFR-02 | 요약 품질 | 핵심 맥락/사용자 의도/결론이 보존될 것 |
| NFR-03 | 토큰 효율 | 20개 원문 대비 토큰 사용량 30~50% 절감 |

## 3. Technical Design

### 3.1 메시지 구성 흐름

```
대화 메시지 총 35개인 경우:

기존 방식:
  [system] + [msg 16~35] (최근 20개만, 1~15 유실)

개선 방식:
  [system] + [memory] + [summary of msg 1~25] + [msg 26~35] (전체 맥락 보존)
```

### 3.2 요약 생성 타이밍

```
메시지 수: 1  2  3 ... 10  11  12 ... 20  21 ...
           ─────────────  ───────────────  ───────
           원문 유지       11번째 메시지 도착 시
                          → msg 1~2를 요약 생성
                          → msg 3~12 원문 유지

                                          21번째 도착 시
                                          → 기존 요약 + msg 3~12 합쳐서 재요약
                                          → msg 13~22 원문 유지
```

### 3.3 DB 스키마 변경

```sql
-- chat_sessions 테이블에 요약 컬럼 추가
ALTER TABLE chat_sessions ADD COLUMN context_summary TEXT DEFAULT '';
ALTER TABLE chat_sessions ADD COLUMN summary_until_index INTEGER DEFAULT 0;
```

- `context_summary`: 압축된 대화 요약 텍스트
- `summary_until_index`: 몇 번째 메시지까지 요약에 포함되었는지

### 3.4 수정 대상 파일

| File | Changes |
|------|---------|
| `services/chat_service.py` | `_build_messages` 수정, `_summarize_old_messages` 추가 |
| `services/context_manager.py` | **신규** - 요약 생성/관리 전담 서비스 |
| `models/database.py` | `init_db`에서 마이그레이션 SQL 실행 |
| `supabase_schema.sql` | chat_sessions 테이블에 컬럼 추가 |

## 4. Message Build 로직 (핵심)

```python
def _build_messages(self, session_id, domain, user_id):
    system_prompt = get_system_prompt(domain)

    # 1. 장기 메모리 (agent_memory)
    memory_context = self.memory.build_memory_prompt(user_id, domain)
    if memory_context:
        system_prompt += memory_context

    messages = [{"role": "system", "content": system_prompt}]

    # 2. 대화 요약 (오래된 메시지 압축본)
    session = db.table("chat_sessions").select("context_summary").eq("id", session_id).execute()
    summary = session.data[0].get("context_summary", "")
    if summary:
        messages.append({"role": "system", "content": f"[이전 대화 요약]\n{summary}"})

    # 3. 최근 N개 원문 메시지
    recent = db.table("chat_messages") \
        .select("role, content") \
        .eq("session_id", session_id) \
        .order("created_at") \
        .limit(WINDOW_SIZE) \          # 기본 10
        .offset(max(0, total - WINDOW_SIZE)) \
        .execute()

    for row in recent.data:
        messages.append({"role": row["role"], "content": row["content"]})

    return messages
```

## 5. Implementation Order

| Phase | Task | Priority |
|-------|------|----------|
| 1 | Supabase 스키마 마이그레이션 (context_summary 컬럼 추가) | P0 |
| 2 | `context_manager.py` 서비스 생성 (요약 생성/갱신 로직) | P0 |
| 3 | `chat_service.py` `_build_messages` 수정 (요약 + 윈도우) | P0 |
| 4 | 요약 갱신 비동기 호출 연결 (stream_chat 완료 후) | P0 |
| 5 | 토큰 추정 및 윈도우 자동 축소 로직 | P1 |
| 6 | 요약 품질 테스트 및 프롬프트 튜닝 | P1 |

## 6. Key Decisions

| Decision | Choice | Reason |
|----------|--------|--------|
| 요약 저장 위치 | chat_sessions 테이블 컬럼 | 세션별 1:1 관계, 별도 테이블 불필요 |
| 요약 생성 모델 | gpt-4o-mini (동일 모델) | 추가 비용 최소화, 충분한 요약 품질 |
| 윈도우 크기 | 10개 (설정 가능) | 맥락 유지와 토큰 효율의 균형점 |
| 요약 갱신 방식 | 점진적 (기존 요약 + 새 메시지) | 매번 전체 재요약보다 효율적 |
| 요약 타이밍 | 응답 완료 후 비동기 | 사용자 체감 지연 없음 |

## 7. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| 요약 시 중요 맥락 누락 | High | 요약 프롬프트에 "핵심 사실, 사용자 의도, 결론 반드시 포함" 명시 |
| 요약 생성 API 비용 추가 | Medium | gpt-4o-mini 사용, 요약은 필요 시에만 갱신 |
| 요약 + 원문 합산 토큰 초과 | Medium | 토큰 추정 안전장치 (FR-04) |
| 요약 비동기 처리 실패 | Low | 실패 시 다음 메시지에서 재시도, best-effort |
