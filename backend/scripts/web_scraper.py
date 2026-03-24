"""
Free Web Scraper - No API keys, no external search libraries.

Uses only httpx (already installed) + beautifulsoup4 to:
1. Search via DuckDuckGo HTML (no library needed)
2. Visit result pages and extract text content
3. Return clean text for LLM to structure

Usage:
    from scripts.web_scraper import WebScraper
    scraper = WebScraper()
    text = scraper.search_and_scrape("기생충 영화 감독 출연진")
"""

import re
import time
import logging

import httpx

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
}


class WebScraper:
    """Simple web scraper using only httpx + bs4. No API keys needed."""

    def __init__(self):
        if not HAS_BS4:
            raise ImportError(
                "beautifulsoup4가 필요합니다: pip install beautifulsoup4"
            )
        self.client = httpx.Client(
            headers=HEADERS,
            timeout=15.0,
            follow_redirects=True,
        )

    def search_and_scrape(self, query: str, max_results: int = 3) -> str:
        """
        Search the web and return combined text from top results.

        1. DuckDuckGo HTML search
        2. Visit top result pages
        3. Extract and return clean text
        """
        logger.info("웹 검색: %s", query)

        # Get search result URLs
        urls = self._search_duckduckgo(query, max_results)

        if not urls:
            # Fallback: try direct Wikipedia search
            logger.info("DuckDuckGo 결과 없음, Wikipedia 검색 시도...")
            wiki_text = self._search_wikipedia(query)
            if wiki_text:
                return wiki_text
            return ""

        # Scrape each URL
        all_text = []
        for url in urls[:max_results]:
            text = self._scrape_page(url)
            if text:
                all_text.append(text)
            time.sleep(1)  # Be polite

        combined = "\n\n---\n\n".join(all_text)

        # Limit total text to avoid overwhelming the LLM
        if len(combined) > 3000:
            combined = combined[:3000] + "..."

        return combined

    def search_only(self, query: str, max_results: int = 5) -> list[dict]:
        """Return search results without scraping pages."""
        return self._search_duckduckgo_with_snippets(query, max_results)

    # ── DuckDuckGo HTML Search ────────────────────────────────────

    def _search_duckduckgo(self, query: str, max_results: int = 5) -> list[str]:
        """Search DuckDuckGo HTML version and extract result URLs."""
        try:
            resp = self.client.get(
                "https://html.duckduckgo.com/html/",
                params={"q": query},
            )
            resp.raise_for_status()

            soup = BeautifulSoup(resp.text, "html.parser")
            urls = []

            for link in soup.select("a.result__a"):
                href = link.get("href", "")
                # DuckDuckGo wraps URLs in redirect
                actual_url = self._extract_url(href)
                if actual_url and self._is_valid_url(actual_url):
                    urls.append(actual_url)
                    if len(urls) >= max_results:
                        break

            logger.info("검색 결과 %d개 URL 발견", len(urls))
            return urls

        except Exception as e:
            logger.warning("DuckDuckGo 검색 실패: %s", e)
            return []

    def _search_duckduckgo_with_snippets(self, query: str, max_results: int = 5) -> list[dict]:
        """Search DuckDuckGo and return titles + snippets."""
        try:
            resp = self.client.get(
                "https://html.duckduckgo.com/html/",
                params={"q": query},
            )
            resp.raise_for_status()

            soup = BeautifulSoup(resp.text, "html.parser")
            results = []

            for result_div in soup.select("div.result"):
                title_el = result_div.select_one("a.result__a")
                snippet_el = result_div.select_one("a.result__snippet")

                if title_el:
                    title = title_el.get_text(strip=True)
                    snippet = snippet_el.get_text(strip=True) if snippet_el else ""
                    href = self._extract_url(title_el.get("href", ""))

                    results.append({
                        "title": title,
                        "snippet": snippet,
                        "url": href,
                    })

                    if len(results) >= max_results:
                        break

            return results

        except Exception as e:
            logger.warning("DuckDuckGo 검색 실패: %s", e)
            return []

    # ── Wikipedia Search (Fallback) ───────────────────────────────

    def _search_wikipedia(self, query: str) -> str:
        """Search Korean Wikipedia as a fallback."""
        try:
            # Use Wikipedia API to search
            resp = self.client.get(
                "https://ko.wikipedia.org/w/api.php",
                params={
                    "action": "query",
                    "list": "search",
                    "srsearch": query,
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

            # Get the page content
            page_title = results[0]["title"]
            return self._get_wikipedia_page(page_title)

        except Exception as e:
            logger.warning("Wikipedia 검색 실패: %s", e)
            return ""

    def _get_wikipedia_page(self, title: str) -> str:
        """Get Wikipedia page content as plain text."""
        try:
            resp = self.client.get(
                "https://ko.wikipedia.org/w/api.php",
                params={
                    "action": "query",
                    "titles": title,
                    "prop": "extracts",
                    "exintro": False,
                    "explaintext": True,
                    "format": "json",
                    "utf8": 1,
                },
            )
            resp.raise_for_status()
            data = resp.json()

            pages = data.get("query", {}).get("pages", {})
            for page_id, page in pages.items():
                text = page.get("extract", "")
                if text:
                    # Limit length
                    if len(text) > 2000:
                        text = text[:2000] + "..."
                    return f"[Wikipedia: {title}]\n{text}"

        except Exception as e:
            logger.warning("Wikipedia 페이지 가져오기 실패: %s", e)

        return ""

    # ── Page Scraper ──────────────────────────────────────────────

    def _scrape_page(self, url: str) -> str:
        """Scrape a web page and extract clean text."""
        try:
            resp = self.client.get(url)
            resp.raise_for_status()

            # Only process HTML
            content_type = resp.headers.get("content-type", "")
            if "text/html" not in content_type:
                return ""

            soup = BeautifulSoup(resp.text, "html.parser")

            # Remove unwanted elements
            for tag in soup.select("script, style, nav, footer, header, aside, .ad, .ads, .advertisement, .sidebar, .menu, .cookie"):
                tag.decompose()

            # Try to find main content
            main_content = (
                soup.select_one("article")
                or soup.select_one("main")
                or soup.select_one(".content")
                or soup.select_one("#content")
                or soup.select_one(".post-content")
                or soup.select_one(".entry-content")
                or soup.body
            )

            if not main_content:
                return ""

            # Extract text
            text = main_content.get_text(separator="\n", strip=True)

            # Clean up
            text = self._clean_text(text)

            # Limit length per page
            if len(text) > 1500:
                text = text[:1500] + "..."

            if len(text) < 50:
                return ""

            logger.info("  페이지 스크랩 완료: %s (%d자)", url[:50], len(text))
            return f"[출처: {url}]\n{text}"

        except Exception as e:
            logger.warning("  페이지 스크랩 실패 %s: %s", url[:50], e)
            return ""

    # ── Helpers ────────────────────────────────────────────────────

    def _extract_url(self, href: str) -> str:
        """Extract actual URL from DuckDuckGo redirect link."""
        if not href:
            return ""
        # DuckDuckGo uses //duckduckgo.com/l/?uddg=ENCODED_URL&...
        if "uddg=" in href:
            match = re.search(r'uddg=([^&]+)', href)
            if match:
                from urllib.parse import unquote
                return unquote(match.group(1))
        if href.startswith("http"):
            return href
        return ""

    def _is_valid_url(self, url: str) -> bool:
        """Filter out unwanted URLs."""
        skip_domains = [
            "youtube.com", "youtu.be",
            "facebook.com", "instagram.com", "twitter.com",
            "tiktok.com", "pinterest.com",
            "play.google.com", "apps.apple.com",
        ]
        for domain in skip_domains:
            if domain in url:
                return False
        return url.startswith("http")

    def _clean_text(self, text: str) -> str:
        """Clean extracted text."""
        # Remove excessive whitespace
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = re.sub(r' {2,}', ' ', text)
        # Remove common junk patterns
        text = re.sub(r'쿠키.*?동의', '', text)
        text = re.sub(r'광고.*?닫기', '', text)
        return text.strip()

    def close(self):
        self.client.close()
