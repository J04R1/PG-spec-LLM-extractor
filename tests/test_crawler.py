"""Quick validation of crawler module — delete after testing."""
from src.crawler import (
    Crawler, RobotsChecker, extract_links_from_html,
    deduplicate_urls, is_rate_limit_error,
)

# 1. Rate limit detection
assert is_rate_limit_error("Error 429 too many requests")
assert is_rate_limit_error("RESOURCE_EXHAUSTED")
assert not is_rate_limit_error("Connection timeout")
print("1. Rate limit detection OK")

# 2. Link extraction
html = '<html><body><a href="/foo">Link</a><a href="https://example.com/bar">Bar</a></body></html>'
links = extract_links_from_html(html, "https://example.com")
assert set(links) == {"https://example.com/bar", "https://example.com/foo"}
print(f"2. Link extraction OK: {links}")

# 3. Deduplication
groups = {
    "previous": ["https://example.com/a", "https://example.com/b"],
    "current": ["https://example.com/b", "https://example.com/c"],
}
configs = {
    "previous": {"is_current": False},
    "current": {"is_current": True},
}
urls, meta = deduplicate_urls(groups, configs)
assert len(urls) == 3
assert meta["https://example.com/b"]["is_current"] is True
print(f"3. Deduplication OK: {len(urls)} unique, 'b' upgraded to current")

# 4. Crawler instantiation
c = Crawler()
assert c.rate_limit_ms == 1500
assert c.user_agent == "OpenPG-SpecExtractor/1.0 (+https://github.com/open-paraglider)"
print("4. Crawler instantiation OK")

# 5. Partial save/load roundtrip
from pathlib import Path
import tempfile, os
with tempfile.TemporaryDirectory() as tmpdir:
    p = Path(tmpdir) / "test.partial"
    data = [{"model_name": "Test", "sizes": []}]
    Crawler.save_partial(data, p)
    loaded = Crawler.load_partial(p)
    assert loaded == data
    print("5. Partial save/load OK (atomic)")

# 6. URL cache keyed roundtrip
with tempfile.TemporaryDirectory() as tmpdir:
    cache = Path(tmpdir) / "urls.json"
    Crawler.save_url_cache_keyed(cache, "src:url", ["https://a.com", "https://b.com"])
    result = Crawler.load_url_cache_keyed(cache, "src:url")
    assert result == ["https://a.com", "https://b.com"]
    assert Crawler.load_url_cache_keyed(cache, "other:url") is None
    print("6. URL cache keyed OK")

print("\nAll tests passed!")
