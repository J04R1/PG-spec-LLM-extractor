# Documentation Index — PG Spec LLM Extractor

This file tracks all iteration documents and reference materials.
Iteration numbers are **global** across all folders (chronological project order).

---

## Iteration History

| # | File | Folder | Description | Status |
|---|------|--------|-------------|--------|
| 01 | `ITERATION_01_PROJECT_FOUNDATION.md` | `architecture/` | Modular project structure, Pydantic models, DB, normalizer, CLI, compliance baseline | Complete |
| 02 | `ITERATION_02_CRAWLER_MODULE.md` | `architecture/` | Crawl4AI wrapper, URL discovery, robots.txt, dedup, crash recovery, pipeline wiring | Complete |
| 03 | `ITERATION_03_LLM_EXTRACTION.md` | `architecture/` | Ollama adapter wiring, extraction prompt, config integration, batch pipeline | Complete |
| 04 | `ITERATION_04_MARKDOWN_FALLBACK.md` | `architecture/` | Deterministic markdown parser, auto-fallback, 43 label mappings, EU decimals | Complete |
| 05 | `ITERATION_05_NORMALIZATION_SQLITE.md` | `architecture/` | Storage wiring, CSV export, --convert-only, provenance tracking | Complete |
| 06 | `ITERATION_06_PIPELINE_CLI.md` | `architecture/` | CLI finalization, status command, --retry-failed, full flow wiring | Complete |
| 07 | `ITERATION_07_OZONE-VALIDATION.md` | `architecture/` | Ozone Validation Run — 10-model sample, 98.1% field match, 0 data errors | Complete |
| 08 | `ITERATION_08_SECOND_MANUFACTURER.md` | `architecture/` | Second Manufacturer (Advance) — 8-model sample, 93.9% field match, unit column handling | Complete |
| 09 | `ITERATION_09_TEST_SUITE.md` | `architecture/` | Pipeline test suite — 129 pytest tests, strict spec assertions, 3 bugs fixed | Complete |

**Next iteration number: 10**

---

## Reference Documents

| File | Folder | Description |
|------|--------|-------------|
| `MASTER_PLAN.md` | `architecture/` | Master plan — 4 phases, 8 iterations, verification criteria, progress tracker |
| `spec-extractor-v1-implementation.md` | `architecture/` | Full architecture reference for the v1 POC (`extract.py`, 1266 lines) |
| `DATA_COMPLIANCE_GUIDELINES.md` | `security/` | Legal and ethical guardrails for data handling (6 sections) |
| `paraglider_pipeline_spec.md` | `specs/` | Original pipeline specification |

---

## Folder Guide

| Folder | Use for |
|--------|---------|
| `architecture/` | Setup, conventions, tech decisions, AI context |
| `data/` | DB schema, data sources, import scripts, provenance |
| `product-analysis/` | Strategy, market research, competitor benchmarks |
| `api/` | API design, OpenAPI spec, endpoint reference |
| `security/` | Legal compliance, data handling guardrails |
| `specs/` | Pipeline and feature specifications |
