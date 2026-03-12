# Iteration 05 — Normalization & SQLite Storage

**Status:** Complete
**Date:** March 2026

---

## Summary

Wired the existing normalizer and SQLite modules into the pipeline, adding
end-to-end flow from raw extraction results through normalization into persistent
storage (SQLite) and CSV export.

## What Was Done

### Storage Wiring (`_store_to_db`)
- For each `ExtractionResult`: validates via Pydantic → `normalize_extraction()` →
  upserts manufacturer, model, size variants, certifications
- Full provenance tracking (every entity gets a `data_sources` entry)
- DB auto-creates on first write (WAL mode, foreign keys enabled)

### CSV Export (`_export_csv`)
- Flattens to one row per (model × size), matching POC's 27-column format
- Handles cert splitting (`"EN B"` → `cert_standard="EN"`, `cert_classification="B"`)
- Numeric formatting: strips trailing `.0` from integer-like floats
- Column order matches POC for backward compatibility

### Pipeline Integration
- `_extract_all()` now calls `_store_to_db()` + `_export_csv()` after finalization
- `--convert-only` fully implemented: loads raw JSON → normalizes → DB + CSV
- Both paths share the same storage functions

### Imports Added to `pipeline.py`
- `csv`, `Database`, `EntityType`, `ExtractionResult`, `Manufacturer`,
  `normalize_certification`, `normalize_extraction`

## Key Design Decisions

- **No separate storage module** — functions live in `pipeline.py` since they're
  pipeline-specific orchestration, not reusable library code
- **CSV is secondary** — DB is the primary output; CSV exists for compatibility
  and quick inspection
- **Provenance for every entity** — manufacturer, model, size_variant, and
  certification each get `data_sources` entries

## Verification

Tested with mock data (1 model, 2 sizes, EN B certs):
- SQLite: manufacturer, model, 2 size_variants, 2 certifications, 6 provenance records ✅
- CSV: 2 rows, 27 columns, correct cert splitting ✅
- `--convert-only`: loads existing raw JSON → DB + CSV ✅
- Import validation: all modules load cleanly ✅

## Files Modified

| File | Changes |
|------|---------|
| `src/pipeline.py` | Added `_store_to_db()`, `_export_csv()`, `_CSV_COLUMNS`; wired into `_extract_all()` and `--convert-only` |

## Dependencies

Uses existing modules completed in Iteration 01:
- `src/normalizer.py` — `normalize_extraction()`, `normalize_certification()`
- `src/db.py` — `Database` class with all upsert methods
- `src/models.py` — `EntityType`, `ExtractionResult`, `Manufacturer`
