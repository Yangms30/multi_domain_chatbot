# Reusable Chatbot Architecture — Skills & Patterns

> 이 문서는 영화 챗봇에서 검증된 설계 패턴을 정리한 것입니다.
> 도메인만 바꾸면 어떤 분야에든 동일한 구조를 적용할 수 있습니다.

---

## 아키텍처 개요: 5단계 응답 파이프라인

```
User Message
  ↓
[1] Pattern Matching     — 키워드/정규식 기반 즉시 응답 (비용 0원)
  ↓ (실패)
[2] Similarity Search    — BM25+/TF-IDF로 DB 유사도 검색 (비용 0원)
  ↓ (실패)
[3] Real-time API        — 외부 API 실시간 호출 + 캐싱 (비용 0원)
  ↓ (실패)
[4] Hybrid LLM           — DB 데이터를 context로 주입 + LLM 분석 (저비용)
  ↓ (실패)
[5] LLM Fallback         — 일반 system prompt + LLM 대화 (기본 비용)
```

**핵심 원칙**: 위에서 아래로 비용이 증가. 가능한 한 위쪽에서 응답을 해결.

---

## Skill 1: Pattern Matching Engine

### 무엇을 하나
키워드/정규식으로 사용자 의도를 분류하고 DB 데이터로 즉시 응답.

### 영화 도메인 예시
```
"액션 영화 추천" → 장르 "액션"으로 DB 조회 → 영화 리스트 포맷팅
"봉준호 감독 영화" → 감독명으로 DB 조회 → 필모그래피
"슬플 때 볼 영화" → 기분→장르 매핑 → "드라마, 로맨스" 조회
```

### 다른 도메인 적용

| 도메인 | 패턴 예시 | DB 조회 |
|--------|----------|--------|
| **고객센터** | "환불 방법" → FAQ 매칭 | policies 테이블 |
| **교육** | "미적분 설명해줘" → 과목 매칭 | lessons 테이블 |
| **부동산** | "강남 2룸 매물" → 조건 파싱 | listings 테이블 |
| **맛집** | "이태원 이탈리안" → 지역+장르 | restaurants 테이블 |
| **의료** | "두통 원인" → 증상 매칭 | symptoms 테이블 |

### 구현 파일
```
services/knowledge_query.py   — 키워드 매칭 + DB 조회 + 포맷팅
```

### 재사용 패턴
```python
class KnowledgeQuery:
    # 1. 키워드 맵 정의
    CATEGORY_MAP = {
        "키워드1": "카테고리A",
        "키워드2": "카테고리B",
    }

    def try_respond(self, message, domain):
        # 2. 의도 분류 체인 (우선순위 순)
        result = self._try_exact_match(msg)     # 정확한 매칭
        if result: return result
        result = self._try_category(msg)        # 카테고리 매칭
        if result: return result
        result = self._try_keyword_combo(msg)   # 복합 키워드
        if result: return result
        return None                             # 다음 단계로

    # 3. 포맷터: 도메인별 응답 형태
    def _format_list(self, title, items):
        # 테이블, 카드, 리스트 등
```

---

## Skill 2: BM25+ Similarity Search

### 무엇을 하나
Pattern Matching이 실패했을 때, DB 전체 문서와 사용자 질문의 유사도를 계산하여 가장 관련 높은 결과 반환.

### 왜 필요한가
패턴 매칭은 미리 정의된 키워드만 처리 가능. 사용자의 다양한 표현을 커버하려면 유사도 검색 필수.

```
"우주에서 살아남는 영화" → 키워드 매칭 실패 → BM25+로 "인터스텔라" 찾음
```

### 다른 도메인 적용

| 도메인 | 패턴 실패 예시 | BM25+ 해결 |
|--------|-------------|-----------|
| **고객센터** | "물건이 안 왔어요" (키워드 "배송" 없음) | "배송 지연" FAQ 매칭 |
| **교육** | "x가 뭐야" (너무 짧음) | "변수 x" 레슨 매칭 |
| **부동산** | "조용한 동네" (조건 아님) | 주거환경 평가 데이터 매칭 |
| **HR** | "연차 쓰려면" (키워드 불일치) | "휴가 신청" 매뉴얼 매칭 |

### 구현 파일
```
services/bm25_engine.py       — BM25+ 인덱스 + 검색
services/tfidf_engine.py      — 한국어 전처리 (_preprocess_korean)
```

