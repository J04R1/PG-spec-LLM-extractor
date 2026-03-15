# Spec Extractor — OpenPG Data Extraction Tool

A standalone tool for extracting factual paraglider specifications from manufacturer
websites. Produces enrichment CSVs compatible with the main OpenPG import pipeline.

## Why This Exists

The main API codebase should not depend on heavy scraping/rendering libraries.
This tool is **isolated** — it has its own virtual environment and dependencies,
and only communicates with the main project via CSV files dropped into `data/`.

## Architecture

```
spec-extractor/
├── extract.py            # Main CLI entrypoint
├── config/
│   └── manufacturers/   # One YAML file per manufacturer
│       └── ozone.yaml
├── strategies/           # Pluggable extraction strategies
│   ├── css_strategy.py   # CSS selector-based (zero LLM cost)
│   └── llm_strategy.py   # LLM-powered fallback (Gemini free tier)
├── prompts/              # Portable extraction prompt kit
│   └── extraction-prompt-kit.md
├── output/               # Raw JSON + CSV output (gitignored except .gitkeep)
│   └── .gitkeep
└── README.md             # This file
```

## Setup

**Important:** Use a separate virtual environment — do NOT install into the main
project venv. This tool has heavy dependencies (Playwright browser engine) that
the API server does not need.

```bash
cd tools/spec-extractor

# Create isolated venv
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install crawl4ai pyyaml httpx

# Set up Playwright browser (required for JS-rendered pages)
crawl4ai-setup

# Verify installation
crawl4ai-doctor
```

## Dependencies

These are installed in the tool's own venv, **not** in the main project:

| Package | Purpose |
|---------|---------|
| `crawl4ai` | Web crawling + extraction (wraps Playwright for JS rendering) |
| `pyyaml` | Read manufacturer config files |
| `httpx` | HTTP client (used by Crawl4AI internally) |

## Usage

```bash
# Activate the tool's venv
cd tools/spec-extractor
source .venv/bin/activate

# Extract previous Ozone gliders
python extract.py --config config/manufacturers/ozone.yaml

# Map URLs only (no extraction, just discover product pages)
python extract.py --config config/manufacturers/ozone.yaml --map-only

# Extract a single URL (for testing)
python extract.py --url https://flyozone.com/paragliders/products/gliders/rush-5

# Retry failed extractions
python extract.py --config config/manufacturers/ozone.yaml --retry-failed

# Convert existing raw JSON to CSV (no web requests)
python extract.py --config config/manufacturers/ozone.yaml --convert-only
```

## Adding a New Manufacturer

1. Copy an existing config: `cp config/manufacturers/ozone.yaml config/manufacturers/niviuk.yaml`
2. Update the URLs, selectors, and field mappings
3. Run with `--map-only` to verify URL discovery
4. Run a test extraction on 2–3 pages
5. Run full extraction

See `config/manufacturers/ozone.yaml` for a documented example.

## Output Pipeline

```
Manufacturer website
  → Crawl4AI renders JS pages
  → CSS or LLM extracts structured specs
  → output/<manufacturer>_raw.json (incremental, crash-safe)
  → output/<manufacturer>_enrichment.csv
  → ../../scripts/import_enrichment_csv.py (imports to DB)
```

## Crash Recovery

The tool saves progress after every page extraction to a `.partial` file.
If interrupted (Ctrl+C, crash, rate limit), re-running the same command
automatically resumes from where it left off.

## Legal Compliance

This tool extracts **only factual technical specifications** (weight, area, cells, etc.)
which are not copyrightable under US Feist doctrine or EU law. It explicitly avoids:
- Marketing descriptions or prose
- Images, logos, or media
- Proprietary diagrams or color tools
- Curated reviews or opinions

See `prompts/extraction-prompt-kit.md` for the full compliance framework.
