#!/usr/bin/env python3
"""
tools/spec-extractor/extract.py

Standalone CLI tool that extracts paraglider specifications from manufacturer
websites using Crawl4AI. Reads YAML config files per manufacturer and outputs
JSON + CSV in the enrichment format consumed by scripts/import_enrichment_csv.py.

Usage (from tools/spec-extractor/ with venv active):
    python extract.py --config config/manufacturers/ozone.yaml          # Full extraction
    python extract.py --config config/manufacturers/ozone.yaml --map-only     # URL discovery only
    python extract.py --config config/manufacturers/ozone.yaml --retry-failed  # Re-extract failures
    python extract.py --config config/manufacturers/ozone.yaml --convert-only  # JSON → CSV only
    python extract.py --url https://flyozone.com/.../rush-5       # Single URL test

Requirements (install in isolated venv):
    pip install crawl4ai pyyaml
    crawl4ai-setup

Environment:
    GEMINI_API_KEY (or whichever key the config specifies via api_key_env)
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import re
import sys
import time
from html.parser import HTMLParser
from typing import Optional
from urllib.parse import urljoin, urlparse

try:
    import yaml
except ImportError:
    print("ERROR: Missing dependency. Install with:")
    print("  pip install pyyaml")
    sys.exit(1)

TOOL_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(TOOL_DIR, "output")

# ───────────────────────────────────────────────────────────────────────────────
# CSV enrichment columns (must match scripts/import_enrichment_csv.py)
# ───────────────────────────────────────────────────────────────────────────────

CSV_COLUMNS = [
    "manufacturer_slug", "name", "year", "category", "target_use", "is_current",
    "cell_count", "line_material", "riser_config", "manufacturer_url", "description",
    "size_label", "flat_area_m2", "flat_span_m", "flat_aspect_ratio",
    "proj_area_m2", "proj_span_m", "proj_aspect_ratio",
    "wing_weight_kg", "ptv_min_kg", "ptv_max_kg",
    "speed_trim_kmh", "speed_max_kmh", "glide_ratio_best", "min_sink_ms",
    "cert_standard", "cert_classification", "cert_test_lab", "cert_test_date",
    "cert_report_url",
]


# ───────────────────────────────────────────────────────────────────────────────
# Error types
# ───────────────────────────────────────────────────────────────────────────────

class CreditExhaustedError(Exception):
    """Raised when the LLM provider returns a rate-limit or quota error."""
    pass


# ───────────────────────────────────────────────────────────────────────────────
# Config loading
# ───────────────────────────────────────────────────────────────────────────────

def load_config(config_path: str) -> dict:
    """Load and validate a manufacturer YAML config file."""
    if not os.path.exists(config_path):
        print(f"ERROR: Config file not found: {config_path}")
        sys.exit(1)

    with open(config_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    if not cfg.get("manufacturer", {}).get("slug"):
        print("ERROR: Config must define manufacturer.slug")
        sys.exit(1)

    if not cfg.get("sources") and not cfg.get("extraction"):
        print("ERROR: Config must define at least 'sources' or 'extraction'")
        sys.exit(1)

    return cfg


def get_output_paths(slug: str) -> dict:
    """Return the standard output file paths for a manufacturer slug."""
    return {
        "raw_json": os.path.join(OUTPUT_DIR, f"{slug}_raw.json"),
        "partial":  os.path.join(OUTPUT_DIR, f"{slug}_raw.json.partial"),
        "csv":      os.path.join(OUTPUT_DIR, f"{slug}_enrichment.csv"),
        "urls":     os.path.join(OUTPUT_DIR, f"{slug}_urls.json"),
    }


# ───────────────────────────────────────────────────────────────────────────────
# Partial save / load (crash recovery)
# ───────────────────────────────────────────────────────────────────────────────

def _save_partial(results: list[dict], partial_path: str):
    """Atomically save results to the .partial file after every extraction."""
    os.makedirs(os.path.dirname(partial_path), exist_ok=True)
    tmp = partial_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str)
    os.replace(tmp, partial_path)


def _load_partial(partial_path: str) -> list[dict]:
    """Load partial results from a previous interrupted run."""
    if os.path.exists(partial_path):
        with open(partial_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


# ───────────────────────────────────────────────────────────────────────────────
# URL cache
# ───────────────────────────────────────────────────────────────────────────────

def _load_url_cache(cache_path: str, cache_key: str):
    """Load cached URLs for a listing page, or None if not cached."""
    if not os.path.exists(cache_path):
        return None
    with open(cache_path, "r", encoding="utf-8") as f:
        cache = json.load(f)
    return cache.get(cache_key)


def _save_url_cache(cache_path: str, cache_key: str, urls: list[str]):
    """Save discovered URLs to the cache file."""
    cache = {}
    if os.path.exists(cache_path):
        with open(cache_path, "r", encoding="utf-8") as f:
            cache = json.load(f)
    cache[cache_key] = urls
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2)


# ───────────────────────────────────────────────────────────────────────────────
# HTML link extraction helper
# ───────────────────────────────────────────────────────────────────────────────

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


# ───────────────────────────────────────────────────────────────────────────────
# Step 1: URL discovery — render listing page and extract product URLs
# ───────────────────────────────────────────────────────────────────────────────

async def map_product_urls(source_key: str, source_cfg: dict,
                           paths: dict) -> list[str]:
    """
    Discover product detail page URLs by rendering the listing page.

    Caches results so re-runs never re-render the listing page.
    """
    from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode

    listing_url = source_cfg["listing_url"]
    url_pattern = source_cfg.get("url_pattern", "")
    url_excludes = source_cfg.get("url_excludes", [])
    cache_key = f"{source_key}:{listing_url}"

    # Check URL cache first
    cached = _load_url_cache(paths["urls"], cache_key)
    if cached is not None:
        print(f"  Using cached URLs ({len(cached)} pages) from {paths['urls']}")
        return cached

    print(f"  Rendering listing page: {listing_url}")

    browser_cfg = BrowserConfig(headless=True, java_script_enabled=True)
    run_cfg = CrawlerRunConfig(cache_mode=CacheMode.BYPASS)

    async with AsyncWebCrawler(config=browser_cfg) as crawler:
        result = await crawler.arun(url=listing_url, config=run_cfg)

    if not result.success:
        print(f"  ❌ Failed to render listing page: {result.error_message}")
        return []

    # Extract all links from the rendered HTML
    all_links = extract_links_from_html(result.html, listing_url)
    print(f"  Raw links from listing page: {len(all_links)}")

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
    seen = set()
    unique_urls = []
    for url in product_urls:
        normalised = url.rstrip("/")
        if normalised not in seen:
            seen.add(normalised)
            unique_urls.append(normalised)

    print(f"  Found {len(unique_urls)} product pages")

    if unique_urls:
        _save_url_cache(paths["urls"], cache_key, unique_urls)

    return unique_urls


# ───────────────────────────────────────────────────────────────────────────────
# Step 2: Spec extraction — render each product page and extract data
# ───────────────────────────────────────────────────────────────────────────────

def _is_rate_limit_error(error_str: str) -> bool:
    """Detect rate-limit / quota / credit exhaustion errors."""
    indicators = [
        "429", "rate limit", "rate_limit", "quota", "exhausted",
        "too many requests", "resource_exhausted", "RESOURCE_EXHAUSTED",
        "402", "payment required",
    ]
    lower = error_str.lower()
    return any(ind.lower() in lower for ind in indicators)


def _build_llm_strategy(extraction_cfg: dict):
    """Build an LLMExtractionStrategy from the config."""
    from crawl4ai.extraction_strategy import LLMExtractionStrategy
    from crawl4ai import LLMConfig

    llm_cfg = extraction_cfg.get("llm", {})
    provider = llm_cfg.get("provider", "gemini/gemini-2.0-flash")
    api_key_env = llm_cfg.get("api_key_env", "GEMINI_API_KEY")
    prompt = llm_cfg.get("prompt", "Extract the technical specifications from this page.")
    schema = llm_cfg.get("schema")

    api_key = os.environ.get(api_key_env)
    if not api_key:
        print(f"ERROR: {api_key_env} environment variable not set.")
        print(f"  export {api_key_env}='your-key-here'")
        sys.exit(1)

    llm_config = LLMConfig(provider=provider, api_token=api_key)

    kwargs = {
        "llm_config": llm_config,
        "instruction": prompt,
    }
    if schema:
        kwargs["schema"] = schema

    return LLMExtractionStrategy(**kwargs)


def _build_css_strategy(extraction_cfg: dict):
    """Build a JsonCssExtractionStrategy from the config."""
    from crawl4ai.extraction_strategy import JsonCssExtractionStrategy

    css_cfg = extraction_cfg.get("css", {})
    schema = css_cfg.get("schema")
    if not schema:
        print("ERROR: CSS extraction strategy requires a 'schema' in config.")
        sys.exit(1)

    return JsonCssExtractionStrategy(schema=schema)


async def extract_specs(urls: list[str], extraction_cfg: dict,
                        paths: dict) -> list[dict]:
    """
    Extract specs from each product page using Crawl4AI.

    Strategies:
    - 'llm': Crawl4AI renders page + LLM extracts via LLMExtractionStrategy
    - 'css': Crawl4AI renders page + CSS selectors extract via JsonCssExtractionStrategy
    - 'markdown': Crawl4AI renders page → markdown → deterministic table parser (free)

    Features:
    - Saves results to .partial file after every extraction (crash-safe)
    - Resumes from partial file on re-run (skips already-done URLs)
    - Aborts on rate-limit / credit exhaustion errors
    """
    from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode

    strategy_type = extraction_cfg.get("strategy", "llm")
    use_markdown_parser = (strategy_type == "markdown")

    strategy = None
    if not use_markdown_parser:
        if strategy_type == "llm":
            strategy = _build_llm_strategy(extraction_cfg)
        elif strategy_type == "css":
            strategy = _build_css_strategy(extraction_cfg)
        else:
            print(f"ERROR: Unknown extraction strategy: {strategy_type}")
            sys.exit(1)

    # Resume from partial results if available
    results = _load_partial(paths["partial"])
    if results:
        done_urls = {r.get("product_url", "").rstrip("/") for r in results}
        remaining = [u for u in urls if u.rstrip("/") not in done_urls]
        print(f"  Resuming: {len(results)} already done, {len(remaining)} remaining")
    else:
        remaining = list(urls)

    total = len(results) + len(remaining)

    if not remaining:
        print("  All URLs already extracted.")
        return results

    browser_cfg = BrowserConfig(headless=True, java_script_enabled=True)
    run_kwargs = {"cache_mode": CacheMode.BYPASS}
    if strategy:
        run_kwargs["extraction_strategy"] = strategy
    run_cfg = CrawlerRunConfig(**run_kwargs)

    async with AsyncWebCrawler(config=browser_cfg) as crawler:
        for i, url in enumerate(remaining, len(results) + 1):
            print(f"  [{i}/{total}] Extracting: {url}")
            try:
                result = await crawler.arun(url=url, config=run_cfg)

                if not result.success:
                    error_msg = result.error_message or "Unknown render error"
                    print(f"         ❌ Render failed: {error_msg}")

                    if _is_rate_limit_error(error_msg):
                        results.append({
                            "model_name": _slug_to_name(url),
                            "product_url": url,
                            "sizes": [],
                            "_error": error_msg,
                        })
                        _save_partial(results, paths["partial"])
                        raise CreditExhaustedError(error_msg)

                    results.append({
                        "model_name": _slug_to_name(url),
                        "product_url": url,
                        "sizes": [],
                        "_error": error_msg,
                    })
                    _save_partial(results, paths["partial"])
                    continue

                # Parse based on strategy
                if use_markdown_parser:
                    extracted = parse_specs_from_markdown(result.markdown or "", url)
                else:
                    extracted = _parse_extraction_result(result, url)

                if extracted and isinstance(extracted, dict) and "model_name" in extracted:
                    if not extracted.get("product_url"):
                        extracted["product_url"] = url
                    results.append(extracted)
                    sizes_count = len(extracted.get("sizes", []))
                    print(f"         ✅ {extracted['model_name']} — {sizes_count} sizes")
                else:
                    print(f"         ⚠️  No specs extracted (page may lack a specs table)")
                    results.append({
                        "model_name": _slug_to_name(url),
                        "product_url": url,
                        "sizes": [],
                        "_extraction_failed": True,
                        "_raw_response": str(extracted)[:500] if extracted else None,
                    })

            except CreditExhaustedError:
                raise
            except Exception as e:
                error_str = str(e)
                print(f"         ❌ Error: {error_str}")
                results.append({
                    "model_name": _slug_to_name(url),
                    "product_url": url,
                    "sizes": [],
                    "_error": error_str,
                })

                if _is_rate_limit_error(error_str):
                    print(f"\n  🛑 Rate limit / credit exhaustion detected — stopping.")
                    print(f"     {len(results)} results saved. Re-run to resume.")
                    _save_partial(results, paths["partial"])
                    raise CreditExhaustedError(error_str)

            # Save after every extraction
            _save_partial(results, paths["partial"])

            # Small delay between requests
            if i < total:
                time.sleep(1)

    # Clean up partial file on successful completion
    if os.path.exists(paths["partial"]):
        os.remove(paths["partial"])

    return results


def _parse_extraction_result(result, url: str) -> dict | None:
    """Parse the extraction result from Crawl4AI into a model dict."""
    content = result.extracted_content
    if not content:
        return None

    # extracted_content may be a JSON string or already parsed
    if isinstance(content, str):
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            return None
    else:
        parsed = content

    # Handle list of results — take the first valid one
    if isinstance(parsed, list):
        if len(parsed) == 0:
            return None
        parsed = parsed[0]

    if isinstance(parsed, dict) and "model_name" in parsed:
        return parsed

    return parsed if isinstance(parsed, dict) else None


def _slug_to_name(url: str) -> str:
    """Convert a URL's last path segment to a human-readable name."""
    slug = url.rstrip("/").split("/")[-1]
    return slug.replace("-", " ").title()


