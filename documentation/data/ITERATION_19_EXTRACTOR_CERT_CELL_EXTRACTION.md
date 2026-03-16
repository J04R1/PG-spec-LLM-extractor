# Iteration 19 — Extractor: Missing Certification & Cell Count Extraction

**Status:** Not Started  
**Created:** 2025-03-16  
**Domain:** data / extraction  

---

## Problem

The markdown parser fallback (`src/markdown_parser.py`) fails to extract **certifications** and **cell count** from Ozone product pages that use the labels `"DHV"` and `"No of cells"`.

### Evidence

Running `pipeline run --url` on the Buzz page with the markdown parser fallback (Ollama unavailable) produces correct geometry and weight data but **zero certifications** and **no cell count**:

```
python -m src.pipeline run --url https://flyozone.com/paragliders/products/gliders/buzz --db output/ozone.db
```

Output includes 5 sizes with all geometry fields but no `certification` or `cell_count` field.

### Root Cause

The crawled markdown contains this spec table:

```
# Specifications
| XS | S | M | L | XL  
---|---|---|---|---|---  
No of cells | 42 | 42 | 42 | 42 | 42  
Area Proj. | 19.55 | 20.93 | 22.7 | 24.86 | 27.25  
...
In flight weight Range* | 55-70 | 65-85 | 80-100 | 95-115 | 110-135  
DHV | 1-2 | 1-2 | 1-2 | 1-2 | 1-2  
```

Two label mapping gaps in `_MD_ROW_MAP`:

| Crawled label | Normalized lookup | Current mappings | Matches? |
|---|---|---|---|
| `No of cells` | `"no of cells"` | `"number of cells"`, `"cells"` | **No** |
| `DHV` | `"dhv"` | `"en"`, `"en/ltf"`, `"ltf / en"`, `"certification"`, `"ltf"` | **No** |

The parser correctly parses the pipe-delimited table and extracts all other rows but silently skips these two because `_MD_ROW_MAP.get(label_low)` returns `None`.

---

## Fix Required

### 1. Add missing label mappings to `_MD_ROW_MAP`

In `src/markdown_parser.py`, add to the cell count section:

```python
"no of cells":                     ("cell_count",         False, False),
"no. of cells":                    ("cell_count",         False, False),
```

Add to the certification section:

```python
"dhv":                             ("certification",      True,  False),
"dhv/ltf":                         ("certification",      True,  False),
```

### 2. Handle DHV-style certification values

The parser's certification handling (around line 260) strips trailing `*` and stores the raw value. DHV values like `"1-2"` need to pass through the normalizer, which should map them to EN equivalents:

| DHV value | EN equivalent |
|---|---|
| `1` | `A` |
| `1-2` | `B` |
| `2` | `C` |
| `2-3` | `D` |
| `3` | (no direct EN mapping — store as-is) |

This mapping may already exist in `src/normalizer.py` (`normalize_certification()`). Verify and extend if needed.

### 3. Add test cases

Add to `tests/test_markdown_parser.py`:

- Test that `"No of cells | 42 | 42"` extracts `cell_count=42`
- Test that `"DHV | 1-2 | 1-2"` extracts `certification="1-2"` per size
- Integration test with the full Buzz table markdown

### 4. Verify with pipeline run

After fixing, re-run the Buzz extraction and confirm:
- `cell_count: 42` appears in model-level data
- Each size has `certification` field populated  
- Normalization maps `DHV 1-2` → `EN B` (or stores raw `1-2` with `DHV` standard)

---

## Scope

**Files to modify:**
- `src/markdown_parser.py` — add label mappings (~4 lines)
- `src/normalizer.py` — verify DHV→EN mapping exists, add if missing
- `tests/test_markdown_parser.py` — add test cases for new labels

**Files to check:**
- `src/models.py` — ensure `CertStandard` enum includes `DHV` if not already
- `src/extractor.py` — no changes expected (passes through to parser)

---

## Impact

- **27 Ozone models** currently flagged with `no_certifications` in validation — many likely have DHV cert rows that are simply not being parsed
- Cell count is missing from most models — same root cause for pages using `"No of cells"` label
- Fix is low-risk: only adds new dictionary entries, no logic changes to the parser

---

## Verification

```bash
# After fix, run extraction
python -m src.pipeline run --url https://flyozone.com/paragliders/products/gliders/buzz --db output/ozone.db

# Expected output should include:
#   "cell_count": 42
#   "certification": "1-2" (or mapped EN value) per size

# Run tests
./run_tests.sh

# Re-validate the full DB
python -m src.pipeline validate --db output/ozone.db
```
