# CLAUDE — PG spec llm extractor (OpenPG)

This file gives Claude (and other AI assistants) the context needed to work effectively
on this codebase. Read it before making any changes.

---

## What This Project Is

A standalone pipeline tool that crawls paraglider manufacturer websites, extracts structured technical specs using an LLM (Ollama + Qwen2.5:3B), normalizes the data, and stores it in a local SQLite database. Evolves from a working POC (`extract.py`, 1266 lines) that used deterministic markdown parsing ($0 cost, 111 Ozone models) into a modular system with LLM-first extraction.

**Two core use cases:**
1. **Extract** new paraglider specs from manufacturer websites → store in DB
2. **Evaluate** quality/accuracy of existing data in other DBs (future phase)

---

## Tech Stack

- **Python 3.11** (venv at `.venv/`)
- **LLM:** Ollama + Qwen2.5:3B (local, fits 8GB RAM) — markdown parser as free fallback
- **Crawling:** Crawl4AI + Playwright (local Chromium rendering)
- **Validation:** Pydantic v2
- **CLI:** Typer
- **DB:** SQLite (local) — schema matches OpenParaglider production Postgres
- **HTTP:** httpx (async-capable)
- **Config:** YAML per manufacturer + python-dotenv for env vars

### Local vs. Production

- This tool runs **locally only** — it is not deployed as a service
- SQLite output is designed to be importable into the OpenParaglider production Postgres DB
- The schema (5 tables: manufacturers, models, size_variants, certifications, data_sources) mirrors production exactly

---

## Documentation Conventions

All documentation lives in `documentation/`, grouped by domain:

| Folder | Use for |
|--------|---------|
| `documentation/product-analysis/` | Strategy, market research, competitor benchmarks |
| `documentation/architecture/` | Setup, conventions, tech decisions, AI context |
| `documentation/api/` | API design, OpenAPI spec, endpoint reference |
| `documentation/data/` | DB schema, data sources, import scripts, provenance |

**Iteration file naming:** `ITERATION_XX_DESCRIPTION.md`
- Underscores as separators, two-digit zero-padded number, uppercase words
- Example: `ITERATION_03_DATA_IMPORT.md`
- Numbers are **global** (chronological across all folders — always check `documentation/README.md` for the highest existing number before creating a new one)

---

## Key Project Decisions

- **LLM-first extraction** with markdown parser as fallback (not the other way around)
- **Ollama locally** — Qwen2.5:3B fits 8GB RAM (~3-4GB), slow batch overnight is acceptable
- **Facts only** — never extract marketing copy, images, or copyrighted descriptions (see `documentation/security/DATA_COMPLIANCE_GUIDELINES.md`)
- **"Link, don't host"** — store URLs to external assets, never download them
- **Config-driven** — one YAML file per manufacturer, no code-per-brand
- **Provenance mandatory** — every DB record must have a `data_sources` entry tracing it to its origin
- **MIT license for code, ODbL for data** (see `LICENSE` and `LICENSE-DATA`)

---

## Data Sources

- **Manufacturer websites** (public product/spec pages) — primary source
- **DHV Geräteportal** (government-adjacent certification portal) — certification records
- **fredvol/Paraglider_specs_studies** (public GitHub dataset) — historical reference
- **Community contributions** (future phase)

---

## Implementation Roadmap Summary

4 phases, 8 iterations (see `/memories/session/plan.md` for full detail):

| Phase | Iterations | Focus |
|-------|-----------|-------|
| 1 — Foundation | 1–2 | Project structure, Pydantic models, crawler module |
| 2 — Extraction | 3–4 | LLM extraction, markdown fallback parser |
| 3 — Storage | 5–6 | Normalization pipeline, SQLite writer, CSV export |
| 4 — Polish | 7–8 | Error handling, multi-manufacturer, CLI UX |

**Current status:** Iteration 01 complete (project structure, models, DB, normalizer, CLI)

---

## Key Files

| File | Purpose |
|------|---------|
| `src/models.py` | Pydantic models (4 enums, 5 domain, 2 extraction) — matches production DB |
| `src/config.py` | YAML config loader, output path management |
| `src/adapters/ollama.py` | Ollama LLM adapter (httpx, JSON mode) |
| `src/extractor.py` | Schema generation + LLM extraction bridge |
| `src/normalizer.py` | Cert/size/slug normalization |
| `src/db.py` | SQLite storage (7-table schema v2, upsert, provenance) |
| `src/seed_import.py` | CSV enrichment import → v2 schema |
| `src/benchmark.py` | Quality/completeness/accuracy scoring engine |
| `src/validator.py` | Per-model validation, issue detection, interactive action log |
| `src/crawler.py` | Crawl4AI wrapper (stub — Iteration 2) |
| `src/pipeline.py` | Typer CLI entry point (run/status/reset) |
| `config/manufacturers/ozone.yaml` | Ozone manufacturer config |
| `extract.py` | Original POC monolith (1266 lines) — reference only |
| `documentation/architecture/spec-extractor-v1-implementation.md` | POC architecture reference |
| `documentation/security/DATA_COMPLIANCE_GUIDELINES.md` | Legal & ethical guardrails |
| `.github/agents/data-compliance-auditor.agent.md` | Compliance audit agent definition |

---

## What NOT to Do

- **Never extract marketing copy, descriptions, or "feel" text** — facts only
- **Never download/host images, PDFs, or logos** — link to them
- **Never mirror a source's table structure** — use our own original schema
- **Never skip provenance** — every record needs a `data_sources` entry
- **Never fake User-Agent strings** — use honest bot identification
- **Never ignore robots.txt** — fetch and enforce before crawling
- **Never store personal data** — no pilot names, emails, user accounts
- **Never edit the data-compliance-auditor agent** — it audits, does not fix

