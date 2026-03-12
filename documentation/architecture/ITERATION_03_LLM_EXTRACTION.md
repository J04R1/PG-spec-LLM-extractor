# ITERATION 03 — LLM ADAPTER & OLLAMA INTEGRATION

**Date:** March 12, 2026
**Status:** Complete
**Folder:** `documentation/architecture/`
**Previous:** `ITERATION_02_CRAWLER_MODULE.md`

---

## Objective

Wire the existing `OllamaAdapter` and `extract_specs()` into the pipeline so that `--url` and full pipeline modes render pages and extract specs via LLM. Support manufacturer-specific extraction prompts from YAML config.

---

## What Was Done

### 1. Enhanced Adapter Interface (`src/adapters/base.py`)

Added optional `instructions` parameter to `LLMAdapter.extract()`:
```python
def extract(self, markdown, schema, instructions=None) -> dict
```
This allows manufacturer-specific extraction prompts from YAML config to be passed to the adapter without breaking the clean interface.

### 2. Improved Extraction Prompt (`src/adapters/ollama.py`)

- `_build_prompt()` now accepts `instructions` parameter
- When config provides `extraction.llm.prompt`, uses it as the base instructions
- Default prompt enhanced with paraglider-specific extraction rules:
  - Weight range splitting (ptv_min/max)
  - Glider weight → wing_weight_kg mapping
  - Certification class extraction
  - Cell count as top-level field

### 3. Extractor with Config Instructions (`src/extractor.py`)

- `extract_specs()` now reads `extraction.llm.prompt` from config and passes as `instructions`
- Added `url` parameter to inject product URL into results
- Continues to support `llm_hints` for schema description enrichment

### 4. Pipeline Wiring (`src/pipeline.py`)

**Single URL mode** (`--url`):
- Renders page via Crawl4AI → gets markdown
- Creates `OllamaAdapter`, checks availability
- Calls `extract_specs()` with config instructions
- Outputs validated JSON to stdout

**Full pipeline mode** (`--config`):
- Discovers URLs → checks adapter availability → extracts all
- `_extract_all()`: iterates URLs, renders page, extracts specs, saves results
- Crash recovery via `Crawler.save_partial()` — saves after each successful extraction
- Resumes from partial progress on restart
- Skips failed URLs (render or extraction failures) and continues
- Attaches `is_current` metadata from URL discovery
- Finalizes results to `{slug}_raw.json`, cleans up partial file

**Helper functions:**
- `_get_adapter()`: Creates OllamaAdapter, verifies availability, provides setup instructions on failure
- `_extract_all()`: Full batch extraction with progress, crash recovery, and result finalization
- `_finalize_results()`: Writes final JSON output

**Dry-run support:**
- `--dry-run` skips adapter initialization (no Ollama needed)
- Lists all URLs that would be extracted without making requests

### 5. Config Integration

The `ozone.yaml` config's `extraction.llm.prompt` (Ozone-specific rules) is passed to the adapter as instructions, giving the LLM manufacturer-specific context for extraction.

---

## Verification Results

| Test | Result |
|------|--------|
| Import chain (pipeline → adapters → extractor → crawler) | ✅ |
| `--url` renders page (32,643 chars) and checks adapter | ✅ |
| `--url --dry-run` skips rendering | ✅ |
| `--config --dry-run` discovers 115 URLs and lists all | ✅ |
| Graceful Ollama-unavailable message with setup instructions | ✅ |
| Config prompt passed through adapter → `_build_prompt()` | ✅ |

**Note:** Live LLM extraction not tested — Ollama not installed on this machine. All wiring verified with dry-run and graceful failure paths. Full end-to-end test deferred to Iteration 7 (Ozone Validation Run).

---

## Files Modified

| File | Changes |
|------|---------|
| `src/adapters/base.py` | Added `instructions` parameter to `extract()` |
| `src/adapters/ollama.py` | `extract()` and `_build_prompt()` accept instructions; enhanced default prompt |
| `src/extractor.py` | `extract_specs()` passes config prompt as instructions; added `url` parameter |
| `src/pipeline.py` | Wired extraction into `--url` and full pipeline; added `_get_adapter()`, `_extract_all()`, `_finalize_results()` |
| `documentation/architecture/ITERATION_03_LLM_EXTRACTION.md` | Created |

---

## What's Next — Iteration 4: Markdown Fallback Strategy

- Port the deterministic markdown parser from `extract.py` (43 label mappings, `_MD_ROW_MAP`, EU decimal handling)
- Make it a pluggable strategy producing `ExtractionResult`
- Auto-fallback: if LLM fails → try markdown parser
- Both strategies produce the same output shape
