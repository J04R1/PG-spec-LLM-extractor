# Iteration 15 — DHV Data Analysis for Seed Import

**Date:** 2026-03-15
**Status:** Analysis
**Domain:** data

---

## Goal

Assess the DHV Geräteportal data files in `data/` and determine how they
could be integrated into the validated import pipeline built in Iteration 14.

---

## Available DHV Files

| File | Rows | Content |
|------|------|---------|
| `data/dhv_unmatched.csv` | 3,192 | Certification records that failed matching against existing DB |
| `data/dhv_unmatched_dryrun_2026-03-11.csv` | 18 | Small dry-run subset (same format) |
| `data/dhv_gap_report.md` | — | Structured analysis of the unmatched data |
| `data/dhv_cache/` | 2,892 files | Cached DHV listing pages (search result HTML, not individual reports) |

### Other data files (not DHV)

| File | Rows | Content |
|------|------|---------|
| `data/fredvol_raw.csv` | 6,481 | Historical specs from fredvol/Paraglider_specs_studies (GliderBase) |
| `data/manufacturers_enrichment.csv` | — | Manufacturer slug/country/website mapping |
| `data/ozone_enrichment.csv` | — | Base Ozone specs (111 models, POC markdown parser) |
| `data/ozone_enrichment_all_by_LLM.csv` | — | LLM-enriched Ozone specs (33 models) |
| `data/advance_enrichment_all_by_LLM.csv` | — | LLM-enriched Advance specs (27 models) |

---

## DHV CSV Structure

```
dhv_url,manufacturer,model,size,equipment_class,test_centre,test_date,report_url,match_failure_reason
```

### Column mapping to our import format

| DHV column | Our CSV column | Mapping notes |
|---|---|---|
| `manufacturer` | `manufacturer_slug` | Needs normalization ("OZONE Gliders Ltd." → "ozone") |
| `model` | `name` | Inconsistent naming (see below) |
| `size` | `size_label` | Direct mapping |
| `equipment_class` | `cert_classification` | A/B/C/D classes |
| — | `cert_standard` | Always "EN" (DHV tests to EN standard) |
| `test_date` | `cert_test_date` | Direct mapping |
| `report_url` | `cert_report_url` | Often empty |
| `dhv_url` | — | Provenance URL, not in import CSV |
| `test_centre` | `cert_test_lab` | Often empty |

### Fields NOT in DHV data (our import needs these)

- `year`, `category`, `target_use`, `is_current`, `cell_count`
- `line_material`, `riser_config`, `manufacturer_url`
- `flat_area_m2`, `flat_span_m`, `flat_aspect_ratio`
- `proj_area_m2`, `proj_span_m`, `proj_aspect_ratio`
- `wing_weight_kg`, `ptv_min_kg`, `ptv_max_kg`
- `speed_trim_kmh`, `speed_max_kmh`, `glide_ratio_best`, `min_sink_ms`

**Conclusion:** DHV provides **only certification data** — no wing specifications.

---

## Failure Type Breakdown

| Reason | Count | Meaning |
|--------|-------|---------|
| Model not found | 2,413 | Model exists at DHV but not in our DB |
| Manufacturer not found | 655 | Manufacturer slug not mapped (119 unique manufacturers) |
| Size not found | 124 | Model exists in DB but specific size isn't |

---

## Manufacturer Coverage

Top manufacturers by missing models (from `data/dhv_gap_report.md`):

| Priority | Manufacturer | Missing Models | Missing Sizes |
|----------|-------------|---------------|---------------|
| P1 | ozone | 54 | 173 |
| P1 | nova | 74 | 202 |
| P1 | gin | 55 | 194 |
| P1 | advance | 39 | 105 |
| P1 | niviuk | 30 | 65 |
| P2 | skywalk | 41 | 157 |
| P2 | swing | 35 | 177 |
| P2 | u-turn | 23 | 72 |
| — | up | 60 | 194 |
| — | phi | 57 | 176 |
| — | macpara | 31 | 116 |

---

## Ozone-Specific Analysis

