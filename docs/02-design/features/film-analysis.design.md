# Film Analysis Design

## Executive Summary

| 항목 | 내용 |
|------|------|
| Feature | 영화 전문 분석 (촬영기법, 스토리 구조, 테마 해석) |
| Plan 참조 | `docs/01-plan/features/film-analysis.plan.md` |
| 설계일 | 2026-03-27 |

### Value Delivered

| 관점 | 내용 |
|------|------|
| **Problem** | 정보 조회만 가능, 깊이 있는 분석 부재 |
| **Solution** | DB context + LLM 분석 전용 prompt |
| **Function UX Effect** | 4개 카테고리 구조화된 전문 분석 |
| **Core Value** | 추천 봇 → 영화 전문 분석 봇 진화 |

---

## 1. 아키텍처

### 핵심 플로우
```
User: "기생충 분석해줘"
  → KnowledgeQuery._try_film_analysis()
    → 키워드 감지 ("분석")
    → 영화 제목 추출 ("기생충")
    → DB에서 영화 데이터 조회
    → return ("__FILM_ANALYSIS__", context_json)  ← 특수 마커
  → ChatService.stream_chat()
    → 특수 마커 감지
    → FilmAnalysisService.build_messages(context)
    → OpenRouter 스트리밍 호출
    → source: "영화 전문 분석 (AI)"
```

### 핵심 설계 결정: 특수 마커 패턴

Film Analysis는 rule-based에서 **감지**하지만 **응답은 LLM**이 생성해야 합니다.
기존 rule_result는 `(response_text, source)` 형태라 LLM 스트리밍과 호환 안 됨.

해결: `_try_film_analysis()`가 특수 마커를 반환하면 `stream_chat()`에서 인식하여 LLM 분석 파이프라인으로 분기.

```python
# knowledge_query.py
return ("__FILM_ANALYSIS__", json.dumps(movie_context))

# chat_service.py (stream_chat)
if rule_result and rule_result[0] == "__FILM_ANALYSIS__":
    # → Film Analysis LLM pipeline
```

---

## 2. 상세 설계

### 2.1 FilmAnalysisService (신규 파일)

**파일**: `backend/services/film_analysis_service.py`

```python
class FilmAnalysisService:
    """Builds analysis-specific LLM messages from movie context."""

    ANALYSIS_SYSTEM_PROMPT = """당신은 영화 전문 분석가입니다...."""

    def build_messages(self, movie_context: dict, user_message: str) -> list[dict]:
        """Build LLM messages with movie data injected into system prompt."""

    def detect_focus(self, message: str) -> str | None:
        """Detect if user wants specific analysis category."""
```

**분석 전용 System Prompt**:

```
당신은 영화 전문 분석가입니다. 아래 영화 정보를 바탕으로 전문적인 분석을 제공하세요.

[영화 정보]
제목: {title}
감독: {director}
장르: {genres}
개봉: {release_date}
줄거리: {overview}
출연: {cast}
평점: {vote_average}/10

다음 항목에 대해 분석해주세요:

## 촬영/연출 분석
감독의 연출 스타일, 촬영 기법, 시각적 특징

## 스토리/서사 구조
서사 구조, 주요 플롯 포인트, 전개 방식

## 테마/상징
핵심 테마, 상징적 요소, 사회적/철학적 메시지

## 총평
영화사적 의미, 추천 대상

규칙:
- 한국어 답변
- 각 섹션 2-3문장
- ⚠️ 스포일러 주의 표시
- 주관적 의견과 객관적 사실 구분
```

**특정 카테고리 집중 분석**:

사용자가 "촬영기법" 같은 특정 키워드를 포함하면 해당 섹션만 깊이 분석:

```python
FOCUS_KEYWORDS = {
    "촬영": "cinematography",
    "연출": "cinematography",
    "카메라": "cinematography",
    "스토리": "narrative",
    "서사": "narrative",
    "구조": "narrative",
    "플롯": "narrative",
    "테마": "theme",
    "상징": "theme",
    "메시지": "theme",
    "의미": "theme",
}
```

### 2.2 KnowledgeQuery 수정

**파일**: `backend/services/knowledge_query.py`

**`_try_film_analysis()` 메서드**:

