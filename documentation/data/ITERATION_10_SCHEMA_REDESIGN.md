# ITERATION 10 — SCHEMA REDESIGN

> **Status:** Planning  
> **Date:** 2026-03-15  
> **Scope:** Redesign the 5-table SQLite schema into a real-world-accurate 7-table schema  
> **Depends on:** Iterations 01 (foundation), 05 (normalization/SQLite), 09 (test suite)

---

## Motivation

After extracting real data from Ozone (111 models), Advance (20+ models), cross-referencing
fredvol (historical pre-2019), and DHV (3,192 certification records across 51+ manufacturers),
the original 5-table schema's limitations have become clear:

1. **`description` field stores marketing copy** — violates facts-only policy
2. **`target_use` is single-valued** — wings serve multiple purposes (e.g., ALPHA DLS = school + hike_and_fly)
3. **Performance fields mixed with geometry** — speed/glide/sink are manufacturer-claimed, not independently verifiable
4. **Certification table too sparse** — missing certified weight ranges, report numbers, certification status
5. **Polymorphic `data_sources` is dishonest** — pretends each record has one source; reality is multi-source + AI-assembled
6. **No temporal lifecycle** — no way to track when a model was discontinued
7. **Redundant proposed fields** — `line_config` duplicates info already in `riser_config`; `num_risers` is always 1 per side

---

## Current Schema (5 tables)

| Table | Purpose | Rows (approx) |
|-------|---------|----------------|
| `manufacturers` | Brand info (slug, country, website) | 24 |
| `models` | Wing designs (name, category, target_use, year, specs, description) | ~200 |
| `size_variants` | Per-size geometry, weight, PTV, performance | ~1,000 |
| `certifications` | EN/LTF/CCC cert records | ~1,000 |
| `data_sources` | Polymorphic per-entity provenance | ~3,000 |

---

## Proposed Schema (7 tables)

### Table 1: `manufacturers`

Minor refinements only.

