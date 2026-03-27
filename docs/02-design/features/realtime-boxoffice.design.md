# 실시간 박스오피스 & 개봉 예정작 Design

## Executive Summary

| 항목 | 내용 |
|------|------|
| Feature | 실시간 박스오피스 순위 + 개봉 예정작 캘린더 |
| Plan 참조 | `docs/01-plan/features/realtime-boxoffice.plan.md` |
| 설계일 | 2026-03-27 |

### Value Delivered

| 관점 | 내용 |
|------|------|
| **Problem** | 정적 DB 데이터만 있어서 실시간 박스오피스/개봉 예정 질문에 답 못함 |
| **Solution** | KOBIS API 실시간 호출 + 6시간 메모리 캐싱 |
| **Function UX Effect** | 실시간 TOP 10 + 관객수 + 변동 표시, LLM 비용 0원 |
| **Core Value** | 정적 → 실시간 챗봇 진화 |

---

## 1. 아키텍처

### 변경 후 플로우
```
User: "오늘 박스오피스"
  → KnowledgeQuery._try_boxoffice()     (신규 메서드)
    → BoxOfficeService.get_daily()       (KOBIS API + 캐시)
    → _format_boxoffice_list()           (포맷팅)
  → 즉시 응답 (LLM 불필요)
```

---

## 2. 상세 설계

### 2.1 BoxOfficeService (신규 파일)

**파일**: `backend/services/boxoffice_service.py`

```python
import os
import time
import logging
from datetime import datetime, timedelta

import httpx

logger = logging.getLogger(__name__)

KOBIS_BASE = "https://kobis.or.kr/kobisopenapi/webservice/rest"
CACHE_TTL = 6 * 60 * 60  # 6시간 (초)


class BoxOfficeService:
    """KOBIS API 실시간 박스오피스 조회 + 메모리 캐싱."""

    def __init__(self):
        self.api_key = os.environ.get("KOBIS_API_KEY", "")
        self._cache: dict[str, tuple[float, list]] = {}
        # 캐시 구조: {"daily_20260327": (timestamp, [movie_list])}

    def _get_cached(self, key: str) -> list | None:
        """TTL 기반 캐시 조회."""
        if key in self._cache:
            cached_time, data = self._cache[key]
            if time.time() - cached_time < CACHE_TTL:
                return data
            del self._cache[key]
        return None

    def _set_cache(self, key: str, data: list):
        self._cache[key] = (time.time(), data)

    def get_daily_boxoffice(self) -> list[dict]:
        """일별 박스오피스 TOP 10. 어제 날짜 기준 (당일 데이터는 늦게 집계됨)."""
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
        cache_key = f"daily_{yesterday}"

        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        if not self.api_key:
            logger.warning("KOBIS_API_KEY not set")
            return []

        try:
            resp = httpx.get(
                f"{KOBIS_BASE}/boxoffice/searchDailyBoxOfficeList.json",
                params={"key": self.api_key, "targetDt": yesterday},
                timeout=10.0,
            )
            resp.raise_for_status()
            data = resp.json()
            movies = data.get("boxOfficeResult", {}).get("dailyBoxOfficeList", [])
            self._set_cache(cache_key, movies)
            return movies
        except Exception as e:
            logger.error("KOBIS daily boxoffice failed: %s", e)
            return []

    def get_weekly_boxoffice(self) -> list[dict]:
        """주간 박스오피스 TOP 10. 지난주 기준."""
        last_week = (datetime.now() - timedelta(weeks=1)).strftime("%Y%m%d")
        cache_key = f"weekly_{last_week}"

        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        if not self.api_key:
            return []

        try:
            resp = httpx.get(
                f"{KOBIS_BASE}/boxoffice/searchWeeklyBoxOfficeList.json",
                params={"key": self.api_key, "targetDt": last_week, "weekGb": "0"},
                timeout=10.0,
            )
            resp.raise_for_status()
            data = resp.json()
            movies = data.get("boxOfficeResult", {}).get("weeklyBoxOfficeList", [])
            self._set_cache(cache_key, movies)
            return movies
        except Exception as e:
            logger.error("KOBIS weekly boxoffice failed: %s", e)
            return []

    def get_upcoming_movies(self) -> list[dict]:
        """개봉 예정작 (오늘 이후 개봉 영화)."""
        today = datetime.now().strftime("%Y")
        cache_key = f"upcoming_{today}"

        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        if not self.api_key:
            return []

        try:
            today_str = datetime.now().strftime("%Y%m%d")
            resp = httpx.get(
                f"{KOBIS_BASE}/movie/searchMovieList.json",
                params={
                    "key": self.api_key,
                    "openStartDt": today_str,
                    "itemPerPage": "10",
                },
                timeout=10.0,
            )
            resp.raise_for_status()
            data = resp.json()
            movies = data.get("movieListResult", {}).get("movieList", [])
            self._set_cache(cache_key, movies)
            return movies
        except Exception as e:
            logger.error("KOBIS upcoming movies failed: %s", e)
            return []
```

### 2.2 KnowledgeQuery 수정

**파일**: `backend/services/knowledge_query.py`

**변경 1: BoxOfficeService 인스턴스 추가**

```python
class KnowledgeQuery:
    def __init__(self):
        self._boxoffice = None  # lazy init

    @property
    def boxoffice(self):
        if self._boxoffice is None:
            from services.boxoffice_service import BoxOfficeService
            self._boxoffice = BoxOfficeService()
        return self._boxoffice
```

**변경 2: `_try_boxoffice()` 신규 메서드**

