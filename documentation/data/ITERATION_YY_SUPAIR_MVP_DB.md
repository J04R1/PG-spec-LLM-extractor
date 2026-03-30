# Iteration YY — Supair MVP Database

**Status:** Not Started  
**Created:** 2026-03-30  
**Domain:** data  
**Prerequisite:** Iteration XX (BGD MVP DB) complete, or can run independently after
Iteration 20 (Ozone MVP DB) since it uses the same pipeline.

---

## Goal

Produce a validated, benchmarked `supair.db` covering the full current Supair paraglider
lineup (9 models) with zero critical validation issues.

Scope: **Current models only.** Supair does not maintain public product pages for
discontinued gliders — historical coverage (Eona 3, Leaf 1/2, older Sora etc.) is
deferred to the fredvol + DHV integration (Iterations 16/17).

---

## Site Reconnaissance (Done — 2026-03-30)

### Source

| Property | Value |
|----------|-------|
| Website | https://supair.com |
| Platform | WordPress / WooCommerce |
| Robots.txt | Disallows `/wp-admin`, `/wp-login.php`, `/wp-json` only — product pages are `Allow: /` |
| Product pages | Largely server-rendered HTML, but **spec tables vary in structure** — Crawl4AI required (see Render Risk below) |
| Product URL pattern | `https://supair.com/en/produit/aile-parapente-supair-{class}-{model}/` |
| URL discovery | Product sitemap: `https://supair.com/product-sitemap.xml` |
| Catalog page | `https://supair.com/en/categorie-produit/voiles/` — JS-filtered, use sitemap instead |

### Product Inventory — 9 Current Paraglider Models

| Model | EN Class | Category | URL slug |
|-------|----------|----------|---------|
| BIRDY 2 | EN-A | paraglider | `en-a-birdy2` |
| EONA 4 | EN-A | paraglider | `en-a-eona4` |
| EIKO 2 | EN A/B/C (variable) | paraglider (mini/lightweight) | `eiko2` |
| LEAF 3 | EN-B | paraglider | `en-b-leaf3` |
| LEAF 3 Light | EN-B | paraglider (lightweight) | `en-b-leaf3-light` |
| STEP CROSS (STEP X) | EN-B | paraglider | `en-b-step-cross` |
| SAVAGE 2 | EN-C | paraglider (lightweight) | `en-c-savage2` |
| WILD 2 | EN-D | paraglider | `en-d-wild2` |
| SORA EVO | — | **tandem** | `tdm-sora-evo` |

> There is also `/produit/mini-glider/` in the sitemap. This requires investigation —
> it may be a training kite or ground-handler (no EN flight cert), similar to
> Ozone's Roadrunner. Exclude from initial crawl; check manually.

**No historical models accessible on supair.com.** The product sitemap confirms only
the 9 models above are published product pages. Historical coverage requires the
fredvol or DHV datasets (deferred).

### BGD/Ozone vs Supair — Key Structural Differences

| Aspect | Ozone / BGD | Supair |
|--------|------------|--------|
| Historical models | Accessible (separate page or same catalog) | Not published |
| Phases needed | 2 (current + historical) | **1 (current only)** |
| Field label consistency | Consistent across models | **Inconsistent — auto-translated from French** |
| Spec table rendering | Static HTML ✓ | **Partially JS-dependent — render risk (see below)** |
| Size label format | Letter (XS/S/M/L) or numeric | Both: letter for most, numeric for EIKO 2 (16/19/21/23/26) |
| Cert per size | Yes | Yes for most; **EIKO 2: multi-class (A/B/C), not per-size column** |
| Performance data | BGD: yes on some pages; Ozone: none | None observed |

---

## ⚠ Render Risk — Spec Table Extraction

During recon, the markdown converter (`web_fetch` tool) successfully extracted full
spec tables for **LEAF 3** and **SAVAGE 2**, but returned only the intro description
for **EIKO 2** — the spec table was absent from the converted markdown, even though
it is present in the raw HTML source.

This is a pre-flight blocker:

```
Phase 0 gate: Before batch crawl, manually verify Crawl4AI renders spec tables
for at least 3 pages including EIKO 2 and SORA EVO (tandem).
```

If Crawl4AI consistently misses spec tables, the fallback is direct HTML parsing
(using `httpx` + `BeautifulSoup`) as a BGD-style static alternative.

---

## Spec Table Field Mapping

Supair pages use **multiple label variants for the same fields**, caused by
inconsistent auto-translation of French terms. All variants must be mapped.

