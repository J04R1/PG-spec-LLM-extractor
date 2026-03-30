# Iteration XX — BGD MVP Database

**Status:** Not Started  
**Created:** 2026-03-30  
**Domain:** data  
**Prerequisite:** Iteration 20 complete (Ozone MVP DB — proven staged-JSON pipeline),  
and current iteration (XX-1) complete.

---

## Goal

Produce a validated, benchmarked `bgd.db` covering all BGD (Bruce Goldsmith Design)
paraglider product lines with zero critical validation issues — starting with the
~14 current models as a proven ground-truth baseline, then extending to the full
historical catalog (~20 additional models).

Scope: **BGD only.** Mirrors the Iteration 20 methodology exactly: live crawl of
manufacturer website → staged JSON → audit → patch → import → benchmark.

No enrichment CSVs. Every value traceable to `flybgd.com`.

---

## Site Reconnaissance (Done — 2026-03-30)

### Source

| Property | Value |
|----------|-------|
| Website | https://www.flybgd.com |
| Robots.txt | `Allow: /` — no crawling restrictions |
| Page rendering | **Static HTML** — no JavaScript execution required |
| Catalog listing | `https://www.flybgd.com/en/paragliders/paragliders-beginner-intermediate-expert-2-0-0.html` |
| URL pattern | `https://www.flybgd.com/en/paragliders/{model}--paraglider-2021-{id}-0.html` |

### Product Inventory

**Current models (~14)** — active in the catalog at time of recon:

| Model | EN Class | Category | URL ID |
|-------|----------|----------|--------|
| Adam Spot | — | accuracy | 2242 |
| ANDA | ? | paraglider (lightweight) | 1888 |
| BASE 3 | EN/LTF-B | paraglider | 2272 |
| BREEZE | EN/LTF-B | paraglider (lightweight) | 2352 |
| CURE 3 | EN C | paraglider | 2348 |
| DIVA 2 | EN C | paraglider (competition) | 2188 |
| DUAL 3 | — | **tandem** | 2515 |
| ECHO 2 | EN/LTF-B | paraglider (lightweight) | 1839 |
| EPIC 2 | EN/LTF-B | paraglider | 1782 |
| EPIC Freestyle | — | **acro** | 2001 |
| KISS | — | **acro** | 1473 |
| LYNX 2 | EN/LTF-B | paraglider (lightweight) | 1953 |
| MAGIC 2 | — | paraglider (hike-and-fly/tandem-adventure) | 2133 |
| ADAM 2 | ? | paraglider | 2033 |

> Model count TBC during URL discovery — the catalog page uses JS filtering,
> but static HTML contains all hrefs. Exact is_current classification confirmed
> by cross-referencing the catalog listing vs URL IDs.

**Historical models (~22)** — on the site but not in the active catalog:

Adam, Base, Base 2, Base 2 Lite, Base Lite, Cure, Cure 2, Diva, Dual,
Dual 2, Dual Lite, Echo, Epic, Lynx, Magic, Punk, Riot, Seed, Tala, Tala Lite,
Wasp

> Full list confirmed during URL discovery step.

### BGD Spec Table — Field Mapping

Each product page has a multi-size spec table (sizes as columns) and a Materials section.
Fields differ from Ozone in several places:

| BGD label (on page) | Schema field | Notes |
|---------------------|-------------|-------|
| `Flat area (m²)` | `flat_area_m2` | Same as Ozone |
| `Projected area (m²)` | `proj_area_m2` | Same as Ozone |
| `Flat span (m)` | `flat_span_m` | Same as Ozone |
| `Projected span (m)` | `proj_span_m` | Same as Ozone |
| `Flat aspect ratio` | `flat_aspect_ratio` | Same as Ozone |
| `Projected aspect ratio` | `proj_aspect_ratio` | Not present on all pages |
| `Glider weight (kg)` | `wing_weight_kg` | Same as Ozone |
| `Certified weight range (kg)` | `ptv_min_kg` / `ptv_max_kg` | Same as Ozone |
| **`Cells`** | `cell_count` | **Different** — Ozone uses "Number of Cells" |
| **`Certification (EN)`** | `certification` | **Different label variant** |
| **`Certification (EN/LTF)`** | `certification` | **Different label variant** |
| **`Trim speed (km/h)`** | `speed_trim_kmh` | **BGD bonus** — not on Ozone pages |
| **`Top speed (km/h)`** | `speed_max_kmh` | **BGD bonus** — not on Ozone pages |
| **`Min sink (m/s)`** | `min_sink_ms` | **BGD bonus** — not on Ozone pages |
| **`Best glide`** | `glide_ratio_best` | **BGD bonus** — not on Ozone pages |
| **`Number of main lines (A/B/C)`** | `riser_config` | New — riser architecture string |
| `Ideal weight range (kg)` | *(ignore)* | BGD-specific; use certified only |
| `Linear scaling factor` | *(ignore)* | Not in schema |
| `Root chord (m)` | *(ignore)* | Not in schema |

