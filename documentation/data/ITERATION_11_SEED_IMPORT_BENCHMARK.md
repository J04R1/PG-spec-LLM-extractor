# ITERATION 11 — SEED IMPORT & BENCHMARK

**Date:** 2026-03-15
**Status:** Complete
**Folder:** `data/`

---

## Goal

Import existing LLM-enriched CSVs (ozone, advance) as seed data into the v2 schema, and build a benchmark scoring system that measures **completeness**, **quality**, and **accuracy** — usable as a baseline for comparing future extraction methods and models.

---

## What Was Built

### 1. Seed Import Module (`src/seed_import.py`)

CSV → database importer that maps the 30-column enrichment CSV format to the 7-table schema:

- Groups rows by `(manufacturer_slug, model_name)` → model + sizes
- Maps CSV columns to domain models via robust parsers (`_safe_int`, `_safe_float`, `_safe_bool`)
- Creates provenance records tracking the import source and method
- Stores target_use via junction table
- Separates performance data (speed, glide, sink) into `performance_data` table
- Skips `description` column (facts-only policy)

### 2. Benchmark Scoring Module (`src/benchmark.py`)

Three-dimension scoring engine:

| Dimension | What it measures | How |
|-----------|-----------------|-----|
| **Completeness** | Field population rate | `populated / total` per field, averaged across table |
| **Quality** | Value plausibility | Range checks (e.g., flat_area 10–50 m², cell_count 15–120) |
| **Accuracy** | Internal consistency | Cross-field checks (e.g., `area ≈ span²/AR`, `ptv_min < ptv_max`, `proj < flat`) |

#### Plausibility Ranges

```python
flat_area_m2:      (10.0, 50.0)     cell_count:       (15, 120)
flat_span_m:       (6.0, 20.0)      year_released:    (1990, 2026)
flat_aspect_ratio: (2.5, 8.5)       wing_weight_kg:   (1.0, 12.0)
proj_area_m2:      (8.0, 42.0)      speed_trim_kmh:   (25.0, 50.0)
proj_span_m:       (5.0, 17.0)      speed_max_kmh:    (35.0, 80.0)
proj_aspect_ratio: (2.0, 7.0)       glide_ratio_best: (5.0, 15.0)
ptv_min_kg:        (30.0, 200.0)    min_sink_ms:      (0.7, 1.8)
ptv_max_kg:        (40.0, 250.0)    line_length_m:    (4.0, 12.0)
```

#### Consistency Checks

| Check | Table | Rule |
|-------|-------|------|
| `ptv_min_lt_max` | size_variants | ptv_min < ptv_max |
| `flat_area_span_ar_consistent` | size_variants | area ≈ span²/AR (±5%) |
| `proj_area_span_ar_consistent` | size_variants | same for projected |
| `proj_lt_flat_area` | size_variants | projected area < flat area |
| `discontinued_has_year` | models | is_current=0 → year_discontinued populated |
| `released_before_discontinued` | models | year_released ≤ year_discontinued |
| `classification_valid_for_standard` | certifications | EN → {A,B,C,D} |
| `trim_lt_max_speed` | performance_data | trim speed < max speed |

### 3. CLI Commands

```bash
# Import a CSV
python -m src.pipeline seed --csv data/ozone_enrichment_all_by_LLM.csv --db output/ozone.db

# Run benchmark
python -m src.pipeline benchmark --db output/seed_benchmark.db
python -m src.pipeline benchmark --db output/seed_benchmark.db --json
```

---

## Seed Import Results

### Combined (Ozone + Advance)

| Entity | Count |
|--------|-------|
| Manufacturers | 2 |
| Models | 60 |
| Size variants | 277 |
| Certifications | 277 |
| Performance records | 18 |

### Benchmark Scores

| Metric | Combined | Ozone | Advance |
|--------|----------|-------|---------|
| **Completeness** | 69.0% | 56.3% | 69.3% |
| **Quality** | 99.9% | 99.9% | 100.0% |
| **Accuracy** | 72.2% | 62.9% | 72.3% |

#### Per-Table Breakdown (Combined)

| Table | Records | Completeness | Quality | Accuracy |
|-------|---------|-------------|---------|----------|
| models | 60 | 98.9% | 100.0% | 0.0% |
| size_variants | 277 | 84.2% | 99.7% | 99.6% |
| certifications | 277 | 42.9% | 100.0% | 89.2% |
| performance_data | 18 | 50.0% | 100.0% | 100.0% |

### Key Findings

1. **Quality is excellent** (99.9%) — LLM-extracted values are almost all within plausible ranges
2. **Accuracy drag from models** (0.0%) — 27 discontinued models have no `year_discontinued` set (enrichment CSVs don't have this data); this is a known gap, not an error
3. **Certification completeness low** (42.9%) — `test_lab` is never populated; `report_url` and `test_date` only from Advance (they publish cert PDFs)
4. **Performance data sparse** — only 18 records (all Advance), no glide/sink data; Ozone doesn't publish performance specs on product pages
5. **Size geometry** — `proj_span_m` only 65% populated (some manufacturers only publish flat geometry)
6. **Implausible values flagged**: 3 wing weights <1kg (likely single-skin or miniwing), 2 PTV max >250kg (tandem), flat_area 8.0 m² (speedwing) — all correct for their niche categories, plausibility ranges are tuned for standard paragliders

---

## Files Changed

| File | Change |
|------|--------|
| `src/seed_import.py` | **New** — CSV → DB import module |
| `src/benchmark.py` | **New** — Benchmark scoring engine |
| `src/pipeline.py` | Added `seed` and `benchmark` CLI commands |
| `tests/test_seed_import.py` | **New** — 26 tests (parsers, builders, integration) |
| `tests/test_benchmark.py` | **New** — 20 tests (score math, integration, bad data) |

## Test Results

```
175 passed in 1.87s (129 existing + 46 new)
```

---

## Using as a Benchmark Baseline

The JSON output from `benchmark --json` produces a stable format for comparison:

```json
{
  "extraction_method": "llm_enrichment_csv",
  "models": 60,
  "sizes": 277,
  "completeness": 0.69,
  "quality": 0.9992,
  "accuracy": 0.7219
}
```

Future extraction runs (different LLM models, re-crawled data, DHV imports) can produce the same format and be compared directly against these baseline numbers.
