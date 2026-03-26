"""
TF-IDF based similarity search engine for domain knowledge.
Replaces LLM calls when pattern matching fails but relevant DB data exists.
"""

import re
import logging
import time

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from models.database import get_db
from services.knowledge_query import KnowledgeQuery

logger = logging.getLogger(__name__)

# Korean postpositions to remove for better matching
_JOSA_PATTERN = re.compile(
    r"(?<=\S)(은|는|이|가|을|를|의|에|에서|으로|로|와|과|도|만|까지|부터|보다|처럼|같은|한테|에게|께서"
    r"|라고|이라고|하고|이랑|랑|이나|나|든지|거나|며|면서|지만|인데|ㄴ데|는데|해서|해줘|알려줘|줘|좀)\b"
)


def _preprocess_korean(text: str) -> str:
    """Preprocess Korean text: remove special chars and postpositions."""
    # Keep Korean, English, numbers, spaces
    text = re.sub(r"[^가-힣a-zA-Z0-9\s]", " ", text)
    # Remove common postpositions
    text = _JOSA_PATTERN.sub("", text)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


class TfidfEngine:
    """Manages per-domain TF-IDF indices and performs similarity search."""

    DOMAIN_CONFIG = {
        "movie": {"threshold_high": 0.35, "threshold_low": 0.15, "top_k": 5},
        "healthcare": {"threshold_high": 0.30, "threshold_low": 0.12, "top_k": 3},
        "default": {"threshold_high": 0.30, "threshold_low": 0.15, "top_k": 5},
    }

    def __init__(self):
        self._indices: dict = {}
        self._knowledge = KnowledgeQuery()

    def build_all_indices(self) -> dict[str, int]:
        """Build TF-IDF indices for all domains. Returns {domain: doc_count}."""
        db = get_db()
        start = time.time()

        # Get all domain knowledge entries
        result = db.table("domain_knowledge").select("id, domain, title, content, tags, data").execute()
        if not result.data:
            logger.warning("No domain_knowledge data found for TF-IDF indexing")
            return {}

        # Group by domain
        by_domain: dict[str, list] = {}
        for row in result.data:
            domain = row["domain"]
            by_domain.setdefault(domain, []).append(row)

        counts = {}
        for domain, rows in by_domain.items():
            counts[domain] = self._build_index_from_rows(domain, rows)

        elapsed = time.time() - start
        logger.info("TF-IDF indices built in %.2fs: %s", elapsed, counts)
        return counts

    def _build_index_from_rows(self, domain: str, rows: list[dict]) -> int:
        """Build index for a single domain from pre-fetched rows."""
        if not rows:
            return 0

        documents = []
        corpus = []

        for row in rows:
            title = row.get("title", "")
            content = row.get("content", "")
            tags = row.get("tags") or []
            tags_text = " ".join(tags) if isinstance(tags, list) else str(tags)

            # Title repeated for higher weight
            raw_text = f"{title} {title} {content} {tags_text}"
            processed = _preprocess_korean(raw_text)

            if len(processed.strip()) < 2:
                continue

            corpus.append(processed)
            documents.append({
                "id": row.get("id"),
                "title": title,
                "data": row.get("data", {}),
                "domain": domain,
            })

        if not corpus:
            return 0

        vectorizer = TfidfVectorizer(
            analyzer="word",
            token_pattern=r"[가-힣a-zA-Z0-9]+",
            max_features=10000,
            sublinear_tf=True,
            min_df=1,
            max_df=0.95,
            ngram_range=(1, 2),
        )

        matrix = vectorizer.fit_transform(corpus)

        self._indices[domain] = {
            "vectorizer": vectorizer,
            "matrix": matrix,
            "documents": documents,
        }

        return len(documents)

    def search(self, query: str, domain: str, top_k: int | None = None) -> list[dict] | None:
        """
        Search for similar documents using TF-IDF cosine similarity.
        Returns list of {"data": {...}, "title": str, "score": float} or None.
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

        query_vec = index["vectorizer"].transform([processed_query])
        scores = cosine_similarity(query_vec, index["matrix"]).flatten()

        # Get top-k results above threshold
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
        Try to respond using TF-IDF search.
        Returns (response_text, function_name) or None.
        """
        results = self.search(message, domain)
        if not results:
            return None

        config = self.DOMAIN_CONFIG.get(domain, self.DOMAIN_CONFIG["default"])
        top_score = results[0]["score"]

        if domain == "movie":
            return self._format_movie_response(results, top_score, config)

        # Generic domain response
        return self._format_generic_response(results, top_score, config)

    def _format_movie_response(
        self, results: list[dict], top_score: float, config: dict
    ) -> tuple[str, str]:
        """Format movie search results using KnowledgeQuery formatters."""
        threshold_high = config["threshold_high"]

        if top_score >= threshold_high and len(results) == 1:
            # High confidence single result -> detail card
            response = self._knowledge._format_movie_detail(results[0]["data"])
            return (response, "TF-IDF 유사도 검색")

        if top_score >= threshold_high:
            # High confidence multiple results -> list
            movies = [r["data"] for r in results]
            response = self._knowledge._format_movie_list("검색 결과", movies)
            return (response, "TF-IDF 유사도 검색")

        # Medium confidence -> suggest list
        movies = [r["data"] for r in results]
        response = "이런 결과를 찾았어요:\n\n"
        response += self._knowledge._format_movie_list("관련 영화", movies)
        return (response, "TF-IDF 유사도 검색")

    def _format_generic_response(
        self, results: list[dict], top_score: float, config: dict
    ) -> tuple[str, str]:
        """Format generic domain search results."""
        threshold_high = config["threshold_high"]

        if top_score >= threshold_high:
            # High confidence - show top result content
            top = results[0]
            title = top["title"]
            data = top["data"]
            content = data.get("content", "") or data.get("overview", "") or str(data)
            if len(content) > 500:
                content = content[:500] + "..."
            response = f"## {title}\n\n{content}"
            if len(results) > 1:
                response += "\n\n### 관련 항목\n"
                for r in results[1:]:
                    response += f"- {r['title']}\n"
            return (response, "TF-IDF 유사도 검색")

        # Medium confidence
        response = "관련 정보를 찾았어요:\n\n"
        for r in results:
            title = r["title"]
            data = r["data"]
            desc = data.get("overview", "") or data.get("content", "")
            if desc and len(desc) > 100:
                desc = desc[:100] + "..."
            response += f"- **{title}**"
            if desc:
                response += f": {desc}"
            response += "\n"
        return (response, "TF-IDF 유사도 검색")