```python
ANALYSIS_KEYWORDS = [
    "분석", "해석", "촬영기법", "스토리 구조", "테마", "상징",
    "연출", "영화적", "기법", "서사", "메시지"
]

def _try_film_analysis(self, msg: str, msg_lower: str) -> tuple[str, str] | None:
    """Detect film analysis request, extract movie title, return context."""
    if not any(kw in msg_lower for kw in ANALYSIS_KEYWORDS):
        return None

    # Extract movie title by removing analysis keywords
    title = msg
    for kw in ANALYSIS_KEYWORDS + ["해줘", "알려줘", "설명", "영화"]:
        title = title.replace(kw, "")
    title = title.strip()

    if len(title) < 2:
        return None

    # Search DB for movie
    movies = self._search_movies_by_title(title, limit=1)
    if movies:
        movie = movies[0]
        context = {
            "title": movie.get("title", title),
            "director": movie.get("director", ""),
            "genres": movie.get("genres", []),
            "release_date": movie.get("release_date", ""),
            "overview": movie.get("overview", ""),
            "cast": [c.get("name", "") for c in movie.get("cast", [])[:5]],
            "vote_average": movie.get("vote_average", 0),
            "from_db": True,
        }
    else:
        # Movie not in DB — LLM will use its own knowledge
        context = {
            "title": title,
            "from_db": False,
        }

    import json
    return ("__FILM_ANALYSIS__", json.dumps(context, ensure_ascii=False))
```

**`try_respond()` 체인 삽입** — `_try_boxoffice()` 앞에:

```python
# 9.5 Film analysis (LLM-assisted)
result = self._try_film_analysis(msg, msg_lower)
if result:
    return result
```

### 2.3 ChatService 수정

**파일**: `backend/services/chat_service.py`

**`stream_chat()` 수정** — rule_result에서 특수 마커 감지:

```python
# Try rule-based response first
rule_result = self.rule_engine.try_respond(message, domain)

if rule_result and rule_result[0] == "__FILM_ANALYSIS__":
    # Film Analysis: LLM streaming with movie context
    import json
    movie_context = json.loads(rule_result[1])
    analysis_svc = FilmAnalysisService()
    messages = analysis_svc.build_messages(movie_context, message)

    yield f"data: {json.dumps({'session_id': session_id, 'message_id': assistant_msg_id, 'content': '', 'start': True, 'source': 'llm', 'function': '영화 전문 분석 (AI)'})}\n\n"

    # Stream LLM response
    stream_gen = await self.openrouter.chat_completion(
        messages=messages,
        model=model_override or config["model"],
        temperature=0.7,
        max_tokens=1500,
        stream=True,
    )
    # ... (existing streaming logic)

elif rule_result:
    # Normal rule-based response (existing logic)
    ...
```

---

## 3. 파일 변경 목록

| 파일 | 변경 유형 | 설명 |
|------|----------|------|
| `backend/services/film_analysis_service.py` | **신규** | 분석 prompt 빌더 + 카테고리 포커스 감지 |
| `backend/services/knowledge_query.py` | 수정 | `_try_film_analysis()` 키워드 감지 + DB 조회 |
| `backend/services/chat_service.py` | 수정 | `__FILM_ANALYSIS__` 마커 감지 + LLM 분기 |

---

## 4. 구현 순서

```
[Step 1] film_analysis_service.py
         - ANALYSIS_SYSTEM_PROMPT
         - build_messages(movie_context, user_message)
         - detect_focus(message) → 특정 카테고리 집중

[Step 2] knowledge_query.py
         - _try_film_analysis() 키워드 감지
         - 영화 제목 추출 + DB 조회
         - __FILM_ANALYSIS__ 마커 반환
         - try_respond() 체인에 삽입

[Step 3] chat_service.py
         - stream_chat()에 __FILM_ANALYSIS__ 분기 추가
         - FilmAnalysisService로 메시지 빌드
         - 기존 스트리밍 로직 재사용
```

---

## 5. 성공 기준

- [ ] "기생충 분석해줘" → 4개 카테고리 구조화된 분석 스트리밍 응답
- [ ] DB에 있는 영화: 정확한 감독/장르/줄거리 기반 분석
- [ ] DB에 없는 영화: LLM 자체 지식 분석 + "DB 정보 없음" 안내
- [ ] "인터스텔라 촬영기법" → 촬영/연출 카테고리만 집중 분석
- [ ] 기존 "기생충 알려줘" (정보 조회)와 충돌 없음
- [ ] source badge: "영화 전문 분석 (AI)"
- [ ] 스트리밍 응답 정상 동작
