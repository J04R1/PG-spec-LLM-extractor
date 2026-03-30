# Iteration 22 — Model List Normalisation

**Status:** Complete
**Created:** 2026-03-30
**Completed:** 2026-03-30
**Domain:** data
**Prerequisite:** Iteration 20 (Ozone MVP DB), Iteration 21 (Data curation TUI)

---

## Goal

Normalise the `models` table schema and data in `ozone.db` so that:
1. The `category` column reflects the **sport/modality** (paraglider, paramotor, speedwing)
2. A new `sub_type` column captures the **structural/use sub-category** within paraglider (solo, tandem, acro, miniwing, single_skin)
3. The `is_current` flag is correct for all 116 models (22 current, 94 discontinued)
4. Known data bugs (Mantra M3 year) are fixed
5. The DB model list is a verified 1:1 match with the Ozone website

**Non-goal:** adding new models, populating `model_target_uses`, enriching paramotor/speedwing data.

---

## Pre-condition Audit (2026-03-30)

### URL List vs DB — Perfect Match

`output/ozone_urls.json` contains 116 unique product slugs:
- Previous gliders page: 115 slugs
- Current gliders page: 22 slugs
- Overlap (current models also on previous page): 21
- Only on current page: 1 (`vibe-gt` — newest model)
- **Total unique: 116**

**DB models: 116. Diff: 0 gaps in either direction.** Every Ozone website entry has a
DB record, and every DB record has a website entry. No models need to be added or removed.

### Category Breakdown (current state)

| category | count |
|----------|-------|
| paraglider | 93 |
| tandem | 11 |
| acro | 5 |
| paramotor | 5 |
| speedwing | 2 |

### is_current Flag

| is_current | count | expected | delta |
|------------|-------|----------|-------|
| 1 | 1 | 22 | -21 |
| 0 | 115 | 94 | +21 |

Only `Vibe Gt` is marked `is_current=1`. The other 21 current models all have
`is_current=0` — likely because `year_discontinued IS NULL` was not used as the
criterion during import.

### Known Data Bugs

| Model | Bug | Current value | Fix |
|-------|-----|---------------|-----|
| Mantra M3 | `year_discontinued` < `year_released` | released=2013, discontinued=2011 | Set `year_discontinued=NULL` (unknown, verify later) |

### Non-paraglider Models in DB (23 rows, all on Ozone paragliders site)

**Tandem (11):** Cosmic Rider, Mag2Lite, Magnum, Magnum 2, Magnum 2009, Magnum 3,
Magnum 4, Swiftmax, Swiftmax 2, Wisp, Wisp 2

**Acro (5):** Addict, Addict 2, Session, Trickster, Trickster 2

**Paramotor (5):** LM4, LM5, LM6, LM7, McDaddy

**Speedwing (2):** XXLite, XXLite 2

All 23 are listed on flyozone.com/paragliders (not /paramotor or /speed), so they
belong in this database. The schema issue is that `category` currently mixes two
dimensions: sport-modality and wing sub-type.

---

## Previously Suspected Missing Models — Resolved

The following models were flagged as potentially missing during the coverage audit
(`data/ozone_model_coverage_audit.md`). All have been resolved:

| Model | Resolution |
|-------|-----------|
| Atom | Not on Ozone previous gliders page. fredvol/DHV data artifact |
| Swift 3 | Not on Ozone previous gliders page. Does not exist as an Ozone product |
| Indy | Not on Ozone previous gliders page. fredvol artifact |
| Fazer / 2 / 3 | Speed wings (flyozone.com/speed), not paragliders. Correctly absent |
| Firefly / 2 / 3 | Speed wings (flyozone.com/speed). Correctly absent |
| Litespeed | Not on Ozone previous gliders page. fredvol artifact |
| Mantra M5 | Does not exist. Ozone went M4 → M6 directly |
| Cosmic (vs Cosmic Rider) | Cosmic Rider is in DB. "Cosmic" is a DHV naming artifact |
| Zero | Not on Ozone previous gliders page. fredvol misattribution |
| XT | Not on Ozone previous gliders page. fredvol artifact |
| Mantra 7 | Alias for Mantra M7 (already in DB). Enrichment CSV naming artifact |

**Source of truth:** https://flyozone.com/paragliders/products/previous-gliders
(94 previous models + 22 current = 116 total, confirmed 1:1 with DB)

