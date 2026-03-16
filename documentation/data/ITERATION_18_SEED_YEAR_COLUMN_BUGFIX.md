# Iteration 18 — Seed Import Year Column Bugfix

**Status:** Complete
**Folder:** `data/`
**Date:** 2026-03-15

---

## Problem

Running `seed` with the year-updated CSV (`ozone_year_updated_LLM_based_list.csv`) failed to populate `year_released` and `year_discontinued` in the database. After seeding, the validation report showed **89 missing year** issues — more than the 83 before the seed — because the CSV added 29 new models that all imported without year data.

### Root Cause

**Column name mismatch between CSV and seed importer.**

| Source | Year column name |
|--------|-----------------|
| DB schema (`models` table) | `year_released`, `year_discontinued` |
| Pydantic model (`WingModel`) | `year_released`, `year_discontinued` |
| Old enrichment CSVs (`ozone_enrichment*.csv`) | `year` |
| Year-updated CSV (`ozone_year_updated_LLM_based_list.csv`) | `year_released`, `year_discontinued` |
| `_build_wing_model()` in `seed_import.py` | `row.get("year", "")` — **matched only old CSVs** |

The importer read `row.get("year", "")`, which returned an empty string for the year-updated CSV (where the column is `year_released`). All year data was silently dropped. The `year_discontinued` column was never read at all.

Additionally, `_MODEL_LEVEL_FIELDS` listed `"year"` instead of `"year_released"` / `"year_discontinued"`.

---

## Fix

**File:** `src/seed_import.py`

### 1. `_build_wing_model()` — read correct column names

```python
# Before (broken):
year_released=_safe_int(row.get("year", "")),
# year_discontinued was never read

# After (fixed):
year_raw = row.get("year_released", "") or row.get("year", "")
year_released=_safe_int(year_raw),
year_discontinued=_safe_int(row.get("year_discontinued", "")),
```

The fallback `or row.get("year", "")` preserves backward compatibility with the old enrichment CSVs that use the `year` column name.

### 2. `_MODEL_LEVEL_FIELDS` — match DB schema names

```python
# Before:
_MODEL_LEVEL_FIELDS = {
    "name", "year", "category", "target_use", "is_current",
    "cell_count", "riser_config", "manufacturer_url",
}

# After:
_MODEL_LEVEL_FIELDS = {
    "name", "year_released", "year_discontinued", "category", "target_use",
    "is_current", "cell_count", "riser_config", "manufacturer_url",
}
```

---

## Verification

### Before fix

```
seed ozone_enrichment_all_by_LLM.csv → validate → 83 missing year
seed ozone_year_updated_LLM_based_list.csv → validate → 89 missing year (worse)
```

### After fix

```
seed ozone_enrichment_all_by_LLM.csv → 32 models, 0 missing year (fallback to "year" works)
seed ozone_year_updated_LLM_based_list.csv → 62 models, 0 missing year
38 models now have year_discontinued populated
```

### Tests

All 32 `test_seed_import.py` tests pass. Existing tests use the old `year` column name and continue to work via the fallback.

---

## Lesson

CSV column names must match the DB schema. When a new CSV changes column names to align with the schema, the importer must be updated to read the new names. A fallback for legacy column names prevents breaking old imports.

---

## Bug 2 — `fix` command can't find validation log from `rebuild`

### Problem

After `rebuild`, running `fix --db output/ozone.db` failed with:

```
No validation log found. Run validate first:
  python -m src.pipeline validate --db output/ozone.db
```

But running `validate` only checks models **in the DB** — the 12 models rejected during import (e.g. Atom 2) are lost because they were never written to the DB. They only exist in the `_first_build` validation log.

### Root Cause

**Filename mismatch between `rebuild` and `fix`.**

| Command | Validation log path |
|---------|-------------------|
| `rebuild` | `ozone.validation_first_build.json` (via `validate_database(db, "first_build")`) |
| `validate` | `ozone.validation.json` (canonical) |
| `fix` | Hardcoded lookup: `db_p.with_suffix(".validation.json")` — **only finds canonical** |

`fix` never found the `_first_build` log, so all 12 import-rejected models (Atom 2, Addict 2, Buzz Z3, etc.) were invisible to the fix flow.

### Fix

**File:** `src/pipeline.py` — new `_find_latest_validation_log()` helper, used by `fix()`

Instead of hardcoding a single log path, `fix` now finds the **most recent** `ozone.validation*.json` by modification time, then merges any import-rejected models from `_first_build` that are still not in the DB:

```python
def _find_latest_validation_log(db_p: Path) -> Path:
    # Find newest validation log by mtime
    candidates = sorted(
        db_p.parent.glob(f"{stem}.validation*.json"),
        key=lambda p: p.stat().st_mtime, reverse=True,
    )
    latest = candidates[0]

    # Merge import-rejected models from _first_build
    if first_build.exists() and first_build != latest:
        # Add models from _first_build that aren't in DB and aren't in latest log
        ...
    return latest
```

### Result

After `rebuild` → `seed year_updated` → `seed enrichment_all_by_LLM`:

| Log | Models | Clean | With issues | Not in DB |
|-----|--------|-------|-------------|-----------|
| `_first_build` | 111 | 0 | 111 | 9 |
| `_year_updated` | 116 | 55 | 61 | 9 |
| `_enrichment_all_by_LLM` (latest) | 117 | 56 | 61 | 9 |

`fix` now picks the latest log (117 models) and merges in the 9 import-rejected models from `_first_build`, so nothing is ever lost regardless of how many `seed` or `validate` runs happen in between.

**DB state after full pipeline:**
- 108 models, 490 sizes, 400 certifications
- 62 with `year_released`, 38 with `year_discontinued`
- 9 models still rejected (validation gate): Addict 2, Atom 2, Buzz Z3, Geo Ii, Magnum, Mantra M2, Mojo 2, Mojo 3, Ultralite