```sql
CREATE TABLE manufacturers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,                         -- Display name: "Advance", "Ozone"
    slug        TEXT UNIQUE NOT NULL,                  -- URL-safe: "advance", "ozone"
    country_code TEXT,                                 -- ISO 3166-1 alpha-2: "CH", "GB"
    website     TEXT,                                  -- Manufacturer homepage
    logo_url    TEXT,                                  -- Link only (never host)
    created_at  TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at  TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE models (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    manufacturer_id   INTEGER NOT NULL REFERENCES manufacturers(id),
    name              TEXT NOT NULL,                   -- "Alpha 8", "Buzz Z7", "Enzo 3"
    slug              TEXT UNIQUE NOT NULL,            -- "ozone-buzz-z7"
    category          TEXT NOT NULL CHECK(category IN (
                        'paraglider', 'tandem', 'miniwing', 'single_skin',
                        'acro', 'speedwing', 'paramotor'
                      )),
    year_released     INTEGER,                        -- Year model was launched
    year_discontinued INTEGER,                        -- Year taken off market (NULL = active or unknown)
    is_current        INTEGER DEFAULT 1,              -- Still in production
    cell_count        INTEGER,                        -- Total cells (open + closed)
    cell_count_closed INTEGER,                        -- Closed cells (shark-nose designs, NULL if none)
    line_material     TEXT,                            -- Primary line material(s)
    riser_config      TEXT,                            -- Full line plan + riser layout
                                                      -- e.g. "3-liner (split-A, winglets)"
                                                      -- e.g. "2-liner (A/B with B-handles)"
                                                      -- e.g. "3/2-liner hybrid (ACR)"
    manufacturer_url  TEXT,                            -- Product page URL
    created_at        TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at        TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE model_target_uses (
    model_id    INTEGER NOT NULL REFERENCES models(id),
    target_use  TEXT NOT NULL CHECK(target_use IN (
                  'school', 'leisure', 'xc', 'competition',
                  'hike_and_fly', 'vol_biv', 'acro', 'speedflying'
                )),
    PRIMARY KEY (model_id, target_use)
);

CREATE TABLE size_variants (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    model_id            INTEGER NOT NULL REFERENCES models(id),
    size_label          TEXT NOT NULL,                 -- Preserved as-is: "22", "XS", "MS", "13"
    flat_area_m2        REAL,                          -- Flat area in m²
    flat_span_m         REAL,                          -- Flat span in m
    flat_aspect_ratio   REAL,                          -- Flat aspect ratio
    proj_area_m2        REAL,                          -- Projected area in m²
    proj_span_m         REAL,                          -- Projected span in m
    proj_aspect_ratio   REAL,                          -- Projected aspect ratio
    wing_weight_kg      REAL,                          -- Glider weight in kg
    ptv_min_kg          REAL,                          -- Min pilot-total-weight (manufacturer stated)
    ptv_max_kg          REAL,                          -- Max pilot-total-weight (manufacturer stated)
    line_length_m       REAL,                          -- Total line length (if available)
    created_at          TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at          TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    UNIQUE(model_id, size_label)
);

CREATE TABLE performance_data (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    size_variant_id   INTEGER NOT NULL REFERENCES size_variants(id),
    speed_trim_kmh    REAL,                            -- Trim speed (km/h)
    speed_max_kmh     REAL,                            -- Max speed accelerated (km/h)
    glide_ratio_best  REAL,                            -- Best L/D ratio
    min_sink_ms       REAL,                            -- Minimum sink rate (m/s)
    source_type       TEXT NOT NULL DEFAULT 'manufacturer_stated'
                      CHECK(source_type IN (
                        'manufacturer_stated', 'test_report', 'independent_test'
                      )),
    created_at        TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE certifications (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    size_variant_id   INTEGER NOT NULL REFERENCES size_variants(id),
    standard          TEXT NOT NULL CHECK(standard IN (
                        'EN', 'LTF', 'AFNOR', 'DGAC', 'CCC', 'other'
                      )),
    classification    TEXT,                             -- "A", "B", "C", "D", "CCC", "load test only", "not rated"
    ptv_min_kg        REAL,                            -- Certified min weight (can differ from mfr PTV)
    ptv_max_kg        REAL,                            -- Certified max weight
    test_lab          TEXT,                             -- Testing laboratory name
    report_number     TEXT,                             -- Official test report identifier
    report_url        TEXT,                             -- Link to test report document (self-documenting source)
    test_date         TEXT,                             -- ISO 8601 date
    status            TEXT DEFAULT 'active'
                      CHECK(status IN ('active', 'expired', 'revoked')),
    created_at        TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE provenance (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    model_id          INTEGER NOT NULL REFERENCES models(id),
    source_name       TEXT NOT NULL,                   -- "manufacturer_website", "dhv_portal",
                                                       -- "fredvol", "gliderbase", "community"
    source_url        TEXT,                            -- Specific URL consulted
    accessed_at       TEXT,                            -- When this source was last consulted
    extraction_method TEXT,                            -- "llm_qwen25_3b", "markdown_parser",
                                                       -- "csv_import", "manual"
    notes             TEXT,                            -- Any relevant context about this source
    created_at        TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

Example rows for Ozone Buzz Z7:

model_id	source_name	source_url	accessed_at	extraction_method
42	manufacturer_website	https://flyozone.com/.../buzz-z7	2026-03-15	llm_qwen25_3b
42	dhv_portal	https://service.dhv.de/...	2026-03-10	csv_import
Example rows for Advance Alpha 6 (historical):

model_id	source_name	source_url	accessed_at	extraction_method
101	fredvol	—	2026-03-01	csv_import
101	gliderbase	—	2019-01-01	csv_import

Data Source Compatibility Matrix
fredvol_raw.csv (historical pre-2019, ~2,000+ rows)
fredvol column	→ Target	Notes
manufacturer	manufacturers.name	Needs slug generation
name	models.name	Includes version numbers
year	models.year_released	2015–2019 range
certification (A/B/C/D)	certifications.classification	
certif_EN	certifications (standard=EN)	
certif_DHV	certifications (standard=LTF)	
certif_AFNOR	certifications (standard=AFNOR)	
certif_MISC / DGAC	certifications (standard=DGAC/other)	
flat_area, flat_span, flat_AR	size_variants.flat_*	
proj_area, proj_span, proj_AR	size_variants.proj_*	
weight	size_variants.wing_weight_kg	
ptv_mini, ptv_maxi	size_variants.ptv_min_kg, ptv_max_kg	
size	size_variants.size_label	Numeric or alpha
source	provenance.source_name	Always "gliderbase"
DHV portal (3,192 records across 51+ manufacturers)
DHV field	→ Target	Notes
Manufacturer	manufacturers.name	Slug format
Model	models.name	
Sizes	size_variants.size_label	
Class	certifications.classification	A/B/C/D
Latest Test	certifications.test_date	ISO 8601
Report URL	certifications.report_url	Self-documenting source

Decisions Log
#	Decision	Rationale
D1	Remove description from models	Facts-only compliance — never store marketing copy
D2	Remove target_use from models → junction table	Wings serve multiple purposes
D3	Separate performance_data table	Manufacturer-claimed, not verifiable; secondary priority
D4	Remove line_config from models	Redundant with riser_config
D5	Remove num_risers from models	Always 1 per side — meaningless field
D6	Replace data_sources with provenance	Multi-source + AI-assembled reality; per-model not per-field
D7	Add certified weight range to certifications	Certified PTV can differ from manufacturer stated PTV
D8	Add report_number and status to certifications	Track cert lifecycle and official identifiers
D9	No model lineage tracking	Keep models independent (user preference)
D10	Motor variants = separate models	Category "paramotor", confirmed as distinct wing products
D11	Size labels preserved as-is	No normalization — "22", "XS", "MS" kept as manufacturer states
D12	Rename country → country_code	Explicit ISO 3166-1 alpha-2 standard
D13	Rename year → year_released	Unambiguous semantics
D14	Add year_discontinued	Temporal lifecycle tracking
D15	Add cell_count_closed	Shark-nose designs increasingly common
D16	Add line_length_m to size_variants	Some manufacturers publish this
D17	No raw external imports without validation	Build data validator first; fredvol/DHV imported only after quality checks pass
D18	Ozone + Advance enrichment CSVs as seed data	Already LLM-extracted and validated — first population of new schema

-- 

## Schema Diagram (text)

manufacturers (1) ──── (N) models (1) ──── (N) model_target_uses
                              │
                              │ (1)
                              │
                              ├──── (N) size_variants (1) ──── (N) certifications
                              │                    │
                              │                    └──── (N) performance_data
                              │
                              └──── (N) provenance


## Flow with gatekeeper for all future data
Source (fredvol, DHV, new crawl) → Validator → DB
                                      ↓
                               Gap detected → Spec-extractor pipeline → fills gap → Validator → DB


--

## Implementation Roadmap

### Phase 1: Schema & Models (blocking)
1. Update Pydantic models in `src/models.py`
2. Update SQLite DDL in `src/db.py`

### Phase 2: Pipeline (depends on Phase 1)
3. Update `src/extractor.py` — ExtractionResult/SizeSpec
4. Update `src/normalizer.py` — field mappings
5. Update `src/pipeline.py` — new table wiring

### Phase 3: Tests (depends on Phase 2)
6. Update all tests in `tests/`

### Phase 4: Seed Import — Ozone + Advance (depends on Phase 3)
7. Import `ozone_enrichment_all_by_LLM.csv` and `advance_enrichment_all_by_LLM.csv` into new schema
   - Already LLM-extracted and validated against manufacturer websites
   - `description` column ignored during import
   - Acts as first real data population and schema smoke test
   - Performance fields (speed, glide, sink) → `performance_data` table where present

### Phase 5: Data Validator (depends on Phase 4)
8. Build a data quality validator (`src/validator.py`) that checks DB records:
   - **Completeness scoring** — per-model/per-size: which fields are populated vs missing
   - **Cross-source consistency** — e.g., certification classification matches between manufacturer and DHV
   - **Gap detection** — which models/sizes have missing geometry, weight, or certifications
   - **Report generation** — structured output of data quality issues
9. Validator triggers spec-extractor pipeline to fill gaps:
   - Model has geometry but no certification → crawl DHV portal
   - Model has cert but no geometry → crawl manufacturer website
   - Model exists in fredvol but not in DB → queue for extraction
   - Priority queue based on gap severity and manufacturer tier

### Phase 6: External Source Import (future — after validator is working)
10. fredvol_raw.csv import — historical pre-2019, validated before insert
11. DHV data import — certification records, validated before insert
12. Each import run through validator before committing to DB

---

## Open Questions

_None at this time. Schema design approved for implementation._

---

## Outcome

_To be updated after implementation._