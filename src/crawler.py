"""
Crawl4AI wrapper — page rendering and URL discovery.

Handles:
  - Rendering JS-heavy pages to markdown via Crawl4AI + Playwright
  - Discovering product URLs from manufacturer listing pages
  - URL caching and crash recovery (partial saves)
  - Rate limiting, robots.txt enforcement, honest User-Agent

Implementation will be completed in Iteration 2.
"""

from __future__ import annotations

import json
import logging
import random
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

USER_AGENT = "OpenPG-SpecExtractor/1.0 (+https://github.com/open-paraglider)"


class Crawler:
    """Crawl4AI-based page renderer and URL discovery engine."""

    def __init__(
        self,
        rate_limit_ms: int = 1500,
        jitter_ms: int = 1000,
        user_agent: str = USER_AGENT,
    ):
        self.rate_limit_ms = rate_limit_ms
        self.jitter_ms = jitter_ms
        self.user_agent = user_agent
        self._last_request_time: float = 0

    async def render_page(self, url: str) -> Optional[str]:
        """Fetch and render a URL to markdown via Crawl4AI.

        Returns:
            Markdown content of the page, or None on failure.
        """
        # TODO: Iteration 2 — implement with Crawl4AI AsyncWebCrawler
        raise NotImplementedError("Crawler.render_page — implement in Iteration 2")

    async def discover_urls(self, source_config: dict) -> list[str]:
        """Discover product URLs from a manufacturer listing page.

        Args:
            source_config: A single source entry from the manufacturer YAML.

        Returns:
            List of discovered product page URLs.
        """
        # TODO: Iteration 2 — port from extract.py map_product_urls()
        raise NotImplementedError("Crawler.discover_urls — implement in Iteration 2")

    def _wait_politely(self) -> None:
        """Enforce rate limiting with random jitter."""
        now = time.monotonic()
        elapsed_ms = (now - self._last_request_time) * 1000
        delay_ms = self.rate_limit_ms + random.randint(0, self.jitter_ms)
        if elapsed_ms < delay_ms:
            sleep_s = (delay_ms - elapsed_ms) / 1000
            time.sleep(sleep_s)
        self._last_request_time = time.monotonic()

    # ── URL cache (crash recovery) ─────────────────────────────────────────

    @staticmethod
    def load_url_cache(cache_path: Path) -> list[str]:
        """Load cached URLs from a previous discovery run."""
        if cache_path.exists():
            with open(cache_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return []

    @staticmethod
    def save_url_cache(urls: list[str], cache_path: Path) -> None:
        """Save discovered URLs to cache."""
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(urls, f, indent=2)

    # ── Partial save / load ────────────────────────────────────────────────

    @staticmethod
    def save_partial(data: list[dict], partial_path: Path) -> None:
        """Save partial extraction results for crash recovery."""
        with open(partial_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    @staticmethod
    def load_partial(partial_path: Path) -> list[dict]:
        """Load partial extraction results from a previous run."""
        if partial_path.exists():
            with open(partial_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return []
