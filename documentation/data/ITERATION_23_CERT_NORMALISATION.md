# Iteration 23 — Certification Standard Normalisation

**Status:** Complete
**Created:** 2026-03-31
**Completed:** 2026-03-31
**Domain:** data
**Prerequisite:** Iteration 22 (Model Normalisation)

---

## Goal

Normalise the 107 `standard='other'` certification rows in `ozone.db` so that
every row has a correct, queryable `standard` value (`LTF`, `EN`, or a genuine
`other`). Fix the root-cause gap in `scripts/import_staged_to_db.py` so future
re-imports don't reintroduce the problem.

---

## Problem Analysis

### What exists today

Running `SELECT standard, classification, COUNT(*) FROM certifications GROUP BY 1,2`:

| standard | classification | count | Note |
|----------|---------------|-------|------|
| CCC | CCC | 10 | ✅ correct |
| EN | A / B / C / D | 324 | ✅ correct |
| other | 1 | 11 | ❌ should be LTF |
| other | 1-2 | 37 | ❌ should be LTF |
| other | 2 | 14 | ❌ should be LTF |
| other | 2-3 | 7 | ❌ should be LTF |
| other | 1 / A | 1 | ❌ dual-cert, EN takes priority → (EN, A) |
| other | 1 / B | 4 | ❌ dual-cert → (EN, B) |
| other | 1/A | 1 | ❌ dual-cert → (EN, A) |
| other | 1/B | 4 | ❌ dual-cert → (EN, B) |
| other | 1-2 / B | 4 | ❌ dual-cert → (EN, B) |
| other | 1-2/B | 8 | ❌ dual-cert → (EN, B) |
| other | 2/3 | 4 | ❌ dual-cert → (EN, C) |
| other | B / 1-2 | 4 | ❌ dual-cert → (EN, B) |
| other | 2 / B | 1 | ❌ dual-cert → (EN, B) |
| other | Load test | 3 | ✅ genuine other (speedwing load test) |
| other | N/A | 1 | ✅ genuine other (no cert) |
| other | (empty) | 3 | ✅ genuine other (no cert info) |

**Total `other` rows:** 107 across 27 models.

**Genuinely `other`:** 7 rows (Load test ×3, N/A ×1, empty ×3) — keep as-is.  
**Misclassified as `other`:** 100 rows — all are LTF or EN.

### Why this happened

`_normalize_cert()` in `scripts/import_staged_to_db.py` handles:
- `CCC`, `EN/LTF B`, `DHV 1-2`, `EN B`, `LTF B`, bare letter `B` ✅

But has **no rule for bare numeric classes** (`"1"`, `"1-2"`, `"2"`, `"2-3"`).
Old Ozone spec pages show these as the certification value directly (e.g.,
`"Certification: 1-2"`), without the `DHV` prefix. They fall through to the
`return ("other", raw)` catch-all.

The normalizer in `src/normalizer.py` also handles bare numerics (lines 97–100)
but that code path is only used by the LLM extraction flow — not by
`import_staged_to_db.py`.

### What these certifications actually are

All 100 affected rows are from Ozone models released 2007–2018 (the DHV/LTF era).
The numeric classification system (`1`, `1-2`, `2`, `2-3`, `3`) was administered
by **LTF** (Luftsportgerätebüro), the German technical authority. DHV published
the results but LTF was the certifying body — hence `standard='LTF'`.

Dual-cert values (e.g., `1-2 / B`) appear on wings certified during the ~2010–2015
transition period when manufacturers obtained both the old LTF cert and the new EN
cert. The accepted convention is: **EN takes priority** (current standard).

### Do we need an AI agent?

No. All 100 misclassified rows follow deterministic rules with 15 distinct input
patterns. A Python lookup table handles them all without ambiguity. LLM judgment
adds latency and hallucination risk for what is a well-defined equivalence table.

---

## Normalisation Mapping

### Pure LTF numeric classes

| DB `classification` | New `standard` | New `classification` |
|---------------------|---------------|----------------------|
| `1` | `LTF` | `1` |
| `1-2` | `LTF` | `1-2` |
| `2` | `LTF` | `2` |
| `2-3` | `LTF` | `2-3` |

### Dual LTF + EN (EN takes priority)

| DB `classification` | New `standard` | New `classification` | Rationale |
|---------------------|---------------|----------------------|-----------|
| `1 / A` | `EN` | `A` | LTF 1 ≈ EN A |
| `1/A` | `EN` | `A` | Same, no spaces |
| `1 / B` | `EN` | `B` | LTF 1-2 / EN B |
| `1/B` | `EN` | `B` | Same, no spaces |
| `1-2 / B` | `EN` | `B` | LTF 1-2 / EN B |
| `1-2/B` | `EN` | `B` | Same, no spaces |
| `2/3` | `EN` | `C` | LTF 2-3 / EN C (Proton GT) |
| `B / 1-2` | `EN` | `B` | EN B / LTF 1-2 (Swift) |
| `2 / B` | `EN` | `B` | LTF 2 / EN B |

### Keep as `other`

| DB `classification` | Reason |
|---------------------|--------|
| `Load test` | Session acro wing — structural load test, not a standard class |
| `N/A` | Ultralite 16 — no certification available |
| `` (empty) | GroundHog, Roadrunner 14m, Roadrunner OS — cert unknown |

---

## Implementation Plan

### Phase 1 — Read-only audit

**Step 1.** Confirm counts match this document by running:
```sql
SELECT standard, classification, COUNT(*)
FROM certifications WHERE standard = 'other'
GROUP BY classification ORDER BY classification;
```
Expected: totals matching the table above (7 genuine other, 100 misclassified).

No files modified.

---

