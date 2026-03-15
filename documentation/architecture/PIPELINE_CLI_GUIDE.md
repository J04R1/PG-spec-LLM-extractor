# Pipeline CLI Guide

Command reference and workflows for `python -m src.pipeline`.

---

## Commands at a Glance

| Command          | Purpose                                          |
|------------------|--------------------------------------------------|
| `seed`           | Quick-import a CSV into a DB (with validation)   |
| `rebuild`        | Build/rebuild a DB from config (with validation) |
| `import-fredvol` | Import wing specs from fredvol_raw.csv           |
| `import-dhv`     | Enrich a DB with DHV certification records       |
| `validate`       | Interactive QA — review and fix flagged models   |
| `fix`            | Re-extract models flagged during validation      |
| `benchmark`      | Score a DB against reference data                |
| `run`            | Full extraction pipeline (crawl → extract → store) |
| `status`         | Show extraction progress                         |
| `reset`          | Clear cached extraction data                     |

---

## Understanding the DB Behavior

All import commands use **upserts**, not plain inserts:

- **Manufacturers & Models**: looked up by `slug`. If found, only NULL fields are
  updated with new non-NULL values. Existing data is never overwritten.
- **Size variants**: looked up by `(model_id, size_label)`. Same NULL-fill logic.
- **Certifications**: looked up by `(size_variant_id, standard)`. **Full replace** —
  all fields are overwritten.
- **Provenance**: always inserted (append-only audit trail).

This means **you can safely import into an existing DB** — new models are added,
existing models get gaps filled, and nothing is lost.

---

## Common Workflows

### 1. First-time import from a CSV

```bash
python -m src.pipeline seed --csv data/ozone_enrichment.csv --db output/ozone.db
```

- Creates `output/ozone.db` if it doesn't exist
- **Validates every model before storing** — models with critical issues are skipped
- Good for quick import when you don't need a full rebuild config

### 2. Import with validation (recommended for production)

```bash
python -m src.pipeline rebuild -c config/manufacturers/ozone.yaml
```

- Reads CSV paths from the config's `import.csv_files` section
- **Rejects models with critical issues** before storing (e.g. `ptv_min > ptv_max`,
  geometry inconsistencies, invalid certifications)
- Runs a post-import validation and writes a `.validation.json` log
- **Default behavior deletes the existing DB** and starts fresh

To resume after interruption:

```bash
python -m src.pipeline rebuild -c config/manufacturers/ozone.yaml --resume
```

### 3. Update an existing DB with an improved CSV

Use `seed` — it upserts, so it works on existing DBs:

```bash
python -m src.pipeline seed \
  --csv data/ozone_year_updated.csv \
  --db output/ozone.db \
  --method llm_year_correction
```

- Existing models: NULL fields get filled with new data
- New models: inserted as new rows
- Already-populated fields: **left untouched** (never overwritten)
- The `--method` label is recorded in provenance so you can trace what came from where

> **Tip**: if your improved CSV has corrections to fields that already have values,
> those won't overwrite. For full corrections, either use `rebuild` with a fresh DB,
> or fix individual models with `validate`/`fix`.

### 4. Review and fix data quality issues

```bash
# Run interactive validation
python -m src.pipeline validate --db output/ozone.db

# Re-extract flagged models
python -m src.pipeline fix --db output/ozone.db
```

### 5. Import historical specs from fredvol dataset

```bash
# Import all Ozone historical specs (1982–2019) from fredvol
python -m src.pipeline import-fredvol --db output/ozone.db --manufacturer ozone

# Import ALL manufacturers into a legacy DB
python -m src.pipeline import-fredvol --db output/legacy.db
```

- Source: `data/fredvol_raw.csv` (6,481 rows, ~200 manufacturers, 1,804 models)
- Provides: flat/projected geometry, weight, PTV range, year, certifications
- All records imported as `is_current=false` (historical data)
- Manufacturer names auto-normalized ("Ozone"/"ozone" → `ozone`, "U-Turn"/"uturn" → `u-turn`)
- Provenance: `fredvol/Paraglider_specs_studies`

### 6. Enrich with DHV certifications

```bash
# Add DHV certs to an existing DB (enrichment)
python -m src.pipeline import-dhv --db output/ozone.db --manufacturer ozone

# Create models for DHV entries that don't match existing models
python -m src.pipeline import-dhv --db output/legacy.db --create-missing

# Only enrich — don't create new models for unmatched entries
python -m src.pipeline import-dhv --db output/ozone.db --no-create-missing
```

- Source: `data/dhv_unmatched.csv` (3,192 rows, ~50 manufacturers)
- Provides: EN certification class, test date, report URL
- Best used **after** fredvol import (fredvol creates models, DHV adds certs)
- DHV legal names auto-normalized ("OZONE Gliders Ltd." → `ozone`)

