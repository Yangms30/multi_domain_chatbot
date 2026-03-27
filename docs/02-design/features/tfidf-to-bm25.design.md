# TF-IDF → BM25+ 검색 엔진 업그레이드 Design

## Executive Summary

| 항목 | 내용 |
|------|------|
| Feature | TF-IDF → BM25+ 검색 엔진 업그레이드 + 인기도 기반 랭킹 |
| Plan 참조 | `docs/01-plan/features/tfidf-to-bm25.plan.md` |
| 설계일 | 2026-03-27 |

### Value Delivered

| 관점 | 내용 |
|------|------|
| **Problem** | TF-IDF는 문서 길이 정규화 미흡 + "유명한 영화" 질문에 관객수 데이터 없음 |
| **Solution** | BM25+ 엔진 + KOBIS audiAcc 수집 + 인기도 랭킹 |
| **Function UX Effect** | 정확한 검색 + 관객수 기반 인기 영화 추천 |
| **Core Value** | 검색 정확도 5~15% 향상 + LLM fallback 감소 |

---

## 1. 아키텍처 개요

### 현재 플로우
```
User Message
  → RuleEngine.try_respond()
    → KnowledgeQuery.try_respond()  (패턴 매칭)
    → TfidfEngine.try_respond()     (유사도 검색)
  → (없으면) LLM fallback
```

### 변경 후 플로우
```
User Message
  → RuleEngine.try_respond()
    → KnowledgeQuery.try_respond()  (패턴 매칭 + 인기도 랭킹 추가)
    → Bm25Engine.try_respond()      (BM25+ 유사도 검색 - TF-IDF 교체)
  → (없으면) LLM fallback
```

### 핵심 변경점
- `TfidfEngine` → `Bm25Engine` 교체 (동일 인터페이스)
- `RuleEngine`에서 import만 변경
- `kobis_collector.py`에 관객수 수집 추가
- `KnowledgeQuery._try_ranking()`에 인기도 키워드 + 관객수 정렬 추가

---

## 2. 상세 설계

### 2.1 Bm25Engine (신규 파일)

**파일**: `backend/services/bm25_engine.py`

**의존성**: `rank-bm25` (pip install rank-bm25)

**클래스 구조**:
```python
class Bm25Engine:
    """BM25+ 기반 유사도 검색 엔진. TfidfEngine 드롭인 교체."""

    DOMAIN_CONFIG = {
        "movie": {"threshold_high": 0.45, "threshold_low": 0.20, "top_k": 5},
        "default": {"threshold_high": 0.40, "threshold_low": 0.20, "top_k": 5},
    }
    # Note: BM25 점수 범위가 TF-IDF cosine(0~1)과 다름
    # BM25 점수는 0~무한대이므로 threshold를 실험으로 재조정 필요

    def __init__(self):
        self._indices: dict = {}
        self._knowledge = KnowledgeQuery()

    def build_all_indices(self) -> dict[str, int]:
        """모든 도메인의 BM25 인덱스 빌드. {domain: doc_count} 반환."""

    def _build_index_from_rows(self, domain: str, rows: list[dict]) -> int:
        """단일 도메인 인덱스 빌드."""
        # 1. 각 문서를 _preprocess_korean()으로 전처리
        # 2. 공백 split으로 토큰화 (한국어는 형태소 분석기 없이 공백+조사제거로)
        # 3. BM25Plus(tokenized_corpus) 생성
        # 4. self._indices[domain]에 저장

    def search(self, query: str, domain: str, top_k: int | None = None) -> list[dict] | None:
        """BM25+ 유사도 검색. TfidfEngine.search()와 동일한 반환 형식."""
        # 1. query를 _preprocess_korean() + 공백 split
        # 2. bm25.get_scores(tokenized_query)
        # 3. 점수 정규화: min-max normalization (0~1 범위로)
        # 4. threshold_low 이상만 반환

    def try_respond(self, message: str, domain: str) -> tuple[str, str] | None:
        """BM25 검색 결과를 포맷팅하여 반환."""
        # TfidfEngine.try_respond()와 동일한 로직
        # source 문자열만 "BM25+ 유사도 검색"으로 변경
```

**핵심 설계 결정**:

