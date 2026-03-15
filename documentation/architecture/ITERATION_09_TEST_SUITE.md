# Iteration 09 — Pipeline Test Suite

**Status:** Complete
**Date:** March 2026

---

## Summary

Created a comprehensive pytest-based test suite covering every pipeline step and a full end-to-end flow. Tests use **real-world verified spec data** from two manufacturers (Ozone + Advance) as ground truth, with strict numeric assertions on 10 key spec fields. The test suite acts as a quality gate before iterations 07 (Ozone validation run) and 08 (second manufacturer).

This iteration also fixed **3 real bugs** discovered by the tests:
1. Normalizer didn't handle `EN/LTF B` certification format (common Ozone pattern)
2. Parser's `_SIZE_LABEL_HINTS` was missing numeric sizes 16–21 (Advance-style wings)
3. Normalizer's `_SIZE_MAP` incorrectly converted numeric area-based sizes (21→L, 22→XL) to alpha equivalents, destroying Advance manufacturer data

---

## Goals Met

### Goal 1: Quality Gate for Pipeline Correctness

Every pipeline step has dedicated unit tests that verify correct behavior in isolation before being composed in E2E tests. Any future code change that corrupts spec values immediately fails.

### Goal 2: Strict Data Quality on Key Spec Fields

10 fields are asserted to ±0.01 tolerance (or exact match for integers):

| Field | Description | Tolerance |
|-------|-------------|-----------|
| `cell_count` | Number of cells | Exact int |
| `flat_area_m2` | Flat area | ±0.01 |
| `flat_span_m` | Flat span | ±0.01 |
| `flat_aspect_ratio` | Flat AR | ±0.01 |
| `proj_area_m2` | Projected area | ±0.01 |
| `proj_span_m` | Projected span | ±0.01 |
| `proj_aspect_ratio` | Projected AR | ±0.01 |
| `wing_weight_kg` | Glider weight | ±0.01 |
| `ptv_min_kg` | Min pilot weight | Exact |
| `ptv_max_kg` | Max pilot weight | Exact |

### Goal 3: Multi-Manufacturer Coverage

Two distinct fixture types prove the pipeline handles both sizing systems:

- **Ozone Swift 6** — Alpha size labels (XS/S/MS/ML/L), 5 sizes, 62 cells, EN B
  - Ground truth: `data/ozone_enrichment.csv`
  - Source: https://flyozone.com/paragliders/products/gliders/swift-6
- **Advance IOTA DLS** — Numeric area-based labels (21/23/25/27/29), 5 sizes, 59 cells, EN B
  - Ground truth: `data/advance_enrichment_all.csv`
  - Source: https://www.advance.swiss/en/products/paragliders/iota-dls

### Goal 4: No External Dependencies Required

All 129 tests run without network, Ollama, or Crawl4AI browser. Mock adapters simulate the LLM path. `./run_tests.sh` gives clear visual pass/fail feedback.

---

## What Each Test Module Does

### `tests/conftest.py` — Shared Fixtures & Ground Truth

**Purpose:** Single source of truth for test data. All ground truth values are verified against real enrichment CSVs.

- `SWIFT6_MARKDOWN` / `ADVANCE_IOTA_DLS_MARKDOWN` — Reconstructed spec tables in pipe-delimited markdown (Ozone format with EU decimal notation)
- `SWIFT6_EXPECTED` / `IOTA_DLS_EXPECTED` — Dict mapping size_label → exact expected spec values for all 10 key fields
- `MockAdapter` — Returns a canned Swift 6 `ExtractionResult` for any input (tests the LLM extraction path without Ollama)
- `FailingAdapter` — Always raises `RuntimeError` to test fallback paths
- `assert_spec_field()` / `assert_size_specs()` — Helpers for strict float comparison with clear error messages showing field name, actual vs expected
- `tmp_db` fixture — Isolated temp SQLite `Database`, auto-closed after test
- `sample_config` / `ozone_manufacturer` — Reusable config and model fixtures

### `tests/test_models.py` — Pydantic Model Validation (11 tests)

**Goal:** Verify data model contracts before anything else in the pipeline uses them.

- `ExtractionResult` round-trips correctly through `model_dump()` / `model_validate()`
- Missing required `model_name` raises `ValidationError`
- `SizeSpec` only requires `size_label` (all spec fields optional for partial extraction)
- All 4 enums (`WingCategory`, `TargetUse`, `CertStandard`, `EntityType`) have correct string values

### `tests/test_config.py` — Configuration Loading (6 tests)