### 재사용 패턴
```python
class SearchEngine:
    def build_all_indices(self):
        # DB에서 도메인별 데이터 로드 → 토큰화 → BM25+ 인덱스 빌드

    def search(self, query, domain, top_k=5):
        # 전처리 → 토큰화 → BM25 점수 계산 → threshold 이상 반환

    def try_respond(self, message, domain):
        # search() 결과를 도메인별 포맷터로 변환
```

### 핵심 설정값
```python
DOMAIN_CONFIG = {
    "your_domain": {
        "threshold_high": 8.0,   # 확신 높은 응답
        "threshold_low": 3.0,    # 최소 관련성
        "top_k": 5,              # 최대 결과 수
    },
}
```

---

## Skill 3: Real-time API Integration

### 무엇을 하나
외부 API를 실시간 호출하여 DB에 없는 최신 데이터 제공. 메모리 캐싱으로 API 호출 최소화.

### 영화 도메인 예시
```
"오늘 박스오피스" → KOBIS API 호출 → TOP 10 순위 (6시간 캐시)
```

### 다른 도메인 적용

| 도메인 | 외부 API | 캐시 TTL | 예시 질문 |
|--------|---------|---------|----------|
| **고객센터** | 배송 추적 API | 30분 | "내 택배 어디야?" |
| **날씨** | 기상청 API | 1시간 | "오늘 날씨 어때?" |
| **주식** | 증권 API | 5분 | "삼성전자 주가" |
| **부동산** | 실거래가 API | 24시간 | "강남 아파트 시세" |
| **맛집** | 네이버 플레이스 API | 6시간 | "근처 맛집" |

### 구현 파일
```
services/boxoffice_service.py  — API 호출 + TTL 캐싱
```

### 재사용 패턴
```python
class ExternalApiService:
    def __init__(self):
        self.api_key = os.environ.get("API_KEY", "")
        self._cache: dict[str, tuple[float, Any]] = {}

    def _get_cached(self, key: str) -> Any | None:
        if key in self._cache:
            cached_time, data = self._cache[key]
            if time.time() - cached_time < CACHE_TTL:
                return data
        return None

    def _set_cache(self, key: str, data: Any):
        self._cache[key] = (time.time(), data)

    def get_data(self, params) -> list:
        cache_key = f"{endpoint}_{params_hash}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached
        # API 호출 → 캐싱 → 반환
```

---

## Skill 4: Hybrid LLM (DB Context + LLM 분석)

### 무엇을 하나
사용자 요청이 "분석/해석/추론"처럼 LLM이 필수인 경우, DB 데이터를 context로 주입하여 hallucination을 줄이고 품질을 높임.

### 영화 도메인 예시
```
"기생충 분석해줘"
  → DB에서 감독/장르/줄거리 조회
  → 분석 전용 system prompt에 DB 데이터 삽입
  → LLM 스트리밍 호출
  → 구조화된 분석 응답 (촬영/스토리/테마/총평)
```

### 다른 도메인 적용

| 도메인 | 감지 키워드 | DB Context | LLM 역할 |
|--------|-----------|-----------|---------|
| **고객센터** | "왜 이런 정책이야?" | 정책 원문 | 정책 배경 설명 |
| **교육** | "왜 이 공식이 성립해?" | 공식 + 예제 | 직관적 설명 생성 |
| **법률** | "이 계약서 분석해줘" | 계약서 텍스트 | 리스크 분석 |
| **HR** | "이 후보 평가해줘" | 이력서 데이터 | 적합성 분석 |
| **의료** | "이 검사 결과 해석해줘" | 수치 데이터 | 일반적 해석 (진단 아님) |

### 구현 파일
```
services/film_analysis_service.py  — 분석 prompt 빌더
services/chat_service.py           — __MARKER__ 감지 + LLM 분기
```

### 재사용 패턴: 마커 기반 하이브리드
```python
# 1. knowledge_query.py — 감지 + DB 조회
def _try_deep_analysis(self, msg):
    if not any(kw in msg for kw in ANALYSIS_KEYWORDS):
        return None
    db_context = self._fetch_from_db(entity)
    return ("__DEEP_ANALYSIS__", json.dumps(db_context))

# 2. analysis_service.py — 전용 prompt 빌더
class AnalysisService:
    SYSTEM_PROMPT = """당신은 {domain} 전문 분석가입니다.
    {db_context}
    위 정보를 바탕으로 분석해주세요..."""

    def build_messages(self, context, user_msg):
        return [
            {"role": "system", "content": self.SYSTEM_PROMPT.format(...)},
            {"role": "user", "content": user_msg},
        ]

# 3. chat_service.py — 마커 감지 + LLM 분기
if rule_result and rule_result[0] == "__DEEP_ANALYSIS__":
    messages = analysis_svc.build_messages(context, message)
    stream = await openrouter.chat_completion(messages=messages, stream=True)
```

