# Iteration 21 — Data Curation & Verification

**Status:** In Progress  
**Created:** 2026-03-30  
**Domain:** data  
**Prerequisite:** Iteration 20 (Complete — Ozone MVP DB, 116 models, quality 100%)

---

## Goal

Fix the data gaps left in `ozone.db` after Iteration 20, establish a per-field
completeness metric and verification system, and build a reusable curation tool
(`scripts/data_curator.py`) for all future brands.

**Priority order (user-defined):**
1. **Certification existence** — `standard` + `classification` are the most critical cert fields.
   A glider with no cert records at all is a hard data gap (status: `incomplete`).
   Old gliders without a certification standard must be explicitly marked `not_available`
   to be considered resolved.
2. Certification details — `test_lab`, `report_url`, `test_date`, `report_number` (all 0%)
3. `wing_weight_kg` — missing on ~66 historical models (86% populated)
4. `year_discontinued` — missing on all 115 historical models (0%)
5. Other minor gaps as discovered

---

## Design Decisions

### `field_verifications` table (new, in `src/db.py`)

A new table records the verification status of individual fields on individual records:

```sql
CREATE TABLE IF NOT EXISTS field_verifications (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    table_name   TEXT    NOT NULL,
    record_id    INTEGER NOT NULL,
    field_name   TEXT    NOT NULL,
    status       TEXT    NOT NULL CHECK(status IN ('verified','not_available','pending_approval')),
    source_url   TEXT,
    verified_at  TEXT,
    verified_by  TEXT    CHECK(verified_by IN ('user','agent')),
    notes        TEXT,
    UNIQUE(table_name, record_id, field_name)
);
```

**Three statuses:**

