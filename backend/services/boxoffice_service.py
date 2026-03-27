"""
Real-time box office data from KOBIS API with in-memory caching.
Provides daily/weekly rankings and upcoming movie listings.
"""

import os
import time
import logging
from datetime import datetime, timedelta

import httpx

logger = logging.getLogger(__name__)

KOBIS_BASE = "https://kobis.or.kr/kobisopenapi/webservice/rest"
CACHE_TTL = 6 * 60 * 60  # 6 hours


class BoxOfficeService:
    """KOBIS API real-time box office with TTL-based memory cache."""

    def __init__(self):
        self.api_key = os.environ.get("KOBIS_API_KEY", "")
        self._cache: dict[str, tuple[float, list]] = {}

    def _get_cached(self, key: str) -> list | None:
        if key in self._cache:
            cached_time, data = self._cache[key]
            if time.time() - cached_time < CACHE_TTL:
                return data
            del self._cache[key]
        return None

    def _set_cache(self, key: str, data: list):
        self._cache[key] = (time.time(), data)

    def get_daily_boxoffice(self) -> list[dict]:
        """Daily box office TOP 10. Uses yesterday (today's data is delayed)."""
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
        cache_key = f"daily_{yesterday}"

        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        if not self.api_key:
            logger.warning("KOBIS_API_KEY not set — skipping box office lookup")
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
        """Weekly box office TOP 10."""
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
        """Upcoming movies (opening after today)."""
        today = datetime.now().strftime("%Y%m%d")
        cache_key = f"upcoming_{today}"

        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        if not self.api_key:
            return []

        try:
            resp = httpx.get(
                f"{KOBIS_BASE}/movie/searchMovieList.json",
                params={
                    "key": self.api_key,
                    "openStartDt": today,
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