| 항목 | 결정 | 이유 |
|------|------|------|
| 토크나이저 | `_preprocess_korean()` + `str.split()` | 기존 전처리 재사용, 형태소 분석기 의존성 불필요 |
| BM25 변형 | `BM25Plus` | 가변 길이 문서(영화 overview)에 최적, delta로 긴 문서 보정 |
| 점수 정규화 | min-max normalization | BM25 raw 점수를 0~1로 변환하여 기존 threshold 체계 호환 |
| Title 가중치 | 제목 3회 반복 (기존 2회→3회) | BM25에서 제목 매칭 중요도 강화 |

**점수 정규화 방법**:
```python
# BM25 raw scores → 0~1 normalized
scores = bm25.get_scores(query_tokens)
max_score = scores.max()
if max_score > 0:
    normalized = scores / max_score  # 최고점 = 1.0
else:
    normalized = scores
```

### 2.2 A/B 비교 테스트 스크립트

**파일**: `backend/scripts/compare_search_engines.py`

**실행 방법**: `cd backend && python -m scripts.compare_search_engines`

**테스트 쿼리셋 (25개)**:
```python
TEST_QUERIES = [
    # 정확한 제목
    ("인터스텔라", "인터스텔라"),
    ("기생충", "기생충"),
    ("올드보이", "올드보이"),

    # 부분 제목
    ("인터스텔", "인터스텔라"),
    ("어벤져", "어벤져스"),

    # 장르 + 키워드
    ("무서운 영화", None),       # 공포/스릴러 장르 기대
    ("웃긴 영화", None),         # 코미디 장르 기대
    ("SF 영화 추천", None),      # SF 장르 기대

    # 기분 기반
    ("슬플 때 볼 영화", None),
    ("심심할 때 영화", None),

    # 배우/감독
    ("봉준호 영화", None),       # 봉준호 감독 작품 기대
    ("송강호 영화", None),       # 송강호 출연작 기대
    ("마동석 영화", None),

    # 개념적 표현
    ("우주 영화", "인터스텔라"),  # 우주 관련 영화 기대
    ("좀비 영화", None),
    ("로봇 영화", None),
    ("시간여행 영화", None),

    # 한국어 변형
    ("재밌는 액션 영화 알려줘", None),
    ("감동적인 영화 뭐 있어", None),

    # 연도
    ("2024년 영화", None),
    ("최근 영화", None),

    # 복합 쿼리
    ("한국 공포 영화", None),
    ("일본 애니메이션", None),
    ("가족이랑 볼 영화", None),
    ("2시간 이내 짧은 영화", None),
]
```

**비교 출력 형식**:
```
┌─────────────────────────┬───────────────────────┬───────────────────────┐
│ Query                   │ TF-IDF Top 3          │ BM25+ Top 3           │
├─────────────────────────┼───────────────────────┼───────────────────────┤
│ 인터스텔라              │ 인터스텔라 (0.85)     │ 인터스텔라 (0.92)     │
│                         │ 그래비티 (0.32)       │ 마션 (0.41)           │
│                         │ 마션 (0.28)           │ 그래비티 (0.35)       │
├─────────────────────────┼───────────────────────┼───────────────────────┤
│ ...                     │ ...                   │ ...                   │
└─────────────────────────┴───────────────────────┴───────────────────────┘

Summary:
- TF-IDF avg top score: 0.XX
- BM25+ avg top score: 0.XX
- TF-IDF avg query time: X.Xms
- BM25+ avg query time: X.Xms
- Exact title match rate: TF-IDF X/X vs BM25+ X/X
```

**스크립트 로직**:
1. DB에서 domain_knowledge 로드
2. TfidfEngine + Bm25Engine 각각 인덱스 빌드
3. 동일 쿼리셋으로 양쪽 검색 실행
4. 결과를 나란히 비교 테이블 출력
5. 요약 통계 (평균 점수, 응답 시간, 제목 매칭률) 출력

### 2.3 관객수 데이터 수집 (kobis_collector 수정)

**수정 파일**: `backend/scripts/kobis_collector.py`

**변경 1: 박스오피스 수집 시 관객수 저장**

