"""
Movie Knowledge Loader - Loads movie data from local seed file into Supabase.

No API key needed. Data is stored in scripts/data/movies_seed.json.
Add more movies to the JSON file anytime and re-run to import.
"""

import json
import logging
import os

from scripts.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

SEED_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "movies_seed.json")


class MovieScraper(BaseScraper):
    domain = "movie"

    async def run(self, pages: int = 5):
        if not os.path.exists(SEED_FILE):
            logger.error("Seed file not found: %s", SEED_FILE)
            return

        with open(SEED_FILE, "r", encoding="utf-8") as f:
            movies = json.load(f)

        logger.info("Loading %d movies from seed file...", len(movies))

        # Collect unique genres for genre entries
        all_genres = set()

        for movie in movies:
            self._process_movie(movie)
            for genre in movie.get("genres", []):
                all_genres.add(genre)

        # Store genre entries
        for genre in all_genres:
            self._upsert_knowledge(
                external_id=f"genre_{genre}",
                category="genre",
                title=genre,
                content=f"{genre} 장르",
                data={"name": genre},
                tags=["genre", genre],
            )

        logger.info("Loaded %d genres", len(all_genres))

    def _process_movie(self, movie: dict):
        external_id = movie.get("id", f"movie_{movie['title']}")
        cast = movie.get("cast", [])
        cast_names = ", ".join(c["name"] for c in cast[:5])
        genres = movie.get("genres", [])
        director = movie.get("director", "")
        year = movie.get("release_date", "")[:4] or "미정"

        # Build search-friendly content
        content = (
            f"{movie['title']} ({year})\n"
            f"감독: {director}\n"
            f"출연: {cast_names}\n"
            f"장르: {', '.join(genres)}\n"
            f"평점: {movie.get('vote_average', 0)}/10\n"
            f"줄거리: {movie.get('overview', '')}"
        )

        # Build tags
        tags = (
            genres
            + [director]
            + [c["name"] for c in cast[:5]]
            + [movie.get("original_language", "")]
        )
        tags = [t for t in tags if t]

        # Store full movie data in data field
        data = {
            "title": movie.get("title", ""),
            "original_title": movie.get("original_title", ""),
            "overview": movie.get("overview", ""),
            "release_date": movie.get("release_date", ""),
            "runtime": movie.get("runtime"),
            "vote_average": movie.get("vote_average", 0),
            "genres": genres,
            "director": director,
            "cast": cast,
            "poster_url": movie.get("poster_url", ""),
            "tagline": movie.get("tagline", ""),
            "original_language": movie.get("original_language", ""),
            "production_countries": movie.get("production_countries", []),
        }

        self._upsert_knowledge(
            external_id=external_id,
            category="movie",
            title=movie.get("title", movie.get("original_title", "")),
            content=content,
            data=data,
            tags=tags,
        )
