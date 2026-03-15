# Iteration 13 — Fix Flow & Certification Handling

**Date:** 2026-03-15
**Status:** Complete
**Domain:** data / architecture

---

## Overview

Added an interactive `fix` command to the CLI pipeline and overhauled certification handling to preserve original manufacturer data (facts-only policy). Fixed duplicate certification bugs caused by blind INSERT on re-extraction.

---

## Changes

### 1. `fix` CLI Command (`src/pipeline.py`)

New Typer command for interactive model repair:

```
python -m src.pipeline fix --db output/ozone.db
python -m src.pipeline fix --db output/ozone.db --model ozone-addict-2
```

**Flow:**
1. Load validation log → show pending models with issue counts
2. User picks a model (or passes `--model` slug directly)
3. Show current DB state (table format)
4. Re-extract from manufacturer URL (crawl → LLM/markdown parser → normalize)
5. Show new extraction result
6. Show diff (changes, fills, kept fields)
7. Confirm: `[y]es` commits, `[n]o` discards, `[j]son` shows raw JSON first
8. On commit: store to DB + update validation log action to `re_extract`

**Supporting functions added:**
- `_lookup_model_url()` — resolve model slug → URL + manufacturer from DB
- `_read_model_from_db()` — read current model/size/cert data for comparison
- `_print_model_data()` — formatted table display
- `_print_diff()` — field-by-field comparison with upsert-aware semantics

### 2. Certification Normalization (`src/normalizer.py`)

**Principle change:** Preserve the original certification exactly as it appears on the wing's type-label. Store facts, not interpretations.

**Before:** `DHV 1-2` → `LTF/B`, `LTF 2` → `LTF/C`, bare `2` → `LTF/C`
**After:** `DHV 1-2` → `LTF/1-2`, `LTF 2` → `LTF/2`, bare `2` → `LTF/2`

- Replaced `_DHV_MAP` (which converted numeric → letter) with `_DHV_NUMERIC` set (identifies valid old numeric classes)
- DHV prefix still maps to LTF standard (same certification body)
- Bare digits `1`, `1-2`, `2`, `2-3`, `3` → `LTF` standard with classification preserved
- Extended `_CERT_PATTERN` regex to capture `\d(?:-\d)?` in the class group
- Letter classifications (A/B/C/D) still uppercased; numeric preserved as-is

**Equivalence reference (for querying, not storage):**

| Modern EN | Old DHV/LTF | Old AFNOR |
|-----------|-------------|-----------|
| EN A | DHV 1 / LTF 1 | Standard |
| EN B | DHV 1-2 / LTF 1-2 | Standard/Performance |
| EN C | DHV 2 / LTF 2 | Performance |
| EN D | DHV 2-3 / LTF 2-3 | Performance/Competition |
| CCC | DHV 3 / LTF 3 | Competition |

### 3. Certification Validation (`src/validator.py`)

- LTF valid classifications expanded: `{A, B, C, D, 1, 1-2, 2, 2-3, 3}`
- EN valid: `{A, B, C, D}` (unchanged)
- AFNOR valid: `{Standard, Performance, Competition}` (unchanged)
- CCC, DGAC, `other` — not validated (no fixed classification set)

### 4. Certification Upsert & Dedup (`src/db.py`)

**Problem:** `insert_certification` did blind INSERTs. Re-extracting a model duplicated all certification rows.

**Fix:**
- Renamed to `upsert_certification` — checks for existing `(size_variant_id, standard)` pair, updates if found, inserts if new
- Added `delete_certifications_for_size(size_variant_id)` — deletes all certs for a size variant
- Backward compat alias: `insert_certification = upsert_certification`

### 5. Store Path Dedup (`src/pipeline.py`)

Both cert storage call sites (single URL and batch) now call `delete_certifications_for_size(sv_id)` before inserting new certs. This ensures re-extraction replaces old certs cleanly, even when the standard changed (e.g., `EN/2` → `LTF/2`).

### 6. Diff Display — Upsert-Aware (`src/pipeline.py`)

`_print_diff()` now reflects actual upsert behavior:
- Fields where old is non-NULL and new is NULL: shown as `(kept — not in new extraction)` instead of alarming `- was X (now empty)`
- New fills: shown as `→X (fill)`
- Cert changes: always shown (certs are replaced, not upserted by NULL-fill)
- Shows `(no effective changes)` when nothing will actually change

---

## Test Impact

- **8 new tests** in `test_normalizer.py`: bare digits (1, 1-2, 2, 2-3, 3), LTF numeric (LTF 2, LTF 1-2), LTF letter (LTF B)
- **Updated 4 test expectations**: DHV/bare-digit tests now expect preserved numeric classification
- **Total: 199 tests passing**

---

## Data Cleanup

Cleaned duplicate certifications in `output/ozone.db` from pre-fix runs:
- Deleted duplicates keeping newest per `(size_variant_id, standard)`
- Affected models: Alpina 4 GT, Buzz Z5, Delta 5, Ultralite 5

---

## Key Decisions

| Decision | Rationale |
|----------|-----------|
| Preserve original certification class | Facts-only policy — store what the manufacturer published, not our interpretation |
| DHV → LTF standard mapping | Same certification body; DHV administered the LTF standard |
| Delete-before-insert for certs on re-extract | Standard may change (EN→LTF); upsert by standard alone can't catch this |
| Diff reflects upsert behavior | Prevents user alarm about "lost" data that upsert actually preserves |
