# Master Plan — Paraglider Spec LLM Extraction Pipeline v1

**Created:** March 2026
**Last Updated:** March 2026

---

## TL;DR

Restructure the working POC monolith (`extract.py`, 1266 lines) into a modular pipeline
with LLM-first extraction (Ollama + Qwen2.5:3B), Pydantic validation, normalization,
and SQLite storage. Keep the proven markdown parser as a free fallback.
Deliver in 4 phases across 8 iterations.

---

## Phase 1 — Foundation (Iterations 1–2)

### Iteration 1: Project Structure & Schema ✅

- Set up `pyproject.toml` with dependencies (crawl4ai, pydantic, httpx, ollama, python-dotenv, typer)
- Create modular `src/` layout: `crawler.py`, `adapters/`, `extractor.py`, `normalizer.py`, `db.py`, `pipeline.py`
- Define Pydantic models: `Manufacturer`, `WingModel`, `SizeVariant`, `Certification`, `DataSource` (matches production Postgres schema)
- Define extraction models: `SizeSpec`, `ExtractionResult`
- Port config loading from `load_config()` and `get_output_paths()`
- Move `ozone.yaml` → `config/manufacturers/ozone.yaml`
- Establish licensing (MIT for code, ODbL for data)
- Create `DATA_COMPLIANCE_GUIDELINES.md` aligned with data-compliance-auditor agent
- Populate `CLAUDE.md` and `.github/copilot-instructions.md` with project context

### Iteration 2: Crawler Module

- Port Crawl4AI wrapping, URL discovery (`map_product_urls()`), HTML link extraction
- URL cache and cross-source deduplication
- Crash recovery (`_save_partial` / `_load_partial`)
- Rate limit detection
- `robots.txt` enforcement (compliance-first — see `DATA_COMPLIANCE_GUIDELINES.md` §2.1)
- Honest User-Agent identification

---

## Phase 2 — LLM Extraction (Iterations 3–4)

### Iteration 3: LLM Adapter & Ollama Integration

- `LLMAdapter` base class with `extract(markdown, schema) -> dict` interface
- `OllamaAdapter` — Qwen2.5:3B at `localhost:11434`, structured JSON output using Pydantic schema
- Build extraction prompt in `src/extractor.py` (adapt from `prompts/extraction-prompt-kit.md` + YAML config hints)
- Test with single URL mode (`--url`)

### Iteration 4: Markdown Fallback Strategy

- Port the deterministic parser (`parse_specs_from_markdown()`, `_MD_ROW_MAP` with 43 label mappings, size detection, EU decimal handling) into a pluggable strategy
- Auto-fallback: if LLM fails or returns empty → try markdown parser
- Both strategies produce the same `ExtractionResult` output shape

---

## Phase 3 — Storage & Pipeline (Iterations 5–6)

### Iteration 5: Normalization & SQLite

- Certification normalization (EN-A/B/C/D, CCC canonical mapping — see pipeline spec §4.2)
- Size normalization (raw labels → XS/S/M/L/XL — see pipeline spec §4.3)
- SQLite storage with 5-table schema: `manufacturers`, `models`, `size_variants`, `certifications`, `data_sources`
- Upsert logic (create if missing, update only NULL fields)
- Provenance tracking — every record gets a `data_sources` entry
- Keep CSV export for backward compatibility

### Iteration 6: Pipeline Orchestrator & CLI

- Typer CLI: `run --config`, `run --url`, `--map-only`, `--convert-only`, `--retry-failed`, `status`, `reset`
- Wire full flow: config → crawl → extract → normalize → store
- Progress reporting and structured logging

---

## Phase 4 — Validation (Iterations 7–8)

### Iteration 7: Ozone Validation Run

- Full extraction of ~111 Ozone models via LLM
- Compare against known-good POC results (field-level diff)
- Measure accuracy, time, and memory on 8GB machine
- Tune extraction prompt if needed

### Iteration 8: Second Manufacturer & Polish

- Add a second brand config (Nova, Advance, or Gin)
- Validate pipeline generalization — no Ozone-specific assumptions leak
- Final cleanup, README, logging

---

## Verification Criteria

These are the acceptance criteria for the complete pipeline:

1. Pydantic schema validates sample data
2. `--map-only` discovers ~115 Ozone URLs
3. `--url <ozone_url>` extracts specs via Ollama, prints valid JSON
4. Same URL with markdown fallback produces matching output
5. SQLite DB contains correct records after extraction
6. All CLI commands work as documented
7. LLM vs POC results: ≤5% field-level discrepancy
8. Second manufacturer extraction completes, records in DB

---

## Constraints & Guardrails

- **Facts only** — never extract marketing copy, images, or copyrighted descriptions
- **"Link, don't host"** — store URLs to external assets, never download them
- **Config-driven** — one YAML file per manufacturer, no code-per-brand
- **Provenance mandatory** — every DB record must trace to its `data_sources` origin
- **Honest scraping** — real User-Agent, `robots.txt` enforcement, polite rate limiting
- **Local-first** — Ollama + Qwen2.5:3B fits 8GB RAM; slow batch overnight is acceptable
- **Schema matches production** — SQLite output is importable into OpenParaglider production Postgres

See `documentation/security/DATA_COMPLIANCE_GUIDELINES.md` for full legal and ethical guardrails.

---

## Progress Tracker

| Iteration | Status |
|-----------|--------|
| 01 — Project Structure & Schema | ✅ Complete |
| 02 — Crawler Module | ✅ Complete |
| 03 — LLM Adapter & Ollama | ✅ Complete |
| 04 — Markdown Fallback | ✅ Complete |
| 05 — Normalization & SQLite | ✅ Complete |
| 06 — Pipeline Orchestrator & CLI | ✅ Complete |
| 07 — Ozone Validation Run | ⬜ Not started |
| 08 — Second Manufacturer & Polish | ⬜ Not started |