# ───────────────────────────────────────────────────────────────────────────────
# Markdown spec table parser (zero LLM cost — deterministic)
# ───────────────────────────────────────────────────────────────────────────────

# Row label → (field_name, is_per_size, needs_range_split)
_MD_ROW_MAP = {
    "number of cells":          ("cell_count",        False, False),
    "cells":                    ("cell_count",        False, False),
    "flat area":                ("flat_area_m2",      True,  False),
    "flat area (m2)":           ("flat_area_m2",      True,  False),
    "flat area (m^2)":          ("flat_area_m2",      True,  False),
    "projected area":           ("proj_area_m2",      True,  False),
    "projected area (m2)":      ("proj_area_m2",      True,  False),
    "flat span":                ("flat_span_m",       True,  False),
    "flat span (m)":            ("flat_span_m",       True,  False),
    "projected span":           ("proj_span_m",       True,  False),
    "projected span (m)":       ("proj_span_m",       True,  False),
    "flat aspect ratio":        ("flat_aspect_ratio",  True,  False),
    "projected aspect ratio":   ("proj_aspect_ratio",  True,  False),
    "glider weight":            ("wing_weight_kg",    True,  False),
    "glider weight (kg)":       ("wing_weight_kg",    True,  False),
    "wing weight":              ("wing_weight_kg",    True,  False),
    "wing weight (kg)":         ("wing_weight_kg",    True,  False),
    "weight (kg)":              ("wing_weight_kg",    True,  False),
    "certified weight range":   ("_ptv_range",        True,  True),
    "certified weight range (kg)": ("_ptv_range",     True,  True),
    "in-flight weight range":   ("_ptv_range",        True,  True),
    "in-flight weight range (kg)": ("_ptv_range",     True,  True),
    "in flight weight range":   ("_ptv_range",        True,  True),
    "weight range":             ("_ptv_range",        True,  True),
    "weight range (kg)":        ("_ptv_range",        True,  True),
    "en":                       ("certification",     True,  False),
    "en/ltf":                   ("certification",     True,  False),
    "ltf / en":                 ("certification",     True,  False),
    "certification":            ("certification",     True,  False),
    "ltf":                      ("certification",     True,  False),
    # Short label variants (older Ozone pages)
    "area flat":                ("flat_area_m2",      True,  False),
    "area proj.":               ("proj_area_m2",      True,  False),
    "area proj":                ("proj_area_m2",      True,  False),
    "span flat":                ("flat_span_m",       True,  False),
    "span proj.":               ("proj_span_m",       True,  False),
    "span proj":                ("proj_span_m",       True,  False),
    "ar flat":                  ("flat_aspect_ratio",  True,  False),
    "ar proj.":                 ("proj_aspect_ratio",  True,  False),
    "ar proj":                  ("proj_aspect_ratio",  True,  False),
    "root chord":               ("root_chord_m",      True,  False),
}