### Weight Range (PTV) — 3 label variants observed

| Label on page | Model(s) | Maps to |
|--------------|---------|---------|
| `"Beach flying weight range (Flying weight range) (kg)"` | LEAF 3 | `ptv_min_kg` / `ptv_max_kg` |
| `"flying weight range (kg)"` | SAVAGE 2, BIRDY 2 | `ptv_min_kg` / `ptv_max_kg` |
| `"Weight Range (kg)"` | EIKO 2 | `ptv_min_kg` / `ptv_max_kg` |

> Likely also: `"weight range (kg)"`, `"in-flight weight range (kg)"`, `"load range (kg)"`.
> Test all 9 models at parse-verification step and expand mappings as needed.

### Glider Weight — 2 label variants

| Label on page | Model(s) | Maps to |
|--------------|---------|---------|
| `"Weight of glider (kg)"` | LEAF 3, SAVAGE 2 | `wing_weight_kg` |
| `"Glider Weight (kg)"` | EIKO 2 | `wing_weight_kg` |

### Certification — unique to Supair

| Label on page | Maps to | Note |
|--------------|---------|------|
| `"Homologation"` | `certification` | **New label** — not used by Ozone or BGD |

Certification **value** formats observed (must handle in normalizer):

| Value on page | Standard | Class | Note |
|--------------|---------|-------|------|
| `"EN - LFT B"` | EN | B | Supair's non-standard rendering of EN/LTF-B; "LFT" is a Supair quirk |
| `"EN-C"` | EN | C | Clean format |
| `"EN - LFT A"` | EN | A | Expected for BIRDY 2 / EONA 4 |

> The normalizer's `normalize_certification()` already handles "EN-B", "EN/LTF B", "LTF B"
> etc. A new case for `"EN - LFT B"` (spaces around hyphen, "LFT" instead of "LTF")
> must be added.

### Other fields

| Label on page | Maps to | Note |
|--------------|---------|------|
| `"Wingspan (m)"` | `flat_span_m` | **New** — BGD/Ozone use "Flat span (m)" |
| `"Number of cells"` | `cell_count` | Already mapped (Ozone) |
| `"Flat area (m²)"` | `flat_area_m2` | Already mapped |
| `"Projected area (m²)"` | `proj_area_m2` | Already mapped |
| `"Projected span (m)"` | `proj_span_m` | Already mapped |
| `"Flat aspect ratio"` | `flat_aspect_ratio` | Already mapped |
| `"Projected aspect ratio"` | `proj_aspect_ratio` | Already mapped |
| `"Number of elevators"` | `riser_config` | Values: "3+1", "A/B/C" |

Fields to **ignore** (not in schema):
- `"Chord (m)"` — structural dimension
- `"Speed bar"` — travel dimension in mm
- `"ACRO"` — boolean flag, used only to infer category
- `"Trim"` — not in schema
- `"Other system of Adjustment"` — not in schema

### EU Decimal Separators

EIKO 2 spec table uses **commas** as decimal separators (e.g., `"8,76"` not `"8.76"`).
The markdown parser already handles EU decimals (added in Iteration 4) — verify this
applies to the EIKO 2 table format.

---

## EIKO 2 — Special Case

The EIKO 2 is a mini/lightweight crossover with several unique characteristics:

**1. Numeric size labels**: Sizes are flat area values — `16`, `19`, `21`, `23`, `26`
(in m²). The parser's `_SIZE_LABEL_HINTS` already supports numeric sizes (extended
in Iteration 8 to cover sizes 14–45 for miniwings). Verify EIKO 2 sizes are recognized.

**2. Multi-class certification**: The EIKO 2 is certified EN Class A, B, or C
depending on the flying weight range. This is **not shown per-size column** in the
spec table — the Homologation section states "Standard EN 926-1 and 2 and LTF 91/09
— Class A, B or C" as a block, not per size.

Handling options (decide at patch time):
- **Option A**: Store one cert record per size variant based on weight range — requires manual lookup of which size is which class
- **Option B**: Store a single cert record with classification `"A/B/C"` — less precise but honest to the source
- **Option C**: Store no cert for EIKO 2 (documented gap) — simplest, not ideal

Recommendation: **Option A** if the per-size cert mapping is available from DHV or
the user manual; **Option B** otherwise, documented as "variable by weight range".

---

## Phase 0 — Reconnaissance & Config

### 0.1 — `config/manufacturers/supair.yaml`