Performance data (speed/glide/sink) is only present on some models — e.g., EPIC 2
shows trim speed 39 km/h, top speed 53 km/h, best glide 9.5. This is captured in the
`performance_data` table (already in schema v2).

---

## Infrastructure

This iteration uses **the existing pipeline unchanged** — no new modules, only additions:

| Component | Location | How used |
|-----------|----------|---------|
| `Crawler` | `src/crawler.py` (Iteration 2) | All crawl scripts instantiate `Crawler` and call `render_page(url)` — identical to `scripts/crawl_previous_to_json.py` |
| `MarkdownParser` | `src/markdown_parser.py` (extended each iteration) | BGD-specific entries **appended** to `_MD_ROW_MAP` — same pattern as Advance labels added in Iteration 8 |
| `db.py` | `src/db.py` | Upsert operations, schema v2, unchanged |
| `normalizer.py` | `src/normalizer.py` | Cert/slug normalisation, unchanged |
| `benchmark.py` | `src/benchmark.py` | 3-axis quality report after import |
| `audit_staged_json.py` | `scripts/` | Reused as-is for staged JSON review |
| `show_spec_table.py` | `scripts/` | Reused as-is for spot-checking output |

---

## Phase 0 — Reconnaissance & Config

### 0.1 — `config/manufacturers/bgd.yaml`

Create a new manufacturer config file following the `ozone.yaml` structure:

```yaml
# BGD Paraglider Specs — Extraction Config

manufacturer:
  name: BGD
  slug: bgd
  website: https://www.flybgd.com

import:
  output_db: output/bgd.db

sources:
  current_gliders:
    listing_url: https://www.flybgd.com/en/paragliders/paragliders-beginner-intermediate-expert-2-0-0.html
    url_pattern: "--paraglider-2021-"
    is_current: true
    url_excludes:
      - "legal-notice"
      - "privacy-policy"
      - "terms-of-use"
      - "contact"
      - "news"
      - "videos"
      - "bgd-team"
      - "dealers"
      - "eshop"
      - "testivals"
      - "inspection"
      - "specifications-gliders"
      - "approved-service"
      - "warranty"
      - "custom-logos"
      - "harnesses"
      - "reserves"
      - "paramotor"

  previous_gliders:
    listing_url: https://www.flybgd.com/en/paragliders/paragliders-beginner-intermediate-expert-2-0-0.html
    url_pattern: "--paraglider-2021-"
    is_current: false
    url_excludes:
      # same as current_gliders

extraction:
  strategy: markdown

  llm:
    provider: "gemini/gemini-2.0-flash"
    api_key_env: "GEMINI_API_KEY"

    prompt: |
      Extract ONLY the factual technical specifications from this BGD paraglider product page.

      RULES:
      - Read the technical specs table carefully. Each column is a size (XS, S, M, ML, L, XL, etc.)
      - "Certified weight range" gives ptv_min_kg and ptv_max_kg (split "73-84" into min=73, max=84)
      - IGNORE "Ideal weight range" — use certified weight range only
      - "Glider weight" gives wing_weight_kg
      - "Certification (EN)" or "Certification (EN/LTF)" gives the class letter (A, B, C, D)
      - "Cells" is the cell_count (single value, same for all sizes)
      - "Number of main lines (A/B/C)" gives riser_config as a string (e.g. "3/2/3")
      - "Trim speed", "Top speed", "Min sink", "Best glide" are performance data — capture if present
      - IGNORE: Linear scaling factor, Root chord, Ideal weight range
      - DO NOT extract marketing descriptions, pilot reviews, or any prose text
      - DO NOT extract image URLs
      - All numeric values must be plain numbers (no units, no "kg", no "m²")
      - Return one size entry per column in the specs table

    schema:
      type: object
      properties:
        model_name:
          type: string
          description: "Wing model name without manufacturer (e.g. 'Epic 2', 'Cure 3', 'Base 3')"
        category:
          type: string
          enum: ["paraglider", "tandem", "miniwing", "single_skin", "acro", "speedwing", "paramotor"]
        target_use:
          type: string
          enum: ["school", "leisure", "xc", "competition", "hike_and_fly", "vol_biv", "acro", "tandem"]
        cell_count:
          type: integer
        riser_config:
          type: string
          description: "Main line architecture (e.g. '3/2/3', '3/3')"
        product_url:
          type: string
        sizes:
          type: array
          items:
            type: object
            properties:
              size_label:
                type: string
              flat_area_m2:
                type: number
              flat_span_m:
                type: number
              flat_aspect_ratio:
                type: number
              proj_area_m2:
                type: number
              proj_span_m:
                type: number
              proj_aspect_ratio:
                type: number
              wing_weight_kg:
                type: number
              ptv_min_kg:
                type: number
              ptv_max_kg:
                type: number
              certification:
                type: string
              speed_trim_kmh:
                type: number
              speed_max_kmh:
                type: number
              min_sink_ms:
                type: number
              glide_ratio_best:
                type: number
            required: ["size_label", "ptv_min_kg", "ptv_max_kg", "certification"]
      required: ["model_name", "sizes"]
```