---

## Design Decisions

### Schema Change: split `category` into `category` + `sub_type`

**Problem:** The current `category` CHECK constraint mixes two dimensions:

1. **Sport/modality** — what activity the wing is for: paragliding, paramotoring, speedflying
2. **Wing sub-type** — structural category within the paragliding family: solo, tandem, acro, miniwing, single-skin

This means a tandem paraglider (`Magnum 4`) and a paramotor tandem (`MagMAX 3`, not
in DB yet) would both use `category='tandem'`, losing the sport distinction.

**Solution:** Two orthogonal columns:

```sql
category    TEXT NOT NULL CHECK(category IN ('paraglider','paramotor','speedwing'))
sub_type    TEXT CHECK(sub_type IN ('solo','tandem','acro','miniwing','single_skin'))
```

| Column | Values | Semantics |
|--------|--------|-----------|
| `category` | paraglider, paramotor, speedwing | The sport / modality. Different activities with different equipment, certification standards, and communities |
| `sub_type` | solo, tandem, acro, miniwing, single_skin | Structural or use sub-category within the paragliding family. NULL for paramotor and speedwing rows |

**Naming rationale:** "discipline" was rejected as it could refer to either axis.
"sub_type" is unambiguous — it is a sub-classification of the category.

### Migration mapping

| Current `category` | → New `category` | → New `sub_type` | Count |
|--------------------|-------------------|-------------------|-------|
| `paraglider` | `paraglider` | `solo` | 93 |
| `tandem` | `paraglider` | `tandem` | 11 |
| `acro` | `paraglider` | `acro` | 5 |
| `paramotor` | `paramotor` | NULL | 5 |
| `speedwing` | `speedwing` | NULL | 2 |
| `miniwing` | `paraglider` | `miniwing` | 0 (none today) |
| `single_skin` | `paraglider` | `single_skin` | 0 (none today) |

After migration: all 109 paraglider-domain rows have `category='paraglider'` with
`sub_type` distinguishing solo (93) / tandem (11) / acro (5). Paramotor (5) and
speedwing (2) retain their categories with `sub_type=NULL`.

### `model_target_uses` — not populated in this iteration

The `model_target_uses` junction table describes **flight purpose** (school, leisure,
xc, competition, hike_and_fly, vol_biv, acro, speedflying), which is independent of
both `category` and `sub_type`.

Example: Swiftmax 2 → `category='paraglider'`, `sub_type='tandem'`, target_uses=`['xc']`
Example: Buzz Z7 → `category='paraglider'`, `sub_type='solo'`, target_uses=`['leisure','school']`

Population requires LLM extraction from manufacturer marketing text, which is a
separate task (future iteration). It is NOT manually populated.

### `sub_type` as required vs optional

`sub_type` will be **required for `category='paraglider'`** rows. Default to `'solo'`
during migration — this covers 93 of 116 rows correctly. The remaining 23 rows
(tandem/acro) are set explicitly.

For `category='paramotor'` and `category='speedwing'` rows, `sub_type` is NULL.

---

## Implementation Plan

### Phase 1 — DB Audit (read-only, diagnostic)

**Step 1.** Run `SELECT category, is_current, COUNT(*) FROM models GROUP BY 1,2`
and a full model list dump to confirm pre-conditions match this document.

No files modified.

---

### Phase 2 — Slug Diff (read-only, diagnostic)

**Step 2.** Normalise DB slugs (strip `ozone-` prefix) and compare against
`output/ozone_urls.json` slug sets.

Expected: 0 gaps in either direction (already confirmed).

No re-crawl needed. No files modified.

---

### Phase 3 — Schema Change

**Step 3.** Add `sub_type` column to `models` table in `src/db.py` SCHEMA_SQL.

Add after the `category` line:
```sql
sub_type    TEXT  CHECK(sub_type IN ('solo','tandem','acro','miniwing','single_skin')),
```

**Step 4.** Update `category` CHECK constraint to 3 values:
```sql
category    TEXT NOT NULL CHECK(category IN ('paraglider','paramotor','speedwing')),
```