`_get_daily_boxoffice()`, `_get_weekly_boxoffice()` 반환값에서 관객수를 추출하여 `collect_monthly_boxoffice()`에서 `_process_movie()`로 전달.

```python
def collect_monthly_boxoffice(self, months: int = 12):
    for movie in movies:
        movie_cd = movie.get("movieCd", "")
        audience = int(movie.get("audiAcc", 0))  # 누적관객수
        sales = int(movie.get("salesAcc", 0))     # 누적매출액
        self._process_movie(movie_cd, movie.get("movieNm", ""),
                           audience_count=audience, sales_amount=sales)
```

**변경 2: `_process_movie()` 시그니처 확장**

```python
def _process_movie(self, movie_cd: str, movie_name: str,
                   audience_count: int = 0, sales_amount: int = 0):
    # ... 기존 로직 ...
    data = {
        # ... 기존 필드 ...
        "audience_count": audience_count,  # 신규
        "sales_amount": sales_amount,      # 신규
    }
```

**변경 3: 기존 데이터 backfill 스크립트**

```python
def backfill_audience_data(self):
    """기존 영화 데이터에 관객수를 backfill."""
    # 1. 최근 5년 월별 박스오피스 재수집
    # 2. audiAcc 매칭하여 기존 레코드의 data JSON 업데이트
    # 3. Supabase update: data->audience_count 필드 추가
```

### 2.4 인기도 기반 랭킹 (knowledge_query 수정)

**수정 파일**: `backend/services/knowledge_query.py`

**변경 1: `_try_ranking()` 키워드 추가**

```python
def _try_ranking(self, msg_lower: str) -> tuple[str, str] | None:
    # 기존: "인기 영화", "인기있는", "인기순", "많이 본", "핫한"
    # 추가: "유명한", "흥행", "대박", "천만", "블록버스터", "관객수"
    if any(kw in msg_lower for kw in [
        "인기 영화", "인기있는", "인기순", "많이 본", "핫한",
        "유명한", "흥행", "대박", "천만", "블록버스터", "관객수"
    ]):
        movies = self._get_popular_movies(limit=5)
        if movies:
            return (self._format_popular_movie_list("인기 영화 TOP 5", movies),
                    "관객수 기반 인기 순위")
        # fallback: 관객수 없으면 평점순
        movies = self._get_top_rated_movies(limit=5)
        if movies:
            return (self._format_movie_list("인기 영화 TOP 5", movies),
                    "인기 영화 순위")
```

**변경 2: `_get_popular_movies()` 신규 메서드**

```python
def _get_popular_movies(self, limit: int = 5) -> list[dict]:
    """관객수 기준으로 인기 영화 조회."""
    db = get_db()
    result = (
        db.table("domain_knowledge")
        .select("data")
        .eq("domain", "movie")
        .eq("category", "movie")
        .order("data->>audience_count", desc=True)
        .limit(limit)
        .execute()
    )
    movies = [r["data"] for r in result.data] if result.data else []
    # audience_count가 0인 것은 제외
    return [m for m in movies if m.get("audience_count", 0) > 0]
```

**변경 3: `_format_popular_movie_list()` 신규 메서드**

```python
def _format_popular_movie_list(self, title: str, movies: list[dict]) -> str:
    """관객수 포함된 영화 리스트 포맷."""
    response = f"## {title}\n\n"
    for i, movie in enumerate(movies, 1):
        year = movie.get("release_date", "")[:4] or "미정"
        audience = movie.get("audience_count", 0)
        audience_str = self._format_audience(audience)
        rating = _safe_rating(movie.get("vote_average", 0))

        response += (
            f"### {i}. {movie.get('title', '')} ({year})\n"
            f"- **관객수**: {audience_str}\n"
            f"- **평점**: {'⭐' * round(rating / 2)} {rating}/10\n"
            f"- **장르**: {', '.join(movie.get('genres', []))}\n"
        )
        director = movie.get("director", "")
        if director:
            response += f"- **감독**: {director}\n"
        response += "\n"

    response += "*영화에 대해 더 자세히 알고 싶으면 제목을 말씀해주세요!*"
    return response

@staticmethod
def _format_audience(count: int) -> str:
    """관객수를 읽기 쉬운 형식으로 변환."""
    if count >= 10_000_000:
        return f"{count / 10_000_000:.1f}천만 명"
    elif count >= 10_000:
        return f"{count / 10_000:.0f}만 명"
    elif count >= 1_000:
        return f"{count / 1_000:.1f}천 명"
    else:
        return f"{count:,} 명"
```