```yaml
# Supair Paraglider Specs — Extraction Config

manufacturer:
  name: Supair
  slug: supair
  website: https://supair.com

import:
  output_db: output/supair.db

sources:
  current_gliders:
    listing_url: https://supair.com/product-sitemap.xml
    url_pattern: "aile-parapente-supair"
    is_current: true
    url_excludes:
      - "mini-glider"
      - "tdm"        # handle tandem separately or include with is_current

  # No previous_gliders source — historical models not publicly accessible

extraction:
  strategy: markdown

  llm:
    provider: "gemini/gemini-2.0-flash"
    api_key_env: "GEMINI_API_KEY"

    prompt: |
      Extract ONLY the factual technical specifications from this Supair paraglider product page.

      RULES:
      - The spec table has sizes as columns (XS, S, M, ML, L, or numeric like 16, 19, 21).
      - "flying weight range" or "weight range" or "beach flying weight range" gives
        ptv_min_kg and ptv_max_kg (split "65-85" into min=65, max=85).
      - "Weight of glider" or "Glider Weight" gives wing_weight_kg.
      - "Homologation" in the spec table column gives the certification class.
        Values may be "EN - LFT B", "EN-C", "EN - LFT A" etc. — extract the class letter only.
      - "Number of cells" gives cell_count (same for all sizes).
      - "Wingspan" gives the flat span in metres (flat_span_m).
      - "Number of elevators" gives riser_config (e.g. "3+1", "A/B/C").
      - IGNORE: Chord, Speed bar, ACRO, Trim, Other system of Adjustment.
      - DO NOT extract marketing text, testimonials, or image URLs.
      - All numeric values must be plain numbers (no units, no commas — convert "8,76" to 8.76).
      - Return one size entry per column in the specs table.

    schema:
      type: object
      properties:
        model_name:
          type: string
          description: "Wing model name (e.g. 'Leaf 3', 'Savage 2', 'Eiko 2')"
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
            required: ["size_label", "ptv_min_kg", "ptv_max_kg"]
      required: ["model_name", "sizes"]
```

### 0.2 — URL List (`output/supair_urls.json`)

The product sitemap lists all 9 paraglider URLs directly. No crawl-based discovery
needed — extract from `https://supair.com/product-sitemap.xml` and filter by
`"aile-parapente-supair"`:

```json
{
  "current": [
    "https://supair.com/en/produit/aile-parapente-supair-en-a-birdy2/",
    "https://supair.com/en/produit/aile-parapente-supair-en-a-eona4/",
    "https://supair.com/en/produit/aile-parapente-supair-eiko2/",
    "https://supair.com/en/produit/aile-parapente-supair-en-b-leaf3/",
    "https://supair.com/en/produit/aile-parapente-supair-en-b-leaf3-light/",
    "https://supair.com/en/produit/aile-parapente-supair-en-b-step-cross/",
    "https://supair.com/en/produit/aile-parapente-supair-en-c-savage2/",
    "https://supair.com/en/produit/aile-parapente-supair-en-d-wild2/",
    "https://supair.com/en/produit/aile-parapente-supair-tdm-sora-evo/"
  ],
  "previous": []
}
```

> Note: `/produit/mini-glider/` excluded until its nature is confirmed (likely a
> training kite with no EN flight certification — handle like Ozone Roadrunner).

### 0.3 — Markdown Parser: Supair Label Mappings

**Append** to `_MD_ROW_MAP` in `src/markdown_parser.py`:

```python
# Supair-specific label mappings
"wingspan (m)":                                              ("flat_span_m",   False, False),
"weight of glider (kg)":                                    ("wing_weight_kg", False, False),
"glider weight (kg)":                                       ("wing_weight_kg", False, False),
"homologation":                                             ("certification",  True,  False),
"flying weight range (kg)":                                 ("ptv_range",      True,  True),
"beach flying weight range (flying weight range) (kg)":     ("ptv_range",      True,  True),
"weight range (kg)":                                        ("ptv_range",      True,  True),
"number of elevators":                                      ("riser_config",   False, False),
```

> Note: The weight-range labels are long and may be cut differently depending on
> the auto-translation. After the smoke test (step 0.4), expand this list with any
> additional variants found on other pages.

**Also update `src/normalizer.py` — `normalize_certification()`** to handle Supair's
non-standard cert value format:

```python
# Handle Supair's "EN - LFT B" / "EN - LFT A" / "EN - LFT C" format
# ("LFT" is a Supair mistranslation of "LTF")
if re.match(r"en\s*-\s*lft\s*[a-d]", raw.lower()):
    class_letter = re.search(r"[a-d]$", raw.strip(), re.IGNORECASE).group().upper()
    return (CertStandard.EN, class_letter)
```

### 0.4 — Render Verification (Phase 0 Gate)

```bash
# Verify Crawl4AI renders spec tables for all 9 models
python3 - <<'EOF'
from src.crawler import Crawler
from src.markdown_parser import parse_specs_from_markdown

crawler = Crawler()
urls = [
    ("LEAF 3",   "https://supair.com/en/produit/aile-parapente-supair-en-b-leaf3/"),
    ("SAVAGE 2", "https://supair.com/en/produit/aile-parapente-supair-en-c-savage2/"),
    ("EIKO 2",   "https://supair.com/en/produit/aile-parapente-supair-eiko2/"),
    ("SORA EVO", "https://supair.com/en/produit/aile-parapente-supair-tdm-sora-evo/"),
    ("WILD 2",   "https://supair.com/en/produit/aile-parapente-supair-en-d-wild2/"),
]
for name, url in urls:
    md = crawler.render_page(url)
    result = parse_specs_from_markdown(md, url, manufacturer_name="Supair")
    print(f"{name}: {len(result.sizes)} sizes, cells={result.cell_count}, "
          f"ptv={'OK' if result.sizes and result.sizes[0].ptv_min_kg else 'MISSING'}")
EOF
```

**Pass criteria:**
- All 5 models return ≥ 1 size with `ptv_min_kg` populated
- EIKO 2 returns 5 sizes with numeric size labels

**Fail criteria (investigate before proceeding):**
- Any model returns 0 sizes → spec table not rendered; may need CSS selector or LLM fallback
- EIKO 2 returns 0 sizes → apply targeted fix (see EIKO 2 Special Case section)

---

## Phase 1 — All Current Models (9 models, single phase)

### Script: `scripts/crawl_supair.py`

```
1. Load config from config/manufacturers/supair.yaml
2. Load output/supair_urls.json → all 9 current URLs
3. Instantiate Crawler (md_cache_dir="output/md_cache")
4. For each URL:
   a. crawler.render_page(url)
   b. parse_specs_from_markdown(md, url, manufacturer_name="Supair")
   c. Append record to staged list
5. Write output/supair_staged.json
6. Print summary
```

### Audit

```bash
python3 scripts/audit_staged_json.py \
    --file output/supair_staged.json \
    --manufacturer supair
```

Review for:
- Models with 0 sizes → spec table render failure
- Models with missing `ptv_min_kg` → weight range label not mapped
- Missing `cell_count` → "Number of cells" label issue
- Missing `certification` → "Homologation" not mapped or cert value not parsed

### Known Category Overrides (pre-planned)

| Model | Correct category | Reason |
|-------|-----------------|--------|
| SORA EVO | `tandem` | Tandem wing |
| EIKO 2 | `paraglider` | Lightweight all-terrain, not true miniwing (EN-A range) |

### Year Backfill

`year_released` is not in spec tables. Estimated release years for `scripts/patch_supair.py`:

| Model | Approx. year | Notes |
|-------|-------------|-------|
| EONA 4 | 2022 | EONA series (school wing) |
| BIRDY 2 | 2024 | Second gen |
| EIKO 2 | 2023 | "EIKO 2" branding |
| LEAF 3 | 2023 | Third generation LEAF |
| LEAF 3 Light | 2023 | Simultaneous with LEAF 3 |
| STEP CROSS (STEP X) | 2024 | Referenced as "new-generation EN-B+" |
| SAVAGE 2 | 2025 | Second generation; user manual dated 2026 |
| WILD 2 | 2024 | Referenced alongside BIRDY 2 development |
| SORA EVO | 2024 | "EVO" revision |

> Verify against Supair news/press pages or DHV records before committing.

### EIKO 2 Certification Patch

EIKO 2 shows "Class A, B or C" per flying weight, not per size column.
Post-import, inspect per DHV portal or user manual to determine the correct
per-size cert and patch `scripts/patch_supair.py` accordingly:

| EIKO 2 size | Flat area | Likely cert class |
|-------------|-----------|------------------|
| 16 | 16 m² | A (small, light pilot) |
| 19 | 19 m² | A or B |
| 21 | 21 m² | B |
| 23 | 23 m² | B |
| 26 | 26 m² | B or C |

