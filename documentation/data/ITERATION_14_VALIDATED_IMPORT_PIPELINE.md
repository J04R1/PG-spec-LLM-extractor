# Iteration 14 — Validated Import Pipeline

**Date:** 2026-03-15
**Status:** Complete
**Domain:** data / architecture

---

## Goal

Integrate validation into the seed import flow so models are checked **before**
they enter the DB. Models failing critical checks are skipped and logged for
the `fix` flow. Per-manufacturer DBs keep each import isolated. The full
pipeline is resumable so it can be left unattended overnight.

---

## Decisions

| Decision | Rationale |
|----------|-----------|
| Critical failures → skip entirely | Don't store half-broken data; log for fix flow |
| Per-manufacturer DBs | `ozone.db`, `advance.db` — merge later when curated |
| Both Ozone CSVs layered | Base (111 models) first, then LLM-enriched (33) on top |
| Normalize certs at import | Run `normalize_certification()` on CSV fields |
| `fredvol_raw.csv` excluded | Potential future cross-check, not a primary source |
| Resumable rebuild | Progress file tracks completed steps; restart continues |

---

## Architecture

### Data Flow

```
config/manufacturers/ozone.yaml     (defines CSVs, output DB, sources)
         │
         ▼
┌─────────────────────┐
│  rebuild command     │  CLI entry point
│  (resumable steps)   │
└────────┬────────────┘
         │
    ┌────┴────┐
    │ Step 1  │  Import base CSV (ozone_enrichment.csv)
    │         │  → normalize certs at import
    │         │  → validate each model before storing
    │         │  → critical issues → skip + log
    └────┬────┘
         │
    ┌────┴────┐
    │ Step 2  │  Layer enrichment CSV (ozone_enrichment_all_by_LLM.csv)
    │         │  → same gate: normalize + validate + skip/store
    └────┬────┘
         │
    ┌────┴────┐
    │ Step 3  │  Run full post-import validation
    │         │  → writes .validation.json
    └────┬────┘
         │
         ▼
  output/ozone.db              (clean, validated)
  output/ozone.validation.json (issues + skipped models)
```

### Resumability

The `rebuild` command writes a progress file (`output/<slug>.rebuild.json`)
tracking which steps have completed:

```json
{
  "manufacturer": "ozone",
  "started_at": "2026-03-15T20:00:00Z",
  "steps": {
    "import_base": "done",
    "import_enriched": "done",
    "validate": "pending"
  }
}
```

On restart with `--resume`, completed steps are skipped. Use `--fresh` to
discard progress and start from scratch (deletes DB + progress file).

---

## CLI Commands

### `rebuild` — Full validated rebuild from CSVs

```bash
# Fresh rebuild
python -m src.pipeline rebuild --config config/manufacturers/ozone.yaml

# Resume after interruption
python -m src.pipeline rebuild --config config/manufacturers/ozone.yaml --resume

# Force fresh start
python -m src.pipeline rebuild --config config/manufacturers/ozone.yaml --fresh
```

**Output:**
```
── Rebuild: Ozone ──
Step 1/3: Import base CSV (ozone_enrichment.csv)
  Imported: 108 models, 497 sizes
  Skipped:  3 models (critical issues)

Step 2/3: Layer enrichment CSV (ozone_enrichment_all_by_LLM.csv)
  Updated: 33 models (richer data merged)
  Skipped: 0

Step 3/3: Post-import validation
  ✓ Clean:    62 models
  △ Warnings: 43 models
  ✗ Critical:  3 models (skipped at import)

Summary: 108 models in output/ozone.db
         3 models need fix (see: fix --db output/ozone.db)
         Log: output/ozone.validation.json
```

### Updated `fix` flow

After `rebuild`, the fix flow handles skipped models:

```bash
# See what needs fixing
python -m src.pipeline fix --db output/ozone.db

# Fix a specific model
python -m src.pipeline fix --db output/ozone.db --model ozone-buzz-z3
```

The fix flow now also validates the new extraction before allowing commit —
prevents storing data that would immediately fail the validator.

---

## Implementation Plan

### Phase 1 — Validated Import

#### Step 1: `validate_model_data()` in `src/validator.py`

New function for **in-memory** validation (no DB dependency):

```python
def validate_model_data(
    model: WingModel,
    sizes: list[SizeVariant],
    certs: list[Certification],
    manufacturer_slug: str,
) -> ModelValidation:
```

Runs the same checks as `_validate_model()` but on Pydantic objects instead
of `sqlite3.Row`. The existing `_validate_model()` becomes a thin wrapper
that reads from DB and delegates.

#### Step 2: Cert normalization in `src/seed_import.py`

Change `_build_certification()` to normalize:

```python
# Before (trusts CSV as-is):
standard = CertStandard(standard_str)
classification = row.get("cert_classification", "").strip()

# After (normalizes):
raw_cert = f"{standard_str} {classification}".strip()
standard, classification = normalize_certification(raw_cert)
```

#### Step 3: Import gate in `src/seed_import.py`

After building model data, validate before storing:

```python
mv = validate_model_data(wing, sizes, certs, mfr_slug)
if mv.has_critical:
    skipped.append(mv)
    continue  # don't store
# else: store normally
```

Return enriched summary including skipped models and their issues.

#### Step 4: Wire ValidationLog into `seed` CLI

The `seed` command creates `.validation.json` alongside the DB. Skipped
models appear with `action=pending`. Stored models with warnings also
appear for review.

### Phase 2 — Rebuild Command

#### Step 5: Update manufacturer YAML

Add `import` section to `config/manufacturers/ozone.yaml`:

```yaml
import:
  output_db: output/ozone.db
  csv_files:
    - path: data/ozone_enrichment.csv
      method: poc_markdown_parser
      label: "Base import (111 models from POC)"
    - path: data/ozone_enrichment_all_by_LLM.csv
      method: llm_enrichment
      label: "LLM enrichment (33 models)"
```

#### Step 6: `rebuild` CLI command

Orchestrates the full flow, config-driven, resumable:

```python
@app.command()
def rebuild(
    config: str = typer.Option(..., "--config", "-c"),
    resume: bool = typer.Option(False, "--resume"),
    fresh: bool = typer.Option(False, "--fresh"),
):
```

### Phase 3 — Integration

#### Step 7: Validate before fix-commit

The `fix` command runs `validate_model_data()` on the new extraction.
If critical issues remain, shows them and asks for confirmation before
allowing commit.

---

## Files Modified

| File | Changes |
|------|---------|
| `src/validator.py` | Add `validate_model_data()` for in-memory validation |
| `src/seed_import.py` | Cert normalization in `_build_certification()`, validation gate |
| `src/pipeline.py` | Update `seed`, add `rebuild` command, validate in `fix`, enhanced `fix` listing |
| `config/manufacturers/ozone.yaml` | Add `import` section (csv_files, output_db) |
| `config/manufacturers/advance.yaml` | Add `import` section |
| `tests/test_validator.py` | Tests for `validate_model_data()`, updated `_seed_db` for validation gate |
| `tests/test_seed_import.py` | Tests for validation gate + cert normalization |

---

## Fix Command Improvements

### Enhanced issue listing

The `fix` command now shows each model's specific issues instead of just a count:

**Before:**
```
1. △ Alpina — 2 issues
6. △ Buzz — 4 issues
```

**After:**
```
1. △ Alpina — missing_year_released; discontinued_no_year
6. △ Buzz — missing_cell_count; missing_year_released; discontinued_no_year; no_certifications
50. △ Mojo — missing_year_released; discontinued_no_year; missing_flat_area_m2 (L, M, S, XL, XS)
```

Size-specific issues show affected sizes in parentheses. The full list is shown
(no 20-item cutoff) for easy copy-paste.

### AI-ready prompt header

The listing now starts with a structured prompt block that can be copied directly
into an AI agent:

```
── Ozone — 83 models need data ──

Most common missing data:
  missing_year_released: 70 models
  no_certifications: 38 models
  missing_cell_count: 15 models

CSV format (one row per size per model):
manufacturer_slug,name,year,...,cert_report_url

Example row:
ozone,Rush 6,2023,paraglider,xc,false,55,...,EN,B,,,
```

This gives an AI agent everything needed: manufacturer context, what's missing,
exact CSV format, and an example row — ready for web research and CSV generation.

---

## Verification Checklist

- [x] Delete `output/ozone.db`, run `rebuild` → 102 models stored, 13 skipped (critical)
- [x] Zero cert duplicates: query returns 0 rows
- [x] `validate --db output/ozone.db` → 114 models in log (102 DB + 12 skipped), 19 clean, 83 warnings, 0 critical in DB
- [x] `fix --db output/ozone.db` → 95 pending models (82 warnings + 13 skipped), skipped models surfaced for re-extract
- [x] Interrupt rebuild mid-step, `--resume` skips completed steps, progress file cleaned up on success
- [x] All tests pass (205)

### Skipped Models Analysis

13 models skipped at import due to critical issues:
- **10 models** with `invalid_en_classification`: CSV had `EN,2` style certs — numeric classes (1, 1-2, 2, 2-3, 3) are LTF, not EN. Source data quality issue.
- **3 models** with `flat_geometry_inconsistent` or `proj_gte_flat`: geometry values fail consistency checks.

---

## Output Directory Cleanup

**Removed** (pre-iteration artifacts that are no longer needed):

| File | Reason |
|------|--------|
| `output/seed_benchmark.db` | Superseded by per-manufacturer DBs |
| `output/ozone_benchmark.db` | Benchmark now runs against manufacturer DB directly |
| `output/advance_benchmark.db` | Same |
| `output/validation_07_results.json` | Iteration 7 artifact, replaced by `.validation.json` pattern |

**Kept:**

| File | Reason |
|------|--------|
| `output/ozone.db` | Will be rebuilt by `rebuild` command |
| `output/ozone.validation.json` | Active validation log |
| `output/ozone_urls.json` | URL discovery cache (reusable) |
| `output/advance_urls.json` | URL discovery cache (reusable) |
| `output/md_cache/` | Markdown render cache (saves re-crawling) |