`try_respond()` 체인에서 `_try_ranking()` 앞에 삽입:

```python
def try_respond(self, message, domain):
    ...
    # 9.5 (신규) 실시간 박스오피스
    result = self._try_boxoffice(msg_lower)
    if result:
        return result
    # 10. Ranking (기존)
    result = self._try_ranking(msg_lower)
    ...
```

**키워드 매칭**:

| 키워드 그룹 | 키워드 | 동작 |
|-----------|--------|------|
| 일별 박스오피스 | "박스오피스", "극장 순위", "오늘 영화 순위", "상영중", "현재 상영", "극장에서" | `get_daily_boxoffice()` |
| 주간 박스오피스 | "이번 주 박스오피스", "주간 순위", "주간 영화", "이번주 영화" | `get_weekly_boxoffice()` |
| 개봉 예정 | "개봉 예정", "곧 개봉", "개봉일", "다음 주 영화", "언제 개봉", "새 영화" | `get_upcoming_movies()` |

```python
def _try_boxoffice(self, msg_lower: str) -> tuple[str, str] | None:
    if any(kw in msg_lower for kw in [
        "박스오피스", "극장 순위", "오늘 영화 순위", "상영중", "현재 상영", "극장에서"
    ]):
        movies = self.boxoffice.get_daily_boxoffice()
        if movies:
            return (self._format_boxoffice_list("오늘의 박스오피스 TOP 10", movies),
                    "실시간 박스오피스")

    if any(kw in msg_lower for kw in [
        "이번 주 박스오피스", "주간 순위", "주간 영화", "이번주 영화"
    ]):
        movies = self.boxoffice.get_weekly_boxoffice()
        if movies:
            return (self._format_boxoffice_list("이번 주 박스오피스 TOP 10", movies),
                    "주간 박스오피스")

    if any(kw in msg_lower for kw in [
        "개봉 예정", "곧 개봉", "개봉일", "다음 주 영화", "언제 개봉", "새 영화"
    ]):
        movies = self.boxoffice.get_upcoming_movies()
        if movies:
            return (self._format_upcoming_list("개봉 예정 영화", movies),
                    "개봉 예정작 조회")

    return None
```

### 2.3 포맷터

**`_format_boxoffice_list()`** — 일별/주간 박스오피스 응답:

```
## 오늘의 박스오피스 TOP 10

| 순위 | 영화 | 당일 관객 | 누적 관객 | 전일 대비 |
|:----:|------|--------:|--------:|--------:|
| 1 | 미션 임파서블 | 12.3만 | 456.7만 | +2.1만 |
| 2 | ... | ... | ... | ... |

*KOBIS 영화진흥위원회 제공 (2026-03-26 기준)*
```

필드 매핑:
- `rank` → 순위
- `movieNm` → 영화명
- `audiCnt` → 당일 관객 (`_format_audience()` 재사용)
- `audiAcc` → 누적 관객
- `audiInten` → 전일 대비 (양수면 +, 음수면 -)
- `openDt` → 개봉일

**`_format_upcoming_list()`** — 개봉 예정작:

```
## 개봉 예정 영화

### 1. 영화제목
- **개봉일**: 2026-04-05
- **장르**: 액션, SF
- **감독**: 홍길동

*KOBIS 영화진흥위원회 제공*
```

필드 매핑:
- `movieNm` → 영화명
- `openDt` → 개봉일 (YYYYMMDD → YYYY-MM-DD 변환)
- `genreAlt` → 장르
- `directors[0].peopleNm` → 감독

---

## 3. 파일 변경 목록

| 파일 | 변경 유형 | 설명 |
|------|----------|------|
| `backend/services/boxoffice_service.py` | **신규** | KOBIS API 실시간 호출 + 캐싱 |
| `backend/services/knowledge_query.py` | 수정 | `_try_boxoffice()` + 포맷터 2개 추가 |

---

## 4. 구현 순서

```
[Step 1] boxoffice_service.py 구현
         - BoxOfficeService 클래스
         - get_daily_boxoffice(), get_weekly_boxoffice(), get_upcoming_movies()
         - TTL 캐싱

[Step 2] knowledge_query.py 수정
         - boxoffice 프로퍼티 (lazy init)
         - _try_boxoffice() 키워드 매칭
         - try_respond() 체인에 삽입

[Step 3] 포맷터 구현
         - _format_boxoffice_list() (테이블 형식)
         - _format_upcoming_list() (리스트 형식)
```

---

## 5. 에러 처리

| 상황 | 처리 |
|------|------|
| KOBIS_API_KEY 미설정 | 빈 리스트 반환 → `_try_boxoffice()` None 반환 → 다음 핸들러로 |
| API 타임아웃 (10초) | 빈 리스트 반환 → 동일 |
| API 응답 에러 | 로그 기록 + 빈 리스트 반환 |
| 당일 데이터 미집계 | 어제 날짜 기준 조회 (KOBIS는 당일 데이터 늦게 집계) |

---

## 6. 성공 기준

- [ ] "박스오피스" → 일별 TOP 10 테이블 응답
- [ ] "이번 주 박스오피스" → 주간 TOP 10 테이블 응답
- [ ] "개봉 예정 영화" → 개봉 예정작 리스트 응답
- [ ] 순위에 당일관객, 누적관객, 전일대비 변동 표시
- [ ] 6시간 캐싱 동작 확인
- [ ] KOBIS API 장애 시 에러 없이 다음 핸들러로 fallthrough
- [ ] source badge "실시간 박스오피스" 표시