# Labels that indicate size headers rather than data rows
_SIZE_LABEL_HINTS = {"xs", "s", "ms", "sm", "m", "ml", "l", "xl", "xxl",
                     "xxs", "xxxl", "22", "23", "24", "25", "26", "27", "28",
                     "29", "30", "31"}


def _strip_md_formatting(s: str) -> str:
    """Strip markdown bold/italic markers from a string."""
    return re.sub(r'\*{1,3}|_{1,3}', '', s).strip()


def _parse_number(s: str) -> float | None:
    """Try to parse a numeric string, stripping units and handling EU decimals."""
    s = s.strip().rstrip("*")
    s = re.sub(r'\s*(kg|m2|m\^2|m|m²)\s*$', '', s, flags=re.IGNORECASE)
    # Handle European comma decimal: "18,9" → "18.9"
    # Only convert if there's exactly one comma and it looks like a decimal
    if "," in s and "." not in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _parse_weight_range(s: str) -> tuple[float | None, float | None]:
    """Parse '65-85' or '65 - 85' into (min, max)."""
    s = s.strip().rstrip("*")
    s = re.sub(r'\s*(kg)\s*$', '', s, flags=re.IGNORECASE)
    parts = re.split(r'\s*[-–—/]\s*', s)
    if len(parts) == 2:
        return _parse_number(parts[0]), _parse_number(parts[1])
    return None, None


