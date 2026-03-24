"""
Domain Knowledge Loader - Loads domain-specific knowledge into Supabase.

Usage:
    python -m scripts.scrape_knowledge --domain movie
    python -m scripts.scrape_knowledge --domain movie --reset

No external API keys needed. Data comes from local seed files (scripts/data/).
Add more entries to the JSON seed files and re-run to import.
"""

import argparse
import asyncio
import logging
import os
import sys

from dotenv import load_dotenv

# Add parent directory to path so we can import from backend
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.scrapers.base import BaseScraper
from scripts.scrapers.movie_scraper import MovieScraper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

SCRAPERS: dict[str, type[BaseScraper]] = {
    "movie": MovieScraper,
}


async def main():
    load_dotenv()

    parser = argparse.ArgumentParser(description="Domain Knowledge Loader")
    parser.add_argument("--domain", required=True, choices=list(SCRAPERS.keys()),
                        help="Domain to load (movie, ...)")
    parser.add_argument("--reset", action="store_true",
                        help="Delete existing data for this domain before loading")
    args = parser.parse_args()

    scraper_class = SCRAPERS[args.domain]
    scraper = scraper_class()

    logger.info("=== Domain Knowledge Loader ===")
    logger.info("Domain: %s", args.domain)

    if args.reset:
        logger.info("Resetting existing %s data...", args.domain)
        scraper.reset_domain()

    await scraper.run()

    stats = scraper.get_stats()
    logger.info("=== Complete ===")
    logger.info("Total: %d items | New: %d | Skipped: %d | Errors: %d",
                stats["total"], stats["new"], stats["skipped"], stats["errors"])


if __name__ == "__main__":
    asyncio.run(main())