### 7. Recommended import order for a new manufacturer

```bash
# Step 1: Historical specs from fredvol
python -m src.pipeline import-fredvol --db output/gin.db --manufacturer gin

# Step 2: DHV certification enrichment
python -m src.pipeline import-dhv --db output/gin.db --manufacturer gin

# Step 3 (optional): Validate data quality
python -m src.pipeline validate --db output/gin.db

# Step 4 (optional): Pipeline crawl for current models
python -m src.pipeline run -c config/manufacturers/gin.yaml
```

### 8. Full extraction from a manufacturer website

```bash
python -m src.pipeline run -c config/manufacturers/ozone.yaml
```

This runs the complete pipeline: crawl pages → LLM extraction → normalize → store in DB.

---

## Command Reference

### `seed`

```
python -m src.pipeline seed --csv <file> [--db output/seed.db] [--method llm_enrichment_csv] [--post-validate]
```

| Flag               | Default                | Description                        |
|--------------------|------------------------|------------------------------------|  
| `--csv`            | *(required)*           | Path to enrichment CSV             |
| `--db`             | `output/seed.db`       | Output database path               |
| `--method`         | `llm_enrichment_csv`   | Provenance label for this import   |
| `--post-validate`  | `false`                | Run DB-wide validation after import |

**Validation**: Per-model gate (enabled by default). Models with critical issues
are skipped and reported. Add `--post-validate` to also run a DB-wide sweep and
write a `.validation.json` log (same as `rebuild`'s final step).  
**DB behavior**: Creates if missing, upserts if existing.

---

### `rebuild`

```
python -m src.pipeline rebuild -c <config.yaml> [--resume] [--fresh]
```

| Flag       | Default | Description                                  |
|------------|---------|----------------------------------------------|
| `-c`       | *(required)* | Manufacturer config YAML                |
| `--resume` | false   | Continue from last completed import step     |
| `--fresh`  | false   | Explicitly delete DB first (default behavior already does this unless `--resume`) |

**Validation**: Yes — models with critical issues are skipped.  
**DB behavior**: Default = fresh DB. With `--resume` = adds to existing.

---

### `validate`

```
python -m src.pipeline validate --db <path>
```

Interactive QA session. Reviews each model, shows issues, lets you mark actions
(`re_extract`, `skip`, `manual_fix`).

---

### `fix`

```
python -m src.pipeline fix --db <path>
```

Re-extracts models that were flagged during validation. Previews changes before applying.

---

### `import-fredvol`

```
python -m src.pipeline import-fredvol --db <path> [--csv data/fredvol_raw.csv] [--manufacturer <slug>]
```

| Flag             | Default                  | Description                             |
|------------------|--------------------------|------------------------------------------|
| `--db`           | *(required)*             | Output database path                     |
| `--csv`          | `data/fredvol_raw.csv`   | Path to fredvol CSV                      |
| `--manufacturer` | *(all)*                  | Filter to one manufacturer slug          |

**Validation**: Per-model gate with relaxed profile. Year range widened to 1980–2026
(fredvol data starts 1982). Missing-field warnings suppressed (fredvol doesn't provide
cell_count, manufacturer_url, etc.). Critical checks active: PTV consistency, geometry
consistency, invalid certifications. Models with critical issues are skipped and reported.  
**DB behavior**: Creates if missing, upserts if existing.  
**Provenance**: `fredvol/Paraglider_specs_studies` with source (GliderBase/Para2000).

---

### `import-dhv`

```
python -m src.pipeline import-dhv --db <path> [--csv data/dhv_unmatched.csv] [--manufacturer <slug>]
```

| Flag                     | Default                    | Description                                  |
|--------------------------|----------------------------|----------------------------------------------|
| `--db`                   | *(required)*               | Target database                              |
| `--csv`                  | `data/dhv_unmatched.csv`   | Path to DHV CSV                              |
| `--manufacturer`         | *(all)*                    | Filter to one manufacturer slug              |
| `--create-missing`       | `true`                     | Create minimal models for unmatched entries  |
| `--no-create-missing`    |                            | Only enrich existing models                  |

**Validation**: Cert classification validated before inserting (EN must be A/B/C/D,
LTF must be 1/1-2/2/2-3/3, AFNOR must be Standard/Performance/Competition). Invalid
certifications are skipped and counted as `invalid_certs`.  
**DB behavior**: Enrichment — adds certifications to existing records. Optionally creates new models.  
**Provenance**: `dhv_geraeteportal` with DHV URL.

---

### `benchmark`

```
python -m src.pipeline benchmark --db <path>
```

Scores the DB against reference data for accuracy metrics.

---

## Choosing Between `seed` and `rebuild`

| Scenario | Use |
|----------|-----|
| Quick import, I trust the CSV | `seed` |
| Production import with quality checks | `rebuild` |
| Adding supplemental data to an existing DB | `seed` (upserts safely) |
| Quick import + validation report | `seed --post-validate` |
| Starting over with corrected CSVs | `rebuild` (deletes old DB) |
| Resuming after a crash | `rebuild --resume` |
| Historical specs from fredvol dataset | `import-fredvol` |
| Add DHV certifications to existing DB | `import-dhv` |
| New manufacturer from scratch (best coverage) | `import-fredvol` → `import-dhv` → `validate` |

---

## Config YAML: `import` Section

For `rebuild`, the config needs an `import` section listing CSVs:

```yaml
import:
  output_db: output/ozone.db
  csv_files:
    - path: data/ozone_enrichment.csv
      method: llm_enrichment_csv
      label: "Base extraction"
    - path: data/ozone_year_corrections.csv
      method: llm_year_correction
      label: "Year corrections"
```

CSVs are imported in order. Each step is tracked for resumability.

---

## Validation Checks Reference

The `rebuild` command runs validation on every model **before** storing it.
Models with **critical** issues are rejected. Models with warnings are imported
but flagged in the `.validation.json` log.

### Model-Level Checks

| Check | Severity | Triggers when |
|-------|----------|---------------|
| `missing_category` | warning | `category` is NULL |
| `missing_cell_count` | warning | `cell_count` is NULL |
| `missing_manufacturer_url` | warning | `manufacturer_url` is NULL |
| `missing_year_released` | warning | `year_released` is NULL |
| `implausible_year_released` | **critical** | `year_released` outside 1990–2026 |
| `implausible_cell_count` | warning | `cell_count` outside 15–120 |
| `discontinued_no_year` | info | `is_current=false` but `year_discontinued` is NULL |
| `no_sizes` | **critical** | Model has zero size variants |

### Size-Level Checks (per size variant)

| Check | Severity | Triggers when |
|-------|----------|---------------|
| `missing_flat_area_m2` | warning | `flat_area_m2` is NULL |
| `missing_ptv_min_kg` | warning | `ptv_min_kg` is NULL |
| `missing_ptv_max_kg` | warning | `ptv_max_kg` is NULL |
| `ptv_min_gte_max` | **critical** | `ptv_min_kg >= ptv_max_kg` |
| `flat_geometry_inconsistent` | **critical** | `flat_area` differs from `span²/AR` by >5% |
| `proj_gte_flat` | **critical** | `proj_area >= flat_area` (projected must be smaller) |
| `implausible_flat_area_m2` | warning | Value outside 10.0–50.0 m² |
| `implausible_flat_span_m` | warning | Value outside 6.0–20.0 m |
| `implausible_flat_aspect_ratio` | warning | Value outside 2.5–8.5 |
| `implausible_proj_area_m2` | warning | Value outside 8.0–42.0 m² |
| `implausible_proj_span_m` | warning | Value outside 5.0–17.0 m |
| `implausible_proj_aspect_ratio` | warning | Value outside 2.0–7.0 |
| `implausible_wing_weight_kg` | warning | Value outside 1.0–12.0 kg |
| `implausible_ptv_min_kg` | warning | Value outside 30.0–200.0 kg |
| `implausible_ptv_max_kg` | warning | Value outside 40.0–250.0 kg |
| `implausible_speed_trim_kmh` | warning | Value outside 25.0–50.0 km/h |
| `implausible_speed_max_kmh` | warning | Value outside 35.0–80.0 km/h |
| `implausible_glide_ratio_best` | warning | Value outside 5.0–15.0 |
| `implausible_min_sink_ms` | warning | Value outside 0.7–1.8 m/s |

### Certification Checks

| Check | Severity | Triggers when |
|-------|----------|---------------|
| `no_certifications` | warning | Model has zero certification records |
| `invalid_en_classification` | **critical** | EN classification not in {A, B, C, D} |
| `invalid_ltf_classification` | **critical** | LTF classification not in {A, B, C, D, 1, 1-2, 2, 2-3, 3} |
| `invalid_afnor_classification` | **critical** | AFNOR classification not in {Standard, Performance, Competition} |

### What Gets Rejected by `rebuild`

Only models with at least one **critical** issue are skipped:
- Implausible year (e.g., year 1850 or 2099)
- No size variants at all
- PTV min ≥ PTV max
- Geometry inconsistency (area ≠ span²/AR by >5%)
- Projected area ≥ flat area
- Invalid certification classification

Models with only **warnings** or **info** issues pass the gate and are imported.