### 2.5 엔진 교체 통합

**수정 파일**: `backend/services/rule_engine.py`

변경이 매우 작음 — import와 인스턴스 생성만 교체:

```python
# Before
from services.tfidf_engine import TfidfEngine

class RuleEngine:
    def __init__(self):
        self._tfidf = TfidfEngine()

# After
from services.bm25_engine import Bm25Engine

class RuleEngine:
    def __init__(self):
        self._tfidf = Bm25Engine()  # 변수명 유지 (하위 호환)
```

**수정 파일**: `backend/main.py`

로그 메시지만 변경:
```python
logger.info("BM25+ indices ready: %s", counts)  # TF-IDF → BM25+
```

---

## 3. 파일 변경 목록

| 파일 | 변경 유형 | 설명 |
|------|----------|------|
| `backend/services/bm25_engine.py` | **신규** | BM25+ 검색 엔진 |
| `backend/scripts/compare_search_engines.py` | **신규** | A/B 비교 테스트 스크립트 |
| `backend/services/rule_engine.py` | 수정 | TfidfEngine → Bm25Engine import 교체 |
| `backend/main.py` | 수정 | 로그 메시지 변경 |
| `backend/scripts/kobis_collector.py` | 수정 | audience_count, sales_amount 수집 + backfill |
| `backend/services/knowledge_query.py` | 수정 | 인기도 키워드 + _get_popular_movies() + 포맷터 |
| `requirements.txt` | 수정 | `rank-bm25` 추가 |

---

## 4. 구현 순서 (의존성 기반)

```
[Step 1] rank-bm25 설치 + bm25_engine.py 구현
         - _preprocess_korean 함수를 tfidf_engine.py에서 import 또는 공통 모듈로 분리
         - BM25Plus 인덱스 빌드 + search + try_respond

[Step 2] compare_search_engines.py 작성 + 실행
         - TfidfEngine vs Bm25Engine 나란히 비교
         - threshold 값 튜닝 (BM25 점수 범위에 맞게)

[Step 3] kobis_collector.py 수정 + backfill 실행
         - audience_count, sales_amount 필드 추가
         - 기존 데이터에 관객수 backfill

[Step 4] knowledge_query.py 수정
         - _try_ranking() 키워드 추가
         - _get_popular_movies() + _format_popular_movie_list()

[Step 5] rule_engine.py + main.py 교체
         - A/B 테스트 결과 확인 후 최종 교체 결정
```

---

## 5. BM25+ Threshold 튜닝 전략

BM25 raw score는 TF-IDF cosine similarity(0~1)과 범위가 다르므로 threshold 재설정 필요:

| 단계 | 작업 |
|------|------|
| 1 | min-max normalization으로 0~1 변환 후 기존 threshold 시도 |
| 2 | 비교 테스트에서 실제 점수 분포 확인 |
| 3 | 정확한 제목 매칭 점수 vs 부분 매칭 점수 간격 분석 |
| 4 | threshold_high, threshold_low 재설정 |

**예상 threshold** (normalization 후):
- `threshold_high`: 0.45 ~ 0.55 (TF-IDF 0.35보다 높을 것으로 예상)
- `threshold_low`: 0.15 ~ 0.25

---

## 6. 성공 기준 체크리스트

- [ ] `bm25_engine.py` 구현 완료 (TfidfEngine과 동일 인터페이스)
- [ ] A/B 비교 테스트 25개 쿼리 실행 완료
- [ ] BM25+가 TF-IDF 대비 동등 이상 성능 확인
- [ ] `kobis_collector.py`에서 audience_count 수집 동작 확인
- [ ] "유명한 영화 추천해줘" → audience_count 기반 TOP 5 응답
- [ ] "많이 본 영화" → 관객수 표시된 리스트 (예: "1,400만 명")
- [ ] 기존 모든 검색 기능 정상 동작 (regression 없음)
- [ ] 응답 시간 100ms 이내 유지
