"""Tests for crawler utility functions — no network calls."""

import json
import tempfile
from pathlib import Path

from src.crawler import (
    deduplicate_urls,
    extract_links_from_html,
    is_rate_limit_error,
)


class TestIsRateLimitError:
    def test_429_detected(self):
        assert is_rate_limit_error("HTTP 429 Too Many Requests")

    def test_rate_limit_text(self):
        assert is_rate_limit_error("rate limit exceeded")

    def test_quota_exhausted(self):
        assert is_rate_limit_error("quota exhausted for this month")

    def test_payment_required(self):
        assert is_rate_limit_error("402 Payment Required")

    def test_normal_error_not_detected(self):
        assert not is_rate_limit_error("404 Not Found")

    def test_empty_string(self):
        assert not is_rate_limit_error("")


class TestExtractLinksFromHtml:
    def test_absolute_links(self):
        html = '<a href="https://example.com/page">Link</a>'
        links = extract_links_from_html(html, "https://example.com")
        assert "https://example.com/page" in links

    def test_relative_links_resolved(self):
        html = '<a href="/products/wing">Wing</a>'
        links = extract_links_from_html(html, "https://example.com")
        assert "https://example.com/products/wing" in links

    def test_fragment_links_excluded(self):
        html = '<a href="#section">Jump</a>'
        links = extract_links_from_html(html, "https://example.com")
        assert len(links) == 0

    def test_multiple_links(self):
        html = """
        <a href="https://example.com/a">A</a>
        <a href="/b">B</a>
        <a href="https://other.com/c">C</a>
        """
        links = extract_links_from_html(html, "https://example.com")
        assert len(links) == 3


class TestDeduplicateUrls:
    def test_removes_duplicates(self):
        url_groups = {
            "current": ["https://example.com/a", "https://example.com/a", "https://example.com/b"],
        }
        source_configs = {"current": {"is_current": True}}
        all_urls, metadata = deduplicate_urls(url_groups, source_configs)
        assert len(all_urls) == len(set(all_urls))
        assert len(all_urls) == 2

    def test_preserves_is_current_upgrade(self):
        url_groups = {
            "archive": ["https://example.com/a"],
            "current": ["https://example.com/a"],
        }
        source_configs = {
            "archive": {"is_current": False},
            "current": {"is_current": True},
        }
        all_urls, metadata = deduplicate_urls(url_groups, source_configs)
        normalised = "https://example.com/a"
        assert metadata[normalised]["is_current"] is True


class TestPartialSaveLoad:
    def test_roundtrip(self):
        from src.crawler import Crawler

        data = [{"url": "https://example.com/wing", "model_name": "Test"}]
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "partial.json"
            Crawler.save_partial(data, path)
            loaded = Crawler.load_partial(path)
            assert loaded == data

    def test_load_missing_returns_empty(self):
        from src.crawler import Crawler

        loaded = Crawler.load_partial(Path("/nonexistent/path.json"))
        assert loaded == []


class TestUrlCacheKeyed:
    def test_roundtrip(self):
        from src.crawler import Crawler

        urls = ["https://example.com/a", "https://example.com/b"]
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "urls.json"
            Crawler.save_url_cache_keyed(path, "test", urls)
            loaded = Crawler.load_url_cache_keyed(path, "test")
            assert loaded == urls

    def test_missing_key_returns_none(self):
        from src.crawler import Crawler

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "urls.json"
            Crawler.save_url_cache_keyed(path, "a", [])
            result = Crawler.load_url_cache_keyed(path, "missing")
            assert result is None
