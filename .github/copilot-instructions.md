# Copilot Repository Instructions — OpenParaglider (OpenPG)

## Project Overview

A standalone pipeline tool that crawls paraglider manufacturer websites, extracts structured technical specs using an LLM (Ollama + Qwen2.5:3B), normalizes the data, and stores it in a local SQLite database. Evolves from a working POC (`extract.py`, 1266 lines) into a modular system with LLM-first extraction.

---

## Documentation Rules

- All iteration and reference documents must be placed in: `documentation/`
- Group documents in subfolders by domain (see folder guide below).
- All documentation files must use Markdown format.
- Naming convention for iteration files: `ITERATION_XX_DESCRIPTION.md`
  (underscores, two-digit zero-padded number, uppercase words).
  Example: `ITERATION_03_DATA_IMPORT.md`
- Iteration numbers are **global across all folders** (chronological project order).
- Always check for the highest existing iteration number before creating a new one.
- See `documentation/README.md` for the full index and iteration history.

### Folder Guide

| Folder | Use for |
|--------|---------|
| `documentation/product-analysis/` | Strategy, market research, competitor benchmarks, opportunity analysis |
| `documentation/architecture/` | Project-wide: setup, conventions, tech decisions, AI context |
| `documentation/api/` | API design, OpenAPI spec, endpoint reference, versioning |
| `documentation/data/` | Data sources, DB schema, import scripts, provenance tracking |

Add new feature folders as needed (e.g., `documentation/community/`).

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

---

## Project-Specific Guidelines

- **LLM-first extraction** with markdown parser as fallback
- **Facts only** — never extract marketing copy, images, or copyrighted descriptions
- **"Link, don't host"** — store URLs to external assets, never download them
- **Config-driven** — one YAML file per manufacturer, no code-per-brand
- **Provenance mandatory** — every DB record must have a `data_sources` entry
- **MIT license for code, ODbL for data**

### Local vs. Production

- This tool runs **locally only** — it is not deployed as a service
- SQLite output is designed to be importable into the OpenParaglider production Postgres DB
- The schema (5 tables: manufacturers, models, size_variants, certifications, data_sources) mirrors production exactly

---

## Critical Context

- **Never extract marketing copy, descriptions, or "feel" text** — facts only
- **Never download/host images, PDFs, or logos** — link to them
- **Never skip provenance** — every record needs a `data_sources` entry
- **Never fake User-Agent strings** — use honest bot identification
- **Never ignore robots.txt** — fetch and enforce before crawling
- **Never store personal data** — no pilot names, emails, user accounts
- **Never edit the data-compliance-auditor agent** — it audits, does not fix
- See `documentation/security/DATA_COMPLIANCE_GUIDELINES.md` for full legal guardrails
- See `CLAUDE.md` for detailed project context, key files, and roadmap

