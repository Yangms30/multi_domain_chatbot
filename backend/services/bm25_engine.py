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

        return len(documents)

    def search(self, query: str, domain: str, top_k: int | None = None) -> list[dict] | None:
        """
        Search for similar documents using BM25+.
        Returns list of {"data": {...}, "title": str, "score": float} or None.
        Scores are raw BM25 values (not normalized). Thresholds adjusted accordingly.
        """
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
        Try to respond using BM25+ search.
        Returns (response_text, function_name) or None.
        """
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
