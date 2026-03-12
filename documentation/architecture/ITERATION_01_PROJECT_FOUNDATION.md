# ITERATION 01 — PROJECT FOUNDATION

**Date:** March 12, 2026
**Status:** Complete
**Folder:** `documentation/architecture/`
**Previous:** None (first iteration — POC reference in `documentation/architecture/spec-extractor-v1-implementation.md`)

---

## Objective

Restructure the working POC monolith (`extract.py`, 1266 lines) into a modular Python package with Pydantic validation, normalized storage, and a Typer CLI. Establish licensing, compliance baseline, and documentation conventions.

---

## What Was Done

### Project Structure

Created `src/` package with 8 modules and proper `pyproject.toml`:

```
src/
  __init__.py
  models.py            # Pydantic models (4 enums, 5 domain, 2 extraction)
  config.py            # YAML config loader, output path management
  adapters/
    __init__.py
    base.py            # LLMAdapter abstract class
    ollama.py          # Ollama local adapter (httpx, JSON mode)
  extractor.py         # Schema generation + LLM extraction bridge
  normalizer.py        # Cert/size/slug normalization
  db.py                # SQLite storage (5-table schema, upsert, provenance)
  crawler.py           # Stub (Iteration 2) — rate limiting, cache, partial save
  pipeline.py          # Typer CLI (run/status/reset)
config/
  manufacturers/
    ozone.yaml         # Migrated from configs/
```

### Pydantic Models (`src/models.py`)

Aligned to the OpenParaglider production Postgres schema (5 tables):

- **Enums:** `WingCategory` (7), `TargetUse` (8), `CertStandard` (6), `EntityType` (4)
- **Domain models:** `Manufacturer`, `WingModel`, `SizeVariant`, `Certification`, `DataSource`
- **Extraction models:** `SizeSpec`, `ExtractionResult` (LLM output schema)

### Normalizer (`src/normalizer.py`)

Fully implemented with:
- `normalize_certification()` — handles EN/LTF/CCC/DHV patterns
- `normalize_size_label()` — maps XS/S/M/L/XL with passthrough
- `make_model_slug()` — e.g. `ozone-buzz-z7`

### Database (`src/db.py`)

SQLite with WAL mode, foreign keys, 5-table schema matching production:
- `upsert_manufacturer()`, `upsert_model()`, `upsert_size_variant()`
- `insert_certification()`, `insert_data_source()`
- `record_provenance()` convenience method

### CLI (`src/pipeline.py`)

Typer app with 3 commands:
- `run` — 7 options (--config, --url, --map-only, --convert-only, --retry-failed, --refresh-urls, --dry-run)
- `status` — show extraction progress
- `reset` — clear partial/cache files

### Compliance & Licensing

- `documentation/security/DATA_COMPLIANCE_GUIDELINES.md` — 6 sections (Legal Framework, Scraper Ethics, Data Classification, Provenance Tracking, Licensing, Audit Checklist)
- `LICENSE` — MIT for source code
- `LICENSE-DATA` — ODbL 1.0 for extracted data
- Aligned with `.github/agents/data-compliance-auditor.agent.md` audit categories

### Documentation

- `CLAUDE.md` — filled in all sections (project context, tech stack, key decisions, data sources, roadmap, key files, constraints)
- `documentation/README.md` — created as global iteration index

---

## Verification Results

All modules validated:

| Module | Test | Result |
|--------|------|--------|
| `models.py` | Pydantic model validation with sample data | ✅ |
| `config.py` | Load ozone.yaml, generate output paths | ✅ |
| `normalizer.py` | EN-B, LTF/EN A, size labels, slug generation | ✅ |
| `db.py` | In-memory: create tables, upsert, provenance | ✅ |
| `pipeline.py` | `--help` shows all 3 commands | ✅ |
| Package | `pip install -e .` succeeds | ✅ |

---

## Files Created/Modified

| Action | File |
|--------|------|
| Created | `pyproject.toml` |
| Created | `src/__init__.py`, `src/adapters/__init__.py` |
| Created | `src/models.py` |
| Created | `src/config.py` |
| Created | `src/adapters/base.py`, `src/adapters/ollama.py` |
| Created | `src/extractor.py` |
| Created | `src/normalizer.py` |
| Created | `src/db.py` |
| Created | `src/crawler.py` |
| Created | `src/pipeline.py` |
| Created | `config/manufacturers/ozone.yaml` (copied from `configs/`) |
| Created | `.env.example` |
| Created | `LICENSE`, `LICENSE-DATA` |
| Updated | `documentation/security/DATA_COMPLIANCE_GUIDELINES.md` (65 → 195 lines) |
| Updated | `.gitignore` (added `output/*.db`) |
| Created | `CLAUDE.md` (filled all sections) |
| Created | `documentation/README.md` |

---

## Next: Iteration 02 — Crawler Module

Implement the Crawl4AI wrapper in `src/crawler.py`:
- `render_page()` — Playwright rendering to markdown
- `discover_urls()` — URL discovery from listing pages
- robots.txt enforcement
- Compliance-aware rate limiting with backoff