def parse_specs_from_markdown(markdown: str, url: str) -> dict | None:
    """
    Parse the specification table from Crawl4AI's markdown output.

    Ozone (and many manufacturers) render specs as pipe-delimited tables:
        Number of Cells | 57 | 57 | 57
        Flat Area (m^2) | 21.41 | 23.86 | 25.16
        Certified Weight Range (kg) | 55-70 | 65-85 | 75-95
        EN | B | B | B

    This parser handles that format without any LLM.
    """
    lines = markdown.split("\n")

    # Find the "Specifications" header to narrow the search area
    spec_start = None
    for i, line in enumerate(lines):
        if re.match(r'^#+\s*specifications?\s*$', line.strip(), re.IGNORECASE):
            spec_start = i
            break

    if spec_start is None:
        # Try finding any line that looks like a spec row
        for i, line in enumerate(lines):
            low = line.strip().lower()
            if any(low.startswith(k) and "|" in line for k in _MD_ROW_MAP):
                spec_start = max(0, i - 5)
                break

    if spec_start is None:
        return None

    # Collect all pipe-delimited rows in the spec section
    spec_rows: list[tuple[str, list[str]]] = []
    for line in lines[spec_start:]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            if spec_rows:
                # If we already have rows and hit a new header or blank, check if
                # we should stop. Allow small gaps (blank lines between rows).
                continue
            continue
        if "|" not in stripped:
            if spec_rows:
                break
            continue

        # Skip separator rows (e.g. "---|---|---|---")
        if re.match(r'^[\s|:-]+$', stripped):
            continue

        parts = [p.strip() for p in stripped.split("|")]
        parts = [p for p in parts if p]  # remove empties from leading/trailing pipes
        if len(parts) >= 2:
            spec_rows.append((parts[0], parts[1:]))

    if not spec_rows:
        return None

    # Determine size labels — the columns represent sizes
    # Try to find the row with known size labels, or infer from cell count row
    num_sizes = max(len(vals) for _, vals in spec_rows)

    # Check if first row has size labels (strip markdown formatting first)
    size_labels = None
    first_label_clean = _strip_md_formatting(spec_rows[0][0]).lower().strip()
    if first_label_clean in ("", "size", "sizes"):
        size_labels = [_strip_md_formatting(v) for v in spec_rows[0][1]]
        spec_rows = spec_rows[1:]

    # If no explicit size row, try to infer size labels
    if not size_labels:
        # Check if ALL cells in the first row (including the label cell) look like size names
        all_cells = [spec_rows[0][0]] + list(spec_rows[0][1])
        all_clean = {_strip_md_formatting(v).lower().strip() for v in all_cells}
        if all_clean <= _SIZE_LABEL_HINTS:
            # All cells are size labels — the row IS the header (no label column)
            size_labels = [_strip_md_formatting(v) for v in all_cells]
            spec_rows = spec_rows[1:]
        else:
            # Check just the values (standard layout with label in first column)
            first_vals_clean = {_strip_md_formatting(v).lower().strip()
                                for v in spec_rows[0][1]} if spec_rows else set()
            if first_vals_clean & _SIZE_LABEL_HINTS:
                size_labels = [_strip_md_formatting(v) for v in spec_rows[0][1]]
                spec_rows = spec_rows[1:]

    if not size_labels:
        size_labels = [f"Size{i+1}" for i in range(num_sizes)]

    # Build size dicts — normalize labels to uppercase
    sizes: list[dict] = [{"size_label": sl.strip().upper()} for sl in size_labels]

    # Model-level fields
    model_data: dict = {}

    for label, values in spec_rows:
        # Strip trailing annotations like "*estimated", "*in progress" (raw, before md strip)
        label_stripped = re.sub(r'\s*\*\w[\w\s]*$', '', label).strip()
        label_low = _strip_md_formatting(label_stripped).lower().strip()
        # Strip trailing units from label for matching
        label_clean = re.sub(r'\s*\(.*?\)\s*$', '', label_low).strip()

        mapping = _MD_ROW_MAP.get(label_low) or _MD_ROW_MAP.get(label_clean)
        if not mapping:
            continue

        field_name, is_per_size, needs_range = mapping

        if not is_per_size:
            # Model-level field (e.g. cell_count) — take first non-empty value
            for v in values:
                parsed = _parse_number(v)
                if parsed is not None:
                    model_data[field_name] = int(parsed) if parsed == int(parsed) else parsed
                    break
        else:
            # Per-size field
            for j, v in enumerate(values):
                if j >= len(sizes):
                    break
                if needs_range:
                    ptv_min, ptv_max = _parse_weight_range(v)
                    if ptv_min is not None:
                        sizes[j]["ptv_min_kg"] = ptv_min
                    if ptv_max is not None:
                        sizes[j]["ptv_max_kg"] = ptv_max
                elif field_name == "certification":
                    cert = v.strip().rstrip("*")
                    if cert:
                        # Normalize certification: CCC variants → CCC
                        cert_upper = cert.upper().strip()
                        if cert_upper.startswith("CCC"):
                            cert = "CCC"
                        sizes[j]["certification"] = cert
                else:
                    parsed = _parse_number(v)
                    if parsed is not None:
                        sizes[j][field_name] = parsed

    # Require at least some valid sizes with weight ranges
    valid_sizes = [s for s in sizes if s.get("ptv_min_kg") or s.get("certification")]
    if not valid_sizes:
        return None

    # Infer model_name from the URL slug (most reliable for manufacturer sites)
    model_name = _slug_to_name(url)

    # Try to find a better model name from the page title pattern
    # e.g. "Rush 5 | Ozone Paragliders" — only override if clearly a product title
    search_range = lines[:spec_start or 80]
    for line in search_range:
        stripped = line.strip()
        if " | " in stripped:
            parts = stripped.split(" | ")
            candidate = parts[0].strip()
            # Must look like a product name: short, not a nav item
            if (2 <= len(candidate) <= 40
                    and not candidate.startswith(("[", "!", "*", "#"))
                    and candidate.lower() not in ("products", "gliders", "home")
                    and any(c.isalnum() for c in candidate)):
                # Verify it's likely a product title by checking the second part
                rest = " | ".join(parts[1:]).lower()
                if "ozone" in rest or "paraglider" in rest or "logo" in rest:
                    model_name = candidate
                    break

    # Infer target_use from certification
    certs = [s.get("certification", "").upper() for s in valid_sizes if s.get("certification")]
    target_use = "leisure"
    if certs:
        primary_cert = certs[0]
        if primary_cert == "A":
            target_use = "school"
        elif primary_cert == "B":
            target_use = "xc"
        elif primary_cert == "C":
            target_use = "xc"
        elif primary_cert == "D":
            target_use = "competition"
        elif primary_cert == "CCC":
            target_use = "competition"

    result = {
        "model_name": model_name,
        "category": "paraglider",
        "target_use": target_use,
        "product_url": url,
        "sizes": valid_sizes,
    }
    result.update(model_data)

    return result