---

## Skill 5: Agent Memory (개인화)

### 무엇을 하나
대화에서 사용자 정보를 자동 추출하여 저장. 다음 대화에서 system prompt에 주입하여 개인화된 응답 제공.

### 영화 도메인 예시
```
사용자: "나 액션 영화 좋아해"
  → 메모리 저장: {type: "preference", content: "액션 영화 선호"}
다음 대화:
  → system prompt에 "[Preferences] 액션 영화 선호" 주입
  → 추천 시 액션 장르 우선
```

### 다른 도메인 적용

| 도메인 | 저장 정보 | 개인화 효과 |
|--------|---------|-----------|
| **고객센터** | 이전 문의 내역, 제품 보유 | 반복 설명 불필요 |
| **교육** | 학습 수준, 약한 분야 | 맞춤 난이도 조절 |
| **헬스** | 알레르기, 운동 루틴 | 안전한 추천 |
| **쇼핑** | 사이즈, 스타일 선호 | 정확한 상품 추천 |

### 구현 파일
```
services/memory_service.py    — CRUD + LLM 기반 자동 추출
services/context_manager.py   — system prompt에 메모리 주입
```

### 메모리 타입
```python
MEMORY_TYPES = {
    "preference": "선호/취향 (좋아하는 것, 싫어하는 것)",
    "context":    "배경 정보 (직업, 나이, 거주지)",
    "goal":       "목표 (다이어트, 학습 목표 등)",
    "feedback":   "피드백 (응답 스타일 선호)",
    "interaction": "대화 요약",
}
```

---

## Skill 6: Voice I/O

### 무엇을 하나
음성 입력(STT) → 텍스트 처리 → 음성 출력(TTS). 핸즈프리 사용 지원.

### 구현 파일
```
services/voice_service.py     — Whisper STT + Edge TTS
routers/voice.py              — 음성 API 엔드포인트
```

### 기술 스택
```
STT: faster-whisper (로컬, 무료)
TTS: edge-tts (Microsoft, 무료)
```

---

## 비용 구조 요약

| 단계 | 비용 | 커버리지 (예상) |
|------|------|--------------|
| Pattern Matching | 0원 | ~40% |
| BM25+ Search | 0원 | ~25% |
| Real-time API | 0원 (API 무료 범위) | ~10% |
| Hybrid LLM | ~$0.0003/요청 | ~10% |
| LLM Fallback | ~$0.001/요청 | ~15% |
| **전체** | **~75% 무료** | **100%** |

---

## 새 도메인 적용 체크리스트

새 도메인 챗봇을 만들 때 이 순서대로:

```
[ ] 1. 도메인 데이터 수집
      - DB 스키마 설계 (domain_knowledge 테이블)
      - 수집 스크립트 작성 (API or 크롤링)

[ ] 2. Pattern Matching 구현
      - 키워드 맵 정의
      - 의도 분류 체인 작성
      - 포맷터 구현

[ ] 3. BM25+ 검색 추가
      - 전처리 함수 (해당 언어)
      - threshold 튜닝

[ ] 4. 외부 API 연동 (필요 시)
      - API 서비스 + 캐싱
      - 키워드 트리거

[ ] 5. Hybrid LLM 분석 (필요 시)
      - 분석 키워드 정의
      - 전용 system prompt
      - __MARKER__ 패턴 구현

[ ] 6. 메모리 시스템
      - 메모리 타입 정의
      - 추출 prompt 작성

[ ] 7. 프론트엔드 연결
      - 스트리밍 SSE
      - source badge 표시
```

---

## 기술 스택

| 역할 | 기술 | 선택 이유 |
|------|------|----------|
| Backend | FastAPI | 비동기 + SSE 스트리밍 |
| DB | Supabase (PostgreSQL) | JSONB 지원 + 무료 티어 |
| 검색 | rank-bm25 | 경량, 한국어 호환 |
| LLM | OpenRouter → gpt-4o-mini | 멀티모델 + 저비용 |
| STT | faster-whisper | 로컬, 무료, 빠름 |
| TTS | edge-tts | 무료, 한국어 자연스러움 |
| Frontend | Vanilla JS + Tailwind | 프레임워크 의존 없음 |