### 0.2 — URL Discovery (`scripts/discover_bgd_urls.py`)

Scrape the catalog listing page static HTML (no Crawl4AI needed — `httpx` suffices):

```
GET https://www.flybgd.com/en/paragliders/paragliders-beginner-intermediate-expert-2-0-0.html
→ extract all hrefs matching "--paraglider-2021-" pattern
→ apply url_excludes list
→ deduplicate
→ classify is_current using model ID heuristic (ID ≥ 1700) + manual override list
→ write output/bgd_urls.json
```

Output format (matches `ozone_urls.json` structure):
```json
{
  "current": ["https://www.flybgd.com/.../epic-2--paraglider-2021-1782-0.html", ...],
  "previous": ["https://www.flybgd.com/.../epic--paraglider-2021-920-0.html", ...]
}
```

> Note: BGD has no separate "previous gliders" page (unlike Ozone). All models —
> current and historical — are accessible from the single catalog listing URL.
> The is_current classification is determined by the model's URL ID heuristic
> (IDs below ~1700 predate the current-generation lineup) plus a manual
> override list for edge cases confirmed during recon.

### 0.3 — Markdown Parser: BGD Label Mappings

**Append** the following entries to `_MD_ROW_MAP` in `src/markdown_parser.py`.
This is identical to the approach used for Advance in Iteration 8
(`"flat surface"`, `"certified takeoff weight"`, etc.):

```python
# BGD-specific label mappings
"cells":                          ("cell_count",       False, False),
"certification (en)":             ("certification",    True,  False),
"certification (en/ltf)":         ("certification",    True,  False),
"trim speed (km/h)":              ("speed_trim_kmh",   False, False),
"top speed (km/h)":               ("speed_max_kmh",    False, False),
"min sink (m/s)":                 ("min_sink_ms",      False, False),
"best glide":                     ("glide_ratio_best", False, False),
"number of main lines (a/b/c)":   ("riser_config",     False, False),
```

Fields to **ignore** (add to skip/discard list or simply leave unmapped):
- `"ideal weight range (kg)"` — BGD-specific pilot advisory range, not the certified range
- `"linear scaling factor"` — geometric normalisation constant, not in schema
- `"root chord (m)"` — structural dimension, not in schema

### 0.4 — Parser Verification

Before Phase 1, manually verify the parser handles a sample of pages correctly:

```bash
# Quick smoke test against three representative pages
python3 - <<'EOF'
from src.crawler import Crawler
from src.markdown_parser import parse_specs_from_markdown

crawler = Crawler()
for url in [
    "https://www.flybgd.com/en/paragliders/cure-3--paraglider-2021-2348-0.html",
    "https://www.flybgd.com/en/paragliders/epic-2--paraglider-2021-1782-0.html",
    "https://www.flybgd.com/en/paragliders/base-3--paraglider-2021-2272-0.html",
]:
    md = crawler.render_page(url)
    result = parse_specs_from_markdown(md, url, manufacturer_name="BGD")
    print(f"\n{result.model_name}: {len(result.sizes)} sizes, cell_count={result.cell_count}")
    for s in result.sizes:
        print(f"  {s.size_label}: {s.flat_area_m2}m² / {s.ptv_min_kg}-{s.ptv_max_kg}kg / {s.certification}")
EOF
```

Expected: All three models parse cleanly with cells, certified weight range,
and certification populated. EPIC 2 should also yield performance data
(trim_speed=39, top_speed=53, best_glide=9.5).

---

## Phase 1 — Current Models (~14 models)