# ───────────────────────────────────────────────────────────────────────────────
# Strategy availability check
# ───────────────────────────────────────────────────────────────────────────────

def _check_llm_availability(extraction_cfg: dict) -> bool:
    """Check if the configured LLM provider is available (API key set)."""
    llm_cfg = extraction_cfg.get("llm", {})
    api_key_env = llm_cfg.get("api_key_env", "GEMINI_API_KEY")
    return bool(os.environ.get(api_key_env))


def _prompt_strategy_choice(extraction_cfg: dict) -> str:
    """
    Ask the user which strategy to use when LLM is unavailable.
    Returns 'markdown', 'llm', or 'cancel'.
    """
    configured = extraction_cfg.get("strategy", "llm")
    llm_cfg = extraction_cfg.get("llm", {})
    api_key_env = llm_cfg.get("api_key_env", "GEMINI_API_KEY")
    provider = llm_cfg.get("provider", "gemini/gemini-2.0-flash")

    if configured == "markdown":
        return "markdown"

    if configured == "llm" and not _check_llm_availability(extraction_cfg):
        print(f"\n  ⚠️  LLM strategy configured ({provider}) but {api_key_env} is not set.")
        print(f"")
        print(f"  Options:")
        print(f"    [1] Use MARKDOWN parser (free, no LLM, works for standard spec tables)")
        print(f"    [2] Set {api_key_env} and continue with LLM")
        print(f"    [3] Cancel")
        print(f"")

        while True:
            try:
                choice = input("  Choose [1/2/3] (default: 1): ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return "cancel"

            if choice in ("", "1"):
                print(f"  → Using markdown parser (zero LLM cost)\n")
                return "markdown"
            elif choice == "2":
                key = input(f"  Enter {api_key_env}: ").strip()
                if key:
                    os.environ[api_key_env] = key
                    print(f"  → {api_key_env} set for this session\n")
                    return "llm"
                else:
                    print(f"  No key entered.")
            elif choice == "3":
                return "cancel"
            else:
                print(f"  Invalid choice. Enter 1, 2, or 3.")

    return configured


# ───────────────────────────────────────────────────────────────────────────────
# Single URL test mode
# ───────────────────────────────────────────────────────────────────────────────

async def extract_single_url(url: str, extraction_cfg: dict | None):
    """Extract specs from a single URL for testing purposes."""
    from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode

    strategy = None
    use_markdown = False

    if extraction_cfg:
        strategy_type = _prompt_strategy_choice(extraction_cfg)
        if strategy_type == "cancel":
            print("  Cancelled.")
            return
        elif strategy_type == "markdown":
            use_markdown = True
        elif strategy_type == "llm":
            strategy = _build_llm_strategy(extraction_cfg)
        elif strategy_type == "css":
            strategy = _build_css_strategy(extraction_cfg)
    else:
        # No config — default to markdown
        use_markdown = True

    browser_cfg = BrowserConfig(headless=True, java_script_enabled=True)
    run_kwargs = {"cache_mode": CacheMode.BYPASS}
    if strategy:
        run_kwargs["extraction_strategy"] = strategy
    run_cfg = CrawlerRunConfig(**run_kwargs)

    print(f"  Rendering: {url}")

    async with AsyncWebCrawler(config=browser_cfg) as crawler:
        result = await crawler.arun(url=url, config=run_cfg)

    if not result.success:
        print(f"  ❌ Failed: {result.error_message}")
        return

    print(f"  ✅ Page rendered ({len(result.html)} bytes HTML)")

    if use_markdown:
        extracted = parse_specs_from_markdown(result.markdown or "", url)
        if extracted:
            print(f"\n--- Extracted data (markdown parser) ---")
            print(json.dumps(extracted, indent=2, default=str))
        else:
            print(f"\n  ⚠️  Markdown parser could not find a specs table.")
            if result.markdown:
                preview = result.markdown[:1500]
                print(f"\n--- Markdown preview (first 1500 chars) ---")
                print(preview)
    elif strategy and result.extracted_content:
        extracted = _parse_extraction_result(result, url)
        print(f"\n--- Extracted data (LLM) ---")
        print(json.dumps(extracted, indent=2, default=str))
    else:
        # No extraction — show discovered links
        links = extract_links_from_html(result.html, url)
        print(f"  Links found: {len(links)}")
        for link in links[:20]:
            print(f"    {link}")
        if len(links) > 20:
            print(f"    ... and {len(links) - 20} more")

        if result.markdown:
            preview = result.markdown[:1000]
            print(f"\n--- Markdown preview (first 1000 chars) ---")
            print(preview)


# ───────────────────────────────────────────────────────────────────────────────
# JSON → CSV conversion
# ───────────────────────────────────────────────────────────────────────────────

def convert_json_to_csv(raw_data: list[dict], manufacturer_slug: str,
                        is_current: bool = False) -> list[dict]:
    """Convert raw extraction JSON to enrichment CSV rows (one per model × size)."""
    rows = []

    for model in raw_data:
        if model.get("_extraction_failed") or model.get("_error"):
            continue

        model_name = model.get("model_name", "").strip()
        if not model_name:
            continue

        sizes = model.get("sizes", [])
        if not sizes:
            continue

        # Use per-model is_current if tagged, otherwise fall back to source-level
        model_is_current = model.get("_is_current", is_current)

        model_fields = {
            "manufacturer_slug": manufacturer_slug,
            "name": model_name,
            "category": model.get("category", ""),
            "target_use": model.get("target_use", ""),
            "is_current": str(model_is_current).lower(),
            "cell_count": model.get("cell_count", ""),
            "line_material": model.get("line_material", ""),
            "manufacturer_url": model.get("product_url", ""),
        }

        for size in sizes:
            row = {col: "" for col in CSV_COLUMNS}
            row.update(model_fields)

            row["size_label"] = size.get("size_label", "")
            row["flat_area_m2"] = size.get("flat_area_m2", "")
            row["flat_span_m"] = size.get("flat_span_m", "")
            row["flat_aspect_ratio"] = size.get("flat_aspect_ratio", "")
            row["proj_area_m2"] = size.get("proj_area_m2", "")
            row["proj_span_m"] = size.get("proj_span_m", "")
            row["proj_aspect_ratio"] = size.get("proj_aspect_ratio", "")
            row["wing_weight_kg"] = size.get("wing_weight_kg", "")
            row["ptv_min_kg"] = size.get("ptv_min_kg", "")
            row["ptv_max_kg"] = size.get("ptv_max_kg", "")

            cert = size.get("certification", "")
            if cert:
                row["cert_standard"] = "CCC" if cert.upper() == "CCC" else "EN"
                row["cert_classification"] = cert

            # Clean numeric values — no trailing .0
            for key in row:
                val = row[key]
                if isinstance(val, float):
                    row[key] = str(int(val)) if val == int(val) else str(val)
                elif isinstance(val, int):
                    row[key] = str(val)

            rows.append(row)

    return rows


def write_csv(rows: list[dict], output_path: str):
    """Write enrichment CSV to disk."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"  Wrote {len(rows)} rows to {output_path}")


# ───────────────────────────────────────────────────────────────────────────────
# Main CLI
# ───────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Extract paraglider specs from manufacturer websites using Crawl4AI.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python extract.py --config config/manufacturers/ozone.yaml           # Full extraction
  python extract.py --config config/manufacturers/ozone.yaml --map-only      # Discover URLs only
  python extract.py --config config/manufacturers/ozone.yaml --retry-failed   # Re-extract failures
  python extract.py --config config/manufacturers/ozone.yaml --convert-only   # JSON → CSV only
  python extract.py --url https://flyozone.com/.../rush-5        # Single URL test

Crash recovery:
  If the script is interrupted or hits rate limits, progress is saved in
  output/<slug>_raw.json.partial. Re-running automatically resumes from
  where it left off.

Then import:
  python3 scripts/import_enrichment_csv.py output/<slug>_enrichment.csv
""",
    )
    parser.add_argument("--config", type=str,
                        help="Path to manufacturer YAML config file")
    parser.add_argument("--url", type=str,
                        help="Single URL to test extraction on")
    parser.add_argument("--map-only", action="store_true",
                        help="Only discover URLs, do not extract specs")
    parser.add_argument("--convert-only", action="store_true",
                        help="Convert existing raw JSON to CSV (no crawling)")
    parser.add_argument("--retry-failed", action="store_true",
                        help="Re-extract only URLs that failed or returned 0 sizes")
    parser.add_argument("--refresh-urls", action="store_true",
                        help="Force re-discovery of product URLs (ignore cache)")
    args = parser.parse_args()

    # Validate arguments
    if not args.config and not args.url:
        parser.error("Either --config or --url is required")

    if args.url and (args.map_only or args.convert_only or args.retry_failed):
        parser.error("--url cannot be combined with --map-only, --convert-only, or --retry-failed")

    # ── Single URL test mode ──────────────────────────────────────────────
    if args.url:
        print("=== Crawl4AI Single URL Test ===\n")
        extraction_cfg = None
        if args.config:
            cfg = load_config(args.config)
            extraction_cfg = cfg.get("extraction")
        asyncio.run(extract_single_url(args.url, extraction_cfg))
        return

    # ── Config-driven mode ────────────────────────────────────────────────
    cfg = load_config(args.config)
    slug = cfg["manufacturer"]["slug"]
    mfr_name = cfg["manufacturer"].get("name", slug)
    paths = get_output_paths(slug)

    print(f"=== Crawl4AI Spec Extractor — {mfr_name} ===\n")

    # ── --convert-only ────────────────────────────────────────────────────
    if args.convert_only:
        source = paths["raw_json"] if os.path.exists(paths["raw_json"]) else paths["partial"]
        if not os.path.exists(source):
            print(f"ERROR: No JSON found at {paths['raw_json']} or {paths['partial']}")
            print("  Run extraction first, or check the file path.")
            sys.exit(1)

        print(f"Loading raw JSON from {source}")
        with open(source, "r", encoding="utf-8") as f:
            raw_data = json.load(f)

        print(f"Converting {len(raw_data)} models to CSV...")
        rows = convert_json_to_csv(raw_data, slug)
        write_csv(rows, paths["csv"])
        print("\nDone.")
        return

    # ── --retry-failed ────────────────────────────────────────────────────
    if args.retry_failed:
        source = paths["partial"] if os.path.exists(paths["partial"]) else paths["raw_json"]
        if not os.path.exists(source):
            print(f"ERROR: No results file found to retry.")
            sys.exit(1)

        print(f"Loading results from {source}")
        with open(source, "r", encoding="utf-8") as f:
            existing = json.load(f)

        retry_urls = []
        keep = []
        for r in existing:
            if r.get("_error") or r.get("_extraction_failed") or len(r.get("sizes", [])) == 0:
                url = r.get("product_url", "")
                if url:
                    retry_urls.append(url)
            else:
                keep.append(r)

        if not retry_urls:
            print("  No failed/empty results to retry.")
            return

        print(f"  {len(keep)} OK results kept, {len(retry_urls)} to re-extract")

        # Save good results as the new partial baseline
        _save_partial(keep, paths["partial"])

        extraction_cfg = cfg.get("extraction", {})
        chosen_strategy = _prompt_strategy_choice(extraction_cfg)
        if chosen_strategy == "cancel":
            print("  Cancelled.")
            return
        extraction_cfg = dict(extraction_cfg)
        extraction_cfg["strategy"] = chosen_strategy

        credit_exhausted = False
        try:
            results = asyncio.run(extract_specs(retry_urls, extraction_cfg, paths))
        except CreditExhaustedError:
            results = _load_partial(paths["partial"])
            credit_exhausted = True

        all_results = _load_partial(paths["partial"]) if os.path.exists(paths["partial"]) else results

        # Save final
        os.makedirs(os.path.dirname(paths["raw_json"]), exist_ok=True)
        with open(paths["raw_json"], "w", encoding="utf-8") as f:
            json.dump(all_results, f, indent=2, default=str)

        success = sum(1 for r in all_results
                      if not r.get("_extraction_failed") and not r.get("_error"))
        still_failed = len(all_results) - success
        print(f"\n  Retry complete: {success} OK, {still_failed} still failing")

        if os.path.exists(paths["partial"]) and not credit_exhausted:
            os.remove(paths["partial"])

        print("\nDone.")
        return

    # ── Full extraction pipeline ──────────────────────────────────────────
    sources = cfg.get("sources", {})
    extraction_cfg = cfg.get("extraction", {})

    if not sources:
        print("ERROR: No sources defined in config.")
        sys.exit(1)

    # Strategy selection — prompt user if LLM unavailable
    chosen_strategy = _prompt_strategy_choice(extraction_cfg)
    if chosen_strategy == "cancel":
        print("  Cancelled.")
        return
    extraction_cfg = dict(extraction_cfg)  # don't mutate original
    extraction_cfg["strategy"] = chosen_strategy

    # Clear URL cache if --refresh-urls
    if args.refresh_urls and os.path.exists(paths["urls"]):
        os.remove(paths["urls"])
        print("  URL cache cleared (--refresh-urls).\n")

    all_results = []
    credit_exhausted = False

    # Collect URLs from all sources first, deduplicating across sources.
    # If a URL appears in both "previous" and "current", prefer "current" metadata.
    all_urls: list[str] = []
    url_metadata: dict[str, dict] = {}  # url → {is_current, source_key}
    seen_urls: set[str] = set()

    for source_key, source_cfg in sources.items():
        is_current = source_cfg.get("is_current", False)
        label = source_key.replace("_", " ")

        print(f"\n--- {label.upper()} ---\n")

        print("Step 1: Discovering product URLs...")
        urls = asyncio.run(map_product_urls(source_key, source_cfg, paths))

        if not urls:
            print(f"  No product URLs found for {label}.")
            continue

        new_count = 0
        dupe_count = 0
        for url in urls:
            normalised = url.rstrip("/")
            if normalised not in seen_urls:
                seen_urls.add(normalised)
                all_urls.append(normalised)
                url_metadata[normalised] = {
                    "is_current": is_current,
                    "source_key": source_key,
                }
                new_count += 1
            else:
                # URL already seen — upgrade to is_current if this source is current
                if is_current and not url_metadata[normalised]["is_current"]:
                    url_metadata[normalised]["is_current"] = True
                    url_metadata[normalised]["source_key"] = source_key
                dupe_count += 1

        print(f"  Found {new_count} new URLs", end="")
        if dupe_count:
            print(f" ({dupe_count} already seen from other source)")
        else:
            print()

    if args.map_only:
        print(f"\n  --map-only: {len(all_urls)} unique URLs discovered across all sources.")
        for url in all_urls:
            meta = url_metadata[url]
            current_tag = " [current]" if meta["is_current"] else ""
            print(f"    {url}{current_tag}")
        print("\nDone (map only).")
        return

    if not all_urls:
        print("\nNo product URLs found.")
        return

    # Step 2: Extract specs from all unique URLs in a single pass
    print(f"\nStep 2: Extracting specs from {len(all_urls)} unique pages...")
    try:
        all_results = asyncio.run(extract_specs(all_urls, extraction_cfg, paths))
    except CreditExhaustedError:
        all_results = _load_partial(paths["partial"])
        credit_exhausted = True

    # Tag each result with source metadata
    for r in all_results:
        url = r.get("product_url", "").rstrip("/")
        meta = url_metadata.get(url, {"is_current": False, "source_key": "unknown"})
        r["_is_current"] = meta["is_current"]
        r["_source"] = meta["source_key"]

    # Summary
    success = sum(1 for r in all_results
                  if not r.get("_extraction_failed") and not r.get("_error"))
    failed = len(all_results) - success
    total_sizes = sum(len(r.get("sizes", [])) for r in all_results)
    print(f"\n  Total: {success} models extracted, {total_sizes} total sizes, {failed} failures")

    if credit_exhausted:
        print("  ⚠️  Rate limit hit. Re-run after cooldown to resume automatically.")

    if not all_results:
        print("\nNo results to save.")
        return

    # Step 3: Save raw JSON
    print(f"\nStep 3: Saving raw JSON to {paths['raw_json']}")
    os.makedirs(os.path.dirname(paths["raw_json"]), exist_ok=True)
    with open(paths["raw_json"], "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"  Saved {len(all_results)} models")

    if os.path.exists(paths["partial"]) and not credit_exhausted:
        os.remove(paths["partial"])

    # Step 4: Convert to CSV
    print(f"\nStep 4: Converting to enrichment CSV...")
    all_rows = []
    for result in all_results:
        is_current = result.pop("_is_current", False)
        result.pop("_source", None)
        result.pop("_extraction_failed", None)
        result.pop("_error", None)
        result.pop("_raw_response", None)
        rows = convert_json_to_csv([result], slug, is_current=is_current)
        all_rows.extend(rows)

    write_csv(all_rows, paths["csv"])

    # Final summary
    models_ok = sum(1 for r in all_results if r.get("sizes"))
    print(f"\n=== Summary ===")
    print(f"  Models extracted:  {models_ok}")
    print(f"  Total size rows:   {len(all_rows)}")
    print(f"  Raw JSON:          {paths['raw_json']}")
    print(f"  Enrichment CSV:    {paths['csv']}")
    if credit_exhausted:
        print(f"\n⚠️  Extraction incomplete — re-run to resume from where you left off.")
    print(f"\nNext step:")
    print(f"  python3 scripts/import_enrichment_csv.py {paths['csv']}")
    print("\nDone.")


if __name__ == "__main__":
    main()
