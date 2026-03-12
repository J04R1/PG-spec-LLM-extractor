# ITERATION 02 — CRAWLER MODULE

**Date:** March 12, 2026
**Status:** Complete
**Folder:** `documentation/architecture/`
**Previous:** `ITERATION_01_PROJECT_FOUNDATION.md`

---

## Objective

Port the Crawl4AI-based crawling from the POC monolith (`extract.py`) into the modular `src/crawler.py`, adding `robots.txt` enforcement, cross-source URL deduplication, and atomic crash recovery. Wire into the pipeline CLI.

---

## What Was Done

### Crawler Module (`src/crawler.py`)

Fully implemented with 7 components:

#### 1. Page Rendering — `Crawler.render_page()`
- Crawl4AI `AsyncWebCrawler` with `BrowserConfig(headless=True, java_script_enabled=True)`
- `CrawlerRunConfig` with `CacheMode.BYPASS` for fresh renders
- Returns markdown content or `None` on failure
- Enforces `robots.txt` and rate limiting before each request

#### 2. URL Discovery — `Crawler.discover_urls()`
- Renders listing pages from manufacturer YAML config
- Extracts links from rendered HTML via `_LinkExtractor` (stdlib `HTMLParser`)
- Filters by `url_pattern` and `url_excludes` from config
- Validates slug segments (rejects bare digits, nested paths)
- Deduplicates preserving order
- Caches results keyed by `source_key:listing_url`

#### 3. HTML Link Extraction — `extract_links_from_html()`
- Stdlib `HTMLParser`-based link extractor (no external dependency)
- Converts relative `/paths` to absolute URLs via `urljoin()`
- Ignores fragment-only and non-HTTP hrefs

#### 4. robots.txt Enforcement — `RobotsChecker`
- Fetches `robots.txt` via httpx (not urllib — fixes silent failures with TLS)
- Caches parsers per domain (one fetch per domain per session)
- Uses `RobotFileParser.parse()` with httpx-fetched content
- Permissive on failure: 404 or network error → allow all
- Checks with honest `USER_AGENT` string

#### 5. Cross-Source URL Deduplication — `deduplicate_urls()`
- Merges URLs from multiple source groups (e.g. previous + current gliders)
- Preserves discovery order
- Upgrades metadata: if URL appears in both "previous" and "current", prefers "current"
- Returns `(all_urls, url_metadata)` tuple

#### 6. Atomic Partial Save — `Crawler.save_partial()`
- Writes to `.tmp` file first, then `os.replace()` for atomic swap
- Prevents data corruption on crash mid-write
- Auto-creates parent directories

#### 7. Rate Limit Detection — `is_rate_limit_error()`
- Detects 429, 402, quota exhaustion, resource exhausted patterns
- Case-insensitive matching against known indicator strings

### Pipeline Integration (`src/pipeline.py`)

- `--map-only` now runs full URL discovery via `Crawler.discover_urls()`
- `--refresh-urls` clears URL cache before discovery
- `_discover_all_urls()` helper wires config → crawler → deduplication
- `_run_single_url()` now renders pages via Crawl4AI (extraction deferred to Iteration 3)
- Full pipeline path discovers URLs (extraction deferred to Iteration 3)

### Bug Fix: robots.txt via httpx

Python's `RobotFileParser.read()` uses urllib internally, which silently fails on some servers (TLS/redirect issues) and defaults to disallow-all. Fixed by:
1. Fetching robots.txt with httpx (already in our dependency stack)
2. Parsing with `rp.parse(lines)` instead of `rp.read()`
3. Treating non-200 responses as "no robots.txt" (allow all)

---

## Verification Results

| Test | Result |
|------|--------|
| `Crawler` imports and instantiation | ✅ |
| `is_rate_limit_error()` — 429, RESOURCE_EXHAUSTED, clean strings | ✅ |
| `extract_links_from_html()` — absolute + relative links | ✅ |
| `deduplicate_urls()` — 3 unique from 5, `is_current` upgrade | ✅ |
| `save_partial()` / `load_partial()` — atomic roundtrip | ✅ |
| `save_url_cache_keyed()` / `load_url_cache_keyed()` — keyed roundtrip | ✅ |
| `RobotsChecker` — flyozone.com `Allow: /` correctly parsed | ✅ |
| `--map-only` — discovers **115 Ozone product URLs** | ✅ |
| Cross-source dedup — 21 duplicates upgraded to `[current]` | ✅ |
| CLI `--help` — all commands and options display correctly | ✅ |

**Master plan verification criteria #2:** `--map-only discovers ~115 Ozone URLs` → **115 discovered** ✅

---

## Files Created/Modified

| File | Action |
|------|--------|
| `src/crawler.py` | Fully implemented (was stub) |
| `src/pipeline.py` | Wired crawler into `--map-only`, `--url`, and full pipeline path |
| `documentation/architecture/ITERATION_02_CRAWLER_MODULE.md` | Created |

---

## What's Next — Iteration 3: LLM Adapter & Ollama Integration

- Wire `OllamaAdapter` + `extract_specs()` into the pipeline for `--url` single-page extraction
- Build extraction prompt from `prompts/extraction-prompt-kit.md` + YAML config hints
- Test with single URL mode: `--url https://flyozone.com/.../rush-6`
- Validate extracted JSON against `ExtractionResult` Pydantic model