### Phase 2 — Fix `_normalize_cert()` in `import_staged_to_db.py`

**Step 2.** Add bare-numeric and dual-cert rules to `_normalize_cert()` in
`scripts/import_staged_to_db.py`, before the catch-all `return ("other", raw)`:

```python
# Bare numeric DHV/LTF class (e.g. "1", "1-2", "2", "2-3", "3")
_LTF_BARE = {"1": "1", "1-2": "1-2", "2": "2", "2-3": "2-3", "3": "3"}

# Dual LTF+EN — EN takes priority
_DUAL_CERT = {
    "1 / a": ("EN", "A"), "1/a": ("EN", "A"),
    "1 / b": ("EN", "B"), "1/b": ("EN", "B"),
    "1-2 / b": ("EN", "B"), "1-2/b": ("EN", "B"),
    "2/3": ("EN", "C"),
    "b / 1-2": ("EN", "B"), "b/1-2": ("EN", "B"),
    "2 / b": ("EN", "B"),
}
```

Insert before the catch-all:
```python
# Dual LTF+EN cert (transition era)
lower = raw.lower().replace(" ", "")
lower_spaced = raw.lower()
dual = _DUAL_CERT.get(lower_spaced) or _DUAL_CERT.get(lower)
if dual:
    return dual

# Bare LTF/DHV numeric
if raw.strip() in _LTF_BARE:
    return ("LTF", _LTF_BARE[raw.strip()])
```

**Files modified:** `scripts/import_staged_to_db.py`

---

### Phase 3 — Data migration

**Step 3.** Run migration SQL on `output/ozone.db`:

```sql
-- Pure LTF numerics
UPDATE certifications SET standard='LTF' WHERE standard='other' AND classification='1';
UPDATE certifications SET standard='LTF' WHERE standard='other' AND classification='1-2';
UPDATE certifications SET standard='LTF' WHERE standard='other' AND classification='2';
UPDATE certifications SET standard='LTF' WHERE standard='other' AND classification='2-3';

-- Dual-cert: EN takes priority
UPDATE certifications SET standard='EN', classification='A'
    WHERE standard='other' AND classification IN ('1 / A', '1/A');
UPDATE certifications SET standard='EN', classification='B'
    WHERE standard='other' AND classification IN (
        '1 / B', '1/B', '1-2 / B', '1-2/B', 'B / 1-2', '2 / B'
    );
UPDATE certifications SET standard='EN', classification='C'
    WHERE standard='other' AND classification='2/3';
```

(Load test, N/A, empty intentionally omitted → remain `other`.)

**Files modified:** `output/ozone.db` (data only)

---

### Phase 4 — Tests

**Step 4.** Add unit tests for the new `_normalize_cert()` rules in a new test
class `TestNormalizeCertStagedImport` in `tests/test_db.py` or a dedicated
`tests/test_import_staged.py`.

Test cases to cover:
- `"1"` → `("LTF", "1")`
- `"1-2"` → `("LTF", "1-2")`
- `"2"` → `("LTF", "2")`
- `"2-3"` → `("LTF", "2-3")`
- `"1/B"` → `("EN", "B")`
- `"1-2 / B"` → `("EN", "B")`
- `"2/3"` → `("EN", "C")`
- `"B / 1-2"` → `("EN", "B")`
- `"Load test"` → `("other", "Load test")`
- Existing passing cases: `"EN B"`, `"CCC"`, `"DHV 1-2"`, `"B"` (bare letter)

**Files modified:** `tests/` (new test class)

---

### Phase 5 — Verification

**Step 5.** Post-migration queries:
```sql
-- No pure numeric LTF left in 'other'
SELECT COUNT(*) FROM certifications
  WHERE standard='other' AND classification IN ('1','1-2','2','2-3','3');
-- Expected: 0

-- No dual-cert strings left in 'other'
SELECT COUNT(*) FROM certifications
  WHERE standard='other' AND classification LIKE '%/%';
-- Expected: 0

-- LTF count (new)
SELECT standard, COUNT(*) FROM certifications GROUP BY standard ORDER BY standard;
-- Expected: CCC=10, EN=~415, LTF=69, other=7

-- All 'other' rows are genuinely unclassified
SELECT classification, COUNT(*) FROM certifications
  WHERE standard='other' GROUP BY classification;
-- Expected: only '', 'N/A', 'Load test'
```

**Step 6.** Run `./run_tests.sh` — all tests must pass.

---

## Files Created / Modified

| File | Change |
|------|--------|
| `scripts/import_staged_to_db.py` | Add bare-numeric + dual-cert rules to `_normalize_cert()` |
| `output/ozone.db` | Data migration: 100 cert rows updated (standard → LTF or EN) |
| `tests/test_import_staged.py` (new) | Unit tests for the fixed `_normalize_cert()` |
| `documentation/README.md` | Add row 23 |

---

## Done Criteria

| Gate | Metric | Target |
|------|--------|--------|
| Data | `standard='other'` count | 7 (Load test ×3, N/A ×1, empty ×3) |
| Data | `standard='LTF'` count | 69 |
| Data | No `other` rows with numeric classif. | 0 |
| Data | No `other` rows with `/` in classif. | 0 |
| Code | `_normalize_cert("1-2")` → `("LTF", "1-2")` | |
| Code | `_normalize_cert("1-2/B")` → `("EN", "B")` | |
| Tests | All existing + new tests pass | |

---

## Why Not an AI Agent?

All 100 rows follow 15 deterministic patterns derivable from a lookup table. The
DHV→LTF→EN equivalence is a published, fact-based standard. LLM reasoning adds
no value here and introduces hallucination risk. This is a **code + SQL** problem,
not a **reasoning** problem.
