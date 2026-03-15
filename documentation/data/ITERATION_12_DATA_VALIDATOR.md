# ITERATION 12 — DATA VALIDATOR

**Date:** 2026-03-15
**Status:** Complete
**Folder:** `data/`

---

## Goal

Build a per-model data validator that detects completeness gaps, implausible values, and internal inconsistencies — then prompts the user to choose an action (re-extract, skip, or manual fix). Maintain a persistent log so validation can be interrupted and resumed without losing progress.

---

## What Was Built

### 1. Validator Module (`src/validator.py`)

Per-model validation engine that checks every model in the database:

#### Issue Severities

| Severity | Marker | Meaning |
|----------|--------|---------|
| `critical` | ✗ | Data is wrong or contradictory — needs fixing |
| `warning` | △ | Data is missing or implausible — should be reviewed |
| `info` | · | Minor gap, cosmetic — acceptable as-is |

#### Checks Performed

**Model-level:**
| Check | Severity | Condition |
|-------|----------|-----------|
| `missing_category` | warning | category is NULL |
| `missing_cell_count` | warning | cell_count is NULL |
| `missing_manufacturer_url` | warning | manufacturer_url is NULL |
| `missing_year_released` | warning | year_released is NULL |
| `implausible_year_released` | critical | year outside 1990–2026 |
| `implausible_cell_count` | warning | cell_count outside 15–120 |
| `discontinued_no_year` | info | is_current=0 but year_discontinued is NULL |

**Size-level:**
| Check | Severity | Condition |
|-------|----------|-----------|
| `missing_flat_area_m2` | warning | flat_area is NULL |
| `missing_ptv_min_kg` | warning | ptv_min is NULL |
| `missing_ptv_max_kg` | warning | ptv_max is NULL |
| `ptv_min_gte_max` | critical | ptv_min ≥ ptv_max |
| `flat_geometry_inconsistent` | critical | flat_area ≠ span²/AR (>5% off) |
| `proj_gte_flat` | critical | projected area ≥ flat area |
| `implausible_*` | warning | any numeric field outside plausibility range |
| `no_sizes` | critical | model has zero size variants |

**Certification-level:**
| Check | Severity | Condition |
|-------|----------|-----------|
| `no_certifications` | warning | no certification records for model |
| `invalid_en_classification` | critical | EN standard with classification not in {A,B,C,D} |

### 2. Interactive Actions

For each model with issues, the user chooses:

| Key | Action | Effect |
|-----|--------|--------|
| `r` | Re-extract | Mark for pipeline re-crawl and re-extraction |
| `s` | Skip | Accept data as-is, move on |
| `m` | Manual fix | Flag for manual correction later |
| `q` | Quit | Save progress and exit (resume with `--resume`) |

### 3. Persistent Validation Log

Every decision saves immediately to `<db>.validation.json`:
- Survives crashes and interruptions
- On `--resume`, already-decided models are skipped
- Tracks which models need re-extraction
- JSON format for external tool consumption

### 4. CLI Command

```bash
# Interactive review
python -m src.pipeline validate --db output/ozone.db

# Non-interactive (auto-skip all)
python -m src.pipeline validate --db output/ozone.db --auto-skip

# Resume after quit or crash
python -m src.pipeline validate --db output/ozone.db --resume
```

---

## Real Data Results (Ozone, 114 models)

```
═══ Validation Summary: output/ozone.db ═══
Total models: 114
  ✓ Clean:       14
  △ With issues: 100
  ✗ Critical:    22

Actions:
  Pending:      100
  Re-extract:   0
  Skipped:      0
  Manual fix:   0
```

### Main Issues Found

1. **81 models missing `year_released`** — base POC extraction didn't capture years
2. **22 models with invalid EN classifications** — old DHV numbering (e.g., "2" instead of "B") or prefixed values (e.g., "EN C" instead of "C") stored from POC parser
3. **3 models with `proj_area ≥ flat_area`** — enrichment data inconsistency for specific Advance models
4. **92 models with `discontinued_no_year`** — `is_current=false` but no `year_discontinued` (expected for older models)

---

## Files Changed

| File | Change |
|------|--------|
| `src/validator.py` | **New** — validation engine, issue detection, action log, persistence |
| `src/pipeline.py` | Added `validate` CLI command with `--resume`, `--auto-skip`, `--show-clean` |
| `tests/test_validator.py` | **New** — 16 tests (issues, scoring, log persistence, integration) |
| `CLAUDE.md` | Added `src/validator.py` to key files table |

## Test Results

```
191 passed in 2.10s (175 existing + 16 new)
```