**Goal:** Verify YAML config loads correctly and output paths follow conventions.

- `load_config()` with real `config/manufacturers/ozone.yaml` returns a dict with `manufacturer.slug`
- `get_output_paths("ozone")` returns all 5 expected path keys (`raw_json`, `partial`, `csv`, `urls`, `db`)
- DB path is shared across manufacturers (`paragliders.db`)
- All values are `Path` objects

### `tests/test_markdown_parser.py` — Deterministic Parser (26 tests)

**Goal:** **Strictest module** — proves the parser extracts exact numeric values from spec tables, not just "something parseable."

- **Swift 6 full extraction (11 tests):** Parses markdown → asserts model metadata, 5 sizes with correct labels, then verifies ALL 9 spec fields for EACH of the 5 sizes against ground truth. Any field off by >0.01 fails.
- **Advance IOTA DLS (10 tests):** Same rigor with numeric size labels (21/23/25/27/29), 59 cells, varying projected aspect ratios (4.01–4.03)
- **Rush 6 backward compat (4 tests):** Existing fixture from `validate_pipeline.py` still parses correctly
- **Edge cases:** EU decimal ("20,14"→20.14), weight range splitting ("55-72"→55.0/72.0 and "65 – 85"→65.0/85.0), no-table→None, URL slug inference

### `tests/test_normalizer.py` — Normalization Logic (18 tests)

**Goal:** Verify normalization preserves data integrity — raw spec values must survive normalization unchanged.

- **Certification (10 patterns):** EN B, LTF A, CCC, CIVL CCC, DHV 1-2, DHV 1, bare "B", EN-C, EN/LTF B, EN D
- **Size labels:** "extra small"→XS, "xs"→XS, MS/ML preserved as-is, numeric "23"/"29" preserved
- **Slugs:** `make_model_slug("ozone", "Swift 6")` → "ozone-swift-6"
- **Full normalization (8 tests):** Parse Swift 6 → `normalize_extraction()` → verify wing slug, 5 sizes, 5 certs, size label order, **all spec values still match ground truth after normalization**, cell_count preserved, source URL set

### `tests/test_extractor.py` — Extraction Bridge (9 tests)

**Goal:** Verify the LLM-first/markdown-fallback strategy works correctly.

- **Schema:** `get_extraction_schema()` has `properties` key with `model_name` and `sizes`
- **Fallback (3 tests):** `adapter=None` → markdown parser produces 5 sizes with strict XS spec values; no URL → returns None
- **MockAdapter (3 tests):** LLM path returns valid result with 2 sizes, preserves exact spec values
- **FailingAdapter (2 tests):** LLM raises → falls back to markdown parser → 5 sizes with strict S spec values

### `tests/test_db.py` — Database Operations (12 tests)

**Goal:** Verify SQLite storage preserves exact spec values through the write→read round-trip.

- **Schema:** All 5 tables exist after `connect()`, FK constraints enabled
- **Upsert idempotency:** Same slug → same ID (manufacturer, model, size_variant)
- **Exact value round-trip:** Insert Swift 6 XS with all 9 spec values → read back from DB → assert each value matches within ±0.01
- **Certification:** Stores correct `standard` and `classification` columns
- **Provenance:** `record_provenance()` creates `data_sources` entry with correct `entity_type`, `source_url`, `source_name`
- **FK enforcement:** Inserting a size_variant with invalid model_id raises `IntegrityError`

### `tests/test_crawler_unit.py` — Crawler Utilities (14 tests)

**Goal:** Verify crawler helpers work correctly without any network calls.

- **Rate limit detection:** "429", "rate limit", "quota exhausted", "402 Payment Required" all detected; "404 Not Found" is not
- **Link extraction:** Absolute URLs preserved, relative URLs resolved against base, fragment-only links excluded
- **Deduplication:** Removes duplicate URLs; upgrades `is_current` flag when a current source provides a previously-archived URL
- **Partial save/load:** Atomic JSON roundtrip; missing file returns `[]`
- **URL cache keyed:** Keyed save/load roundtrip; missing key returns `None`

### `tests/test_e2e.py` — End-to-End Pipeline (12 tests)

**Goal:** **Most important module** — proves the full pipeline produces correct data end-to-end.

Each test exercises the complete flow: **markdown → extract → normalize → DB store → read back → verify**

