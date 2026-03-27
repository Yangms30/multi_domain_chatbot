"""
Knowledge Query Service - Searches domain_knowledge table for rule-based responses.
Returns formatted answers from DB without calling LLM.
"""

import re
import logging
import random
from datetime import datetime, timedelta

from models.database import get_db

logger = logging.getLogger(__name__)


def _safe_rating(val) -> float:
    """Safely convert rating to float."""
    try:
        return float(val or 0)
    except (ValueError, TypeError):
        return 0.0


class KnowledgeQuery:
    """Queries domain_knowledge table to generate responses without LLM."""

    _boxoffice = None

    @property
    def boxoffice(self):
        if self._boxoffice is None:
            from services.boxoffice_service import BoxOfficeService
            self._boxoffice = BoxOfficeService()
        return self._boxoffice

    # ── Mood → Genre mapping ──────────────────────────────────────
    MOOD_GENRES = {
        # 슬플 때
        "슬플 때": ["드라마", "로맨스"],
        "슬픈": ["드라마", "로맨스"],
        "우울": ["코미디", "가족"],
        "울고 싶": ["드라마", "로맨스"],
        "눈물": ["드라마"],
        "감동": ["드라마", "가족"],
        "감성": ["드라마", "로맨스"],
        "위로": ["드라마", "가족"],
        # 무서운 거
        "무서운": ["공포", "스릴러"],
        "소름": ["공포", "스릴러"],
        "오싹": ["공포", "스릴러"],
        "공포": ["공포"],
        "호러": ["공포"],
        "겁나는": ["공포", "스릴러"],
        # 웃긴 거
        "웃긴": ["코미디"],
        "재밌는": ["코미디", "액션"],
        "빵터지는": ["코미디"],
        "가볍게": ["코미디", "로맨스"],
        "힐링": ["가족", "드라마", "애니메이션"],
        "편하게": ["코미디", "가족", "애니메이션"],
        # 긴장감
        "긴장": ["스릴러", "범죄"],
        "손에 땀": ["스릴러", "액션"],
        "몰입": ["스릴러", "범죄", "미스터리"],
        "반전": ["스릴러", "미스터리"],
        "충격": ["스릴러", "미스터리"],
        # 짜릿한
        "짜릿": ["액션", "모험"],
        "시원한": ["액션", "모험"],
        "통쾌": ["액션", "범죄"],
        "박진감": ["액션", "전쟁"],
        "아드레날린": ["액션", "스릴러"],
        # 로맨틱
        "로맨틱": ["로맨스"],
        "사랑": ["로맨스", "드라마"],
        "연애": ["로맨스"],
        "달달": ["로맨스", "코미디"],
        "설레": ["로맨스"],
        "데이트": ["로맨스", "코미디"],
        # 생각할 거리
        "생각": ["SF", "드라마"],
        "철학": ["SF", "드라마"],
        "깊은": ["드라마", "SF"],
        "뇌섹": ["SF", "미스터리"],
        "머리": ["미스터리", "SF"],
        # 아이/가족
        "아이": ["애니메이션", "가족"],
        "아이들": ["애니메이션", "가족"],
        "가족": ["가족", "애니메이션"],
        "온가족": ["가족", "애니메이션"],
        "어린이": ["애니메이션", "가족"],
        "애들": ["애니메이션", "가족"],
        # 상황
        "심심": ["액션", "코미디", "스릴러"],
        "시간 때우": ["코미디", "액션"],
        "밤에": ["공포", "스릴러"],
        "새벽": ["드라마", "로맨스"],
        "주말": ["액션", "모험", "코미디"],
        "비 오는 날": ["드라마", "로맨스"],
        "비올 때": ["드라마", "로맨스"],
    }

    # ── Country keywords ──────────────────────────────────────────
    COUNTRY_MAP = {
        "한국": "ko", "한국 영화": "ko", "국내": "ko", "국산": "ko", "k무비": "ko",
        "할리우드": "en", "미국": "en", "헐리우드": "en",
        "일본": "ja", "일본 영화": "ja", "일본 애니": "ja",
    }

    # ── Year/era keywords ─────────────────────────────────────────
    ERA_MAP = {
        "90년대": (1990, 1999),
        "2000년대": (2000, 2009),
        "2010년대": (2010, 2019),
        "2020년대": (2020, 2029),
        "옛날": (1970, 1999),
        "고전": (1970, 1999),
        "클래식": (1970, 1999),
    }

    def try_respond(self, message: str, domain: str) -> tuple[str, str] | None:
        if domain != "movie":
            return None

        msg = message.strip()
        msg_lower = msg.lower()

        # 1. Greeting
        result = self._try_greeting(msg_lower)
        if result:
            return result

        # 2. Movie search by title
        result = self._try_movie_search(msg, msg_lower)
        if result:
            return result

        # 3. Similar movie recommendation
        result = self._try_similar_movie(msg, msg_lower)
        if result:
            return result

        # 4. Mood-based recommendation
        result = self._try_mood_recommend(msg_lower)
        if result:
            return result

        # 5. Country-based recommendation
        result = self._try_country_recommend(msg_lower)
        if result:
            return result

        # 6. Era-based recommendation
        result = self._try_era_recommend(msg_lower)
        if result:
            return result

        # 7. Genre-based recommendation
        result = self._try_genre_recommend(msg_lower)
        if result:
            return result

        # 8. Actor filmography
        result = self._try_actor_search(msg, msg_lower)
        if result:
            return result

        # 9. Director filmography
        result = self._try_director_search(msg, msg_lower)
        if result:
            return result

        # 10. Film analysis (LLM-assisted)
        result = self._try_film_analysis(msg, msg_lower)
        if result:
            return result

        # 11. Real-time box office
        result = self._try_boxoffice(msg_lower)
        if result:
            return result

        # 11. Ranking
        result = self._try_ranking(msg_lower)
        if result:
            return result

        # 11. Movie comparison
        result = self._try_compare(msg, msg_lower)
        if result:
            return result

        # 12. Runtime-based
        result = self._try_runtime(msg_lower)
        if result:
            return result

        # 13. Random recommendation
        result = self._try_random(msg_lower)
        if result:
            return result

        return None

    # ── Greeting ──────────────────────────────────────────────────

    def _try_greeting(self, msg_lower: str) -> tuple[str, str] | None:
        if len(msg_lower) > 15:
            return None
        greetings = {
            "안녕": "안녕하세요! 영화에 대해 궁금한 점이 있으시면 편하게 질문해주세요!\n\n"
                    "이런 것들을 물어보실 수 있어요:\n"
                    "- \"액션 영화 추천해줘\"\n"
                    "- \"봉준호 감독 영화\"\n"
                    "- \"슬플 때 볼 영화\"\n"
                    "- \"인터스텔라 알려줘\"\n"
                    "- \"인셉션이랑 비슷한 영화\"",
            "하이": "안녕하세요! 영화 전문가입니다. 무엇이든 물어보세요!",
            "hello": "안녕하세요! 영화에 대해 궁금한 점이 있으시면 말씀해주세요!",
            "hi": "안녕하세요! 영화 추천이 필요하시면 편하게 질문해주세요!",
        }
        for trigger, response in greetings.items():
            if trigger in msg_lower:
                return (response, "인사말")
        return None

    # ── Movie Title Search ────────────────────────────────────────

    def _try_movie_search(self, msg: str, msg_lower: str) -> tuple[str, str] | None:
        info_keywords = ["알려", "정보", "줄거리", "내용", "어떤 영화", "뭐야", "소개",
                         "출연", "감독", "평점", "언제 개봉", "개봉일", "몇 분", "러닝타임",
                         "어때", "재밌어", "리뷰"]
        if not any(kw in msg_lower for kw in info_keywords):
            return None

        # Remove keywords from message to extract title
        # Sort by length DESC so "알려줘" is removed before "알려"
        remove_words = info_keywords + [
            "영화", "좀", "해줘", "해 줘", "알려줘", "에 대해", "에대해",
            "어떤", "봤어", "봤는데", "줘", "좀",
            "은", "는", "이", "가", "을", "를", "의", "?", "?",
        ]
        remove_words.sort(key=len, reverse=True)

        title_query = msg
        for kw in remove_words:
            title_query = title_query.replace(kw, "")
        title_query = title_query.strip()

        if len(title_query) < 2:
            return None

        movies = self._search_movies_by_title(title_query)
        if not movies:
            return None

        movie = movies[0]
        return (self._format_movie_detail(movie), "영화 정보 조회")

    # ── Similar Movie Recommendation ──────────────────────────────

    def _try_similar_movie(self, msg: str, msg_lower: str) -> tuple[str, str] | None:
        similar_keywords = ["비슷한", "같은", "유사한", "느낌의", "분위기",
                            "스타일", "종류", "타입"]
        if not any(kw in msg_lower for kw in similar_keywords):
            return None

        # Extract title
        title_query = msg
        for kw in similar_keywords + ["영화", "추천", "좀", "해줘", "알려줘",
                                       "이랑", "하고", "처럼", "같은 거",
                                       "은", "는", "이", "가", "을", "를", "의", "?", "?"]:
            title_query = title_query.replace(kw, "")
        title_query = title_query.strip()

        if len(title_query) < 2:
            return None

        # Find the reference movie
        source_movies = self._search_movies_by_title(title_query)
        if not source_movies:
            return None

        source = source_movies[0]
        source_genres = source.get("genres", [])
        source_director = source.get("director", "")

        # Find movies with same genres (excluding the source)
        similar = []
        for genre in source_genres:
            candidates = self._search_movies_by_genre(genre, limit=10)
            for c in candidates:
                if c.get("title") != source.get("title") and c not in similar:
                    similar.append(c)

        # Also add same director's movies
        if source_director:
            director_movies = self._search_movies_by_director(source_director, limit=5)
            for d in director_movies:
                if d.get("title") != source.get("title") and d not in similar:
                    similar.insert(0, d)  # prioritize same director

        if not similar:
            return None

        # Score by genre overlap
        def similarity_score(movie):
            movie_genres = set(movie.get("genres", []))
            overlap = len(movie_genres & set(source_genres))
            same_dir = 2 if movie.get("director") == source_director else 0
            return overlap + same_dir + _safe_rating(movie.get("vote_average", 0)) / 10

        similar.sort(key=similarity_score, reverse=True)
        top = similar[:5]

        title = f"{source.get('title', '')}과(와) 비슷한 영화"
        response = self._format_movie_list(title, top)
        response += f"\n\n*{source.get('title', '')}의 장르({', '.join(source_genres)})와 감독({source_director})을 기준으로 추천했습니다.*"
        return (response, "유사 영화 추천")

    # ── Mood-based Recommendation ─────────────────────────────────

    def _try_mood_recommend(self, msg_lower: str) -> tuple[str, str] | None:
        matched_mood = None
        matched_genres = None

        for mood_keyword, genres in self.MOOD_GENRES.items():
            if mood_keyword in msg_lower:
                matched_mood = mood_keyword
                matched_genres = genres
                break

        if not matched_genres:
            return None

        # Collect movies from matched genres
        movies = []
        seen_titles = set()
        for genre in matched_genres:
            candidates = self._search_movies_by_genre(genre, limit=5)
            for c in candidates:
                title = c.get("title", "")
                if title not in seen_titles:
                    seen_titles.add(title)
                    movies.append(c)

        if not movies:
            return None

        # Sort by rating, take top 5
        movies.sort(key=lambda m: _safe_rating(m.get("vote_average", 0)), reverse=True)
        top = movies[:5]

        mood_label = matched_mood.rstrip("때 을를")
        list_title = f"\"{matched_mood}\" 기분에 맞는 영화 추천"
        response = self._format_movie_list(list_title, top)
        response += f"\n\n*{', '.join(matched_genres)} 장르에서 추천했습니다.*"
        return (response, "기분별 영화 추천")

    # ── Country-based Recommendation ──────────────────────────────

    def _try_country_recommend(self, msg_lower: str) -> tuple[str, str] | None:
        recommend_keywords = ["추천", "볼만한", "재밌는", "좋은", "알려", "뭐 있"]
        if not any(kw in msg_lower for kw in recommend_keywords):
            return None

        matched_country = None
        matched_lang = None
        for keyword, lang in self.COUNTRY_MAP.items():
            if keyword in msg_lower:
                matched_country = keyword
                matched_lang = lang
                break

        if not matched_lang:
            return None

        movies = self._search_movies_by_language(matched_lang, limit=5)
        if not movies:
            return None

        return (
            self._format_movie_list(f"{matched_country} 영화 추천", movies),
            f"{matched_country} 영화 추천"
        )

    # ── Era-based Recommendation ──────────────────────────────────

    def _try_era_recommend(self, msg_lower: str) -> tuple[str, str] | None:
        recommend_keywords = ["추천", "볼만한", "재밌는", "좋은", "알려", "영화"]
        if not any(kw in msg_lower for kw in recommend_keywords):
            return None

        matched_era = None
        matched_range = None
        for keyword, year_range in self.ERA_MAP.items():
            if keyword in msg_lower:
                matched_era = keyword
                matched_range = year_range
                break

        if not matched_range:
            return None

        movies = self._search_movies_by_year_range(matched_range[0], matched_range[1], limit=5)
        if not movies:
            return None

        return (
            self._format_movie_list(f"{matched_era} 영화 추천", movies),
            f"{matched_era} 영화 추천"
        )

    # ── Genre Recommendation ──────────────────────────────────────

    def _try_genre_recommend(self, msg_lower: str) -> tuple[str, str] | None:
        recommend_keywords = ["추천", "볼만한", "재밌는", "재미있는", "좋은", "볼 영화",
                              "뭐 볼", "뭐볼", "보고 싶", "보고싶"]
        if not any(kw in msg_lower for kw in recommend_keywords):
            return None

        genre_map = {
            "액션": "액션", "action": "액션",
            "코미디": "코미디", "comedy": "코미디",
            "로맨스": "로맨스", "romance": "로맨스",
            "공포": "공포", "호러": "공포", "horror": "공포",
            "sf": "SF", "공상과학": "SF", "sci-fi": "SF",
            "스릴러": "스릴러", "thriller": "스릴러",
            "애니메이션": "애니메이션", "animation": "애니메이션", "애니": "애니메이션",
            "드라마": "드라마", "drama": "드라마",
            "판타지": "판타지", "fantasy": "판타지",
            "범죄": "범죄", "crime": "범죄",
            "전쟁": "전쟁", "war": "전쟁",
            "다큐멘터리": "다큐멘터리", "documentary": "다큐멘터리", "다큐": "다큐멘터리",
            "가족": "가족", "family": "가족",
            "음악": "음악", "musical": "음악", "뮤지컬": "음악",
            "모험": "모험", "adventure": "모험",
            "미스터리": "미스터리", "mystery": "미스터리",
            "역사": "역사", "history": "역사", "사극": "역사",
            "서부": "서부", "western": "서부",
        }

        matched_genre = None
        for keyword, genre_name in genre_map.items():
            if keyword in msg_lower:
                matched_genre = genre_name
                break

        if not matched_genre:
            return None

        movies = self._search_movies_by_genre(matched_genre, limit=5)
        if not movies:
            return None

        return (self._format_movie_list(f"{matched_genre} 영화 추천", movies), f"{matched_genre} 영화 추천")

    # ── Actor Search ──────────────────────────────────────────────

    def _try_actor_search(self, msg: str, msg_lower: str) -> tuple[str, str] | None:
        actor_keywords = ["출연작", "나온 영화", "필모", "필모그래피", "배우"]
        if not any(kw in msg_lower for kw in actor_keywords):
            return None

        name_query = msg
        for kw in actor_keywords + ["영화", "좀", "알려줘", "알려", "해줘", "의",
                                     "은", "는", "이", "가", "?", "?"]:
            name_query = name_query.replace(kw, "")
        name_query = name_query.strip()

        if len(name_query) < 2:
            return None

        movies = self._search_movies_by_actor(name_query, limit=5)
        if not movies:
            return None

        return (self._format_movie_list(f"{name_query} 출연 영화", movies), "배우 출연작 조회")

    # ── Director Search ───────────────────────────────────────────

    def _try_director_search(self, msg: str, msg_lower: str) -> tuple[str, str] | None:
        director_keywords = ["감독 영화", "감독 작품", "감독이 만든", "감독님"]
        if not any(kw in msg_lower for kw in director_keywords):
            return None

        name_query = msg
        for kw in director_keywords + ["영화", "좀", "알려줘", "알려", "해줘", "의",
                                        "은", "는", "이", "가", "?", "?"]:
            name_query = name_query.replace(kw, "")
        name_query = name_query.strip()

        if len(name_query) < 2:
            return None

        movies = self._search_movies_by_director(name_query, limit=5)
        if not movies:
            return None

        return (self._format_movie_list(f"{name_query} 감독 작품", movies), "감독 작품 조회")

    # ── Ranking ───────────────────────────────────────────────────

    # ── Real-time Box Office ──────────────────────────────────────

    # ── Film Analysis (LLM-assisted) ──────────────────────────────

    _ANALYSIS_KEYWORDS = [
        "분석", "해석", "촬영기법", "스토리 구조", "테마", "상징",
        "연출", "영화적", "기법", "서사", "메시지",
    ]

    def _try_film_analysis(self, msg: str, msg_lower: str) -> tuple[str, str] | None:
        """Detect film analysis request, extract movie title, return __FILM_ANALYSIS__ marker."""
        if not any(kw in msg_lower for kw in self._ANALYSIS_KEYWORDS):
            return None

        # Extract movie title by removing analysis keywords and common suffixes
        title = msg
        for kw in self._ANALYSIS_KEYWORDS + [
            "해줘", "알려줘", "설명", "영화", "좀", "해봐", "부탁",
            "에 대해", "의", "을", "를", "이", "가",
        ]:
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
            context = {
                "title": title,
                "from_db": False,
            }

        import json as _json
        return ("__FILM_ANALYSIS__", _json.dumps(context, ensure_ascii=False))

    # ── Real-time Box Office ──────────────────────────────────────

    def _try_boxoffice(self, msg_lower: str) -> tuple[str, str] | None:
        """Try real-time box office / upcoming movies via KOBIS API."""
        # Daily box office
        if any(kw in msg_lower for kw in [
            "박스오피스", "극장 순위", "오늘 영화 순위", "상영중", "현재 상영",
            "극장에서", "극장 영화", "오늘 극장"
        ]):
            movies = self.boxoffice.get_daily_boxoffice()
            if movies:
                return (self._format_boxoffice_list("오늘의 박스오피스 TOP 10", movies),
                        "실시간 박스오피스")

        # Weekly box office
        if any(kw in msg_lower for kw in [
            "이번 주 박스오피스", "주간 순위", "주간 영화", "이번주 영화", "주간 박스오피스"
        ]):
            movies = self.boxoffice.get_weekly_boxoffice()
            if movies:
                return (self._format_boxoffice_list("이번 주 박스오피스 TOP 10", movies),
                        "주간 박스오피스")

        # Upcoming movies
        if any(kw in msg_lower for kw in [
            "개봉 예정", "곧 개봉", "개봉일", "다음 주 영화", "언제 개봉",
            "새 영화", "개봉 영화", "곧 나오는"
        ]):
            movies = self.boxoffice.get_upcoming_movies()
            if movies:
                return (self._format_upcoming_list("개봉 예정 영화", movies),
                        "개봉 예정작 조회")

        return None

    def _format_boxoffice_list(self, title: str, movies: list[dict]) -> str:
        """Format daily/weekly box office as a table."""
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

        response = f"## {title}\n\n"
        response += "| 순위 | 영화 | 당일 관객 | 누적 관객 | 전일 대비 |\n"
        response += "|:----:|------|--------:|--------:|--------:|\n"

        for movie in movies:
            rank = movie.get("rank", "")
            name = movie.get("movieNm", "")
            audi_cnt = int(movie.get("audiCnt", 0))
            audi_acc = int(movie.get("audiAcc", 0))
            audi_change = int(movie.get("audiInten", 0))

            audi_cnt_str = self._format_audience(audi_cnt)
            audi_acc_str = self._format_audience(audi_acc)

            if audi_change > 0:
                change_str = f"+{self._format_audience(audi_change)}"
            elif audi_change < 0:
                change_str = f"-{self._format_audience(abs(audi_change))}"
            else:
                change_str = "-"

            response += f"| {rank} | {name} | {audi_cnt_str} | {audi_acc_str} | {change_str} |\n"

        response += f"\n*KOBIS 영화진흥위원회 제공 ({yesterday} 기준)*"
        return response

    def _format_upcoming_list(self, title: str, movies: list[dict]) -> str:
        """Format upcoming movies list."""
        response = f"## {title}\n\n"

        for i, movie in enumerate(movies, 1):
            name = movie.get("movieNm", "")
            open_dt = movie.get("openDt", "")
            if open_dt and len(open_dt) == 8:
                open_dt = f"{open_dt[:4]}-{open_dt[4:6]}-{open_dt[6:8]}"
            genre = movie.get("genreAlt", "")
            directors = movie.get("directors", [])
            director = directors[0].get("peopleNm", "") if directors else ""

            response += f"### {i}. {name}\n"
            if open_dt:
                response += f"- **개봉일**: {open_dt}\n"
            if genre:
                response += f"- **장르**: {genre}\n"
            if director:
                response += f"- **감독**: {director}\n"
            response += "\n"

        response += "*KOBIS 영화진흥위원회 제공*"
        return response

    # ── Ranking ────────────────────────────────────────────────────

    def _try_ranking(self, msg_lower: str) -> tuple[str, str] | None:
        if any(kw in msg_lower for kw in ["인기 영화", "인기있는", "인기순", "많이 본", "핫한",
                                           "유명한", "흥행", "대박", "천만", "블록버스터", "관객수"]):
            # Try audience-count based ranking first
            movies = self._get_popular_movies(limit=5)
            if movies:
                return (self._format_popular_movie_list("인기 영화 TOP 5", movies), "관객수 기반 인기 순위")
            # Fallback to rating-based
            movies = self._get_top_rated_movies(limit=5)
            if movies:
                return (self._format_movie_list("인기 영화 TOP 5", movies), "인기 영화 순위")

        if any(kw in msg_lower for kw in ["평점 높은", "명작", "최고 영화", "별점 높은", "평점순",
                                           "잘 만든", "레전드", "갓작"]):
            movies = self._get_top_rated_movies(limit=5)
            if movies:
                return (self._format_movie_list("평점 TOP 5 영화", movies), "평점 순위")

        if any(kw in msg_lower for kw in ["최신", "새로 나온", "신작", "요즘"]):
            movies = self._get_recent_movies(limit=5)
            if movies:
                return (self._format_movie_list("최신 영화", movies), "최신 영화 조회")

        if any(kw in msg_lower for kw in ["짧은 영화", "짧은", "단편", "빨리 볼"]):
            movies = self._get_short_movies(limit=5)
            if movies:
                return (self._format_movie_list("짧은 영화 추천 (2시간 이내)", movies), "짧은 영화 추천")

        if any(kw in msg_lower for kw in ["긴 영화", "대작", "장편", "오래"]):
            movies = self._get_long_movies(limit=5)
            if movies:
                return (self._format_movie_list("장편 대작 영화 추천 (2시간 30분 이상)", movies), "장편 영화 추천")

        return None

    # ── Movie Comparison ──────────────────────────────────────────

    def _try_compare(self, msg: str, msg_lower: str) -> tuple[str, str] | None:
        compare_keywords = ["vs", "비교", "차이", "뭐가 더", "어떤 게 더"]
        if not any(kw in msg_lower for kw in compare_keywords):
            return None

        # Try to split by vs or 비교
        parts = None
        for sep in [" vs ", " VS ", "vs", " 비교 ", "비교", " 하고 ", "이랑 ", "랑 "]:
            if sep in msg:
                parts = msg.split(sep, 1)
                break

        if not parts or len(parts) != 2:
            return None

        # Clean up title parts
        clean_words = ["영화", "비교", "차이", "뭐가", "더", "좋", "어떤", "?", "?",
                       "해줘", "알려줘", "좀"]
        title1 = parts[0].strip()
        title2 = parts[1].strip()
        for w in clean_words:
            title1 = title1.replace(w, "").strip()
            title2 = title2.replace(w, "").strip()

        if len(title1) < 2 or len(title2) < 2:
            return None

        movies1 = self._search_movies_by_title(title1)
        movies2 = self._search_movies_by_title(title2)

        if not movies1 or not movies2:
            return None

        m1, m2 = movies1[0], movies2[0]
        return (self._format_comparison(m1, m2), "영화 비교")

    # ── Runtime-based ─────────────────────────────────────────────

    def _try_runtime(self, msg_lower: str) -> tuple[str, str] | None:
        if any(kw in msg_lower for kw in ["짧은 영화", "짧은", "빨리 볼", "금방 볼"]):
            movies = self._get_short_movies(limit=5)
            if movies:
                return (self._format_movie_list("짧은 영화 추천 (2시간 이내)", movies), "짧은 영화 추천")

        if any(kw in msg_lower for kw in ["긴 영화", "대작", "장편"]):
            movies = self._get_long_movies(limit=5)
            if movies:
                return (self._format_movie_list("장편 대작 추천 (2시간 30분 이상)", movies), "장편 영화 추천")

        return None

    # ── Random Recommendation ─────────────────────────────────────

    def _try_random(self, msg_lower: str) -> tuple[str, str] | None:
        random_keywords = ["아무거나", "랜덤", "뭐든", "상관없", "골라줘", "정해줘",
                           "뭐 볼까", "뭐볼까", "추천 좀", "영화 추천", "뭐 없을까"]
        if not any(kw in msg_lower for kw in random_keywords):
            return None

        movies = self._get_all_movies()
        if not movies:
            return None

        selected = random.sample(movies, min(5, len(movies)))
        return (self._format_movie_list("랜덤 영화 추천", selected), "랜덤 영화 추천")

    # ── DB Queries ────────────────────────────────────────────────

    def _search_movies_by_title(self, title: str, limit: int = 3) -> list[dict]:
        db = get_db()
        result = (
            db.table("domain_knowledge")
            .select("data")
            .eq("domain", "movie")
            .eq("category", "movie")
            .ilike("title", f"%{title}%")
            .limit(limit)
            .execute()
        )
        if result.data:
            return [r["data"] for r in result.data]

        # Fallback: search original_title too
        result = (
            db.table("domain_knowledge")
            .select("data")
            .eq("domain", "movie")
            .eq("category", "movie")
            .ilike("content", f"%{title}%")
            .limit(limit)
            .execute()
        )
        return [r["data"] for r in result.data] if result.data else []

    def _search_movies_by_genre(self, genre: str, limit: int = 5) -> list[dict]:
        db = get_db()
        result = (
            db.table("domain_knowledge")
            .select("data")
            .eq("domain", "movie")
            .eq("category", "movie")
            .contains("tags", [genre])
            .order("data->>vote_average", desc=True)
            .limit(limit)
            .execute()
        )
        return [r["data"] for r in result.data] if result.data else []

    def _search_movies_by_actor(self, actor_name: str, limit: int = 5) -> list[dict]:
        db = get_db()
        result = (
            db.table("domain_knowledge")
            .select("data")
            .eq("domain", "movie")
            .eq("category", "movie")
            .ilike("content", f"%{actor_name}%")
            .order("data->>vote_average", desc=True)
            .limit(limit)
            .execute()
        )
        return [r["data"] for r in result.data] if result.data else []

    def _search_movies_by_director(self, director_name: str, limit: int = 5) -> list[dict]:
        db = get_db()
        result = (
            db.table("domain_knowledge")
            .select("data")
            .eq("domain", "movie")
            .eq("category", "movie")
            .ilike("content", f"%{director_name}%")
            .order("data->>vote_average", desc=True)
            .limit(limit)
            .execute()
        )
        return [r["data"] for r in result.data] if result.data else []

    def _search_movies_by_language(self, lang: str, limit: int = 5) -> list[dict]:
        db = get_db()
        result = (
            db.table("domain_knowledge")
            .select("data")
            .eq("domain", "movie")
            .eq("category", "movie")
            .contains("tags", [lang])
            .order("data->>vote_average", desc=True)
            .limit(limit)
            .execute()
        )
        return [r["data"] for r in result.data] if result.data else []

    def _search_movies_by_year_range(self, start: int, end: int, limit: int = 5) -> list[dict]:
        db = get_db()
        # Fetch all movies and filter by year in Python (JSONB date filtering is complex)
        result = (
            db.table("domain_knowledge")
            .select("data")
            .eq("domain", "movie")
            .eq("category", "movie")
            .order("data->>vote_average", desc=True)
            .execute()
        )
        if not result.data:
            return []

        filtered = []
        for r in result.data:
            release = r["data"].get("release_date", "")
            if release and len(release) >= 4:
                try:
                    year = int(release[:4])
                    if start <= year <= end:
                        filtered.append(r["data"])
                except ValueError:
                    pass
        return filtered[:limit]

    def _get_top_rated_movies(self, limit: int = 5) -> list[dict]:
        db = get_db()
        result = (
            db.table("domain_knowledge")
            .select("data")
            .eq("domain", "movie")
            .eq("category", "movie")
            .order("data->>vote_average", desc=True)
            .limit(limit)
            .execute()
        )
        return [r["data"] for r in result.data] if result.data else []

    def _get_recent_movies(self, limit: int = 5) -> list[dict]:
        db = get_db()
        result = (
            db.table("domain_knowledge")
            .select("data")
            .eq("domain", "movie")
            .eq("category", "movie")
            .order("data->>release_date", desc=True)
            .limit(limit)
            .execute()
        )
        return [r["data"] for r in result.data] if result.data else []

    def _get_short_movies(self, limit: int = 5) -> list[dict]:
        db = get_db()
        result = (
            db.table("domain_knowledge")
            .select("data")
            .eq("domain", "movie")
            .eq("category", "movie")
            .order("data->>vote_average", desc=True)
            .execute()
        )
        if not result.data:
            return []
        filtered = [r["data"] for r in result.data if (r["data"].get("runtime") or 999) <= 120]
        return filtered[:limit]

    def _get_long_movies(self, limit: int = 5) -> list[dict]:
        db = get_db()
        result = (
            db.table("domain_knowledge")
            .select("data")
            .eq("domain", "movie")
            .eq("category", "movie")
            .order("data->>vote_average", desc=True)
            .execute()
        )
        if not result.data:
            return []
        filtered = [r["data"] for r in result.data if (r["data"].get("runtime") or 0) >= 150]
        return filtered[:limit]

    def _get_popular_movies(self, limit: int = 5) -> list[dict]:
        """Get movies ordered by audience count (popularity)."""
        db = get_db()
        result = (
            db.table("domain_knowledge")
            .select("data")
            .eq("domain", "movie")
            .eq("category", "movie")
            .order("data->>audience_count", desc=True)
            .limit(limit * 2)
            .execute()
        )
        if not result.data:
            return []
        # Filter out movies with no audience data
        movies = [r["data"] for r in result.data if (r["data"].get("audience_count") or 0) > 0]
        return movies[:limit]

    def _get_all_movies(self) -> list[dict]:
        db = get_db()
        result = (
            db.table("domain_knowledge")
            .select("data")
            .eq("domain", "movie")
            .eq("category", "movie")
            .execute()
        )
        return [r["data"] for r in result.data] if result.data else []

    # ── Formatters ────────────────────────────────────────────────

    def _format_movie_detail(self, movie: dict) -> str:
        year = movie.get("release_date", "")[:4] or "미정"
        genres = ", ".join(movie.get("genres", []))
        cast_list = movie.get("cast", [])
        cast_str = ", ".join(c["name"] for c in cast_list[:5]) if cast_list else "정보 없음"
        rating = _safe_rating(movie.get("vote_average", 0))
        runtime = movie.get("runtime")
        runtime_str = f"{runtime}분" if runtime else "정보 없음"
        tagline = movie.get("tagline", "")
        poster = movie.get("poster_url", "")

        response = f"## {movie.get('title', '')} ({year})\n\n"

        if tagline:
            response += f"*\"{tagline}\"*\n\n"

        if poster:
            response += f"![포스터]({poster})\n\n"

        response += (
            f"| 항목 | 정보 |\n"
            f"|------|------|\n"
            f"| 감독 | {movie.get('director', '정보 없음')} |\n"
            f"| 출연 | {cast_str} |\n"
            f"| 장르 | {genres or '정보 없음'} |\n"
            f"| 평점 | {'⭐' * round(rating / 2)} {rating}/10 |\n"
            f"| 상영시간 | {runtime_str} |\n"
            f"| 개봉일 | {movie.get('release_date', '미정')} |\n"
        )

        overview = movie.get("overview", "")
        if overview:
            response += f"\n### 줄거리\n{overview}\n"

        if cast_list:
            response += "\n### 주요 출연진\n"
            for c in cast_list[:5]:
                char = c.get("character", "")
                response += f"- **{c['name']}** {f'({char})' if char else ''}\n"

        response += "\n*더 궁금한 점이 있으면 편하게 질문해주세요!*"
        return response

    def _format_movie_list(self, title: str, movies: list[dict]) -> str:
        response = f"## {title}\n\n"

        for i, movie in enumerate(movies, 1):
            year = movie.get("release_date", "")[:4] or "미정"
            genres = ", ".join(movie.get("genres", []))
            rating = _safe_rating(movie.get("vote_average", 0))
            director = movie.get("director", "")
            overview = movie.get("overview", "")

            response += (
                f"### {i}. {movie.get('title', '')} ({year})\n"
                f"- **평점**: {'⭐' * round(rating / 2)} {rating}/10\n"
                f"- **장르**: {genres}\n"
            )
            if director:
                response += f"- **감독**: {director}\n"
            if overview:
                response += f"- {overview}\n"
            response += "\n"

        response += "*영화에 대해 더 자세히 알고 싶으면 제목을 말씀해주세요!*"
        return response

    def _format_popular_movie_list(self, title: str, movies: list[dict]) -> str:
        """Format movie list with audience count."""
        response = f"## {title}\n\n"

        for i, movie in enumerate(movies, 1):
            year = movie.get("release_date", "")[:4] or "미정"
            audience = movie.get("audience_count", 0)
            audience_str = self._format_audience(audience)
            rating = _safe_rating(movie.get("vote_average", 0))
            genres = ", ".join(movie.get("genres", []))

            response += (
                f"### {i}. {movie.get('title', '')} ({year})\n"
                f"- **관객수**: {audience_str}\n"
                f"- **평점**: {'⭐' * round(rating / 2)} {rating}/10\n"
                f"- **장르**: {genres}\n"
            )
            director = movie.get("director", "")
            if director:
                response += f"- **감독**: {director}\n"
            response += "\n"

        response += "*영화에 대해 더 자세히 알고 싶으면 제목을 말씀해주세요!*"
        return response

    @staticmethod
    def _format_audience(count: int) -> str:
        """Format audience count for display."""
        if count >= 10_000_000:
            return f"{count / 10_000_000:.1f}천만 명"
        elif count >= 10_000:
            return f"{count / 10_000:.0f}만 명"
        elif count >= 1_000:
            return f"{count / 1_000:.1f}천 명"
        else:
            return f"{count:,} 명"

    def _format_comparison(self, m1: dict, m2: dict) -> str:
        def year(m):
            return m.get("release_date", "")[:4] or "미정"

        def cast_str(m):
            return ", ".join(c["name"] for c in m.get("cast", [])[:3]) or "정보 없음"

        def runtime_str(m):
            rt = m.get("runtime")
            return f"{rt}분" if rt else "정보 없음"

        r1 = _safe_rating(m1.get("vote_average", 0))
        r2 = _safe_rating(m2.get("vote_average", 0))

        response = f"## {m1.get('title', '')} vs {m2.get('title', '')}\n\n"
        response += (
            f"| 항목 | {m1.get('title', '')} | {m2.get('title', '')} |\n"
            f"|------|------|------|\n"
            f"| 개봉 | {year(m1)} | {year(m2)} |\n"
            f"| 감독 | {m1.get('director', '')} | {m2.get('director', '')} |\n"
            f"| 장르 | {', '.join(m1.get('genres', []))} | {', '.join(m2.get('genres', []))} |\n"
            f"| 평점 | {'⭐' * round(r1 / 2)} {r1}/10 | {'⭐' * round(r2 / 2)} {r2}/10 |\n"
            f"| 상영시간 | {runtime_str(m1)} | {runtime_str(m2)} |\n"
            f"| 주연 | {cast_str(m1)} | {cast_str(m2)} |\n"
        )

        # Winner by rating
        if r1 > r2:
            response += f"\n평점 기준으로는 **{m1.get('title', '')}**이(가) 더 높습니다!\n"
        elif r2 > r1:
            response += f"\n평점 기준으로는 **{m2.get('title', '')}**이(가) 더 높습니다!\n"
        else:
            response += f"\n두 영화의 평점이 동일합니다!\n"

        response += "\n*두 영화 모두 훌륭한 작품입니다. 더 궁금한 점이 있으면 질문해주세요!*"
        return response