### Script: `scripts/crawl_bgd_current.py`

Mirrors `scripts/crawl_previous_to_json.py` for BGD current models:

```
1. Load config from config/manufacturers/bgd.yaml
2. Load output/bgd_urls.json → filter current URLs
3. Instantiate Crawler (md_cache_dir="output/md_cache")
4. For each URL:
   a. crawler.render_page(url)  ← uses on-disk cache; --force to bypass
   b. parse_specs_from_markdown(md, url, manufacturer_name="BGD")
   c. Append record to staged list
5. Write output/bgd_current_staged.json
6. Print crawl summary (success / parse-failed / skipped)
```

Supports `--force` flag to bypass markdown cache (same as Ozone scripts).

### Audit

```bash
python3 scripts/audit_staged_json.py \
    --file output/bgd_current_staged.json \
    --manufacturer bgd
```

Review for:
- Models with 0 sizes → parse failure (page layout differs)
- Models with no `cell_count` → missing "Cells" label mapping
- Models with no `certification` → label variant not yet mapped
- Incorrect `category` auto-detection (e.g., DUAL 3 must be `tandem`)

### Known Category Overrides (pre-planned)

Based on recon, these categories cannot be reliably inferred from page content
and must be set explicitly in `scripts/patch_bgd_phase1.py`:

| Model | Correct category | Reason |
|-------|-----------------|--------|
| DUAL 3 | `tandem` | Tandem wing |
| EPIC Freestyle | `acro` | Freestyle/acro wing |
| KISS | `acro` | Freestyle/acro wing |
| MAGIC 2 | `paraglider` | Hike-and-fly adventure wing (not truly tandem despite appearing in tandem section) |

### Year Backfill

`year_released` is never published on BGD spec pages (same situation as Ozone Phase 1).
`scripts/patch_bgd_phase1.py` must backfill from manual lookup or enrichment source.

Estimated release years for current models (from public records / site dating):

| Model | Approx. year |
|-------|-------------|
| EPIC 2 | 2022 |
| ECHO 2 | 2022 |
| LYNX 2 | 2023 |
| DIVA 2 | 2023 |
| MAGIC 2 | 2023 |
| EPIC Freestyle | 2022 |
| ADAM 2 | 2023 |
| ADAM SPOT | 2023 |
| ANDA | 2022 |
| BASE 3 | 2024 |
| BREEZE | 2024 |
| CURE 3 | 2025 |
| DUAL 3 | 2025 |
| KISS | 2021 |

> These are estimates. Verify against BGD news pages or DHV records before
> committing to the DB. A dedicated year-verification pass can be done
> post-import using the data curator TUI (Iteration 21).

### Import

```bash
python3 scripts/import_bgd_to_db.py \
    --staged output/bgd_current_staged.json \
    --db output/bgd.db \
    --dry-run  # review first

python3 scripts/import_bgd_to_db.py \
    --staged output/bgd_current_staged.json \
    --db output/bgd.db
```

### Phase 1 Benchmark Target

```
models (~14 records):
  category:         14/14 (100%) ✓
  cell_count:       14/14 (100%) ✓
  year_released:    14/14 (100%) ✓  (after patch)
  manufacturer_url: 14/14 (100%) ✓

size_variants (expected ~60-75 records):
  flat_area_m2:      ~100% ✓
  proj_area_m2:      ~100% ✓  (present on all current pages)
  wing_weight_kg:    ~100% ✓
  ptv_min/max_kg:    ~100% ✓  (except acro/accuracy wings)
  flat_aspect_ratio: ~100% ✓

performance_data (expected ~20-30 records from models that publish speed):
  speed_trim_kmh, speed_max_kmh, etc. — partial coverage expected

QUALITY:  100%  ← target
ACCURACY: 100%  ← target
```

---

## Phase 2 — Historical Models (~22 models)

### Script: `scripts/crawl_bgd_previous.py`

Same pattern as Phase 1 but filtering `previous` URLs from `bgd_urls.json`:

```
1. Load output/bgd_urls.json → filter previous URLs
2. Crawl → parse → stage
3. Write output/bgd_previous_staged.json
```

### Expected Challenges

Based on Ozone Phase 2 experience, old pages may exhibit:

| Issue | Likely BGD models | Mitigation |
|-------|------------------|-----------|
| Older label variants | Adam, Punk, Riot, Seed | May need additional `_MD_ROW_MAP` entries |
| Missing projected geometry | Pre-2018 models | Expected NULL — document as source gap |
| Missing `wing_weight_kg` | Very old pages | Expected NULL |
| No certification published | Old experimental/acro models | Expected NULL — document |
| Tandem category mis-detected | Dual, Dual 2, Dual Lite | Category override in patch script |