| Status | Meaning |
|--------|---------|
| `verified` | Field value is confirmed correct from a known source |
| `not_available` | Field is intentionally absent (data doesn't exist for this record) |
| `pending_approval` | AI suggested a value; awaiting human review |

**`not_available` counts as filled** in the completeness score — it means the question
has been answered (the answer is "not available"), which is complete knowledge.

### Upsert guard

`upsert_certification()` is extended to skip writing any field that already has
`status = 'verified'` or `status = 'not_available'` in `field_verifications`. This
prevents a re-crawl from overwriting cert detail fields (`test_lab`, `report_url`, etc.)
that were manually curated.

`upsert_model()` and `upsert_size_variant()` already use fill-NULL-only logic, so verified
values there are protected by the existing NULL check.

### Completeness metric

Fields are split into two tiers:

| Tier | Tables → Fields | Blocks |
|------|----------------|--------|
| **Required** | models → category, year_released, cell_count | `complete` status |
| | size_variants → flat_area_m2, flat_span_m, proj_area_m2, ptv_min_kg, ptv_max_kg | |
| | certifications → standard, classification | |
| **Optional** | models → year_discontinued | `verified` status |
| | size_variants → wing_weight_kg, proj_span_m, proj_aspect_ratio, line_length_m | |
| | certifications → test_lab, report_url, test_date, report_number | |

**Model status logic:**

```
score = (populated + not_available_verified) / total_expected

incomplete → required_score < 1.0
complete   → required_score == 1.0  AND  optional_score < 1.0
verified   → required_score == 1.0  AND  optional_score == 1.0
```

---

## Tool: `scripts/data_curator.py`

Brand-agnostic (takes `--db PATH`). Uses `rich` (already installed v14.3.3) — no new deps.

### Mode A — Interactive TUI (default)

```bash
python3 scripts/data_curator.py --db output/ozone.db
```

---

**Screen 1 — Dashboard**

```
╭─ ozone.db · 116 models · avg 68% · incomplete: 89 · complete: 27 · verified: 0 ─╮

  #    slug                      req%    opt%    status       top gaps
  1    ozone-mantra-r4            67%     0%     incomplete   year_released, …
  2    ozone-buzz-z5             100%     0%     complete     test_lab, wing_weight…
 …
116    ozone-rush-6              100%   100%     verified
```

Prompt: `[number]` open model · `[f text]` filter · `[r]` refresh · `[q]` quit

---

**Screen 2 — Model detail** (type row number)

Shows three gap-focused panels — MODEL FIELDS (all fields), SIZE VARIANTS
(gap summary: field → X/Y populated), CERTIFICATIONS (gap summary).

```
╭─ Ozone Mantra M6 · paraglider · 2016–? · 76 cells ──────────────────────╮

MODEL FIELDS
  field               value        V?    range / allowed
  category            paraglider   ✓
  year_released       2016         ✓     1990–2030
  year_discontinued   —            —     1990–2030        ← yellow
  cell_count          76           ✓     15–120

SIZE VARIANTS (5 sizes) — gap summary
  field              populated     status
  flat_area_m2       5/5           ✓
  wing_weight_kg     0/5           gaps   ← red

CERTIFICATIONS (5 certs) — gap summary
  field              populated     status
  classification     5/5           ✓
  test_lab           0/5           gaps   ← red
  report_url         0/5           gaps   ← red
```

Prompt: `[field-name]` edit · `[l]` lock all non-NULL · `[b]` back

---

**Field edit** (type a field name)

```
  test_lab  [Testing laboratory]  range: text (e.g. SHV, DHV, ACPUL)
  context: Ozone Mantra M6 size S cert EN/D
  current: —
  > Enter value  [n]=not available  [?]=ask AI  [s]=skip
  > SHV
  Write 'SHV' to certifications.test_lab on Ozone Mantra M6 size S cert EN/D? [y/N] y
  ✓ Saved. Score: 40% → 60%
```

- Plain value → validate plausibility → confirm → write DB + `field_verifications(verified, user)`
- `[n]` → mark `not_available` (no DB value change); counts toward completeness score
- `[?]` → **only then** call Ollama inline — shows suggestion + confidence + training-data note;
  user accepts/edits/rejects. AI is never called automatically.
- `[s]` → skip, field remains pending
- For size_variant/cert fields: iterates through all sizes/certs with missing values one by one

**`[l]` lock** → marks all currently non-NULL fields of the model as `verified`.
Confirmation prompt before writing.

---

### Mode B — CLI flags (batch AI delegation)

```bash
# Export pending gaps as a JSON task file for an AI agent session
python3 scripts/data_curator.py --db output/ozone.db \
  --export-tasks output/tasks/cert_tasks.json --field test_lab

# Review and apply an AI-researched patch
python3 scripts/data_curator.py --db output/ozone.db \
  --apply-patch output/tasks/cert_patch.json
```

**`--export-tasks TASK_FILE`** — produces:
```json
{
  "task_id": "...",
  "created_at": "...",
  "db_path": "output/ozone.db",
  "total_items": 434,
  "items": [{
    "table": "certifications",
    "record_id": 42,
    "model_slug": "ozone-mantra-m6",
    "model_name": "Mantra M6",
    "size_label": "S",
    "field": "test_lab",
    "current_value": null,
    "context": "Mantra M6 size S cert EN/D",
    "search_hint": "DHV Geräteportal — test laboratory name for Mantra M6",
    "search_urls": ["https://www.dhv.de/db2/module/geraet/suche/"],
    "value": null,
    "source_url": null
  }]
}
```
AI agent fills `value` + `source_url` per item and returns a patch JSON.

**`--apply-patch PATCH_FILE`** — rich diff table:
```
  #    Model               Size  Field       Current  Proposed  Source
  1    ozone-mantra-m6     S     test_lab    —        SHV       https://dhv.de/…
  2    ozone-mantra-m6     S     report_url  —        https://… https://dhv.de/…
```
Prompt: `[a]` accept all · `[1,3,5]` accept by number · `[r]` reject all

Accepts: write to DB + `field_verifications(verified, agent)`.  
Skips items already marked `verified`.  
Validates `item.table` and `item.field` against allowed lists (security guard vs adversarial patch files).

---

## Phase 4 — Fix Ozone Gaps

After the tool is built, run the fix workflow in priority order:

| Priority | Gap | Workflow |
|----------|-----|---------|
| 1 | Cert details (0% → target ≥80%) | `--export-tasks --field test_lab` → AI session (DHV portal) → `--apply-patch` |
| 2 | `wing_weight_kg` (86% → target ≥95%) | `--export-tasks --field wing_weight_kg` → AI session (fredvol + manufacturer archive) → `--apply-patch` |
| 3 | `year_discontinued` (0% → target ≥70%) | `--export-tasks --field year_discontinued` → AI session → `--apply-patch` |
| 4 | Lock 22 current models | Interactive TUI → `[l]` on each (already 100% quality from Iteration 20) |

---

## Quality Fixes Applied

### Scoring bug — models with zero cert records reported as `complete`

**Found:** 2026-03-30, during first live TUI run against `ozone.db`.

**Symptom:** `ozone-mantra-m6` showed as `complete · 71%` in the dashboard despite having
no certification records at all. `standard` and `classification` were absent from its
top-gaps list.

**Root cause:** `compute_model_score()` in `scripts/data_curator.py` only iterated over
*existing* cert rows. When a size variant had zero cert records, the certification
table fields were never added to the denominator — so they were invisible to the score.

**Fix:** When a size variant has no cert records, each field in
`REQUIRED_FIELDS["certifications"]` (`standard`, `classification`) is now added as a
missing required gap, contributing to both the denominator and the gap list.

**Result:** Mantra M6 correctly becomes `incomplete · req 74%`, with
`standard` and `classification` as top-priority gaps.

**Detail screen:** The cert panel now shows a red warning
`CERTIFICATIONS — no records for N/M sizes (standard, classification required)`
instead of the silent dim `No certifications.`

### Design rationale — `certifications.standard` and `certifications.classification`

`standard` and `classification` are the two most important fields in the certification
domain. Without them, a glider's safety certification is unknown — this is a hard data
gap regardless of how complete all other fields are.

- They are the only cert fields in **`REQUIRED_FIELDS["certifications"]`**; all other
  cert detail fields (`test_lab`, `report_url`, etc.) are **optional**.
- A model missing cert records entirely is always `incomplete`, never `complete`.
- For old or non-certified gliders (e.g. ground handlers, acro wings without EN cert),
  the correct action is to mark `standard` and `classification` as `not_available`
  via `n` in the TUI field edit. `not_available` counts towards the score — it means
  the question has been answered ("no certification exists"), which is complete knowledge.

---

### Bug — `edit_field_for_model` silently did nothing when cert records were absent

**Found:** 2026-03-30, during first live TUI session.

**Symptom:** After the scoring fix correctly flagged `standard` as a required gap,
typing `standard` in the model detail screen triggered no prompts and returned
immediately with no feedback. The certifications section showed a warning but provided
no path to fix it.

**Root cause:** The cert branch of `edit_field_for_model()` iterated only over existing
cert rows (`for cert in cert_rows`). With zero rows, the loop body never executed.

**Fix:** Added a `_create_cert_for_size()` helper. When the cert branch finds a size
variant with no cert records and the field is `standard` or `classification`, it now
runs an interactive creation flow: prompts for `standard` (enum-validated), then
`classification`, inserts the row, and marks both fields `verified`. For any other cert
field entered before a cert record exists, it prints a clear hint:
`Size S: no cert record exists — type 'standard' first to create one.`

**Cert warning updated:** The red `CERTIFICATIONS — no records for N/M sizes` message
now includes the action hint:
`→ Type 'standard' to add certification data for each size`

---

### Bug — TUI commands invisible or non-functional due to Rich markup collision

**Found:** 2026-03-30, during live TUI testing.

**Symptoms** (three separate issues):
1. Commands bar showed `=lock all non-NULL  · =back  · =quit` — the key letters were
   invisible. Typing `b`, `l`, or `q` appeared not to work.
2. Pressing Enter on an empty prompt triggered the **back** action unexpectedly.
3. After editing all gaps, the screen said `Cancelled` with no score update.

**Root causes:**
1. Rich markup strings interpreted `[b]`, `[l]`, `[q]`, `[n]`, `[s]`, `[r]`, `[a]`,
   `[f]` as formatting tags (`[b]` = bold; others silently stripped). All command-key
   labels were inside `[yellow][x][/yellow]` — the inner `[x]` tag ate the letter.
2. The loop condition was `if cmd in ("b", "")` — plain Enter collapsed to `""` and
   triggered `break`/back.
3. `edit_field_for_model()` returned `changes=0` with no message when all sizes already
   had values, leaving the user uncertain whether anything happened.

**Fixes:**
1. Removed brackets from key labels in all `console.print()` command bars throughout
   the script. Keys now render without markup: `l lock  b back  q quit`.
2. Separated the empty-string case: `cmd == "b"` → break; `cmd == ""` → `continue`
   (re-renders the screen, no navigation).
3. Added `else` branch after `edit_field_for_model()`: prints
   `No pending gaps for '<field>' (all sizes already filled or verified).`
4. The `>` prompt now prints the accepted commands directly above it on every loop
   iteration so they are always visible without scrolling:
   ```
   field-name edit  l lock  b back  q quit
   > 
   ```
5. Field list in the detail screen split into
   `Required fields: …` (red) and `Optional fields: …` (dim), replacing the undifferentiated
   alphabetical list.

---

### Improvement — `--export-tasks` field priority filtering

**Added:** 2026-03-30.

**Motivation:** The default `--export-tasks` export contained up to 4× more items than
necessary for a typical agent session (cert details, projected geometry) that are either
rarely available or difficult to source. Including them diluted the agent's focus and
inflated task file sizes.

**Implementation:** Added `FIELD_TASK_PRIORITY` dict and `--all-fields` CLI flag.

```python
FIELD_TASK_PRIORITY = {
    # low = cert details (hard to source, secondary value)
    "test_lab": "low",  "report_url": "low",  "test_date": "low",  "report_number": "low",
    # low = projected geometry (may genuinely not be published by manufacturer)
    "proj_area_m2": "low",  "proj_span_m": "low",  "proj_aspect_ratio": "low",  "line_length_m": "low",
    # all other fields default to "high"
}
```

**Default behaviour (no `--all-fields`):** only high-priority gaps are exported (the
fields an agent can actually fill in a single web session: `ptv_min_kg`, `ptv_max_kg`,
`flat_area_m2`, `flat_span_m`, `wing_weight_kg`, `year_discontinued`, `standard`,
`classification`).

**`--all-fields` flag:** includes all gaps including low-priority ones — useful when
dedicating a session solely to cert detail lookup on the DHV portal.

**Every item** now carries a `"priority": "high"|"low"` field so the patch JSON is
self-describing and the applying agent can choose to skip low-priority items.

**`scope` header field** in the exported JSON tells the agent which mode was used:
```json
{ "scope": "high-priority fields only (use --all-fields to include cert details and rare geometry)" }
```

**Smoke-test result (rush-4):**
- Default: 13 items, all `high`, fields: `ptv_min_kg`, `ptv_max_kg`, `year_discontinued`
- `--all-fields`: 43 items — 13 high + 30 low

---

## Files Created / Modified

| File | Change |
|------|--------|
| `src/db.py` | Add `field_verifications` table, helpers, upsert guard on `upsert_certification` |
| `scripts/data_curator.py` | New — interactive TUI + CLI batch modes |
| `scripts/data_curator.py` | Bug fix: scoring missed zero-cert-record sizes (2026-03-30) |
| `scripts/data_curator.py` | Bug fix: `edit_field_for_model` silent on missing cert rows; added `_create_cert_for_size()` (2026-03-30) |
| `scripts/data_curator.py` | Bug fix: Rich markup ate command-key letters; empty-Enter triggered back; no-changes feedback (2026-03-30) |
| `scripts/data_curator.py` | Bug fix: confirmation prompts only accepted `y`; typing `yes` triggered Cancelled (2026-03-30) |
| `scripts/data_curator.py` | Improvement: `FIELD_TASK_PRIORITY` + `--all-fields` flag; `priority` field on every exported item; `scope` header in task JSON (2026-03-30) |

---

## Done Criteria

| Gate | Metric | Target |
|------|--------|--------|
| Schema | `field_verifications` table present in DB | ✓ created |
| Upsert guard | Re-crawl does not overwrite `verified` cert fields | ✓ confirmed |
| TUI | Dashboard renders sorted completeness table | ✓ |
| TUI | Field edit writes to DB + verification record | ✓ |
| Tests | All existing tests pass unchanged | 316/316 |
| Phase 4 | `test_lab` completeness after cert fix | ≥ 80% |
| Phase 4 | Overall completeness score improvement over Iteration 20 | > 51.3% |
