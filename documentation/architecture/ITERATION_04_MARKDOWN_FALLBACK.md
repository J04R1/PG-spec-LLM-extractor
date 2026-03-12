# Iteration 04 — Markdown Fallback Strategy

**Status:** Complete
**Date:** March 2026

---

## Summary

Ported the deterministic markdown table parser from the POC (`extract.py`, lines 477–700)
into a standalone module (`src/markdown_parser.py`). Wired it as an auto-fallback in
`src/extractor.py` — when the LLM adapter is unavailable or returns empty, the pipeline
falls back to the markdown parser. Both strategies produce the same `ExtractionResult`
Pydantic model.

---

## Changes

### New Files

| File | Purpose |
|------|---------|
| `src/markdown_parser.py` | Deterministic pipe-delimited spec table parser (ported from POC) |

### Modified Files

| File | Changes |
|------|---------|
| `src/extractor.py` | Refactored into LLM-first with markdown fallback; `extract_specs()` accepts `adapter=None` |
| `src/pipeline.py` | Graceful Ollama-unavailable handling — uses markdown fallback instead of exiting |

---

## Architecture

### Two-Strategy Extraction

```
extract_specs(adapter, markdown, config, url)
  ├── Strategy 1: LLM extraction (if adapter is not None)
  │   └── adapter.extract(markdown, schema, instructions)
  │       └── ExtractionResult.model_validate(raw)
  │
  └── Strategy 2: Markdown parser fallback (if LLM fails or no adapter)
      └── parse_specs_from_markdown(markdown, url)
          └── Returns ExtractionResult directly
```

Both strategies produce `ExtractionResult` — downstream normalization and storage
are strategy-agnostic.

### Markdown Parser Design

Ported from the POC's `parse_specs_from_markdown()` with these components:

1. **`_MD_ROW_MAP`** — 43 label-to-field mappings covering:
   - Cell count (model-level)
   - Flat/projected geometry (area, span, aspect ratio)
   - Wing weight
   - Weight range (needs range split → `ptv_min_kg` / `ptv_max_kg`)
   - Certification labels (EN, LTF, EN/LTF variants)
   - Short label variants for older Ozone pages

2. **`_SIZE_LABEL_HINTS`** — Size detection set (XS–XXXL + numeric 22–31)

3. **8-phase parse pipeline:**
   - Phase 1: Find spec table (heading match or row-label heuristic)
   - Phase 2: Collect pipe-delimited rows
   - Phase 3: Detect size labels (3 strategies + synthetic fallback)
   - Phase 4: Parse data rows into per-size dicts
   - Phase 5: Validate (require weight ranges or certifications)
   - Phase 6: Infer model name from URL slug or page title
   - Phase 7: Infer `target_use` from primary certification
   - Phase 8: Build `ExtractionResult` with `SizeSpec` objects

4. **EU decimal handling:** Comma → period when no period present (`"18,9"` → `"18.9"`)

5. **Weight range parsing:** Supports hyphens, en-dashes, em-dashes, forward slashes

6. **CCC normalization:** `CCC+`, `CCC*` variants → `"CCC"`

### Pipeline Behavior Change

Previously: Ollama unavailable → pipeline exits with error.
Now: Ollama unavailable → logs info message → proceeds with markdown-only extraction.

This makes the pipeline usable without Ollama installed, using the free deterministic
parser as the sole extraction strategy.

---

## Testing

### Parser Direct Tests

| Test | Input | Result |
|------|-------|--------|
| Standard Ozone table | 5 sizes (XS–XL), full specs, EN B | ✅ All fields extracted correctly |
| EU decimals | Comma decimals (`18,9`) | ✅ Converted to `18.9` |
| CCC certification | `CCC+` in cert column | ✅ Normalized to `"CCC"` |
| Target use inference | EN A cert | ✅ `target_use = "school"` |
| Older label formats | `AR Flat`, `Area Proj.` | ✅ Mapped correctly |
| No explicit size row | Size labels inferred from `_SIZE_LABEL_HINTS` | ✅ Detected |
| Model name from URL | `rush-6` slug | ✅ `"Rush 6"` |

### Integration Tests

| Test | Result |
|------|--------|
| `extract_specs(None, markdown, {}, url=...)` | ✅ Falls back to markdown parser |
| `--url` with Ollama unavailable | ✅ Renders page, falls back to markdown parser |
| All imports (`markdown_parser`, `extractor`, `pipeline`) | ✅ Clean |

---

## Verification Criteria Met

From the master plan:
- ✅ Deterministic parser ported into pluggable module
- ✅ Auto-fallback: LLM fails → markdown parser
- ✅ Both strategies produce `ExtractionResult`
- ✅ 43 label mappings preserved from POC
- ✅ EU decimal handling, weight range parsing, CCC normalization
