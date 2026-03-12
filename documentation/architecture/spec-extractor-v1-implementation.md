# Spec Extractor v1 — Complete Implementation Reference

**Created:** March 12, 2026
**Status:** Production — Successfully extracted 111 Ozone models (466 size variants)
**Location:** `tools/spec-extractor/`
**Iteration:** 09 (see `documentation/data/ITERATION_09_EXTRACTION_FRAMEWORK.md`)

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Architecture & Design Philosophy](#2-architecture--design-philosophy)
3. [File Structure](#3-file-structure)
4. [Dependencies & Environment](#4-dependencies--environment)
5. [Configuration System](#5-configuration-system)
6. [CLI Interface](#6-cli-interface)
7. [Execution Pipeline](#7-execution-pipeline)
8. [URL Discovery Engine](#8-url-discovery-engine)
9. [Markdown Spec Table Parser](#9-markdown-spec-table-parser)
10. [LLM Extraction Strategy](#10-llm-extraction-strategy)
11. [Crash Recovery & Resilience](#11-crash-recovery--resilience)
12. [CSV Conversion Pipeline](#12-csv-conversion-pipeline)
13. [DB Import Pipeline](#13-db-import-pipeline)
14. [Ozone Extraction Results](#14-ozone-extraction-results)
15. [Lessons Learned & Edge Cases](#15-lessons-learned--edge-cases)
16. [Replication Guide for New Manufacturers](#16-replication-guide-for-new-manufacturers)
17. [Complete Function Reference](#17-complete-function-reference)
18. [Data Structures & Constants](#18-data-structures--constants)
19. [Known Limitations](#19-known-limitations)

---

## 1. Executive Summary

The spec-extractor is a standalone CLI tool that extracts paraglider technical specifications
from manufacturer websites using **local browser rendering** (Crawl4AI + Playwright) and a
**deterministic markdown table parser** — achieving $0 cost per extraction with no external
API dependencies.

### Key Numbers (Ozone First Run)

| Metric | Value |
|--------|-------|
| Total URLs discovered | 115 (94 previous + 21 current, deduplicated) |
| Models successfully extracted | 111 |
| Models with no spec table | 4 (very old/special pages) |
| Total size variants (CSV rows) | 466 |
| LLM API calls made | 0 |
| Total monetary cost | $0.00 |
| Average time per page | ~2-3 seconds |
| Total extraction time | ~5-6 minutes for 115 pages |

### Why It Was Built

The previous approach (Firecrawl, Iteration 08) failed mid-extraction at page 24/94 due to
credit exhaustion ($0.01-0.03 per page). The spec-extractor replaces it with:

1. **Free local rendering** — Crawl4AI uses Playwright (local Chromium) instead of cloud rendering
2. **Deterministic parsing** — Markdown table parser instead of LLM extraction
3. **Config-driven** — One engine, one YAML config per manufacturer
4. **Portable** — Works on any machine with Python 3.10+ and a browser

---

## 2. Architecture & Design Philosophy

### Three-Layer Architecture

```
Layer 1: Crawl4AI Engine
  └── Playwright renders JS pages locally (free, unlimited)
  └── Converts rendered DOM to clean markdown
  └── Handles retries, caching, browser lifecycle

Layer 2: Extraction Strategies (pluggable)
  ├── markdown (DEFAULT) — Deterministic pipe-table parser, zero cost
  ├── llm (FALLBACK)     — Any LLM via litellm (Gemini, OpenAI, Ollama)
  └── css (FUTURE)       — JsonCssExtractionStrategy for DOM selectors

Layer 3: Output Pipeline
  └── Raw JSON → Enrichment CSV → import_enrichment_csv.py → SQLite DB
```

### Design Principles

1. **Markdown-first, LLM-fallback** — The deterministic parser handles all standard spec tables.
   LLM is only needed for pages with unusual layouts. This makes the tool free to run.

2. **Config-driven, not code-per-brand** — Adding a new manufacturer means creating a YAML file
   (~15 minutes), not writing a new Python script.

3. **Crash-safe** — Every extraction is saved to a `.partial` file immediately. Re-running
   automatically resumes from where it stopped.

4. **Isolated from API** — Lives in `tools/spec-extractor/` with its own venv, dependencies,
   and output directory. Never touches the Flask app or production DB directly.

5. **Cross-source deduplication** — URLs appearing in multiple listing pages (e.g., both
   "previous" and "current") are extracted only once, with correct metadata tagging.

---

## 3. File Structure

```
tools/spec-extractor/
├── extract.py                           # Main CLI engine (1266 lines)
├── README.md                            # Setup and usage guide
├── configs/
│   └── ozone.yaml                       # Ozone manufacturer config (140 lines)
├── documentation/
│   └── spec-extractor-v1-implementation.md  # This document
├── prompts/
│   └── extraction-prompt-kit.md         # Portable prompt for ChatGPT/Gemini/Claude
├── output/                              # All output files (gitignored except .gitkeep)
│   ├── .gitkeep
│   ├── ozone_raw.json                   # Raw extraction results (115 models)
│   ├── ozone_enrichment.csv             # Enrichment CSV (466 rows)
│   └── ozone_urls.json                  # Cached discovered URLs
├── strategies/                          # Future: pluggable strategy modules
└── .venv/                               # Isolated Python 3.11 virtual environment
```

### Related Files Outside This Directory

```
.github/agents/paraglider-data-extractor.agent.md  # Copilot extraction agent
scripts/import_enrichment_csv.py                     # DB import script
documentation/data/ITERATION_09_EXTRACTION_FRAMEWORK.md  # Iteration documentation
.gitignore                                           # Patterns for output files
```

---

## 4. Dependencies & Environment

### Python Version

**Python 3.10+ is required.** Crawl4AI uses `type | None` union syntax (PEP 604) which is
only available in Python 3.10+. The tool venv uses Python 3.11 via Homebrew.

The main project uses Python 3.9 (macOS system) — that's why the tool has its own venv.

### Setup Commands

```bash
cd tools/spec-extractor

# Create venv with Python 3.11 (Homebrew)
/usr/local/bin/python3.11 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install crawl4ai pyyaml httpx

# Download Playwright Chromium (~95MB to ~/Library/Caches/ms-playwright/)
crawl4ai-setup
```

### Direct Dependencies

| Package | Purpose |
|---------|---------|
| `crawl4ai` | JS page rendering + extraction strategies |
| `pyyaml` | YAML config file parsing |
| `httpx` | HTTP client (used by crawl4ai internally) |

### Transitive Dependencies (installed by crawl4ai)

| Package | Purpose |
|---------|---------|
| `playwright` | Browser automation (Chromium Headless Shell) |
| `litellm` | Universal LLM API wrapper (for LLM strategy) |
| `beautifulsoup4` | HTML parsing |

### Browser Binary

Crawl4AI downloads a Chromium Headless Shell binary during `crawl4ai-setup`:
- **Location:** `~/Library/Caches/ms-playwright/chromium_headless_shell-XXXX/`
- **Size:** ~95MB
- **Managed by:** Playwright (auto-updated)

---

## 5. Configuration System

### Config File Format (YAML)

Each manufacturer has one YAML config file in `configs/`. The Ozone config is the
reference implementation:

```yaml
# configs/ozone.yaml — Full annotated config

manufacturer:
  name: Ozone                              # Display name
  slug: ozone                              # URL-safe identifier, matches DB manufacturer slug
  website: https://flyozone.com            # Base URL (informational)

sources:
  # Each source is a listing page to scrape for product URLs.
  # Multiple sources are supported — URLs are deduplicated across them.
  # The iteration order matters: sources listed first get scraped first.
  
  previous_gliders:
    listing_url: https://flyozone.com/paragliders/products/previous-gliders
    url_pattern: "/products/gliders/"       # Only keep links matching this pattern
    is_current: false                       # Tag for DB import (previous = not current)
    url_excludes:                           # Links to skip
      - "#"
      - "?"
      - "sitemap.xml"
      - "/products/previous-gliders"
      - "/products/harnesses"
      - "/products/reserves"
      - "/products/accessories"

  current_gliders:
    listing_url: https://flyozone.com/paragliders/products/gliders
    url_pattern: "/products/gliders/"
    is_current: true                        # These models are current/active
    url_excludes:
      - "#"
      - "?"
      - "sitemap.xml"
      - "/products/previous-gliders"
      - "/products/harnesses"
      - "/products/reserves"
      - "/products/accessories"

extraction:
  strategy: markdown                        # DEFAULT: free deterministic parser

  # LLM fallback configuration (used if user explicitly chooses LLM strategy)
  llm:
    provider: "gemini/gemini-2.0-flash"     # litellm model string
    api_key_env: "GEMINI_API_KEY"           # Environment variable name
    prompt: |                               # Extraction instruction for the LLM
      Extract ONLY the factual technical specifications from this page...
    schema:                                 # JSON Schema for structured extraction
      type: object
      properties:
        model_name: { type: string }
        category: { type: string, enum: [...] }
        target_use: { type: string, enum: [...] }
        cell_count: { type: integer }
        line_material: { type: string }
        product_url: { type: string }
        sizes:
          type: array
          items:
            type: object
            properties:
              size_label: { type: string }
              flat_area_m2: { type: number }
              # ... all spec fields
              certification: { type: string }
```

### Config Validation

`load_config()` validates:
1. `manufacturer.slug` must exist (used for output filenames)
2. At least one of `sources` or `extraction` must be defined
3. File must exist at the specified path

### Output Path Convention

All output files are derived from `manufacturer.slug`:

```python
{
    "raw_json": "output/{slug}_raw.json",        # Full extraction data
    "partial":  "output/{slug}_raw.json.partial", # Crash recovery file
    "csv":      "output/{slug}_enrichment.csv",   # Import-ready CSV
    "urls":     "output/{slug}_urls.json",        # URL discovery cache
}
```

---

## 6. CLI Interface

### Arguments

```
python extract.py [OPTIONS]

Required (one of):
  --config PATH          Path to manufacturer YAML config file
  --url URL              Single URL to test extraction on

Optional:
  --map-only             Only discover URLs, do not extract specs
  --convert-only         Convert existing raw JSON to CSV (no crawling)
  --retry-failed         Re-extract only URLs that failed or returned 0 sizes
  --refresh-urls         Force re-discovery of product URLs (ignore cache)
```

### Argument Validation Rules

- `--config` or `--url` must be provided (at least one)
- `--url` cannot be combined with `--map-only`, `--convert-only`, or `--retry-failed`
- `--config` + `--url` together: loads config for extraction strategy, tests single URL

### Execution Modes

| Mode | Trigger | What It Does |
|------|---------|--------------|
| **Single URL test** | `--url` | Renders one page, extracts and prints JSON |
| **Map only** | `--config --map-only` | Discovers URLs from all sources, prints list |
| **Convert only** | `--config --convert-only` | Reads existing `_raw.json`, writes CSV |
| **Retry failed** | `--config --retry-failed` | Re-extracts only failed/empty entries |
| **Full extraction** | `--config` | Discovers URLs → extracts all → saves JSON + CSV |

---

## 7. Execution Pipeline

### Full Extraction Flow (Step by Step)

```
1. Load config (YAML)
2. Build output paths from manufacturer slug
3. Strategy selection (interactive prompt if LLM key missing)
4. Clear URL cache if --refresh-urls
5. FOR EACH source in config:
     a. Check URL cache → hit? use cached list
     b. Cache miss → render listing page with Playwright
     c. Extract all <a href> links from rendered HTML
     d. Filter by url_pattern and url_excludes
     e. Deduplicate within source (preserving order)
     f. Cache discovered URLs to disk
     g. Deduplicate across sources (current wins over previous)
6. Single extraction pass on all unique URLs:
     a. Load partial results (resume from crash)
     b. Skip already-extracted URLs
     c. FOR EACH remaining URL:
          i.   Render page with Playwright
          ii.  Extract specs (markdown parser or LLM)
          iii. Save to .partial file (atomic write)
          iv.  1-second delay between requests
     d. Delete .partial file on success
7. Tag results with is_current and source metadata
8. Save raw JSON
9. Convert to enrichment CSV
10. Print summary with next step (import command)
```

### Interactive Strategy Selection

When `strategy: llm` is configured but the API key env var is unset:

```
⚠️  LLM strategy configured (gemini/gemini-2.0-flash) but GEMINI_API_KEY is not set.

Options:
  [1] Use MARKDOWN parser (free, no LLM, works for standard spec tables)
  [2] Set GEMINI_API_KEY and continue with LLM
  [3] Cancel

Choose [1/2/3] (default: 1):
```

When `strategy: markdown` is configured, no prompt is shown — markdown is used directly.

---

## 8. URL Discovery Engine

### Function: `map_product_urls()`

```python
async def map_product_urls(source_key: str, source_cfg: dict, paths: dict) -> list[str]
```

**Purpose:** Discover all product detail page URLs from a listing page.

**Flow:**

1. **Check URL cache** — `_load_url_cache()` reads `output/{slug}_urls.json` keyed by
   `"{source_key}:{listing_url}"`. If found, returns cached list immediately.

2. **Render listing page** — Launches Playwright Chromium in headless mode, navigates
   to the listing URL, waits for JS to render (critical for Next.js sites like Ozone).

3. **Extract links** — `extract_links_from_html()` uses Python's `HTMLParser` to find
   all `<a href>` tags in the rendered DOM. Converts relative URLs to absolute.

4. **Filter** — Applies `url_pattern` (must contain this string) and `url_excludes`
   (skip if any exclude string is found in the URL).

5. **Slug validation** — The URL segment after `url_pattern` must:
   - Not be empty
   - Not contain `/` (must be a leaf page)
   - Not be purely numeric

6. **Deduplicate** — Preserves order, normalizes by stripping trailing `/`.

7. **Cache** — Saves to `output/{slug}_urls.json` for future runs.

### Cross-Source Deduplication (in `main()`)

When multiple sources are defined, URLs are deduplicated in the main loop:

```python
all_urls: list[str] = []
url_metadata: dict[str, dict] = {}
seen_urls: set[str] = set()

for source_key, source_cfg in sources.items():
    urls = map_product_urls(source_key, source_cfg, paths)
    for url in urls:
        normalised = url.rstrip("/")
        if normalised not in seen_urls:
            seen_urls.add(normalised)
            all_urls.append(normalised)
            url_metadata[normalised] = {
                "is_current": is_current,
                "source_key": source_key,
            }
        else:
            # Already seen — upgrade to is_current if this source is current
            if is_current and not url_metadata[normalised]["is_current"]:
                url_metadata[normalised]["is_current"] = True
                url_metadata[normalised]["source_key"] = source_key
```

**Key behavior:** If a URL appears in both `previous_gliders` and `current_gliders`,
the `is_current=True` metadata wins. This correctly tags models like Rush 6 as "current"
even though they also appear on the "previous" listing page.

### URL Cache Format

```json
// output/ozone_urls.json
{
  "previous_gliders:https://flyozone.com/paragliders/products/previous-gliders": [
    "https://flyozone.com/paragliders/products/gliders/moxie",
    "https://flyozone.com/paragliders/products/gliders/alta-gt",
    // ... 115 URLs
  ],
  "current_gliders:https://flyozone.com/paragliders/products/gliders": [
    "https://flyozone.com/paragliders/products/gliders/moxie",
    "https://flyozone.com/paragliders/products/gliders/alta-gt",
    // ... 21 URLs
  ]
}
```

### HTML Link Extractor

```python
class _LinkExtractor(HTMLParser):
    """Extracts all href values from <a> tags in rendered HTML."""
    def handle_starttag(self, tag, attrs):
        if tag == "a":
            for name, value in attrs:
                if name == "href" and value:
                    self.links.append(value)
```

Uses Python's built-in `HTMLParser` — no BeautifulSoup dependency for this step.

---

## 9. Markdown Spec Table Parser

This is the core innovation of the tool — a deterministic, zero-cost parser that extracts
structured data from Crawl4AI's markdown output.

### Function: `parse_specs_from_markdown()`

```python
def parse_specs_from_markdown(markdown: str, url: str) -> dict | None
```

**Returns:** A dict with `model_name`, `category`, `target_use`, `product_url`, `sizes[]`,
and `cell_count` — or `None` if no spec table is found.

### How It Works (Step by Step)

#### Step 1: Find the Specifications Section

```python
# First try: look for a markdown header "# Specifications"
for i, line in enumerate(lines):
    if re.match(r'^#+\s*specifications?\s*$', line.strip(), re.IGNORECASE):
        spec_start = i
        break

# Fallback: look for any line starting with a known row label + pipe
for i, line in enumerate(lines):
    low = line.strip().lower()
    if any(low.startswith(k) and "|" in line for k in _MD_ROW_MAP):
        spec_start = max(0, i - 5)
        break
```

#### Step 2: Collect Pipe-Delimited Rows

Starting from `spec_start`, scans downward collecting rows that contain `|`:

```python
for line in lines[spec_start:]:
    stripped = line.strip()
    
    # Skip blanks and headers (allow gaps between rows)
    if not stripped or stripped.startswith("#"):
        if spec_rows: continue
        continue
    
    # Stop if we hit a line without pipes after collecting some rows
    if "|" not in stripped:
        if spec_rows: break
        continue
    
    # Skip separator rows like "---|---|---|---"
    if re.match(r'^[\s|:-]+$', stripped):
        continue
    
    # Split by pipe and collect
    parts = [p.strip() for p in stripped.split("|")]
    parts = [p for p in parts if p]  # remove empties from leading/trailing pipes
    if len(parts) >= 2:
        spec_rows.append((parts[0], parts[1:]))
```

Each row becomes a tuple: `(label, [value1, value2, ...])`.

#### Step 3: Detect Size Labels

Three detection methods, tried in order:

**Method 1:** First cell is empty, "size", or "sizes"
```python
first_label_clean = _strip_md_formatting(spec_rows[0][0]).lower()
if first_label_clean in ("", "size", "sizes"):
    size_labels = [_strip_md_formatting(v) for v in spec_rows[0][1]]
```

**Method 2:** ALL cells in the first row are recognized size names
```python
all_cells = [spec_rows[0][0]] + list(spec_rows[0][1])
all_clean = {_strip_md_formatting(v).lower().strip() for v in all_cells}
if all_clean <= _SIZE_LABEL_HINTS:
    # Row like "| **XS** | **S** | **M** | **L** |" — entire row is headers
    size_labels = [_strip_md_formatting(v) for v in all_cells]
```

**Method 3:** Value cells (not the label) match size hints
```python
first_vals_clean = {_strip_md_formatting(v).lower().strip() for v in spec_rows[0][1]}
if first_vals_clean & _SIZE_LABEL_HINTS:
    size_labels = [_strip_md_formatting(v) for v in spec_rows[0][1]]
```

**Fallback:** Generic labels `Size1`, `Size2`, ...

#### Step 4: Map Row Labels to Fields

For each remaining row, the label is cleaned and looked up in `_MD_ROW_MAP`:

```python
for label, values in spec_rows:
    # 1. Strip annotations like "*estimated", "*in progress"
    label_stripped = re.sub(r'\s*\*\w[\w\s]*$', '', label).strip()
    
    # 2. Strip markdown formatting (**bold**, *italic*)
    label_low = _strip_md_formatting(label_stripped).lower().strip()
    
    # 3. Strip trailing units like "(m2)", "(kg)"
    label_clean = re.sub(r'\s*\(.*?\)\s*$', '', label_low).strip()
    
    # 4. Look up in row map (try both with and without units)
    mapping = _MD_ROW_MAP.get(label_low) or _MD_ROW_MAP.get(label_clean)
```

#### Step 5: Parse Values

Three parsing modes based on the field type:

**Numeric fields (most specs):**
```python
parsed = _parse_number(v)
# Handles: "21.41", "18,9" (EU decimal), "4.51*" (strip asterisk)
# Strips trailing units: "21.41 m2" → "21.41"
# EU decimal: "18,9" → "18.9" (only if no period present)
```

**Weight ranges (PTV):**
```python
ptv_min, ptv_max = _parse_weight_range(v)
# Handles: "65-85", "65 - 85", "65–85" (en-dash), "65—85" (em-dash), "65/85"
```

**Certification:**
```python
cert = v.strip().rstrip("*")
cert_upper = cert.upper().strip()
if cert_upper.startswith("CCC"):
    cert = "CCC"  # Normalize "CCCC" → "CCC"
```

#### Step 6: Model Name Extraction

Two-stage approach:

```python
# Primary: URL slug
model_name = _slug_to_name(url)
# "rush-5" → "Rush 5"

# Override: Page title pattern "Rush 5 | Ozone Paragliders"
for line in lines[:spec_start]:
    if " | " in stripped:
        candidate = stripped.split(" | ")[0].strip()
        rest = " | ".join(parts[1:]).lower()
        if "ozone" in rest or "paraglider" in rest:
            model_name = candidate
```

#### Step 7: Infer `target_use` from Certification

```python
cert_to_use = {
    "A": "school",
    "B": "xc",
    "C": "xc",
    "D": "competition",
    "CCC": "competition",
}
# Default: "leisure"
```

#### Step 8: Validate and Return

```python
# Require at least one size with a weight range or certification
valid_sizes = [s for s in sizes if s.get("ptv_min_kg") or s.get("certification")]
if not valid_sizes:
    return None
```

### Two Ozone Table Formats

The parser handles two distinct table formats found on Ozone's website:

#### Modern Format (2018+)

Used by Rush 5, Buzz Z7, Swift 6, Enzo 3, etc.

```markdown
| | **XS** | **S** | **M** | **ML** | **L** | **XL** |
|---|---|---|---|---|---|---|
| Number of Cells | 57 | 57 | 57 | 57 | 57 | 57 |
| Flat Area (m^2) | 21.41 | 23.86 | 25.16 | 27.08 | 28.93 | 30.81 |
| Certified Weight Range (kg) | 55-70 | 65-85 | 75-95 | 85-105 | 95-115 | 110-130 |
| EN | B | B | B | B | B | B |
```

Characteristics:
- Leading `|` on every row (pipe-wrapped)
- Empty first cell in header row
- Full label names: "Flat Area (m^2)", "Certified Weight Range (kg)"
- Dot decimal notation: `21.41`

#### Legacy Format (pre-2018)

Used by Alpina (original), older models.

```markdown
| **XS** | **S** | **M** | **L**
---|---|---|---|---
Cells | 58 | 58 | 58 | 58
Area Flat | 21,9 | 24 | 26 | 28,3
Glider Weight *estimated | 4,11* | 4,31* | 4,51* | 4,71*
In flight weight range | 55-70 | 65-85 | 80-100 | 95-115
LTF / EN *in progress | C | C | C | C
```

Characteristics:
- No leading `|` on data rows
- Bold markdown headers (`**XS**`)
- No empty first cell in header — all cells are size labels
- Short label names: "Area Flat", "AR Proj.", "Span Flat"
- Comma decimal notation: `21,9` (European format)
- Trailing annotations: `*estimated`, `*in progress`
- Separator rows: `---|---|---|---|---`

### Parser Edge Cases Handled

| Edge Case | How It's Handled |
|-----------|------------------|
| Bold size headers `**XS**` | `_strip_md_formatting()` removes `*` markers |
| EU comma decimals `18,9` | `_parse_number()` converts comma → period |
| Trailing asterisks `4.51*` | `rstrip("*")` in `_parse_number()` |
| Trailing units `21.41 m2` | Regex strips `kg`, `m2`, `m^2`, `m²` |
| Label annotations `*estimated` | Stripped before markdown formatting removal |
| Separator rows `---\|---` | Regex skip: `r'^[\s|:-]+$'` |
| "CCC" vs "CCCC" variants | Normalized: anything starting with "CCC" → "CCC" |
| Missing spec table | Returns `None`, logged as "no specs table" |
| Weight range formats | Handles `-`, `–`, `—`, `/` as separators |
| Numeric sizes (harnesses) | `_SIZE_LABEL_HINTS` includes "22" through "31" |

---

## 10. LLM Extraction Strategy

The LLM strategy exists as a fallback for pages with non-standard table layouts.

### How It Works

1. Crawl4AI renders the page with Playwright (same as markdown strategy)
2. Instead of parsing markdown, passes the rendered content to an LLM via
   `LLMExtractionStrategy` (Crawl4AI's built-in)
3. LLM receives the extraction prompt and JSON schema from the YAML config
4. Returns structured JSON matching the schema

### LLM Config in YAML

```yaml
extraction:
  strategy: llm
  llm:
    provider: "gemini/gemini-2.0-flash"   # litellm model string
    api_key_env: "GEMINI_API_KEY"         # env var name (not the key itself!)
    prompt: |
      Extract ONLY the factual technical specifications...
    schema:
      type: object
      properties:
        model_name: { type: string }
        sizes:
          type: array
          items:
            type: object
            properties:
              size_label: { type: string }
              flat_area_m2: { type: number }
              # ... etc
```

### Supported LLM Providers

Via litellm, any provider works:

| Provider | Model String | Free Tier |
|----------|-------------|-----------|
| Google Gemini | `gemini/gemini-2.0-flash` | 15 RPM (may require billing in EU) |
| Google Gemini (older) | `gemini/gemini-1.5-flash` | May have better EU availability |
| OpenAI | `openai/gpt-4o-mini` | No free tier |
| Ollama (local) | `ollama/llama3` | Unlimited (local) |
| Groq | `groq/llama-3.1-70b` | 30 RPM free |

### EU Regional Note

Google Gemini free tier in EU/EEA regions may show `limit: 0` even without usage.
This is a regional restriction, not quota exhaustion. Options:
1. Link a billing account (still free within tier limits)
2. Use `gemini-1.5-flash` (may have better EU availability)
3. Use the markdown parser instead (recommended)

---

## 11. Crash Recovery & Resilience

### Partial File System

Every extraction result is saved immediately to a `.partial` file:

```python
def _save_partial(results: list[dict], partial_path: str):
    """Atomically save results to the .partial file after every extraction."""
    tmp = partial_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str)
    os.replace(tmp, partial_path)  # Atomic on POSIX
```

**Atomic write pattern:** Write to `.tmp` file, then `os.replace()` to target.
This prevents corruption if the process is killed mid-write.

### Resume Logic

On re-run, `extract_specs()` loads the partial file and skips already-done URLs:

```python
results = _load_partial(paths["partial"])
if results:
    done_urls = {r.get("product_url", "").rstrip("/") for r in results}
    remaining = [u for u in urls if u.rstrip("/") not in done_urls]
    print(f"Resuming: {len(results)} already done, {len(remaining)} remaining")
```

### Rate Limit Detection

```python
def _is_rate_limit_error(error_str: str) -> bool:
    indicators = [
        "429", "rate limit", "rate_limit", "quota", "exhausted",
        "too many requests", "resource_exhausted", "RESOURCE_EXHAUSTED",
        "402", "payment required",
    ]
    lower = error_str.lower()
    return any(ind.lower() in lower for ind in indicators)
```

On detection:
1. Current result is saved to partial file
2. `CreditExhaustedError` is raised
3. Main loop catches it, prints resume instructions
4. User can re-run to continue from where it stopped

### Request Pacing

1-second delay between page extractions:

```python
if i < total:
    time.sleep(1)
```

### Retry Failed

`--retry-failed` reads the existing results, separates failed/empty entries from
successful ones, and re-extracts only the failed URLs:

```python
for r in existing:
    if r.get("_error") or r.get("_extraction_failed") or len(r.get("sizes", [])) == 0:
        retry_urls.append(r.get("product_url", ""))
    else:
        keep.append(r)
```

---

## 12. CSV Conversion Pipeline

### Function: `convert_json_to_csv()`

```python
def convert_json_to_csv(raw_data: list[dict], manufacturer_slug: str,
                        is_current: bool = False) -> list[dict]
```

Converts the raw JSON (one entry per model) into flat CSV rows (one per model × size).

### CSV Column Layout

30 columns matching `scripts/import_enrichment_csv.py`:

```
manufacturer_slug, name, year, category, target_use, is_current,
cell_count, line_material, riser_config, manufacturer_url, description,
size_label, flat_area_m2, flat_span_m, flat_aspect_ratio,
proj_area_m2, proj_span_m, proj_aspect_ratio,
wing_weight_kg, ptv_min_kg, ptv_max_kg,
speed_trim_kmh, speed_max_kmh, glide_ratio_best, min_sink_ms,
cert_standard, cert_classification, cert_test_lab, cert_test_date, cert_report_url
```

### Model-Level vs Size-Level Fields

| Level | Fields |
|-------|--------|
| Model (same for all sizes) | manufacturer_slug, name, year, category, target_use, is_current, cell_count, line_material, riser_config, manufacturer_url, description |
| Size (varies per size) | size_label, flat_area_m2, flat_span_m, flat_aspect_ratio, proj_area_m2, proj_span_m, proj_aspect_ratio, wing_weight_kg, ptv_min_kg, ptv_max_kg |
| Certification (derived) | cert_standard (EN/CCC), cert_classification (A/B/C/D/CCC), cert_test_lab, cert_test_date, cert_report_url |
| Not yet extracted | year, line_material, riser_config, description, speed_trim_kmh, speed_max_kmh, glide_ratio_best, min_sink_ms, cert_test_lab, cert_test_date, cert_report_url |

### Certification Mapping

```python
cert = size.get("certification", "")
if cert:
    row["cert_standard"] = "CCC" if cert.upper() == "CCC" else "EN"
    row["cert_classification"] = cert
```

### Number Formatting

Clean trailing `.0` from integer values:
```python
for key in row:
    val = row[key]
    if isinstance(val, float):
        row[key] = str(int(val)) if val == int(val) else str(val)
```

This produces `"58"` instead of `"58.0"` for cell counts.

---

## 13. DB Import Pipeline

### Script: `scripts/import_enrichment_csv.py`

This script is **not part of the spec-extractor** — it's part of the main API codebase.
The spec-extractor's CSV output is designed to be consumed by it.

### What It Does

1. Reads the enrichment CSV
2. For each row, matches `manufacturer_slug` to a `manufacturers` record
3. Upserts `models` (WingModel) by `(manufacturer_id, name)`
4. Upserts `size_variants` by `(model_id, size_label)`
5. Upserts `certifications` by `(size_variant_id, standard)`

### Upsert Behavior

- **Creates** records that don't exist
- **Updates** only NULL fields (never overwrites existing data)
- **Idempotent** — safe to run multiple times

### Prerequisite

The manufacturer must exist in the DB:
```sql
SELECT id, slug FROM manufacturers WHERE slug = 'ozone';
```

### Command

```bash
cd /Users/j765/Projects/OpenParaglider
source .venv/bin/activate
python3 scripts/import_enrichment_csv.py tools/spec-extractor/output/ozone_enrichment.csv
```

### DB Tables Written

| Table | Fields Updated |
|-------|---------------|
| `models` | name, slug, category, target_use, year, is_current, cell_count, line_material, riser_config, manufacturer_url, description |
| `size_variants` | size_label, flat_area_m2, flat_span_m, flat_aspect_ratio, proj_area_m2, proj_span_m, proj_aspect_ratio, wing_weight_kg, ptv_min_kg, ptv_max_kg |
| `certifications` | standard, classification |

---

## 14. Ozone Extraction Results

### Summary Statistics

| Metric | Value |
|--------|-------|
| Total unique URLs | 115 |
| URLs from previous_gliders | 94 |
| URLs from current_gliders | 21 |
| URLs appearing in both | 21 (deduplicated) |
| Models successfully extracted | 111 |
| Models with no spec table | 4 |
| Total size variants | 466 |

### Failed Models (4)

| Model | URL | Reason |
|-------|-----|--------|
| Roadrunner | .../gliders/roadrunner | Tandem harness, no paraglider spec table |
| Addict | .../gliders/addict | Very old model, page has no spec table |
| Groundhog | .../gliders/groundhog | Ground-handling trainer, no spec table |
| Mantrar07 | .../gliders/mantrar07 | Very old model, page has no spec table |

### Sample Extracted Data

#### Successful (Moxie — EN-A, 6 sizes):

```json
{
  "model_name": "Moxie",
  "category": "paraglider",
  "target_use": "school",
  "product_url": "https://flyozone.com/paragliders/products/gliders/moxie",
  "sizes": [
    {
      "size_label": "XXS",
      "proj_area_m2": 17.24,
      "flat_area_m2": 20.4,
      "proj_span_m": 7.62,
      "flat_span_m": 9.9,
      "proj_aspect_ratio": 3.37,
      "flat_aspect_ratio": 4.81,
      "root_chord_m": 2.64,
      "wing_weight_kg": 4.16,
      "ptv_min_kg": 45.0,
      "ptv_max_kg": 65.0,
      "certification": "A"
    }
    // ... 5 more sizes
  ],
  "cell_count": 38
}
```

#### Failed (Roadrunner — no spec table):

```json
{
  "model_name": "Roadrunner",
  "product_url": "https://flyozone.com/paragliders/products/gliders/roadrunner",
  "sizes": [],
  "_extraction_failed": true,
  "_raw_response": null
}
```

### CSV Sample

```csv
manufacturer_slug,name,...,size_label,flat_area_m2,...,cert_standard,cert_classification,...
ozone,Moxie,...,XXS,20.4,...,EN,A,...
ozone,Moxie,...,XS,22.4,...,EN,A,...
ozone,Rush 5,...,XS,21.41,...,EN,B,...
ozone,Enzo 2,...,S,18.8,...,CCC,CCC,...
```

### Fields Successfully Extracted

| Field | Coverage | Notes |
|-------|----------|-------|
| model_name | 111/111 | From page title or URL slug |
| cell_count | 111/111 | All models have this |
| flat_area_m2 | 111/111 | Always present in spec tables |
| flat_span_m | 111/111 | Always present |
| flat_aspect_ratio | 111/111 | Always present |
| proj_area_m2 | 111/111 | Always present |
| proj_span_m | 111/111 | Always present |
| proj_aspect_ratio | 111/111 | Always present |
| wing_weight_kg | ~105/111 | Some older models don't list this |
| ptv_min_kg | 111/111 | Always present (required for validation) |
| ptv_max_kg | 111/111 | Always present |
| certification | 111/111 | Always present (required for validation) |
| root_chord_m | ~80/111 | Only on newer models; not in DB schema |
| target_use | 111/111 | Inferred from certification |

### Fields NOT Extracted (Not in Spec Tables)

| Field | Where It Exists | Extraction Difficulty |
|-------|----------------|----------------------|
| year | Not on product pages | Would need release date data |
| line_material | "Materials" section (prose) | Would need secondary parser |
| riser_config | Not consistently listed | Manual or LLM |
| description | Marketing text | Could extract but not needed |
| speed_trim_kmh | Not in spec table | Would need flight test data |
| speed_max_kmh | Not in spec table | Would need flight test data |
| glide_ratio_best | Not in spec table | Would need flight test data |
| min_sink_ms | Not in spec table | Would need flight test data |

---

## 15. Lessons Learned & Edge Cases

### Key Insights from Ozone Extraction

1. **Crawl4AI's markdown output is the key.** The rendered HTML is too complex (546KB, deeply
   nested React DOM), but Crawl4AI's markdown conversion produces clean, parseable pipe tables.

2. **Two table formats on the same manufacturer site.** Modern Ozone pages (2018+) use a
   different markdown table format than older pages. The parser must handle both.

3. **EU decimal commas are real.** Older Ozone pages use `18,9` instead of `18.9`. This is
   the European standard and must be converted.

4. **"Previous" and "current" listings overlap.** 21 of 115 Ozone URLs appear on both
   listing pages. Without cross-source deduplication, these get extracted twice.

5. **Not all product pages have spec tables.** The Roadrunner (tandem harness), Groundhog
   (trainer), and two very old models have no spec table. The parser correctly returns None.

6. **`*estimated` and `*in progress` annotations.** Older models have labels like
   "Glider Weight *estimated" and "LTF / EN *in progress". These must be stripped before
   label matching.

7. **Markdown bold markers in size labels.** Legacy pages render size headers as `**XS**`
   in markdown. The parser strips these before matching against `_SIZE_LABEL_HINTS`.

8. **Model name extraction is tricky.** The page title pattern "Rush 5 | Ozone Paragliders"
   is reliable, but some old pages have different patterns. URL slug is the safe fallback.

9. **1-second delay is sufficient.** Ozone doesn't rate-limit at this pace. The total
   extraction (115 pages) took ~5-6 minutes.

10. **Atomic writes prevent corruption.** The `os.replace()` pattern ensures the partial
    file is never half-written if the process is killed.

### What Would Break the Parser

| Scenario | Impact | Mitigation |
|----------|--------|------------|
| Manufacturer uses non-pipe tables | Parser returns None | Fall back to LLM strategy |
| Spec data in tabs/accordions not rendered | Missing data | Adjust Crawl4AI wait config |
| Row labels in a different language | Not matched in _MD_ROW_MAP | Add translations to map |
| Specs split across multiple tables | Only first table parsed | Would need multi-table logic |
| Very different row label naming | Not matched | Add variants to _MD_ROW_MAP |

---

## 16. Replication Guide for New Manufacturers

### Steps to Add a New Manufacturer

1. **Explore the website** — visit the manufacturer's product listing pages and a few
   product detail pages. Note:
   - What is the listing page URL?
   - What URL pattern do product detail pages follow?
   - Are there separate listing pages for current vs. previous models?
   - Is the site JS-rendered (React, Next.js, Vue)?

2. **Test with `--url`** — run a single page test to see the markdown output:
   ```bash
   python extract.py --url https://manufacturer.com/products/model-name
   ```
   Look at the markdown output. Is there a pipe-delimited spec table?

3. **Create the YAML config** — copy `configs/ozone.yaml` and modify:
   - `manufacturer.name` and `manufacturer.slug`
   - `sources` — listing URLs, URL pattern, excludes
   - `extraction.strategy` — `markdown` if spec tables are pipe-delimited

4. **Check row label mapping** — does the manufacturer use the same spec labels as
   Ozone? If not, add new entries to `_MD_ROW_MAP` in `extract.py`:
   ```python
   "superficie plana":     ("flat_area_m2",    True,  False),  # Spanish
   "envergure à plat":     ("flat_span_m",     True,  False),  # French
   ```

5. **Test `--map-only`** — discover all product URLs:
   ```bash
   python extract.py --config configs/manufacturer.yaml --map-only
   ```

6. **Test a few pages** — extract 2-3 models and verify accuracy:
   ```bash
   python extract.py --config configs/manufacturer.yaml --url https://...
   ```

7. **Full run** — extract all models:
   ```bash
   python extract.py --config configs/manufacturer.yaml
   ```

8. **Import** — load into the DB:
   ```bash
   python3 scripts/import_enrichment_csv.py output/manufacturer_enrichment.csv
   ```

### Estimated Time per Manufacturer

| Task | Time |
|------|------|
| Website exploration | 10-15 min |
| YAML config creation | 10-15 min |
| Row map additions (if needed) | 5-10 min |
| Testing (3-5 pages) | 5-10 min |
| Full extraction run | 2-10 min (depends on page count) |
| **Total** | **30-50 min per brand** |

---

## 17. Complete Function Reference

### Config & Setup

| Function | Line | Purpose |
|----------|------|---------|
| `load_config(config_path)` | 77 | Load and validate YAML config |
| `get_output_paths(slug)` | 97 | Return standard output file paths |

### Crash Recovery

| Function | Line | Purpose |
|----------|------|---------|
| `_save_partial(results, path)` | 111 | Atomic save to .partial file |
| `_load_partial(path)` | 120 | Load partial results from interrupted run |

### URL Cache

| Function | Line | Purpose |
|----------|------|---------|
| `_load_url_cache(path, key)` | 132 | Load cached URLs for a listing page |
| `_save_url_cache(path, key, urls)` | 141 | Save discovered URLs to cache |

### HTML Parsing

| Function/Class | Line | Purpose |
|----------------|------|---------|
| `_LinkExtractor` (class) | 157 | HTMLParser subclass for extracting `<a href>` |
| `extract_links_from_html(html, base_url)` | 171 | Parse HTML, return absolute URLs |

### URL Discovery

| Function | Line | Purpose |
|----------|------|---------|
| `map_product_urls(source_key, source_cfg, paths)` | 188 | Async — discover product URLs from listing page |

### Extraction Strategies

| Function | Line | Purpose |
|----------|------|---------|
| `_is_rate_limit_error(error_str)` | 263 | Detect rate-limit/quota errors |
| `_build_llm_strategy(extraction_cfg)` | 274 | Create LLMExtractionStrategy from config |
| `_build_css_strategy(extraction_cfg)` | 303 | Create JsonCssExtractionStrategy from config |
| `extract_specs(urls, extraction_cfg, paths)` | 316 | Async — main extraction loop with resume |
| `_parse_extraction_result(result, url)` | 450 | Parse Crawl4AI LLM extraction result |
| `_slug_to_name(url)` | 477 | Convert URL slug to model name |

### Markdown Parser

| Function/Constant | Line | Purpose |
|-------------------|------|---------|
| `_MD_ROW_MAP` (dict) | 488 | Maps row labels to (field, is_per_size, needs_range) |
| `_SIZE_LABEL_HINTS` (set) | 533 | Known size label values |
| `_strip_md_formatting(s)` | 538 | Strip `**bold**` and `*italic*` markers |
| `_parse_number(s)` | 543 | Parse numeric string (handles EU decimals) |
| `_parse_weight_range(s)` | 557 | Parse "65-85" into (min, max) |
| `parse_specs_from_markdown(markdown, url)` | 567 | Main parser — markdown → structured dict |

### Strategy Selection

| Function | Line | Purpose |
|----------|------|---------|
| `_check_llm_availability(extraction_cfg)` | 766 | Check if API key env var is set |
| `_prompt_strategy_choice(extraction_cfg)` | 773 | Interactive strategy selection prompt |

### Single URL Test

| Function | Line | Purpose |
|----------|------|---------|
| `extract_single_url(url, extraction_cfg)` | 825 | Async — extract and display one URL |

### CSV Conversion

| Function | Line | Purpose |
|----------|------|---------|
| `convert_json_to_csv(raw_data, slug, is_current)` | 898 | Raw JSON → CSV rows |
| `write_csv(rows, output_path)` | 962 | Write CSV file to disk |

### Main CLI

| Function | Line | Purpose |
|----------|------|---------|
| `main()` | 976 | CLI argument parser + mode dispatcher |

---

## 18. Data Structures & Constants

### `_MD_ROW_MAP` — Row Label Mapping (43 entries)

Maps lowercase row labels (as they appear in markdown tables) to extraction targets.

```python
{
    # Cell count (model-level, not per-size)
    "number of cells":          ("cell_count",        False, False),
    "cells":                    ("cell_count",        False, False),

    # Flat area (per-size)
    "flat area":                ("flat_area_m2",      True,  False),
    "flat area (m2)":           ("flat_area_m2",      True,  False),
    "flat area (m^2)":          ("flat_area_m2",      True,  False),
    "area flat":                ("flat_area_m2",      True,  False),  # Legacy Ozone

    # Projected area (per-size)
    "projected area":           ("proj_area_m2",      True,  False),
    "projected area (m2)":      ("proj_area_m2",      True,  False),
    "area proj.":               ("proj_area_m2",      True,  False),  # Legacy Ozone
    "area proj":                ("proj_area_m2",      True,  False),

    # Flat span (per-size)
    "flat span":                ("flat_span_m",       True,  False),
    "flat span (m)":            ("flat_span_m",       True,  False),
    "span flat":                ("flat_span_m",       True,  False),  # Legacy Ozone

    # Projected span (per-size)
    "projected span":           ("proj_span_m",       True,  False),
    "projected span (m)":       ("proj_span_m",       True,  False),
    "span proj.":               ("proj_span_m",       True,  False),  # Legacy Ozone
    "span proj":                ("proj_span_m",       True,  False),

    # Aspect ratios (per-size)
    "flat aspect ratio":        ("flat_aspect_ratio",  True,  False),
    "projected aspect ratio":   ("proj_aspect_ratio",  True,  False),
    "ar flat":                  ("flat_aspect_ratio",  True,  False),  # Legacy Ozone
    "ar proj.":                 ("proj_aspect_ratio",  True,  False),  # Legacy Ozone
    "ar proj":                  ("proj_aspect_ratio",  True,  False),

    # Glider weight (per-size)
    "glider weight":            ("wing_weight_kg",    True,  False),
    "glider weight (kg)":       ("wing_weight_kg",    True,  False),
    "wing weight":              ("wing_weight_kg",    True,  False),
    "wing weight (kg)":         ("wing_weight_kg",    True,  False),
    "weight (kg)":              ("wing_weight_kg",    True,  False),

    # Weight range (per-size, needs range parsing)
    "certified weight range":   ("_ptv_range",        True,  True),
    "certified weight range (kg)": ("_ptv_range",     True,  True),
    "in-flight weight range":   ("_ptv_range",        True,  True),
    "in-flight weight range (kg)": ("_ptv_range",     True,  True),
    "in flight weight range":   ("_ptv_range",        True,  True),
    "weight range":             ("_ptv_range",        True,  True),
    "weight range (kg)":        ("_ptv_range",        True,  True),

    # Certification (per-size)
    "en":                       ("certification",     True,  False),
    "en/ltf":                   ("certification",     True,  False),
    "ltf / en":                 ("certification",     True,  False),  # Legacy Ozone
    "certification":            ("certification",     True,  False),
    "ltf":                      ("certification",     True,  False),

    # Root chord (per-size, not in DB schema yet)
    "root chord":               ("root_chord_m",      True,  False),
}
```

### `_SIZE_LABEL_HINTS` — Known Size Names

```python
{"xs", "s", "ms", "sm", "m", "ml", "l", "xl", "xxl",
 "xxs", "xxxl", "22", "23", "24", "25", "26", "27", "28",
 "29", "30", "31"}
```

Numeric sizes (22-31) are used by harness manufacturers.

### `CSV_COLUMNS` — Output Column Order

```python
["manufacturer_slug", "name", "year", "category", "target_use", "is_current",
 "cell_count", "line_material", "riser_config", "manufacturer_url", "description",
 "size_label", "flat_area_m2", "flat_span_m", "flat_aspect_ratio",
 "proj_area_m2", "proj_span_m", "proj_aspect_ratio",
 "wing_weight_kg", "ptv_min_kg", "ptv_max_kg",
 "speed_trim_kmh", "speed_max_kmh", "glide_ratio_best", "min_sink_ms",
 "cert_standard", "cert_classification", "cert_test_lab", "cert_test_date",
 "cert_report_url"]
```

### Error Types

```python
class CreditExhaustedError(Exception):
    """Raised when the LLM provider returns a rate-limit or quota error."""
```

---

## 19. Known Limitations

### Current Limitations

1. **Model year not extracted** — Not available on Ozone product pages. Would need
   release date data from another source.

2. **Line material not extracted** — Listed in a "Materials" prose section, not in the
   spec table. Would need a secondary parser (regex or LLM).

3. **Performance data not extracted** — Speed, glide ratio, sink rate are not in spec
   tables. Would need flight test data from certification reports.

4. **Single spec table only** — The parser only finds the first spec table on each page.
   If specs are split across multiple tables (rare), only the first is captured.

5. **Model name heuristics** — The page title extraction has safeguards against nav items
   but could theoretically pick up wrong text on unusually structured pages.

6. **No validation against external data** — Extracted specs are not cross-referenced
   with DHV Geräteportal or other sources in this pipeline.

7. **root_chord_m extracted but not in DB schema** — The markdown parser extracts root
   chord data, but the DB schema and CSV format don't have a column for it. The data
   exists in the raw JSON but is lost during CSV conversion.

### Scalability Considerations

- Playwright browser startup: ~1-2 seconds overhead per session (amortized across pages)
- Memory: Chromium Headless Shell uses ~200-400MB RAM
- Disk: Output files are small (~240KB JSON, ~90KB CSV for 115 models)
- Network: One HTTP request per page (~2-3 seconds including JS render time)
- Parallelism: Current implementation is sequential (one page at a time). Could be
  parallelized with Crawl4AI's batch mode for faster extraction.

---

## Appendix A: Portable Extraction Prompt Kit

Located at `tools/spec-extractor/prompts/extraction-prompt-kit.md`.

This document contains a complete extraction prompt + JSON schema that can be used
manually with any LLM (ChatGPT, Gemini, Claude). It includes:

1. Step-by-step instructions for each LLM platform
2. The exact JSON schema (same as in the YAML config)
3. Legal compliance guardrails
4. Validation checklist
5. Example output

This enables contributors to extract data for new brands without running the tool.

## Appendix B: Copilot Agent

Located at `.github/agents/paraglider-data-extractor.agent.md`.

A custom Copilot agent that orchestrates the extraction workflow:
- Guides users through creating new manufacturer configs
- Runs the extraction tool
- Validates extracted data
- Generates enrichment CSV and guides import
- Write-restricted to `tools/spec-extractor/`, `documentation/data/`, and `data/`

## Appendix C: Ozone Website Technical Details

| Aspect | Detail |
|--------|--------|
| Framework | Next.js + Sanity CMS |
| Rendering | Fully JS-rendered (SSR + client hydration) |
| Product URL pattern | `/paragliders/products/gliders/{slug}` |
| Listing pages | `/products/gliders` (current), `/products/previous-gliders` |
| Spec table format | Modern: pipe-wrapped rows. Legacy: non-wrapped, EU decimals |
| Page size | ~327-546 KB rendered HTML |
| Render time | ~2-3 seconds per page |
| Rate limiting | None observed at 1 req/sec |
| CDN | Cloudflare (no blocking at this rate) |
| Image hosting | Sanity CDN (`cdn.sanity.io`) |