175 DHV rows across 54 unique model names. Many are name variations of models
already in `ozone.db`:

| DHV name | Likely DB match | Issue |
|----------|----------------|-------|
| `BuzzZ5` | `Buzz Z5` | Missing space |
| `Gliders Buzz Z3` | `Buzz Z3` | "Gliders " prefix |
| `Ultra lite` | `Ultralite` | Extra space |
| `Rush2` | `Rush 2` | Missing space |
| `Mc Daddy` | `Mcdaddy` | Spacing/casing |
| `Cosmic` | `Cosmic Rider` | Truncated name |
| `Mantra 2` | `Mantra M2` | Naming convention difference |

After normalization, the DHV data would primarily **add certifications to
existing models** — directly addressing the `no_certifications` issue that
affects 38 of our 83 pending Ozone models.

---

## Impact Assessment: Direct Seed Import

### Cannot import directly

The DHV CSV format (9 columns) does not match our enrichment CSV format
(30 columns). Running `pipeline seed` against DHV data would fail.

### If converted to our format

If a transformer script generated our 30-column CSV with only cert fields
populated, every imported model would immediately trigger warnings:

- `missing_year_released` — no year in DHV
- `missing_cell_count` — no specs in DHV
- `missing_manufacturer_url` — no URL in DHV
- `missing_flat_area_m2` — no geometry in DHV
- `missing_ptv_min_kg` / `missing_ptv_max_kg` — no weight range in DHV

The validation gate would **pass** these (warnings, not critical), so they'd
enter the DB — but as very sparse records with only certifications.

---

## Recommendation

The DHV data is most valuable as a **certification enrichment layer**, not a
standalone import source.

### Proposed approach: DHV adapter

Build a dedicated DHV importer (`src/dhv_import.py`) that:

1. **Normalizes manufacturer names → slugs** — map "OZONE Gliders Ltd." to
   "ozone", "ADVANCE Thun AG" to "advance", etc.
2. **Normalizes model names** — strip "Gliders " prefix, fix spacing, map
   known aliases ("Mantra 2" → "Mantra M2")
3. **Matches against existing DB** — only enrich models that already exist
4. **Inserts certifications** — standard=EN, class from `equipment_class`,
   test date + report URL as provenance
5. **Logs unmatched** — models that don't exist in DB are logged for future
   full extraction from manufacturer websites

### Integration into rebuild pipeline

Add DHV enrichment as an optional step in the `rebuild` command:

```yaml
# config/manufacturers/ozone.yaml
import:
  output_db: output/ozone.db
  csv_files:
    - path: data/ozone_enrichment.csv
      method: poc_markdown_parser
      label: "Base import (111 models from POC)"
    - path: data/ozone_enrichment_all_by_LLM.csv
      method: llm_enrichment
      label: "LLM enrichment (33 models)"
  dhv_enrichment:
    path: data/dhv_unmatched.csv
    label: "DHV certification enrichment"
```

### What this would fill

For the 38 Ozone models currently flagged with `no_certifications`, the DHV
data could add EN certification records with classification, test date, and
report URL — directly resolving those validation issues.

### What it cannot fill

DHV has no wing specs. Models missing `year_released`, `cell_count`, or
geometry data would still need those from manufacturer websites (web
extraction pipeline or AI-assisted research via the `fix` prompt).

### Future: fredvol cross-reference

`data/fredvol_raw.csv` (6,481 rows) contains historical specs from
GliderBase with geometry, weight ranges, and certifications. This is a
potential second enrichment source that could fill spec gaps, but:

- Needs its own adapter (different column names: `flat_AR`, `ptv_maxi`, etc.)
- Data quality unknown (no validation against known-good sources yet)
- Excluded from Iteration 14 scope by design decision

---

## Files

No code changes in this iteration — analysis only.

| File | Purpose |
|------|---------|
| `data/dhv_unmatched.csv` | Primary DHV data source (3,192 cert records) |
| `data/dhv_gap_report.md` | Existing analysis of DHV gaps |
| This document | Assessment and integration recommendation |