- **Swift 6 pipeline (6 tests):** Manufacturer exists in DB, model slug = "ozone-swift-6", 5 sizes stored, 5 certifications, ≥6 provenance records, **strict verification of ALL 9 key spec fields for ALL 5 sizes read back from DB**
- **Advance IOTA DLS pipeline (2 tests):** Numeric size labels (21–29) stored correctly, **strict spec values for all 5 sizes from DB**
- **CSV export (4 tests):** 27 columns matching `_CSV_COLUMNS`, 5 rows (one per size), strict flat_area/weight spot-checks, cert_standard="EN" and cert_classification="B"
- **Idempotency:** Run pipeline twice on same data → 1 manufacturer, 1 model, 5 size_variants (no duplicates)
- **Mock LLM pipeline:** `MockAdapter` → full flow → 2 sizes stored, XS spec values verified from DB

---

## Bugs Found & Fixed

### Bug 1: `EN/LTF B` certification normalization

**File:** `src/normalizer.py`
**Problem:** `normalize_certification("EN/LTF B")` returned `(EN, "")` — dropped the classification letter "B". This is the most common Ozone certification format.
**Fix:** Added a combined EN/LTF pattern handler before the general regex matcher.

### Bug 2: Missing numeric size hints 16–21

**File:** `src/markdown_parser.py`
**Problem:** `_SIZE_LABEL_HINTS` only had sizes 22–31. When parsing IOTA DLS with size "21", the parser couldn't identify it as a size label, causing the "21" column to be consumed as a data row and all values to shift by one position.
**Fix:** Added sizes 16–21 to `_SIZE_LABEL_HINTS`.

### Bug 3: Numeric sizes mapped to alpha equivalents

**File:** `src/normalizer.py`
**Problem:** `_SIZE_MAP` mapped "21"→"L", "22"→"XL", "18"→"XS", etc. These were wrong for Advance-style wings where "21" means a 21 m² flat area wing, not a "Large" wing. Also mapped PTV weights (70→XS, 85→L) which were never valid size labels.
**Fix:** Removed all double-digit numeric and weight-based mappings. Numeric and non-standard labels are now preserved as-is.

---

## Files Created

| File | Purpose |
|------|---------|
| `tests/conftest.py` | Shared fixtures, ground truth data, mock adapters, assertion helpers |
| `tests/test_models.py` | Pydantic model validation (11 tests) |
| `tests/test_config.py` | Config loading & output paths (6 tests) |
| `tests/test_markdown_parser.py` | Deterministic parser with strict spec assertions (26 tests) |
| `tests/test_normalizer.py` | Cert/size/slug normalization with data integrity checks (18 tests) |
| `tests/test_extractor.py` | Extraction bridge — LLM, fallback, schema (9 tests) |
| `tests/test_db.py` | DB operations with exact value round-trip (12 tests) |
| `tests/test_crawler_unit.py` | Crawler utilities without network (14 tests) |
| `tests/test_e2e.py` | Full pipeline E2E with strict data quality (12 tests) |
| `run_tests.sh` | Executable test runner with banner output |

## Files Modified

| File | Changes |
|------|---------|
| `pyproject.toml` | Added `[project.optional-dependencies] dev = ["pytest>=8.0", "pytest-sugar>=1.0"]` |
| `src/normalizer.py` | Fixed EN/LTF B handling; removed incorrect numeric size mappings |
| `src/markdown_parser.py` | Added sizes 16–21 to `_SIZE_LABEL_HINTS` |

## Files Unchanged

| File | Status |
|------|--------|
| `tests/validate_pipeline.py` | Kept as-is (legacy validation script) |
| `tests/test_crawler.py` | Kept as-is (existing crawler tests) |

---

## Ground Truth Data Sources

| Fixture | Source File | Verified Against |
|---------|------------|-----------------|
| Ozone Swift 6 (XS/S/MS/ML/L) | `data/ozone_enrichment.csv` | https://flyozone.com/paragliders/products/gliders/swift-6 |
| Advance IOTA DLS (21/23/25/27/29) | `data/advance_enrichment_all.csv` | https://www.advance.swiss/en/products/paragliders/iota-dls |
| Ozone Rush 6 (XS/S/M/ML/L) | `tests/validate_pipeline.py` | Original POC validation fixture |

---

## Running the Tests

```bash
# Install dev dependencies (one-time)
pip install -e ".[dev]"

# Run full suite with visual feedback
./run_tests.sh

# Run specific module
python -m pytest tests/test_markdown_parser.py -v

# Run only E2E tests
python -m pytest tests/test_e2e.py -v

# Run with extra verbose for debugging
python -m pytest tests/ -vv --tb=long
```

**Requirements:** Python 3.11+, no network, no Ollama, no browser.

**Total:** 129 tests across 8 modules — all green.
