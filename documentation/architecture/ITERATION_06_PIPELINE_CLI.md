# Iteration 06 — Pipeline Orchestrator & CLI

**Status:** Complete
**Date:** March 2026

---

## Summary

Finalized all CLI commands and wired the full pipeline flow end-to-end.
All Typer commands and options are now functional.

## What Was Done

### `status` Command
- Scans `config/manufacturers/*.yaml` for known manufacturers
- Reports per-manufacturer: raw JSON model count, partial progress,
  CSV presence, SQLite DB presence

### `--retry-failed` Option
- Copies finalized `raw_json` → `partial` file so `_extract_all()`
  re-processes URLs that didn't produce results on the last run
- Seamlessly integrates with existing crash-recovery logic

### Full Pipeline Flow
All stages verified end-to-end:
```
config → crawl → extract → normalize → store (DB + CSV)
```

## CLI Reference

| Command/Option | Status | Description |
|----------------|--------|-------------|
| `run --config` | ✅ | Full pipeline for a manufacturer |
| `run --url` | ✅ | Single URL test mode |
| `--map-only` | ✅ | URL discovery only |
| `--convert-only` | ✅ | Raw JSON → DB + CSV |
| `--retry-failed` | ✅ | Re-extract failed URLs |
| `--refresh-urls` | ✅ | Clear URL cache before discovery |
| `--dry-run` | ✅ | Show plan without requests |
| `status` | ✅ | Show extraction state per manufacturer |
| `reset` | ✅ | Clear partial/cache files |

## Files Modified

| File | Changes |
|------|---------|
| `src/pipeline.py` | Implemented `status` command, `--retry-failed` logic |
