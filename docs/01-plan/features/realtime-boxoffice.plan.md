# 실시간 박스오피스 & 개봉 예정작 Plan

## Executive Summary

| 항목 | 내용 |
|------|------|
| Feature | 실시간 박스오피스 순위 + 개봉 예정작 캘린더 |
| 시작일 | 2026-03-27 |
| 목표 | "오늘 박스오피스 1위?" "이번 주 개봉 영화?" 질문에 실시간 데이터로 즉시 응답 |

### Value Delivered

| 관점 | 내용 |
|------|------|
| **Problem** | 현재 영화 데이터는 수집 시점의 정적 데이터만 있어서 "지금 극장에서 뭐해?" 같은 실시간 질문에 답할 수 없음 |
| **Solution** | KOBIS API를 실시간으로 호출하여 일별/주간 박스오피스 + 개봉 예정작을 조회하고 캐싱 |
| **Function UX Effect** | "오늘 박스오피스" → 실시간 TOP 10 순위 + 관객수 + 전일 대비 변동, LLM 비용 0원 |
| **Core Value** | 정적 DB 기반 챗봇에서 실시간 데이터 제공 챗봇으로 진화, 사용자 재방문 이유 생성 |

---

## 1. 배경

### 현재 상태
- KOBIS API 연동 완료 (`kobis_collector.py`에 `_get_daily_boxoffice`, `_get_weekly_boxoffice` 이미 존재)
- 하지만 이건 **수집 스크립트** 전용이라 챗봇에서 실시간 호출 불가
- "오늘 박스오피스" 질문 → 현재 `_try_ranking()`에서 `vote_average` 정렬된 정적 데이터만 반환

### KOBIS API 활용 가능한 엔드포인트
| 엔드포인트 | 용도 | 호출 제한 |
|-----------|------|---------|
| `searchDailyBoxOfficeList` | 일별 박스오피스 TOP 10 | 일 3,000회 |
| `searchWeeklyBoxOfficeList` | 주간 박스오피스 TOP 10 | 일 3,000회 |
| `searchMovieList` | 영화 목록 검색 (개봉예정 포함) | 일 3,000회 |

### 박스오피스 API 반환 데이터
```
rank, movieNm, openDt, salesAmt, salesShare, salesInten, salesChange,
salesAcc, audiCnt, audiInten, audiChange, audiAcc, scrnCnt, showCnt
```
- `rank`: 순위
- `audiCnt`: 당일 관객수
- `audiAcc`: 누적 관객수
- `audiInten`: 전일 대비 관객수 증감
- `salesAcc`: 누적 매출
- `openDt`: 개봉일
- `scrnCnt`: 상영 스크린 수

## 2. 구현 범위

### Task 1: 실시간 박스오피스 서비스
- **파일**: `backend/services/boxoffice_service.py` (신규)
- KOBIS API 실시간 호출 + 메모리 캐싱 (TTL: 6시간)
- `get_daily_boxoffice()` → 일별 TOP 10
- `get_weekly_boxoffice()` → 주간 TOP 10
- `get_upcoming_movies()` → 개봉 예정작 (openStartDt으로 미래 날짜 검색)

### Task 2: knowledge_query.py 키워드 추가
- `_try_ranking()`에 실시간 박스오피스 키워드 추가:
  - "박스오피스", "극장", "상영중", "현재 상영", "오늘 영화", "지금 뭐해"
  - "개봉 예정", "개봉일", "곧 개봉", "다음 주 영화", "언제 개봉"
- 실시간 데이터로 응답 (기존 DB 데이터가 아닌 KOBIS API 직접 호출)

### Task 3: 응답 포맷터
- `_format_boxoffice_list()`: 순위 + 영화명 + 당일관객 + 누적관객 + 전일대비 변동
- `_format_upcoming_list()`: 영화명 + 개봉일 + 장르 + 감독

## 3. 기술 결정

### 캐싱 전략
- **메모리 캐시** (TTL 6시간): 같은 날 반복 질문에 API 재호출 방지
- KOBIS 일 3,000회 제한 충분 (6시간 캐시면 하루 최대 4회 호출)
- 서버 재시작 시 캐시 초기화 (괜찮음 — 첫 질문에서 재로드)

### LLM 비용
- **0원** — 모든 응답이 API 데이터 기반 포맷팅, LLM 불필요

## 4. 구현 순서

```
[1] boxoffice_service.py 구현 (API 호출 + 캐싱)
 ↓
[2] knowledge_query.py 키워드 추가 + 서비스 연동
 ↓
[3] 포맷터 구현 + 테스트
```

## 5. 성공 기준

- [ ] "오늘 박스오피스" → 실시간 TOP 10 순위 응답
- [ ] "이번 주 박스오피스" → 주간 TOP 10 응답
- [ ] "개봉 예정 영화" → 향후 개봉 예정작 리스트 응답
- [ ] 순위에 당일관객수, 누적관객수, 전일대비 변동 표시
- [ ] 캐싱으로 동일 질문 반복 시 API 재호출 없음
- [ ] LLM 비용 0원
- [ ] KOBIS API 장애 시 graceful fallback (기존 DB 데이터)
