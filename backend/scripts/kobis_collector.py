"""
KOBIS Movie Collector - Collects real Korean movie data from 영화진흥위원회 API.

No hallucination - all data comes from official Korean film database.

KOBIS API docs: https://kobis.or.kr/kobisopenapi/homepg/apiservice/searchServiceInfo.do

Available endpoints:
- 일별 박스오피스: Daily box office rankings
- 주간/주말 박스오피스: Weekly box office
- 영화 목록: Search all movies
- 영화 상세정보: Movie details (director, actors, genres, etc.)

Usage:
    cd backend
    python -m scripts.kobis_collector --mode boxoffice --days 365
    python -m scripts.kobis_collector --mode search --year 2024
    python -m scripts.kobis_collector --mode search --year 2023
    python -m scripts.kobis_collector --mode infinite

Requires KOBIS_API_KEY in .env
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta

import httpx
from dotenv import load_dotenv
from supabase import create_client

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

KOBIS_BASE = "https://kobis.or.kr/kobisopenapi/webservice/rest"

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9",
}


class KobisCollector:
    def __init__(self):
        load_dotenv()
        self.api_key = os.environ.get("KOBIS_API_KEY")
        if not self.api_key:
            raise RuntimeError("KOBIS_API_KEY가 .env에 필요합니다.")

        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_KEY")
        if not url or not key:
            raise RuntimeError("SUPABASE_URL, SUPABASE_KEY가 .env에 필요합니다.")
        self.db = create_client(url, key)
        self.client = httpx.Client(timeout=15.0, headers=HEADERS, follow_redirects=True)
        self.stats = {"total": 0, "success": 0, "skipped": 0, "errors": 0}

    # ── Box Office Collection ─────────────────────────────────────

    def collect_monthly_boxoffice(self, months: int = 12):
        """Collect movies from monthly box office (1st of each month, TOP 10)."""
        logger.info("=== 월별 박스오피스 수집 (최근 %d개월) ===", months)
        collected_codes = set()

        for i in range(months):
            # Get 1st day of each past month
            target = datetime.now().replace(day=1) - timedelta(days=i * 30)
            # Use 15th of the month for more stable results
            target = target.replace(day=15)
            date_str = target.strftime("%Y%m%d")
            month_label = target.strftime("%Y년 %m월")

            movies = self._get_daily_boxoffice(date_str)
            if not movies:
                continue

            new_this_month = 0
            for movie in movies:
                movie_cd = movie.get("movieCd", "")
                if movie_cd in collected_codes:
                    continue
                collected_codes.add(movie_cd)
                new_this_month += 1

                audience = int(movie.get("audiAcc", 0))
                sales = int(movie.get("salesAcc", 0))
                self._process_movie(movie_cd, movie.get("movieNm", ""),
                                    audience_count=audience, sales_amount=sales)

            logger.info("  %s: %d편 (신규 %d)", month_label, len(movies), new_this_month)
            time.sleep(0.3)

        logger.info("월별 박스오피스에서 총 %d편 발견", len(collected_codes))

    def collect_weekly_boxoffice(self, weeks: int = 52):
        """Collect movies from weekly box office."""
        logger.info("=== 주간 박스오피스 수집 (최근 %d주) ===", weeks)
        collected_codes = set()

        for i in range(weeks):
            date = datetime.now() - timedelta(weeks=i + 1)
            date_str = date.strftime("%Y%m%d")

            movies = self._get_weekly_boxoffice(date_str)
            if not movies:
                continue

            for movie in movies:
                movie_cd = movie.get("movieCd", "")
                if movie_cd in collected_codes:
                    continue
                collected_codes.add(movie_cd)

                audience = int(movie.get("audiAcc", 0))
                sales = int(movie.get("salesAcc", 0))
                self._process_movie(movie_cd, movie.get("movieNm", ""),
                                    audience_count=audience, sales_amount=sales)

            time.sleep(0.3)

        logger.info("주간 박스오피스에서 총 %d편 발견", len(collected_codes))

    # ── Movie List Search ─────────────────────────────────────────

    def collect_by_year(self, year: int):
        """Collect all movies from a specific year."""
        logger.info("=== %d년 영화 수집 ===", year)
        page = 1

        while True:
            movies, total = self._search_movies(year=year, page=page)
            if not movies:
                break

            logger.info("  페이지 %d (%d편 / 전체 %d편)", page, len(movies), total)

            for movie in movies:
                movie_cd = movie.get("movieCd", "")
                self._process_movie(movie_cd, movie.get("movieNm", ""))

            if page * 10 >= total:
                break
            page += 1
            time.sleep(0.3)

    def collect_infinite(self):
        """Continuously collect movies from all available years."""
        current_year = datetime.now().year

        # 1. Recent box office (most popular)
        logger.info("\n🔄 Phase 1: 월별 박스오피스 수집")
        self.collect_monthly_boxoffice(months=60)  # 최근 5년
        self._print_stats()

        # 2. Year by year (recent → old)
        for year in range(current_year, 1990, -1):
            logger.info(f"\n🔄 Phase 2: {year}년 영화 수집")
            self.collect_by_year(year)
            self._print_stats()

        logger.info("\n=== 전체 수집 완료 ===")
        self._print_stats()

    # ── KOBIS API Calls ───────────────────────────────────────────

    def _get_daily_boxoffice(self, date: str) -> list[dict]:
        try:
            resp = self.client.get(
                f"{KOBIS_BASE}/boxoffice/searchDailyBoxOfficeList.json",
                params={"key": self.api_key, "targetDt": date},
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("boxOfficeResult", {}).get("dailyBoxOfficeList", [])
        except Exception as e:
            logger.warning("박스오피스 조회 실패 (%s): %s", date, e)
            return []

    def _get_weekly_boxoffice(self, date: str) -> list[dict]:
        try:
            resp = self.client.get(
                f"{KOBIS_BASE}/boxoffice/searchWeeklyBoxOfficeList.json",
                params={"key": self.api_key, "targetDt": date, "weekGb": "0"},
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("boxOfficeResult", {}).get("weeklyBoxOfficeList", [])
        except Exception as e:
            logger.warning("주간 박스오피스 조회 실패 (%s): %s", date, e)
            return []

    def _search_movies(self, year: int, page: int = 1) -> tuple[list[dict], int]:
        try:
            resp = self.client.get(
                f"{KOBIS_BASE}/movie/searchMovieList.json",
                params={
                    "key": self.api_key,
                    "openStartDt": str(year),
                    "openEndDt": str(year),
                    "curPage": str(page),
                    "itemPerPage": "10",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            result = data.get("movieListResult", {})
            movies = result.get("movieList", [])
            total = int(result.get("totCnt", 0))
            return movies, total
        except Exception as e:
            logger.warning("영화 검색 실패 (%d, page %d): %s", year, page, e)
            return [], 0

    def _get_movie_detail(self, movie_cd: str) -> dict | None:
        try:
            resp = self.client.get(
                f"{KOBIS_BASE}/movie/searchMovieInfo.json",
                params={"key": self.api_key, "movieCd": movie_cd},
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("movieInfoResult", {}).get("movieInfo")
        except Exception as e:
            logger.warning("영화 상세 조회 실패 (%s): %s", movie_cd, e)
            return None

    # ── Web Crawling for Overview & Rating ────────────────────────

    def _crawl_extra_info(self, title: str, year: str) -> dict:
        """Crawl overview and rating from Naver/Google. Returns {overview, vote_average}."""
        result = {"overview": "", "vote_average": 0}

        if not HAS_BS4:
            return result

        # Try Naver movie search
        naver = self._crawl_naver_movie(title)
        if naver.get("overview"):
            result["overview"] = naver["overview"]
        if naver.get("vote_average"):
            result["vote_average"] = naver["vote_average"]

        # If Naver didn't work, try Wikipedia
        if not result["overview"]:
            wiki = self._crawl_wikipedia(title, year)
            if wiki:
                result["overview"] = wiki

        return result

    def _crawl_naver_movie(self, title: str) -> dict:
        """Search Naver movie and extract overview + rating."""
        result = {"overview": "", "vote_average": 0}
        try:
            # Naver search for movie
            resp = self.client.get(
                "https://search.naver.com/search.naver",
                params={"where": "nexearch", "query": f"{title} 영화"},
            )
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            # Try to find plot/overview
            # Naver shows movie info in structured cards
            for tag in soup.select("p, span, div"):
                text = tag.get_text(strip=True)
                # Look for plot text (usually in specific containers)
                if len(text) > 50 and any(kw in text for kw in ["감독", "줄거리", "이야기"]):
                    # Skip if it's just cast/crew info
                    if not any(skip in text for skip in ["출연진", "포토", "영상"]):
                        result["overview"] = text[:500]
                        break

            # Try to find a longer description
            for desc_el in soup.select('[class*="desc"], [class*="plot"], [class*="story"], [class*="synopsis"]'):
                text = desc_el.get_text(strip=True)
                if len(text) > 30:
                    result["overview"] = text[:500]
                    break

            # Try to find rating
            for rating_el in soup.select('[class*="score"], [class*="rating"], [class*="point"]'):
                text = rating_el.get_text(strip=True)
                # Look for number patterns like "8.5" or "85"
                import re
                match = re.search(r'(\d+\.?\d*)', text)
                if match:
                    val = float(match.group(1))
                    if 0 < val <= 10:
                        result["vote_average"] = round(val, 1)
                        break
                    elif 10 < val <= 100:
                        result["vote_average"] = round(val / 10, 1)
                        break

        except Exception as e:
            logger.debug("네이버 크롤링 실패 (%s): %s", title, e)

        return result

    def _crawl_wikipedia(self, title: str, year: str) -> str:
        """Get movie overview from Korean Wikipedia."""
        try:
            # Wikipedia API search
            resp = self.client.get(
                "https://ko.wikipedia.org/w/api.php",
                params={
                    "action": "query",
                    "list": "search",
                    "srsearch": f"{title} {year} 영화",
                    "format": "json",
                    "srlimit": 1,
                    "utf8": 1,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            results = data.get("query", {}).get("search", [])
            if not results:
                return ""

            # Get page extract
            page_title = results[0]["title"]
            resp2 = self.client.get(
                "https://ko.wikipedia.org/w/api.php",
                params={
                    "action": "query",
                    "titles": page_title,
                    "prop": "extracts",
                    "exintro": True,
                    "explaintext": True,
                    "format": "json",
                    "utf8": 1,
                },
            )
            resp2.raise_for_status()
            pages = resp2.json().get("query", {}).get("pages", {})
            for page in pages.values():
                text = page.get("extract", "")
                if text and len(text) > 20:
                    return text[:500]

        except Exception as e:
            logger.debug("Wikipedia 크롤링 실패 (%s): %s", title, e)

        return ""

    # ── Process & Store ───────────────────────────────────────────

    def _process_movie(self, movie_cd: str, movie_name: str,
                       audience_count: int = 0, sales_amount: int = 0):
        self.stats["total"] += 1
        external_id = f"kobis_{movie_cd}"

        # Skip if exists
        try:
            existing = (
                self.db.table("domain_knowledge")
                .select("id")
                .eq("domain", "movie")
                .eq("external_id", external_id)
                .execute()
            )
            if existing.data:
                self.stats["skipped"] += 1
                return
        except Exception:
            pass

        # Get detail
        detail = self._get_movie_detail(movie_cd)
        if not detail:
            self.stats["errors"] += 1
            return

        # Parse KOBIS data
        title = detail.get("movieNm", movie_name)
        original_title = detail.get("movieNmEn", "")
        open_dt = detail.get("openDt", "")
        runtime = detail.get("showTm", "")
        genres = [g.get("genreNm", "") for g in detail.get("genres", [])]
        genres = [g for g in genres if g]
        nations = [n.get("nationNm", "") for n in detail.get("nations", [])]

        # Directors
        directors = [d.get("peopleNm", "") for d in detail.get("directors", [])]
        director = ", ".join(directors) if directors else ""

        # Cast
        cast = []
        for actor in detail.get("actors", [])[:10]:
            cast.append({
                "name": actor.get("peopleNm", ""),
                "character": actor.get("cast", ""),
            })

        # Format date
        release_date = ""
        if open_dt and len(open_dt) == 8:
            release_date = f"{open_dt[:4]}-{open_dt[4:6]}-{open_dt[6:8]}"

        # Format date
        year = release_date[:4] if release_date else "미정"

        # Crawl overview & rating from web
        extra = self._crawl_extra_info(title, year)

        # Build data object
        data = {
            "title": title,
            "original_title": original_title,
            "release_date": release_date,
            "runtime": int(runtime) if runtime.isdigit() else None,
            "vote_average": extra.get("vote_average", 0),
            "genres": genres,
            "director": director,
            "cast": cast,
            "overview": extra.get("overview", ""),
            "tagline": "",
            "original_language": "ko",
            "production_countries": nations,
            "kobis_cd": movie_cd,
            "audience_count": audience_count,
            "sales_amount": sales_amount,
        }

        # Build content for search
        cast_names = ", ".join(c["name"] for c in cast[:5])
        content = (
            f"{title} ({year})\n"
            f"감독: {director}\n"
            f"출연: {cast_names}\n"
            f"장르: {', '.join(genres)}\n"
            f"평점: {data['vote_average']}/10\n"
            f"줄거리: {data['overview']}"
        )

        # Tags
        tags = genres + [director] + [c["name"] for c in cast[:5]] + ["ko"]
        tags = [t for t in tags if t]

        try:
            self.db.table("domain_knowledge").insert({
                "domain": "movie",
                "external_id": external_id,
                "category": "movie",
                "title": title,
                "content": content,
                "data": data,
                "tags": tags,
            }).execute()
            self.stats["success"] += 1
            logger.info("  ✅ %s (%s)", title, year)
        except Exception as e:
            self.stats["errors"] += 1
            logger.error("  ❌ %s 저장 실패: %s", title, e)

        time.sleep(0.3)  # Rate limit

    def _print_stats(self):
        s = self.stats
        logger.info("--- 누적: 전체 %d | 성공 %d | 스킵 %d | 실패 %d ---",
                     s["total"], s["success"], s["skipped"], s["errors"])

    def close(self):
        self.client.close()


def main():
    parser = argparse.ArgumentParser(description="KOBIS Movie Collector")
    parser.add_argument("--mode", required=True,
                        choices=["monthly", "weekly", "search", "infinite"],
                        help="Collection mode")
    parser.add_argument("--months", type=int, default=12,
                        help="Months for monthly mode (default: 12)")
    parser.add_argument("--weeks", type=int, default=52,
                        help="Weeks for weekly mode (default: 52)")
    parser.add_argument("--year", type=int, default=2024,
                        help="Year for search mode (default: 2024)")
    args = parser.parse_args()

    collector = KobisCollector()

    start = time.time()

    if args.mode == "monthly":
        collector.collect_monthly_boxoffice(months=args.months)
    elif args.mode == "weekly":
        collector.collect_weekly_boxoffice(weeks=args.weeks)
    elif args.mode == "search":
        collector.collect_by_year(year=args.year)
    elif args.mode == "infinite":
        collector.collect_infinite()

    elapsed = time.time() - start
    collector._print_stats()
    logger.info("소요 시간: %.1f초", elapsed)
    collector.close()


if __name__ == "__main__":
    main()