> These are rough estimates. Use DHV certification data as authoritative source.

### Import

```bash
python3 scripts/import_supair_to_db.py \
    --staged output/supair_staged.json \
    --db output/supair.db \
    --dry-run

python3 scripts/import_supair_to_db.py \
    --staged output/supair_staged.json \
    --db output/supair.db
```

### Phase 1 Benchmark Target

```
models (9 records):
  category:         9/9  (100%) ✓
  cell_count:       9/9  (100%) ✓
  year_released:    9/9  (100%) ✓  (after patch)
  manufacturer_url: 9/9  (100%) ✓

size_variants (expected ~40-50 records):
  flat_area_m2:      ~100% ✓
  proj_area_m2:      ~100% ✓
  flat_span_m:       ~100% ✓  (from "Wingspan")
  proj_span_m:       ~100% ✓
  wing_weight_kg:    ~100% ✓
  ptv_min/max_kg:    ~89%  ✓  (SORA EVO tandem may not have standard PTV)
  flat_aspect_ratio: ~100% ✓

certifications (~35-40 records):
  standard:          ~100% ✓
  classification:    ~89%  ✓  (EIKO 2 variable-cert needs patch)

QUALITY:  100%  ← target
ACCURACY: 100%  ← target
```

---

## Scripts to Create

| Script | Purpose | Mirrors |
|--------|---------|---------|
| `scripts/crawl_supair.py` | Crawl all 9 models → staged JSON | `scripts/crawl_previous_to_json.py` |
| `scripts/patch_supair.py` | Category overrides, year backfill, EIKO 2 cert patch | `scripts/patch_ozone_phase1.py` |
| `scripts/import_supair_to_db.py` | Import staged JSON → `output/supair.db` | `scripts/import_staged_to_db.py` |

> No URL discovery script needed — 9 URLs hardcoded from sitemap (see 0.2 above).

**Reused without modification:** `scripts/audit_staged_json.py`, `scripts/show_spec_table.py`,
`src/crawler.py`, `src/db.py`, `src/normalizer.py`, `src/benchmark.py`

**Modified (appended/extended):**
- `src/markdown_parser.py` — 8 new `_MD_ROW_MAP` entries (plus BGD entries from Iteration XX)
- `src/normalizer.py` — 1 new cert format case for `"EN - LFT {class}"`

---

## Output Files

| File | Contents |
|------|---------|
| `output/supair.db` | Supair database — 9 current models |
| `output/supair_urls.json` | URL list (hardcoded from sitemap) |
| `output/supair_staged.json` | Staged JSON (single phase) |
| `config/manufacturers/supair.yaml` | Supair manufacturer config |

---

## Done Criteria

| Gate | Metric | Target |
|------|--------|--------|
| Phase 0 | Render verification: all 5 sample pages return ≥1 size with ptv | ✓ |
| Phase 0 | Label mapping smoke test: LEAF 3, SAVAGE 2, EIKO 2 parse cleanly | ✓ |
| Phase 1 | Critical validation issues | 0 |
| Phase 1 | All 9 models have `cell_count` | 9/9 |
| Phase 1 | All 9 models have `year_released` | 9/9 |
| Phase 1 | Quality score | 100% |
| Phase 1 | Accuracy score | 100% |
| All phases | All existing automated tests pass | 316/316+ |
| Docs | `ITERATION_YY_SUPAIR_MVP_DB.md` renamed + README updated | ✓ |

---

## Known Gaps (Pre-declared)

| Field | Expected coverage | Reason |
|-------|------------------|--------|
| Historical models | 0 | Not published on supair.com — needs fredvol/DHV |
| `year_discontinued` | 0% | Not published; needs fredvol/DHV |
| `report_url` / `test_date` / `test_lab` | 0% | DHV portal integration (deferred) |
| EIKO 2 per-size certification | Approximate | Multi-class cert, not per-size in source |
| `performance_data` | 0 | Not published on Supair product pages |

---

## Future (Post-Iteration YY)

- **Historical models**: Supair's older lineup (Eona 3, Leaf 1/2, Sora, etc.) can be
  recovered from the fredvol dataset (Iterations 16/17) — no manufacturer pages to crawl.
- **EIKO 2 cert**: DHV portal can provide per-size cert classification once DHV
  integration is implemented.
- **Multi-brand scaling**: After Ozone + BGD + Supair, apply to Nova, Skywalk, Niviuk.
  The pipeline requires no structural changes.
