"""
BM25+ based similarity search engine for domain knowledge.
Drop-in replacement for TfidfEngine with better document length normalization.
"""

import logging
import time

import numpy as np
from rank_bm25 import BM25Plus

from models.database import get_db
from services.tfidf_engine import _preprocess_korean
from services.knowledge_query import KnowledgeQuery

logger = logging.getLogger(__name__)


def _tokenize_with_bigrams(text: str) -> list[str]:
    """Tokenize text into unigrams + bigrams for better matching."""
    words = text.split()
    tokens = list(words)
    for i in range(len(words) - 1):
        tokens.append(f"{words[i]}_{words[i+1]}")
    return tokens


class Bm25Engine:
    """Manages per-domain BM25+ indices and performs similarity search."""

    # BM25 raw scores (not 0~1). Tuned based on actual score distribution.
    DOMAIN_CONFIG = {
        "movie": {"threshold_high": 8.0, "threshold_low": 3.0, "top_k": 5},
        "default": {"threshold_high": 6.0, "threshold_low": 2.0, "top_k": 5},
    }

    def __init__(self):
        self._indices: dict = {}
        self._knowledge = KnowledgeQuery()
        # In-memory title index for exact/substring matching (bypasses BM25 scoring)
        self._title_index: dict[str, list[dict]] = {}  # {domain: [{title, title_lower, doc}]}

    def build_all_indices(self) -> dict[str, int]:
        """Build BM25+ indices for all domains. Returns {domain: doc_count}."""
        db = get_db()
        start = time.time()

        result = db.table("domain_knowledge").select("id, domain, title, content, tags, data").order("id").execute()
        if not result.data:
            logger.warning("No domain_knowledge data found for BM25+ indexing")
            return {}

        by_domain: dict[str, list] = {}
        for row in result.data:
            domain = row["domain"]
            by_domain.setdefault(domain, []).append(row)

        counts = {}
        for domain, rows in by_domain.items():
            counts[domain] = self._build_index_from_rows(domain, rows)

        elapsed = time.time() - start
        logger.info("BM25+ indices built in %.2fs: %s", elapsed, counts)
        return counts

    def _build_index_from_rows(self, domain: str, rows: list[dict]) -> int:
        """Build BM25+ index for a single domain."""
        if not rows:
            return 0

        documents = []
        tokenized_corpus = []

        for row in rows:
            title = row.get("title", "")
            content = row.get("content", "")
            tags = row.get("tags") or []
            tags_text = " ".join(tags) if isinstance(tags, list) else str(tags)

            # Title repeated 3x for higher weight (Design spec: 2→3)
            raw_text = f"{title} {title} {title} {content} {tags_text}"
            processed = _preprocess_korean(raw_text)

            if len(processed.strip()) < 2:
                continue

            tokens = _tokenize_with_bigrams(processed)
            tokenized_corpus.append(tokens)
            documents.append({
                "id": row.get("id"),
                "title": title,
                "data": row.get("data", {}),
                "domain": domain,
            })

        if not tokenized_corpus:
            return 0

        bm25 = BM25Plus(tokenized_corpus)

        self._indices[domain] = {
            "bm25": bm25,
            "documents": documents,
        }

        # Build title index for fast substring matching
        title_entries = []
        for doc in documents:
            title = doc.get("title", "")
            if title:
                title_entries.append({
                    "title": title,
                    "title_lower": title.lower(),
                    "doc": doc,
                })
            # Also index original_title (English) and data.title for movies
            data = doc.get("data") or {}
            orig_title = data.get("original_title", "")
            if orig_title and orig_title.lower() != title.lower():
                title_entries.append({
                    "title": title,  # keep Korean title for display
                    "title_lower": orig_title.lower(),
                    "doc": doc,
                })
        self._title_index[domain] = title_entries

        return len(documents)

    def _title_search(self, query: str, domain: str, top_k: int = 5) -> list[dict] | None:
        """
        Fast in-memory title substring matching.
        Checks if query contains a movie title or vice versa.
        Returns matching documents sorted by title length (longer = more specific match).
        """
        if domain not in self._title_index:
            return None

        query_lower = query.lower().strip()
        if len(query_lower) < 2:
            return None

        # Extract potential title keywords by removing common query words
        title_stopwords = [
            "정보", "알려", "줘", "해줘", "알려줘", "영화", "좀", "에 대해", "뭐야",
            "출연진", "누구", "감독", "작품", "목록", "출연", "필모", "배우",
            "추천", "비슷한", "같은", "유사한", "비교",
            "소개", "줄거리", "내용", "평점", "러닝타임", "몇 분",
            "관객수", "정확히", "역할", "어때", "재밌어",
        ]
        cleaned = query_lower
        for sw in title_stopwords:
            cleaned = cleaned.replace(sw, " ")
        # Remove common particles
        import re
        cleaned = re.sub(r'\b(은|는|이|가|을|를|의|에|에서|도|만|이랑|랑|하고|와|과)\b', ' ', cleaned)
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()

        if len(cleaned) < 2:
            return None

        matches = []
        seen_titles = set()
        for entry in self._title_index[domain]:
            t_lower = entry["title_lower"]
            # Check: cleaned query contains the title OR title contains cleaned query
            if cleaned in t_lower or t_lower in cleaned:
                if entry["title"] not in seen_titles:
                    seen_titles.add(entry["title"])
                    matches.append({
                        "data": entry["doc"].get("data", {}),
                        "title": entry["title"],
                        "score": 100.0 + len(t_lower),  # title match = very high score
                    })

        if not matches:
            return None

        # Sort by title length desc (longer title = more specific match)
        matches.sort(key=lambda x: x["score"], reverse=True)
        return matches[:top_k]

    def search(self, query: str, domain: str, top_k: int | None = None) -> list[dict] | None:
        """
        Search for similar documents using BM25+.
        First tries title matching, then falls back to BM25 scoring.
        Returns list of {"data": {...}, "title": str, "score": float} or None.
        """
        # Try title matching first for more accurate results
        title_results = self._title_search(query, domain, top_k=top_k or 5)
        if title_results:
            return title_results

        if domain not in self._indices:
            return None

        config = self.DOMAIN_CONFIG.get(domain, self.DOMAIN_CONFIG["default"])
        if top_k is None:
            top_k = config["top_k"]
        threshold_low = config["threshold_low"]

        index = self._indices[domain]
        processed_query = _preprocess_korean(query)

        if len(processed_query.strip()) < 2:
            return None

        query_tokens = _tokenize_with_bigrams(processed_query)
        raw_scores = index["bm25"].get_scores(query_tokens)

        # Normalize using percentile-based scaling instead of min-max
        # This avoids the problem of max_score always becoming 1.0
        # Use raw scores with adjusted thresholds
        scores = raw_scores

        # Get top-k results above threshold (using raw BM25 scores)
        ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
        results = []
        for idx, score in ranked[:top_k]:
            if score < threshold_low:
                break
            doc = index["documents"][idx]
            results.append({
                "data": doc["data"],
                "title": doc["title"],
                "score": float(score),
            })

        return results if results else None

    def try_respond(self, message: str, domain: str) -> tuple[str, str] | None:
        """
        Try to respond using title matching first, then BM25+ search.
        Returns (response_text, function_name) or None.
        """
        # 1. Try fast title substring matching first (most accurate for known titles)
        title_results = self._title_search(message, domain)
        if title_results:
            config = self.DOMAIN_CONFIG.get(domain, self.DOMAIN_CONFIG["default"])
            if domain == "movie":
                return self._format_movie_response(title_results, title_results[0]["score"], config)
            return self._format_generic_response(title_results, title_results[0]["score"], config)

        # 2. Fall back to BM25+ similarity search
        results = self.search(message, domain)
        if not results:
            return None

        config = self.DOMAIN_CONFIG.get(domain, self.DOMAIN_CONFIG["default"])
        top_score = results[0]["score"]

        if domain == "movie":
            return self._format_movie_response(results, top_score, config)

        return self._format_generic_response(results, top_score, config)

    def _format_movie_response(
        self, results: list[dict], top_score: float, config: dict
    ) -> tuple[str, str]:
        """Format movie search results using KnowledgeQuery formatters."""
        threshold_high = config["threshold_high"]

        if top_score >= threshold_high and len(results) == 1:
            response = self._knowledge._format_movie_detail(results[0]["data"])
            return (response, "BM25+ 유사도 검색")

        if top_score >= threshold_high:
            movies = [r["data"] for r in results]
            response = self._knowledge._format_movie_list("검색 결과", movies)
            return (response, "BM25+ 유사도 검색")

        movies = [r["data"] for r in results]
        response = "이런 결과를 찾았어요:\n\n"
        response += self._knowledge._format_movie_list("관련 영화", movies)
        return (response, "BM25+ 유사도 검색")

    def _format_generic_response(
        self, results: list[dict], top_score: float, config: dict
    ) -> tuple[str, str]:
        """Format generic domain search results."""
        threshold_high = config["threshold_high"]

        if top_score >= threshold_high:
            top = results[0]
            title = top["title"]
            data = top["data"]
            content = data.get("content", "") or data.get("overview", "") or str(data)
            response = f"## {title}\n\n{content}"
            if len(results) > 1:
                response += "\n\n### 관련 항목\n"
                for r in results[1:]:
                    response += f"- {r['title']}\n"
            return (response, "BM25+ 유사도 검색")

        response = "관련 정보를 찾았어요:\n\n"
        for r in results:
            title = r["title"]
            data = r["data"]
            desc = data.get("overview", "") or data.get("content", "")
            response += f"- **{title}**"
            if desc:
                response += f": {desc}"
            response += "\n"
        return (response, "BM25+ 유사도 검색")
