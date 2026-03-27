# TF-IDF → BM25 검색 엔진 업그레이드 Plan

## Executive Summary

| 항목 | 내용 |
|------|------|
| Feature | TF-IDF → BM25+ 검색 엔진 업그레이드 + 인기도 기반 랭킹 |
| 시작일 | 2026-03-27 |
| 목표 | 검색 품질 5~15% 향상 + "유명한 영화" 등 인기도 기반 쿼리 지원 |

### Value Delivered

| 관점 | 내용 |
|------|------|
| **Problem** | 현재 TF-IDF는 문서 길이 정규화가 미흡하여, overview가 긴 영화와 짧은 영화 간 불공정한 점수 차이 발생. 또한 "유명한 영화 추천해줘" 같은 인기도 기반 질문에 관객수 데이터가 없어 평점순으로만 정렬됨 |
| **Solution** | BM25+ 알고리즘으로 교체하여 문서 길이 정규화 개선 + KOBIS 박스오피스 API의 누적관객수(audiAcc) 수집·저장하여 인기도 랭킹 지원 |
| **Function UX Effect** | 더 정확한 검색 결과 + "유명한 영화", "많이 본 영화" 질문에 실제 관객수 기반 응답 |
| **Core Value** | 검색 정확도 향상으로 LLM fallback 감소 + 관객수 데이터로 인기도 기반 추천 가능 |

---

## 1. 배경 및 현재 상태

### 현재 검색 엔진 (TF-IDF)
- `backend/services/tfidf_engine.py`
- `sklearn.TfidfVectorizer` + `cosine_similarity`
- 설정: `sublinear_tf=True`, `ngram_range=(1,2)`, 한국어 조사 제거
- 도메인별 threshold: movie (high: 0.35, low: 0.15)

### 현재 문제점
1. **문서 길이 정규화 미흡**: overview가 2줄인 영화 vs 10줄인 영화 간 불균형
2. **단어 빈도 포화 없음**: 특정 단어 반복 시 점수가 과도하게 올라감
3. **인기도 데이터 부재**: KOBIS 박스오피스 API에서 `audiAcc`(누적관객수)를 수집하지 않음
4. **"유명한 영화" 쿼리 한계**: 현재 `_try_ranking()`에서 `vote_average`(평점)순 정렬만 가능

### KOBIS 박스오피스 API 데이터 확인
- `dailyBoxOfficeList` 응답에 포함되는 필드:
  - `audiAcc`: **누적관객수** (핵심!)
  - `salesAcc`: 누적매출액
  - `rankOldAndNew`: 신규진입 여부
  - `rank`: 순위
- 현재 `kobis_collector.py`에서 박스오피스 데이터 수집 시 `movie_cd`만 추출하고 나머지는 버리는 중

## 2. 구현 범위

### Task 1: BM25+ 엔진 구현
- **파일**: `backend/services/bm25_engine.py` (신규)
- **라이브러리**: `rank_bm25` (경량, numpy만 의존)
- **구현 내용**:
  - `TfidfEngine`과 동일한 인터페이스 (`build_all_indices`, `search`, `try_respond`)
  - `_preprocess_korean()` 함수 재사용
  - BM25+ 알고리즘 선택 (가변 길이 문서에 최적)
  - 동일한 threshold/top_k 설정 체계

### Task 2: A/B 비교 테스트 스크립트
- **파일**: `backend/scripts/compare_search_engines.py` (신규)
- **테스트 쿼리셋** (20~30개):
  - 정확한 제목 검색: "인터스텔라", "기생충"
  - 부분 제목: "인터스텔", "기생"
  - 장르+키워드: "무서운 한국 영화"
  - 기분 기반: "슬플 때 볼 영화"
  - 배우/감독: "봉준호 영화"
  - 유사한 표현: "우주 영화", "외계인 나오는 영화"
- **비교 지표**:
  - 검색 결과 Top-5 일치율
  - 평균 점수 분포
  - 응답 시간 (ms)
  - 관련성 판단 (수동 평가)

### Task 3: 관객수 데이터 수집 및 저장
- **수정 파일**: `backend/scripts/kobis_collector.py`
- **변경 내용**:
  - 박스오피스 수집 시 `audiAcc`, `salesAcc` 추출
  - `domain_knowledge.data` JSON에 `audience_count`, `sales_amount` 필드 추가
  - 기존 데이터에 관객수 backfill하는 스크립트 추가

### Task 4: 인기도 기반 랭킹 추가
- **수정 파일**: `backend/services/knowledge_query.py`
- **변경 내용**:
  - `_try_ranking()`에 "유명한", "흥행", "대박", "천만" 등 키워드 추가
  - `_get_popular_movies()` 메서드: `audience_count` 순 정렬
  - "많이 본 영화" 쿼리 시 관객수 표시 (예: "1,400만 관객")

### Task 5: 엔진 교체 및 통합
- **수정 파일**: `backend/services/tfidf_engine.py` or `main.py`
- A/B 테스트 결과에 따라:
  - BM25+가 우수: 기본 엔진을 BM25+로 교체
  - 큰 차이 없음: TF-IDF 유지하되 인기도 랭킹만 추가
- 기존 `TfidfEngine` 인터페이스 유지 (하위 호환)

## 3. 기술 결정

### BM25+ 선택 이유
| 항목 | TF-IDF (현재) | BM25 | BM25+ (선택) |
|------|-------------|------|-------------|
| 문서 길이 정규화 | cosine으로 부분 보완 | b 파라미터 | b + 하한선 보장 |
| 단어 빈도 포화 | sublinear_tf | k1 파라미터 | 동일 |
| 긴 문서 페널티 | 없음 | 과도할 수 있음 | **delta로 보정** |
| 가변 길이 적합성 | 보통 | 좋음 | **최적** |

### 라이브러리 선택: `rank_bm25`
- 이유: 순수 Python, 가벼움, BM25Okapi/BM25L/BM25Plus 모두 지원
- 대안 `bm25s`도 빠르지만, 현재 데이터 규모(수백~수천)에서는 속도 차이 무의미
- 설치: `pip install rank-bm25`

## 4. 구현 순서

```
[1] BM25+ 엔진 구현 (bm25_engine.py)
 ↓
[2] 비교 테스트 스크립트 작성 & 실행
 ↓
[3] 관객수 데이터 수집 (kobis_collector 수정)
 ↓
[4] 인기도 기반 랭킹 추가 (knowledge_query 수정)
 ↓
[5] 테스트 결과 기반 엔진 교체 결정 & 통합
```

## 5. 성공 기준

- [ ] BM25+ vs TF-IDF 비교 테스트 완료 (20개 이상 쿼리)
- [ ] 검색 결과 관련성이 기존 대비 동등 이상
- [ ] "유명한 영화 추천해줘" → 관객수 기반 TOP 5 응답
- [ ] "많이 본 영화" → 누적 관객수 표시된 리스트 응답
- [ ] 응답 시간 100ms 이내 유지

## 6. 리스크

| 리스크 | 대응 |
|--------|------|
| BM25+가 TF-IDF보다 한국어에서 크게 나아지지 않을 수 있음 | A/B 테스트로 검증 후 교체 결정 |
| KOBIS 박스오피스 API의 관객수가 모든 영화에 있지 않음 | 관객수 없는 영화는 평점 fallback |
| rank_bm25 토크나이저가 한국어에 맞지 않을 수 있음 | 기존 `_preprocess_korean` 함수를 토크나이저로 활용 |
