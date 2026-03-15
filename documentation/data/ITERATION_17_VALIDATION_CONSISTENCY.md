# Iteration 17 — Validation Consistency Across Import Commands

**Status**: In Progress  
**Folder**: `data/`  
**Depends on**: Iteration 14 (Validated Import Pipeline), Iteration 16 (fredvol + DHV Import)

---

## Problem Statement

After Iteration 16 added `import-fredvol` and `import-dhv`, three of the five import
commands lack validation:

| Command         | Per-model validation gate | Post-import DB sweep | Status |
|-----------------|--------------------------|----------------------|--------|
| `rebuild`       | ✓ (critical issues block) | ✓ (writes `.validation.json`) | Complete |
| `seed`          | ✓ (validate=True default) | ✗ | **Undocumented** |
| `import-fredvol`| ✗ | ✗ | **Missing** |
| `import-dhv`    | ✗ | ✗ | **Missing** |
| `validate`      | — (interactive QA tool) | ✓ (writes `.validation.json`) | Complete |

### Discovery: `seed` Already Validates

During discussion, code inspection revealed that `import_enrichment_csv()` in
`src/seed_import.py` has `validate: bool = True` as a default parameter. The `seed`
CLI command calls it without setting `validate=False`, which means **seed already
validates every model before storing** — rejecting models with critical issues, exactly
like `rebuild` does.

The Pipeline CLI Guide incorrectly documented seed as "No validation. All rows imported
as-is." This is wrong and must be corrected.

### What `seed` Does NOT Do (That `rebuild` Does)

The difference between `seed` and `rebuild` is not per-model validation (both do it),
but the **post-import database-wide sweep**:

- `rebuild`: After importing, runs `validate_database()` which scans all models in the
  DB, produces a `ValidationLog`, and writes `.validation.json` to disk.
- `seed`: Stops after import. No DB-wide sweep, no `.validation.json` output.

### Why This Matters

- `import-fredvol` ingests 6,481 rows of historical data (1982–2019). Without validation,
  bad data (impossible PTV, inconsistent geometry) goes straight into the DB.
- `import-dhv` adds certifications. Invalid cert classifications (e.g., "E" where only
  A/B/C/D are valid for EN) should be caught before storage.
- Users running `seed` may want a `.validation.json` report without having to run
  `validate --db` as a separate step.

---

## Solution Design

Three changes, layered to maintain backward compatibility:

### 1. Extend `validate_model_data()` for Flexible Validation Profiles

The current `validate_model_data()` uses hardcoded `PLAUSIBILITY` ranges. fredvol data
goes back to 1982, but the year check rejects anything before 1990. Rather than creating
importer-specific validation functions, extend the existing validator with two optional
parameters:

```python
def validate_model_data(
    model, sizes, certs, manufacturer_slug,
    model_id=0, cert_size_labels=None,
    # NEW parameters:
    plausibility_overrides: dict | None = None,   # e.g. {"year_released": (1980, 2026)}
    skip_missing_warnings: bool = False,           # suppress missing_* warnings
) -> ModelValidation:
```

**`plausibility_overrides`**: Dict of field → (min, max) that overrides the default
`PLAUSIBILITY` dict for specific checks. fredvol uses `{"year_released": (1980, 2026)}`
to accept its older data range.

**`skip_missing_warnings`**: When True, suppresses all `missing_*` warnings. fredvol
and DHV don't provide many fields (no cell_count, no manufacturer_url, etc.), so
flagging these as missing is noise rather than signal.

All **critical** checks remain active regardless of these parameters:
- `ptv_min_gte_max`
- `flat_geometry_inconsistent`
- `proj_gte_flat`
- `no_sizes`
- `implausible_year_released` (with overridden range)
- `invalid_*_classification`

### 2. Add Validation to `import-fredvol`

Add a `validate: bool = True` parameter to `import_fredvol_csv()`:

```python
def import_fredvol_csv(
    csv_path, db, *,
    manufacturer_filter=None,
    tier_filter=None, tier_config=None,
    validate: bool = True,    # NEW
) -> dict:
```

When `validate=True`:
- Each model is validated before storing via `validate_model_data()` with:
  - `plausibility_overrides={"year_released": (1980, 2026)}` — fredvol data starts 1982
  - `skip_missing_warnings=True` — fredvol doesn't have cell_count, manufacturer_url, etc.
- Models with critical issues are skipped and counted in the return dict
- The CLI outputs skipped models and their critical issues

New return dict keys: `"skipped"` (count), `"skipped_models"` (list of `ModelValidation`)

### 3. Add Validation to `import-dhv`

Add a `validate: bool = True` parameter to `import_dhv_csv()`:

```python
def import_dhv_csv(
    csv_path, db, *,
    manufacturer_filter=None,
    create_missing: bool = True,
    validate: bool = True,    # NEW
) -> dict:
```

When `validate=True` and `create_missing=True`:
- Each newly created model is validated before storing via `validate_model_data()` with:
  - `skip_missing_warnings=True` — DHV only provides cert data, not full specs
- For enrichment-only (adding certs to existing models), validate cert classification
  against `_VALID_CLASSES` before inserting
- Invalid cert records are skipped and counted

New return dict key: `"invalid_certs"` (count of skipped invalid certifications)