### Import

```bash
python3 scripts/import_bgd_to_db.py \
    --staged output/bgd_previous_staged.json \
    --db output/bgd.db  # upsert — won't overwrite Phase 1 current models
```

### Phase 2 Benchmark Target

```
All models combined (~36 records):
  category:         100% ✓
  year_released:    100% ✓  (after patch)

size_variants (expected ~130-160 records):
  flat_area_m2:     ~95%+ ✓
  wing_weight_kg:   ~85%+ ✓  (old pages may lack weight)
  certification:    ~90%+ ✓

QUALITY:  100%  ← target (every populated value within plausibility range)
```

---

## Scripts to Create

| Script | Purpose | Mirrors |
|--------|---------|---------|
| `scripts/discover_bgd_urls.py` | URL discovery → `output/bgd_urls.json` | *(new — BGD has no separate previous-gliders page)* |
| `scripts/crawl_bgd_current.py` | Crawl current models → staged JSON | `scripts/crawl_previous_to_json.py` |
| `scripts/crawl_bgd_previous.py` | Crawl historical models → staged JSON | `scripts/crawl_previous_to_json.py` |
| `scripts/patch_bgd_phase1.py` | Category overrides, year backfill, any post-crawl fixes | `scripts/patch_ozone_phase1.py` |
| `scripts/import_bgd_to_db.py` | Import staged JSON → `output/bgd.db` with `--dry-run` | `scripts/import_staged_to_db.py` |

**Reused without modification:**
- `scripts/audit_staged_json.py`
- `scripts/show_spec_table.py`
- `src/crawler.py`
- `src/db.py`
- `src/normalizer.py`
- `src/benchmark.py`
- `src/extractor.py`

**Modified (appended only):**
- `src/markdown_parser.py` — 8 new entries in `_MD_ROW_MAP`

---

## Output Files

| File | Contents |
|------|---------|
| `output/bgd.db` | BGD database — all models, Phase 1 + Phase 2 |
| `output/bgd_urls.json` | URL cache — all product URLs with `is_current` flag |
| `output/bgd_current_staged.json` | Phase 1 staged JSON (current models) |
| `output/bgd_previous_staged.json` | Phase 2 staged JSON (historical models) |
| `config/manufacturers/bgd.yaml` | BGD manufacturer config |

---

## Done Criteria

| Gate | Metric | Target |
|------|--------|--------|
| Phase 0 | Parser smoke test: Cure 3, Epic 2, Base 3 parse cleanly | ✓ |
| Phase 1 | Critical validation issues on current models | 0 |
| Phase 1 | All current models have `cell_count` | 14/14 |
| Phase 1 | All current models have `year_released` | 14/14 |
| Phase 1 | Quality score | 100% |
| Phase 1 | Accuracy score | 100% |
| Phase 2 | Critical validation issues | 0 |
| Phase 2 | Quality score | 100% |
| All phases | All existing automated tests pass | 316/316 |
| Docs | `ITERATION_XX_BGD_MVP_DB.md` renamed with final number + README updated | ✓ |

---

## Known Gaps (Pre-declared)

These gaps are expected and do not constitute failures:

| Field | Expected coverage | Reason |
|-------|------------------|--------|
| `year_discontinued` | 0% for historical models | Not published on manufacturer pages (same as Ozone) |
| `report_url` / `test_date` / `test_lab` | 0% | DHV/EN certification portal data — deferred |
| `performance_data` | ~50% of current models | Only published by BGD for some wings (unlike Ozone, which publishes none) |
| `riser_config` | ~80% | Absent on some older pages |
| Acro wings (KISS, EPIC Freestyle) | No `ptv_min/max_kg` | Standard acro: load-test certified, not weight-range certified |
| Adam Spot | No `certification` | Accuracy kite — no EN serial class |

---

## Future (Post-Iteration XX)

- **DHV enrichment** (Iteration 16/17 scope): Add certification `report_url`, `test_date`,
  `test_lab` from the DHV portal — same as planned for Ozone.
- **`year_discontinued`**: Not set for historical models — fill from DHV or manual curation.
- **Performance data gap**: BGD publishes performance specs on approximately half its models.
  Once DHV test reports are integrated, performance fields can be completed for remaining models.
- **Multi-brand expansion**: After BGD + Ozone, the same pipeline applies to Nova, Skywalk,
  Niviuk, and other T1/T2 brands — no structural changes needed.
