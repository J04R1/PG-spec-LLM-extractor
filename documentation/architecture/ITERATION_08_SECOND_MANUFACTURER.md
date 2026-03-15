# Iteration 08 — Second Manufacturer (Advance)

## Goal

Validate the pipeline against a second manufacturer (Advance.swiss) to prove it
is not Ozone-specific. Fix any hardcoded assumptions discovered during the process.

## Scope

- **8-model validation sample** (6 current + 2 discontinued)
- Baseline: `data/advance_enrichment_all.csv` (23 models, 118 rows, LLM-extracted)

### Validation Models

| Model | Cert | Current | URL |
|-------|------|---------|-----|
| ALPHA | A | yes | /products/paragliders/alpha-series/alpha |
| EPSILON DLS | B | yes | /products/paragliders/epsilon-dls |
| SIGMA DLS | C | yes | /products/paragliders/sigma-dls |
| OMEGA ULS | D | yes | /products/paragliders/omega-uls |
| PI ULS | B-D | yes | /products/paragliders/pi-uls |
| BIBETA 6 | A | yes | /products/paragliders/bibeta-6 |

Discontinued models may not have individual crawlable pages (all point to
`/services/downloads`), so validation focuses on current models.

## Changes Made

### Code Changes

1. **`config/manufacturers/advance.yaml`** — new config for Advance
2. **`src/markdown_parser.py`**:
   - `parse_specs_from_markdown()` now accepts optional `manufacturer_name` param
   - Breadcrumb check no longer hardcodes "ozone"
   - Added Advance-specific label mappings: "flat surface", "projected surface",
     "certified takeoff weight", "recommended takeoff weight", "span", "aspect ratio"
   - Unit column detection: auto-strips the unit column (m2, kg, m) when tables
     have `Label | Unit | Val1 | Val2 | ...` format (Advance-style)
   - Extended `_SIZE_LABEL_HINTS` to cover sizes 14-45 (was 16-31), supporting
     miniwings and tandems
3. **`src/extractor.py`** — `_extract_via_markdown()` forwards `manufacturer_name`
   from config to the markdown parser
4. **`tests/validate_advance.py`** — validation script for Advance (8-model sample)

### Key Decisions

- No `previous_gliders` source — Advance discontinued models share a generic
  downloads page and can't be individually crawled
- Cookie consent wall on advance.swiss — Crawl4AI with Playwright handles it
- Advance uses numeric size labels (22, 24, 26, 28, 31) instead of letter sizes (XS, S, M, L)

## Validation Results

### Markdown Parser — 93.9% overall (387/412 fields)

| Model | Result | Match | Sizes | Notes |
|-------|--------|-------|-------|-------|
| ALPHA | PASS | 55/55 (100%) | 5/5 | |
| ALPHA DLS | PASS | 55/55 (100%) | 5/5 | |
| EPSILON DLS | PASS | 55/55 (100%) | 5/5 | |
| SIGMA DLS | PASS | 55/55 (100%) | 5/5 | |
| OMEGA ULS | PASS | 44/44 (100%) | 4/4 | |
| PI ULS | WARN | 56/71 (78.9%) | 7/7 | Load-dependent cert (B/C/D by weight range) — page uses separate cert rows per class |
| BIBETA 6 | PASS | 22/22 (100%) | 2/2 | Tandem wing |
| IOTA DLS | WARN | 45/55 (81.8%) | 5/5 | Baseline proj_span/proj_aspect_ratio values differ from website — website is authoritative |

### Known Limitations

- **PI ULS load-dependent certification**: The PI ULS has different EN cert classes
  depending on pilot weight range (A/B/C/D). The page shows separate weight range
  rows per cert class instead of a single "Certification" row. The parser doesn't
  handle this format — would need LLM or custom logic.
- **IOTA DLS proj values**: The baseline (LLM-extracted) has different projected
  span and aspect ratio values than the live website shows. The website data is
  the ground truth — the baseline was inaccurate for these fields.

## Test Results

129 tests pass — no regressions from Ozone or any other module.

## Status

COMPLETE
