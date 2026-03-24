"""
Base scraper interface for domain knowledge collection.
All domain scrapers inherit from this class.
"""

import logging
import os
from abc import ABC, abstractmethod

from supabase import create_client

logger = logging.getLogger(__name__)


class BaseScraper(ABC):
    """Base class for all domain knowledge scrapers."""

    domain: str = ""

    def __init__(self):
        self.stats = {"total": 0, "new": 0, "skipped": 0, "errors": 0}

        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_KEY")
        if not url or not key:
            raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be set in .env")
        self.db = create_client(url, key)

    @abstractmethod
    async def run(self):
        """Load data and store results in domain_knowledge table."""
        ...

    def reset_domain(self):
        """Delete all existing knowledge for this domain."""
        self.db.table("domain_knowledge").delete().eq("domain", self.domain).execute()
        logger.info("Deleted all %s knowledge entries.", self.domain)

    def get_stats(self) -> dict:
        return self.stats

    def _upsert_knowledge(self, external_id: str, category: str, title: str,
                          content: str, data: dict, tags: list[str]):
        """Insert or update a knowledge entry. Skips if external_id already exists."""
        self.stats["total"] += 1

        # Check if already exists
        existing = (
            self.db.table("domain_knowledge")
            .select("id")
            .eq("domain", self.domain)
            .eq("external_id", external_id)
            .execute()
        )
        if existing.data:
            self.stats["skipped"] += 1
            return

        try:
            self.db.table("domain_knowledge").insert({
                "domain": self.domain,
                "external_id": external_id,
                "category": category,
                "title": title,
                "content": content,
                "data": data,
                "tags": tags,
            }).execute()
            self.stats["new"] += 1
        except Exception as e:
            logger.error("Failed to insert %s: %s", title, e)
            self.stats["errors"] += 1