### 4. Add `--post-validate` to `seed`

Add a `--post-validate / --no-post-validate` flag to the `seed` CLI command:

```python
@app.command()
def seed(
    csv_file: str = ...,
    db_path: str = ...,
    method: str = ...,
    post_validate: bool = typer.Option(
        False, "--post-validate/--no-post-validate",
        help="Run DB-wide validation after import"
    ),
) -> None:
```

When `--post-validate`:
- After import, runs `validate_database(db_path)` — same function `rebuild` calls
- Writes `.validation.json` to disk
- Prints summary (clean/warning/critical counts)

This bridges the gap between `seed` (quick import) and `rebuild` (full pipeline) without
requiring the user to run `validate --db` as a separate step.

### 5. Fix CLI Guide Accuracy

Update the Pipeline CLI Guide to:
- Correct seed's description from "No validation" to "Per-model validation gate (enabled
  by default). Models with critical issues are skipped."
- Add `--post-validate` flag to seed's command reference
- Add validation descriptions to `import-fredvol` and `import-dhv` reference sections
- Update the decision table with accurate validation information

---

## Implementation Details

### Files Modified

| File | Changes |
|------|---------|
| `src/validator.py` | Add `plausibility_overrides` and `skip_missing_warnings` params to `validate_model_data()` |
| `src/fredvol_import.py` | Add `validate` param, call `validate_model_data()` with fredvol profile, update return dict |
| `src/dhv_import.py` | Add `validate` param, validate certs before insert, validate created models |
| `src/pipeline.py` | Add `--post-validate` to `seed`, show skipped models in `import-fredvol`/`import-dhv` output |
| `documentation/architecture/PIPELINE_CLI_GUIDE.md` | Fix seed description, add validation info to all commands |
| `tests/test_fredvol_import.py` | Add tests for validation gate (skipped models, relaxed year) |
| `tests/test_dhv_import.py` | Add tests for cert validation (invalid class skipped) |
| `tests/test_validator.py` | Add tests for new parameters (overrides, skip_missing) |

### Validator Parameter Behavior

```
validate_model_data(model, sizes, certs, mfr_slug)
  → Default: all checks, PLAUSIBILITY ranges, all missing_* warnings

validate_model_data(..., plausibility_overrides={"year_released": (1980, 2026)})
  → Override specific range, all other checks normal

validate_model_data(..., skip_missing_warnings=True)
  → Suppress missing_category, missing_cell_count, missing_*
  → Keep all critical, plausibility, and consistency checks

validate_model_data(..., plausibility_overrides={...}, skip_missing_warnings=True)
  → fredvol profile: relaxed year + no missing warnings
```

### fredvol Validation Profile

| Check | Behavior | Rationale |
|-------|----------|-----------|
| `implausible_year_released` | Range widened to 1980–2026 | fredvol has data from 1982 |
| `missing_*` warnings | Suppressed | fredvol doesn't provide cell_count, manufacturer_url, etc. |
| `ptv_min_gte_max` | **Active (critical)** | Data integrity — impossible PTV ranges must be caught |
| `flat_geometry_inconsistent` | **Active (critical)** | Data integrity — area ≠ span²/AR indicates bad data |
| `proj_gte_flat` | **Active (critical)** | Data integrity — projected must be < flat |
| `no_sizes` | **Active (critical)** | Structurally invalid — models without sizes are useless |
| `invalid_*_classification` | **Active (critical)** | EN/LTF/AFNOR classes must be valid |
| Implausible plausibility (non-year) | **Active (warning)** | Still useful to flag extreme values |

### DHV Validation Profile

| Check | Behavior | Rationale |
|-------|----------|-----------|
| Cert classification | Validated pre-insert | Only A/B/C/D for EN, 1/1-2/2/2-3/3 for LTF |
| `missing_*` warnings | Suppressed for created models | DHV provides only cert data |
| `no_sizes` | Skipped for created models | DHV models have exactly one size per cert record |
| Other critical checks | Active for created models | PTV, geometry (usually NULL — won't trigger) |

---

## Verification Criteria

1. **Existing tests pass**: All 274 tests from Iteration 16 still pass
2. **fredvol validation gate**: Models with critical issues (ptv_min ≥ ptv_max,
   geometry inconsistency) are skipped and reported
3. **fredvol year acceptance**: Models with year_released=1982 pass validation
   (would fail with default range of 1990–2026)
4. **DHV cert validation**: Invalid cert classifications (e.g., "E" for EN) are
   skipped and counted
5. **seed --post-validate**: Produces `.validation.json` identical to what
   `validate --db` would produce
6. **CLI guide accuracy**: All command descriptions match actual behavior
7. **Backward compatibility**: Default behavior unchanged — validate_model_data()
   without new params behaves identically to before

---

## Risk Assessment

| Risk | Mitigation |
|------|------------|
| Relaxed year range lets truly bad years through | 1980 lower bound still catches impossible values (e.g. year 0, 1850) |
| fredvol models rejected by geometry check | Expected — fredvol has some questionable data. Rejection is correct behavior. |
| DHV cert validation too strict | Only validates against well-defined EN/LTF/AFNOR classes. Unknown standards pass through. |
| Breaking change to validate_model_data() API | New params are optional with defaults matching current behavior. Zero breaking changes. |