**Step 5.** Add a migration function in `src/db.py` that runs on `Database.__init__()`:
- Check if `sub_type` column exists (`PRAGMA table_info(models)`)
- If not: `ALTER TABLE models ADD COLUMN sub_type TEXT`
- Run the migration mapping UPDATE statements (see table above)
- Update the CHECK constraint (SQLite does not support ALTER CONSTRAINT;
  migration will run UPDATEs on data, but the new CHECK only applies to new rows
  created after the schema is applied to a fresh DB)

**Step 6.** Update `src/models.py`:
- Simplify `WingCategory` enum to 3 values
- Add `WingSubType` enum: `solo`, `tandem`, `acro`, `miniwing`, `single_skin`
- Add `sub_type: Optional[WingSubType] = None` to `WingModel`

**Step 7.** Update `scripts/data_curator.py`:
- Add `sub_type` to REQUIRED_FIELDS for models (if category='paraglider')
- Update scoring/display to show sub_type in model detail

**Files modified:**
- `src/db.py`
- `src/models.py`
- `scripts/data_curator.py`

---

### Phase 4 — Data Fixes

**Step 8.** Run the migration mapping (Phase 3 step 5) on `ozone.db`.

**Step 9.** Fix `is_current` flag:
```sql
-- Current models: match the 22 on flyozone.com/paragliders/products/gliders
UPDATE models SET is_current = 0;
UPDATE models SET is_current = 1 WHERE slug IN (
    'ozone-moxie','ozone-alta-gt','ozone-buzz-z7','ozone-geo-7',
    'ozone-rush-6','ozone-swift-6','ozone-delta-5','ozone-alpina-4-gt',
    'ozone-alpina-5','ozone-photon','ozone-lyght','ozone-zeolite-2-gt',
    'ozone-zeolite-2','ozone-zeno-2','ozone-enzo-3','ozone-ultralite-5',
    'ozone-session','ozone-magnum-4','ozone-swiftmax-2','ozone-wisp-2',
    'ozone-roadrunner','ozone-vibe-gt'
);
```

**Step 10.** Fix Mantra M3 year_discontinued:
```sql
UPDATE models SET year_discontinued = NULL WHERE slug = 'ozone-mantra-m3';
```

**Files modified:** `output/ozone.db` (data only; schema already applied in Phase 3)

---

### Phase 5 — Verification

**Step 11.** Post-migration queries:
```sql
-- Category distribution
SELECT category, sub_type, COUNT(*) FROM models GROUP BY 1, 2;
-- Expected: paraglider/solo=93, paraglider/tandem=11, paraglider/acro=5,
--           paramotor/NULL=5, speedwing/NULL=2

-- Current models
SELECT COUNT(*) FROM models WHERE is_current = 1;
-- Expected: 22

-- Discontinued models
SELECT COUNT(*) FROM models WHERE is_current = 0;
-- Expected: 94

-- No impossible dates
SELECT name, year_released, year_discontinued FROM models
  WHERE year_discontinued IS NOT NULL AND year_discontinued < year_released;
-- Expected: 0 rows

-- All paraglider rows have sub_type
SELECT COUNT(*) FROM models
  WHERE category = 'paraglider' AND sub_type IS NULL;
-- Expected: 0
```

**Step 12.** Run `./run_tests.sh` — all tests must pass. Tests that reference the
old 7-value `WingCategory` enum will need updating.

---

## Files Created / Modified

| File | Change |
|------|--------|
| `src/db.py` | SCHEMA_SQL: new `sub_type` column, simplified `category` CHECK, migration function |
| `src/models.py` | `WingCategory` simplified to 3 values, new `WingSubType` enum, `sub_type` field |
| `scripts/data_curator.py` | Add `sub_type` to field config, update display |
| `output/ozone.db` | Data migration: category+sub_type, is_current fix, Mantra M3 fix |
| `documentation/README.md` | Add row 22 to iteration table |

---

## Done Criteria

| Gate | Metric | Target |
|------|--------|--------|
| Schema | `sub_type` column exists with CHECK constraint | |
| Schema | `category` has exactly 3 allowed values | |
| Data | `category='paraglider'` count = 109 (93+11+5) | |
| Data | `is_current=1` count = 22 | |
| Data | `is_current=0` count = 94 | |
| Data | No `year_discontinued < year_released` rows | |
| Data | All `category='paraglider'` rows have `sub_type` set | |
| Tests | All existing tests pass (update enum references) | |