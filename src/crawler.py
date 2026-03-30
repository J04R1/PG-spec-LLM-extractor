"""
Crawl4AI wrapper — page rendering and URL discovery.

Handles:
  - Rendering JS-heavy pages to markdown via Crawl4AI + Playwright
  - Discovering product URLs from manufacturer listing pages
  - URL caching and crash recovery (atomic partial saves)
  - Rate limiting, robots.txt enforcement, honest User-Agent
  - Cross-source URL deduplication
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import random
import time
from html.parser import HTMLParser
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx

logger = logging.getLogger(__name__)

USER_AGENT = "PG-Spec/1.0 ()"

_RATE_LIMIT_INDICATORS = [
    "429", "rate limit", "rate_limit", "quota", "exhausted",
    "too many requests", "resource_exhausted", "402", "payment required",
]


def is_rate_limit_error(error_str: str) -> bool:
    """Detect rate-limit / quota / credit exhaustion errors."""
    lower = error_str.lower()
    return any(ind in lower for ind in _RATE_LIMIT_INDICATORS)


# ── HTML link extraction ───────────────────────────────────────────────────


class _LinkExtractor(HTMLParser):
    """Extracts all href values from <a> tags in rendered HTML."""

    def __init__(self):
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            for name, value in attrs:
                if name == "href" and value:
                    self.links.append(value)


def extract_links_from_html(html: str, base_url: str) -> list[str]:
    """Parse rendered HTML and return all absolute link URLs."""
    parser = _LinkExtractor()
    parser.feed(html)
    absolute = []
    for href in parser.links:
        if href.startswith(("http://", "https://")):
            absolute.append(href)
        elif href.startswith("/"):
            absolute.append(urljoin(base_url, href))
    return absolute


# ── robots.txt enforcement ─────────────────────────────────────────────────


class RobotsChecker:
    """Fetches and caches robots.txt per domain, checks URL eligibility."""

    def __init__(self, user_agent: str = USER_AGENT):
        self.user_agent = user_agent
        self._parsers: dict[str, RobotFileParser] = {}

    def _get_parser(self, url: str) -> RobotFileParser:
        """Fetch and cache robots.txt for the domain of the given URL."""
        parsed = urlparse(url)
        domain = f"{parsed.scheme}://{parsed.netloc}"

        if domain in self._parsers:
            return self._parsers[domain]

        robots_url = f"{domain}/robots.txt"
        rp = RobotFileParser()
        rp.set_url(robots_url)
        try:
            # Use httpx instead of rp.read() — urllib's read() silently fails
            # on some servers (TLS issues, redirects) and defaults to disallow-all
            resp = httpx.get(robots_url, timeout=10, follow_redirects=True)
            if resp.status_code == 200:
                lines = resp.text.splitlines()
                rp.parse(lines)
                logger.info("Loaded robots.txt from %s", robots_url)
            else:
                # Non-200 (404, 5xx) → allow all (no robots.txt = no restrictions)
                rp.allow_all = True
                logger.info("No robots.txt at %s (HTTP %d) — allowing all", robots_url, resp.status_code)
        except Exception:
            # Network error → allow all (be permissive on transient failures)
            rp.allow_all = True
            logger.warning("Could not fetch robots.txt from %s — allowing all", robots_url)

        self._parsers[domain] = rp
        return rp

    def is_allowed(self, url: str) -> bool:
        """Check if the URL is allowed by robots.txt."""
        rp = self._get_parser(url)
        return rp.can_fetch(self.user_agent, url)


# ── Cross-source URL deduplication ─────────────────────────────────────────


def deduplicate_urls(
    url_groups: dict[str, list[str]],
    source_configs: dict[str, dict],
) -> tuple[list[str], dict[str, dict]]:
    """Deduplicate URLs across multiple sources, preferring 'current' metadata.

    Args:
        url_groups: {source_key: [urls]} from each discovery run.
        source_configs: {source_key: source_config_dict} from YAML.

    Returns:
        (all_urls, url_metadata) where url_metadata maps normalized URL
        to {"is_current": bool, "source_key": str}.
    """
    all_urls: list[str] = []
    url_metadata: dict[str, dict] = {}
    seen: set[str] = set()

    for source_key, urls in url_groups.items():
        is_current = source_configs[source_key].get("is_current", False)

        new_count = 0
        dupe_count = 0
        for url in urls:
            normalised = url.rstrip("/")
            if normalised not in seen:
                seen.add(normalised)
                all_urls.append(normalised)
                url_metadata[normalised] = {
                    "is_current": is_current,
                    "source_key": source_key,
                }
                new_count += 1
            else:
                # Upgrade to is_current if this source is current
                if is_current and not url_metadata[normalised]["is_current"]:
                    url_metadata[normalised]["is_current"] = True
                    url_metadata[normalised]["source_key"] = source_key
                dupe_count += 1

        logger.info(
            "Source '%s': %d new URLs, %d duplicates", source_key, new_count, dupe_count
        )

    return all_urls, url_metadata


# ── Crawler ────────────────────────────────────────────────────────────────


# Default markdown cache directory (relative to project root)
_DEFAULT_MD_CACHE_DIR = Path("output/md_cache")


class Crawler:
    """Crawl4AI-based page renderer and URL discovery engine.

    Page markdown is cached on disk by default so each URL is only
    rendered once.  Pass ``force=True`` to ``render_page()`` to bypass
    the cache and fetch a fresh copy.
    """

    def __init__(
        self,
        rate_limit_ms: int = 1500,
        jitter_ms: int = 1000,
        user_agent: str = USER_AGENT,
        md_cache_dir: Optional[Path] = _DEFAULT_MD_CACHE_DIR,
    ):
        self.rate_limit_ms = rate_limit_ms
        self.jitter_ms = jitter_ms
        self.user_agent = user_agent
        self._last_request_time: float = 0
        self._robots = RobotsChecker(user_agent=user_agent)
        self._md_cache_dir: Optional[Path] = md_cache_dir
        if self._md_cache_dir:
            self._md_cache_dir.mkdir(parents=True, exist_ok=True)

    # ── Markdown cache helpers ────────────────────────────────────────────

    def _cache_path(self, url: str) -> Optional[Path]:
        """Return the cache file path for a URL, or None if caching is disabled."""
        if not self._md_cache_dir:
            return None
        key = hashlib.sha256(url.encode()).hexdigest()
        return self._md_cache_dir / f"{key}.md"

    def _cache_read(self, url: str) -> Optional[str]:
        """Return cached markdown for url, or None if not cached."""
        path = self._cache_path(url)
        if path and path.exists():
            logger.debug("Cache hit: %s", url)
            return path.read_text(encoding="utf-8")
        return None

    def _cache_write(self, url: str, markdown: str) -> None:
        """Write markdown to the cache for url."""
        path = self._cache_path(url)
        if path:
            path.write_text(markdown, encoding="utf-8")
            logger.debug("Cached: %s → %s", url, path.name)

    def cache_invalidate(self, url: str) -> bool:
        """Delete the cached markdown for a URL.  Returns True if a file was removed."""
        path = self._cache_path(url)
        if path and path.exists():
            path.unlink()
            logger.info("Cache invalidated: %s", url)
            return True
        return False

    async def render_page(self, url: str, force: bool = False) -> Optional[str]:
        """Fetch and render a URL to markdown via Crawl4AI.

        Checks the on-disk markdown cache first.  If a cached copy exists and
        ``force`` is False, it is returned immediately without any network
        request.  On a cache miss (or when ``force=True``) the page is fetched,
        the result is written to cache, and the markdown is returned.

        Args:
            url:   Page URL to render.
            force: Bypass cache and always re-crawl.  Overwrites any existing
                   cached copy.

        Returns:
            Markdown content of the page, or None on failure.
        """
        from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode

        if not force:
            cached = self._cache_read(url)
            if cached is not None:
                return cached

        if not self._robots.is_allowed(url):
            logger.warning("Blocked by robots.txt: %s", url)
            return None

        self._wait_politely()

        browser_cfg = BrowserConfig(headless=True, java_script_enabled=True)
        run_cfg = CrawlerRunConfig(cache_mode=CacheMode.BYPASS)

        async with AsyncWebCrawler(config=browser_cfg) as crawler:
            result = await crawler.arun(url=url, config=run_cfg)

        if not result.success:
            logger.error("Render failed for %s: %s", url, result.error_message)
            return None

        self._cache_write(url, result.markdown)
        return result.markdown

    async def discover_urls(
        self,
        source_key: str,
        source_config: dict,
        cache_path: Optional[Path] = None,
    ) -> list[str]:
        """Discover product URLs from a manufacturer listing page.

        Renders the listing page, extracts links, filters by url_pattern
        and url_excludes from config. Caches results so re-runs never
        re-render the listing page.

        Args:
            source_key: Key name from the sources dict (e.g. 'current_gliders').
            source_config: A single source entry from the manufacturer YAML.
            cache_path: Optional path to the URL cache JSON file.

        Returns:
            List of discovered product page URLs.
        """
        from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode

        listing_url = source_config["listing_url"]
        url_pattern = source_config.get("url_pattern", "")
        url_excludes = source_config.get("url_excludes", [])
        cache_key = f"{source_key}:{listing_url}"

        # Check URL cache first
        if cache_path:
            cached = self.load_url_cache_keyed(cache_path, cache_key)
            if cached is not None:
                logger.info("Using cached URLs (%d pages) for %s", len(cached), source_key)
                return cached

        if not self._robots.is_allowed(listing_url):
            logger.warning("Blocked by robots.txt: %s", listing_url)
            return []

        self._wait_politely()
        logger.info("Rendering listing page: %s", listing_url)

        browser_cfg = BrowserConfig(headless=True, java_script_enabled=True)
        run_cfg = CrawlerRunConfig(cache_mode=CacheMode.BYPASS)

        async with AsyncWebCrawler(config=browser_cfg) as crawler:
            result = await crawler.arun(url=listing_url, config=run_cfg)

        if not result.success:
            logger.error("Failed to render listing page: %s", result.error_message)
            return []

        # Extract all links from the rendered HTML
        all_links = extract_links_from_html(result.html, listing_url)
        logger.info("Raw links from listing page: %d", len(all_links))

        # Filter to product detail pages
        product_urls = []
        for url in all_links:
            if url_pattern and url_pattern not in url:
                continue
            if any(excl in url for excl in url_excludes):
                continue
            # Must have a slug segment after the url_pattern
            if url_pattern:
                slug_part = url.split(url_pattern)[-1].strip("/")
                if not slug_part or "/" in slug_part:
                    continue
                if slug_part.isdigit():
                    continue
            product_urls.append(url)

        # Deduplicate preserving order
        seen: set[str] = set()
        unique_urls: list[str] = []
        for url in product_urls:
            normalised = url.rstrip("/")
            if normalised not in seen:
                seen.add(normalised)
                unique_urls.append(normalised)

        logger.info("Found %d product pages for %s", len(unique_urls), source_key)

        # Cache the results
        if cache_path and unique_urls:
            self.save_url_cache_keyed(cache_path, cache_key, unique_urls)

        return unique_urls

    def _wait_politely(self) -> None:
        """Enforce rate limiting with random jitter."""
        now = time.monotonic()
        elapsed_ms = (now - self._last_request_time) * 1000
        delay_ms = self.rate_limit_ms + random.randint(0, self.jitter_ms)
        if elapsed_ms < delay_ms:
            sleep_s = (delay_ms - elapsed_ms) / 1000
            time.sleep(sleep_s)
        self._last_request_time = time.monotonic()

    # ── URL cache (keyed by source:listing_url) ────────────────────────────

    @staticmethod
    def load_url_cache_keyed(cache_path: Path, cache_key: str) -> Optional[list[str]]:
        """Load cached URLs for a specific source key, or None if not cached."""
        if not cache_path.exists():
            return None
        with open(cache_path, "r", encoding="utf-8") as f:
            cache = json.load(f)
        return cache.get(cache_key)

    @staticmethod
    def save_url_cache_keyed(cache_path: Path, cache_key: str, urls: list[str]) -> None:
        """Save discovered URLs under a cache key."""
        cache: dict = {}
        if cache_path.exists():
            with open(cache_path, "r", encoding="utf-8") as f:
                cache = json.load(f)
        cache[cache_key] = urls
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2)

    # ── Simple URL cache (flat list) ───────────────────────────────────────

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
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(urls, f, indent=2)

    # ── Partial save / load (atomic writes) ────────────────────────────────

    @staticmethod
    def save_partial(data: list[dict], partial_path: Path) -> None:
        """Atomically save partial extraction results for crash recovery."""
        partial_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = partial_path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)
        os.replace(tmp, partial_path)

    @staticmethod
    def load_partial(partial_path: Path) -> list[dict]:
        """Load partial extraction results from a previous run."""
        if partial_path.exists():
            with open(partial_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return []

    # ── Markdown cache ─────────────────────────────────────────────────────

    @staticmethod
    def _md_cache_key(url: str) -> str:
        """Create a filesystem-safe cache key from a URL."""
        import hashlib
        return hashlib.sha256(url.encode()).hexdigest()

    @staticmethod
    def save_markdown_cache(url: str, markdown: str, cache_dir: Path) -> None:
        """Save rendered markdown to a file-based cache."""
        cache_dir.mkdir(parents=True, exist_ok=True)
        key = Crawler._md_cache_key(url)
        cache_file = cache_dir / f"{key}.md"
        with open(cache_file, "w", encoding="utf-8") as f:
            f.write(markdown)
        logger.debug("Cached markdown for %s → %s", url, cache_file)

    @staticmethod
    def load_markdown_cache(url: str, cache_dir: Path) -> Optional[str]:
        """Load cached markdown if available."""
        key = Crawler._md_cache_key(url)
        cache_file = cache_dir / f"{key}.md"
        if cache_file.exists():
            with open(cache_file, "r", encoding="utf-8") as f:
                content = f.read()
            logger.info("Using cached markdown for %s (%d chars)", url, len(content))
            return content
        return None
