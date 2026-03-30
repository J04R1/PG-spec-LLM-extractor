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
| 10 | `ITERATION_10_SCHEMA_REDESIGN.md` | `data/` | Schema v2 — 7-table redesign, provenance model, performance separation, 18 decisions | Complete |
| 11 | `ITERATION_11_SEED_IMPORT_BENCHMARK.md` | `data/` | Seed import + benchmark — CSV import, 3-axis scoring (completeness/quality/accuracy), 60 models baseline | Complete |
| 12 | `ITERATION_12_DATA_VALIDATOR.md` | `data/` | Data validator — per-model issue detection, interactive action prompts, persistent log with resume | Complete |
| 13 | `ITERATION_13_FIX_FLOW_CERTIFICATIONS.md` | `data/` | Fix command — interactive re-extract with preview, cert normalization preserves original labels, dedup fix | Complete |
| 14 | `ITERATION_14_VALIDATED_IMPORT_PIPELINE.md` | `data/` | Validated import pipeline — validation gate at import, per-manufacturer DBs, resumable rebuild command | Complete |
| 15 | `ITERATION_15_DHV_DATA_ANALYSIS.md` | `data/` | DHV data analysis — certification enrichment assessment, adapter recommendation, fredvol cross-ref | Analysis |
| 16 | `ITERATION_16_FREDVOL_DHV_UNIFIED_IMPORT.md` | `data/` | fredvol + DHV unified import — adapters, manufacturer curation (T1/T2/legacy), CLI commands, 76 tests | In Progress |
| 17 | `ITERATION_17_VALIDATION_CONSISTENCY.md` | `data/` | Validation consistency — per-model gate for all importers, --post-validate for seed, relaxed fredvol profile, cert validation for DHV | In Progress |
| 18 | `ITERATION_18_SEED_YEAR_COLUMN_BUGFIX.md` | `data/` | Seed year column bugfix — `_build_wing_model()` read `year` instead of `year_released`/`year_discontinued`, silently dropping all year data from updated CSVs | Complete |
| 19 | `ITERATION_19_EXTRACTOR_CERT_CELL_EXTRACTION.md` | `data/` | Extractor cert/cell extraction — markdown parser missing `"DHV"` and `"No of cells"` label mappings, silently dropping certifications and cell count | Complete |
| 20 | `ITERATION_20_OZONE_MVP_DB.md` | `data/` | Ozone MVP DB — 116 models (22 current + 94 previous), 483 size variants, 368 certs. Quality 100%, staged JSON pipeline, category fix | Complete |
| 21 | `ITERATION_21_DATA_CURATION.md` | `data/` | Data curation TUI — field_verifications table, per-model completeness score, interactive rich TUI + CLI patch workflow | In Progress |
| 22 | `ITERATION_22_MODEL_NORMALISATION.md` | `data/` | Model list normalisation — category/sub_type split, is_current fix, Mantra M3 fix | Complete |
| 23 | `ITERATION_23_CERT_NORMALISATION.md` | `data/` | Certification standard normalisation — 100 misclassified `other` rows fixed to LTF/EN, dual-cert policy, import_staged_to_db gap patched | Complete |

**Next iteration number: 24**

## BACKLOG
> **Planned (not yet started):** `ITERATION_XX_BGD_MVP_DB.md` — BGD MVP Database,
> will be renumbered when execution begins.

---

## Reference Documents

| File | Folder | Description |
|------|--------|-------------|
| `MASTER_PLAN.md` | `architecture/` | Master plan — 4 phases, 8 iterations, verification criteria, progress tracker |
| `spec-extractor-v1-implementation-for-openparaglider.md` | `specs/` | Full architecture reference for the v1 POC (`extract.py`, 1266 lines) |
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
