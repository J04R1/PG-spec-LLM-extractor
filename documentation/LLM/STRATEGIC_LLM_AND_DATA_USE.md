# Strategic LLM & Data Use — OpenPG Spec Extractor

**Created:** 2026-03-12
**Status:** Active reference document
**Scope:** How to leverage existing datasets and Ollama/Qwen2.5:3b for extraction quality

---

## 1. Overview

The pipeline uses a local LLM (Ollama + Qwen2.5:3b) as the primary extraction strategy, with a deterministic markdown parser as fallback. The LLM is a frozen model — it cannot "learn" from our data at inference time. However, we can significantly improve extraction quality through three complementary strategies:

1. **Few-shot prompting** — embed real examples in the extraction prompt
2. **Validation & accuracy measurement** — compare LLM output against known-good data
3. **Pre-seeding & gap-filling** — populate the DB with verified data, then target gaps

This document maps every existing dataset to its optimal role in these strategies.

---

## 2. Existing Data Inventory

### 2.1 `data/ozone_enrichment.csv`

| Property | Value |
|----------|-------|
| Rows | 564 |
| Unique models | 111 |
| Manufacturer | Ozone only |
| Source | POC extractor (`extract.py`) — deterministic markdown parsing |
| Columns | 30 — matches our pipeline schema exactly |
| Quality | High — parsed from structured Ozone spec tables |

**Column mapping to our schema:**

| CSV Column | Pipeline Field | Notes |
|------------|---------------|-------|
| `manufacturer_slug` | `manufacturer.slug` | Always "ozone" |
| `name` | `model.name` | e.g. "Buzz Z7", "Rush 6" |
| `year` | `model.year` | Often empty — Ozone doesn't always publish year |
| `category` | `model.category` | paraglider, tandem, etc. |
| `target_use` | `model.target_use` | school, xc, competition |
| `is_current` | `model.is_current` | Boolean — current vs. previous |
| `cell_count` | `model.cell_count` | Top-level field |
| `line_material` | `model.line_material` | String |
| `riser_config` | `model.riser_config` | String |
| `manufacturer_url` | source URL | Used for provenance |
| `size_label` | `size_variant.size_label` | XS, S, M, ML, L, XL |
| `flat_area_m2` | `size_variant.flat_area_m2` | Decimal |
| `flat_span_m` | `size_variant.flat_span_m` | Decimal |
| `flat_aspect_ratio` | `size_variant.flat_aspect_ratio` | Decimal |
| `proj_area_m2` | `size_variant.proj_area_m2` | Decimal |
| `proj_span_m` | `size_variant.proj_span_m` | Decimal |
| `proj_aspect_ratio` | `size_variant.proj_aspect_ratio` | Decimal |
| `wing_weight_kg` | `size_variant.wing_weight_kg` | Decimal |
| `ptv_min_kg` | `size_variant.ptv_min_kg` | Decimal |
| `ptv_max_kg` | `size_variant.ptv_max_kg` | Decimal |
| `speed_trim_kmh` | `size_variant.speed_trim_kmh` | Rarely populated |
| `speed_max_kmh` | `size_variant.speed_max_kmh` | Rarely populated |
| `glide_ratio_best` | `size_variant.glide_ratio_best` | Rarely populated |
| `min_sink_ms` | `size_variant.min_sink_ms` | Rarely populated |
| `cert_standard` | `certification.standard` | EN, LTF |
| `cert_classification` | `certification.classification` | A, B, C, D |
| `cert_test_lab` | `certification.test_lab` | Usually empty |
| `cert_test_date` | `certification.test_date` | Usually empty |
| `cert_report_url` | `certification.report_url` | Usually empty |

**Strategic role:** Ground truth for Ozone. Best used for few-shot examples and validation.

---

### 2.2 `data/fredvol_raw.csv`

| Property | Value |
|----------|-------|
| Rows | 6,481 |
| Unique models | 1,805 |
| Manufacturers | 233 |
| Sources | GliderBase, Para2000 |
| Columns | 19 (subset of our schema) |
| Quality | Medium — community-aggregated, some gaps |

**Columns available:**

| Column | Maps to | Notes |
|--------|---------|-------|
| `manufacturer` | `manufacturer.name` | Title case (e.g. "Advance", "Gin") |
| `name` | `model.name` | e.g. "Alpha 6", "Epsilon 9" |
| `year` | `model.year` | Integer or empty |
| `size` | `size_variant.size_label` | Numeric (22, 24, 26...) not named (XS, S, M...) |
| `flat_area` | `size_variant.flat_area_m2` | Float |
| `flat_span` | `size_variant.flat_span_m` | Float |
| `flat_AR` | `size_variant.flat_aspect_ratio` | Float |
| `proj_area` | `size_variant.proj_area_m2` | Float |
| `proj_span` | `size_variant.proj_span_m` | Float |
| `proj_AR` | `size_variant.proj_aspect_ratio` | Float |
| `weight` | `size_variant.wing_weight_kg` | Float |
| `ptv_mini` | `size_variant.ptv_min_kg` | Float |
| `ptv_maxi` | `size_variant.ptv_max_kg` | Float |
| `certification` | overall cert class | A, B, C, D, DGAC |
| `certif_EN` | `certification.standard=EN` | Classification letter |
| `certif_DHV` | `certification.standard=LTF` | Classification letter/number |
| `certif_AFNOR` | historical French standard | Rarely populated |
| `certif_MISC` | other standards | DGAC, etc. |
| `source` | provenance | "GliderBase" or "Para2000" |

**Key differences from our schema:**
- Sizes are numeric (flat area in m²) rather than named labels (XS, S, M)
- No `category`, `target_use`, `cell_count`, `line_material`, or `riser_config`
- No speed, glide ratio, or sink rate data
- Certification is split across 4 columns instead of our `(standard, classification)` tuple

**Strategic role:** Cross-manufacturer validation reference. Useful for verifying LLM output accuracy across many brands. Not suitable for few-shot examples (schema mismatch).

---

### 2.3 `data/dhv_unmatched.csv`

| Property | Value |
|----------|-------|
| Rows | 3,192 |
| Content | DHV-certified wings not matched to existing DB records |
| Columns | `dhv_url`, `manufacturer`, `model`, `size`, `equipment_class`, `test_centre`, `test_date`, `report_url`, `match_failure_reason` |
| Quality | High — official government certification data |

**Failure reasons observed:**
- `model not found: 'Torre' (mfr: up)` — model doesn't exist in our DB
- `model not found: 'PHI MAESTRO 3 light' (mfr: phi)` — newer models

**Strategic role:** Prioritization queue. Each row represents a certified wing we don't have yet. The `report_url` links to the official DHV test report with authoritative spec data (weight ranges, classification). Could be used to enrich/validate LLM-extracted certification data.

---

### 2.4 `data/dhv_gap_report.md`

| Property | Value |
|----------|-------|
| Lines | 1,220 |
| Content | Structured analysis of what's missing from our DB vs. DHV |
| Missing models total | 2,413 models not in DB |
| Unknown manufacturers | 630 entries for manufacturers not tracked |

**Priority breakdown from the report:**

| Priority | Manufacturers | Why |
|----------|--------------|-----|
| P1 | Advance, Gin, Niviuk, Nova, Ozone | Major brands, most missing models |
| P2 | Dudek, Sky, Skywalk, Swing, Triple Seven, U-Turn | Mid-tier brands |
| — | 30+ others (PHI, UP, Macpara, etc.) | Smaller or legacy brands |

**Strategic role:** Roadmap for multi-manufacturer expansion (Iteration 8+). Tells you exactly which brands to tackle next and how many models they're missing.

---

### 2.5 `data/manufacturers_enrichment.csv`

| Property | Value |
|----------|-------|
| Rows | 24 |
| Columns | `slug`, `country`, `website` |
| Content | Ready-made manufacturer records |

**Full list:** Advance, Ozone, Nova, Niviuk, Gin, Sky, Swing, Triple Seven, Skywalk, BGD, Dudek, U-Turn, Macpara, Gradient, Sol, Independence, Apco, Icaro, Aircross, Air Design, Supair, Nervures, Axis, Flow.

**Strategic role:** Direct import — each row maps to the `manufacturers` table. Use to generate YAML config files for multi-manufacturer expansion.

---

### 2.6 `data/dhv_cache/`

| Property | Value |
|----------|-------|
| Files | 2,892 HTML files |
| Size | ~93–104 KB each (~280 MB total) |
| Content | DHV Geräteportal list pages (search results) |
| Naming | SHA-256 hash filenames (no human-readable mapping) |

**What's inside:** Each HTML file is a search results page from the DHV equipment database. They contain links to individual `technicdatareport2.php` detail pages but not the spec data itself.

**Strategic role:** Low immediate value for LLM extraction. The linked detail pages (not cached) contain the actual spec data. However, the URLs extracted from these list pages could feed a targeted DHV detail-page crawler in a future iteration.

---

## 3. Strategy 1: Few-Shot Prompting

### Why it matters

Qwen2.5:3b is a small model. Without examples, it often:
- Includes units in numeric fields (e.g. `"23.5 m²"` instead of `23.5`)
- Misinterprets weight ranges (e.g. treats "55-75" as a single number)
- Returns extra fields not in the schema
- Misses the multi-size table structure (returns one size instead of all)

Adding 2–3 concrete input→output examples in the prompt dramatically improves structured extraction accuracy — this is called **few-shot prompting**.

### How to build few-shot examples

Use `ozone_enrichment.csv` rows + their source markdown as paired examples.

**Example construction (manual process):**

1. Pick a well-known Ozone model with a clean spec table (e.g. Rush 6, Buzz Z7)
2. Crawl the page to get the markdown representation
3. Take the corresponding rows from `ozone_enrichment.csv`
4. Format as: "Given this markdown → produce this JSON"

**Example pair for the prompt:**

```
EXAMPLE INPUT:
| | XS | S | M |
|---|---|---|---|
| Cells | 48 | 48 | 48 |
| Flat area (m²) | 22,1 | 24,1 | 25,7 |
| In-flight weight range (kg) | 55-70 | 65-85 | 75-95 |
| Certification | EN/LTF B | EN/LTF B | EN/LTF B |

EXAMPLE OUTPUT:
{
  "model_name": "Buzz Z7",
  "cell_count": 48,
  "sizes": [
    {"size_label": "XS", "flat_area_m2": 22.1, "ptv_min_kg": 55, "ptv_max_kg": 70,
     "cert_standard": "EN", "cert_classification": "B"},
    {"size_label": "S", "flat_area_m2": 24.1, "ptv_min_kg": 65, "ptv_max_kg": 85,
     "cert_standard": "EN", "cert_classification": "B"},
    {"size_label": "M", "flat_area_m2": 25.7, "ptv_min_kg": 75, "ptv_max_kg": 95,
     "cert_standard": "EN", "cert_classification": "B"}
  ]
}
```

### Implementation approach

The few-shot examples should be injected into the prompt via `OllamaAdapter._build_prompt()`. Two options:

**Option A — Hardcoded in default prompt** (simplest):
Add 2–3 examples directly in the fallback prompt string inside `_build_prompt()`. Works immediately, no config changes needed.

**Option B — Config-driven per manufacturer** (scalable):
Add a `few_shot_examples` section to each manufacturer YAML config. The adapter reads them and injects into the prompt. More work but allows different examples per brand.

**Recommended:** Start with Option A for the Ozone validation run. Move to Option B when expanding to other manufacturers.

### How many examples?

- **2–3 examples** is the sweet spot for Qwen2.5:3b
- More examples consume context window and slow inference
- Pick diverse examples: one with EU decimals (commas), one with period decimals, one tandem/non-standard

### Source pairing candidates from `ozone_enrichment.csv`

| Model | Why it's a good example |
|-------|----------------------|
| Buzz Z7 | Standard 6-size EN B, clean table, EU decimals |
| Rush 6 | 5 sizes, common column layout |
| Moxie | EN A school wing, different target_use |
| Zeno 2 | EN D competition, different cert class |
| Magnum 3 | Tandem category, different weight ranges |

---

## 4. Strategy 2: Validation & Accuracy Measurement

### Why it matters

Without ground truth, you can't tell if the LLM extracted correctly. You might get "good-looking" JSON that has wrong numbers. The existing datasets provide a built-in answer key.

### Validation workflow

```
┌─────────────┐     ┌──────────────┐     ┌────────────────┐
│ Crawl page  │────→│ LLM extracts │────→│ Compare output │
│ (markdown)  │     │ (JSON)       │     │ vs. known data │
└─────────────┘     └──────────────┘     └────────────────┘
                                                │
                                    ┌───────────┴───────────┐
                                    │  ozone_enrichment.csv │
                                    │  fredvol_raw.csv      │
                                    └───────────────────────┘
```

### Field-level accuracy metrics

For each extracted model, compare against the reference data:

| Field | Comparison method | Tolerance |
|-------|------------------|-----------|
| `model_name` | Fuzzy string match | Case-insensitive, ignore whitespace |
| `cell_count` | Exact integer match | ±0 |
| `flat_area_m2` | Float comparison | ±0.1 m² |
| `flat_span_m` | Float comparison | ±0.05 m |
| `flat_aspect_ratio` | Float comparison | ±0.05 |
| `wing_weight_kg` | Float comparison | ±0.1 kg |
| `ptv_min_kg` | Exact integer match | ±0 |
| `ptv_max_kg` | Exact integer match | ±0 |
| `cert_classification` | Exact string match | Must match exactly |

### Accuracy scoring

```
accuracy = fields_correct / fields_compared × 100

Per-model score:  "Buzz Z7 XS: 9/9 fields correct (100%)"
Per-run score:    "Ozone batch: 108/111 models fully correct (97.3%)"
```

### Using `ozone_enrichment.csv` for Ozone validation

This is the primary validation dataset for Iteration 7 (Ozone Validation Run):

1. Run the pipeline against all Ozone URLs
2. For each extracted model+size, find the matching row in `ozone_enrichment.csv`
3. Compare every numeric field within tolerance
4. Report: total accuracy, per-field accuracy, models that failed

### Using `fredvol_raw.csv` for cross-manufacturer validation

For Iteration 8+ (multi-manufacturer expansion):

1. Extract specs from a new manufacturer (e.g. Advance, Gin)
2. Find matching models in fredvol by `(manufacturer, name, size)`
3. Compare overlapping fields (flat_area, PTV range, weight, cert)
4. Note: fredvol uses numeric sizes (22, 24, 26) while manufacturers use labels (XS, S, M) — matching requires mapping flat_area values

**Caveat:** fredvol data comes from GliderBase/Para2000, which may have their own errors. Use as a sanity check, not absolute truth. When values disagree, the manufacturer's website is authoritative.

### Using DHV data for certification validation

The `dhv_unmatched.csv` has official certification classifications. Cross-check:

```
LLM says: Buzz Z7 XS → EN B
DHV says: Buzz Z7 XS → equipment_class B
Match: ✅
```

DHV is the highest-authority source for certification data (it's the actual testing body).

---

## 5. Strategy 3: Pre-Seeding & Gap-Filling

### Why it matters

Instead of extracting everything from scratch, start with what you already have and fill gaps.

### Pre-seeding the database

**Step 1:** Import `ozone_enrichment.csv` via `--convert-only`:
```bash
# Structure the data as raw JSON matching ExtractionResult format
# Then: python -m src.pipeline run --config ozone --convert-only
```

This gives you 111 Ozone models (564 size variants) in the DB immediately.

**Step 2:** Import `manufacturers_enrichment.csv`:
The 24 manufacturer records can be loaded directly into the `manufacturers` table. Each row has `slug`, `country`, and `website` — exactly what `Manufacturer` model needs.

### Gap-filling workflow

Once the DB is seeded with known-good data:

1. **Identify gaps** using `dhv_gap_report.md` — it lists every model that exists in DHV but not in our DB
2. **Prioritize** by manufacturer (P1: Advance, Gin, Niviuk, Nova, Ozone)
3. **Target extraction** — only crawl pages for models we don't have yet
4. **Validate** new extractions against fredvol_raw where overlap exists

```
┌────────────────────┐
│ Start: 111 Ozone   │
│ models (seed data) │
└────────┬───────────┘
         │
         ▼
┌────────────────────┐     ┌─────────────────────┐
│ DHV gap report     │────→│ Target: 54 missing   │
│ says 54 Ozone      │     │ Ozone models         │
│ models missing     │     └─────────┬─────────────┘
└────────────────────┘               │
                                     ▼
                          ┌─────────────────────┐
                          │ Crawl + LLM extract  │
                          │ only missing models  │
                          └─────────┬─────────────┘
                                     │
                                     ▼
                          ┌─────────────────────┐
                          │ Validate vs fredvol  │
                          │ where overlap exists │
                          └─────────────────────┘
```

### Multi-manufacturer expansion plan

Based on `dhv_gap_report.md` priorities and `manufacturers_enrichment.csv`:

| Phase | Manufacturer | Missing models | YAML config needed | Validation source |
|-------|-------------|---------------|-------------------|-------------------|
| Current | Ozone | 54 (+ 111 seeded) | ✅ exists | ozone_enrichment.csv |
| Next | Advance | 39 models, 105 sizes | Create | fredvol (500+ rows) |
| Next | Nova | 74 models, 202 sizes | Create | fredvol (400+ rows) |
| Next | Gin | 55 models, 194 sizes | Create | fredvol (300+ rows) |
| Next | Niviuk | 30 models, 65 sizes | Create | fredvol (200+ rows) |
| Later | Skywalk | 41 models, 157 sizes | Create | fredvol |
| Later | Swing | 35 models, 177 sizes | Create | fredvol |

For each new manufacturer:
1. Create YAML config in `config/manufacturers/<slug>.yaml` (use ozone.yaml as template)
2. Add manufacturer-specific few-shot examples from fredvol data
3. Run extraction pipeline
4. Validate against fredvol + DHV

---

## 6. LLM Configuration & Tuning

### Current setup

| Setting | Value | Notes |
|---------|-------|-------|
| Model | `qwen2.5:3b` | ~1.9 GB, fits comfortably in 8 GB RAM |
| Endpoint | `localhost:11434` | Ollama default |
| Timeout | 300s (default) | First call slow (~2 min) for model loading |
| JSON mode | On (`"format": "json"`) | Forces structured JSON output |
| Temperature | Default (0.7) | Not explicitly set |

### Recommended tuning

**Temperature:** Set to `0.0` or `0.1` for extraction tasks. We want deterministic, factual output — creativity is harmful here. This can be added to the Ollama API call:

```python
json={
    "model": self.model,
    "messages": [{"role": "user", "content": prompt}],
    "format": "json",
    "stream": False,
    "options": {"temperature": 0.0},  # Deterministic extraction
}
```

**Context window:** Qwen2.5:3b has a 32K context window. A typical Ozone spec page is ~5–12K chars of markdown. With 2–3 few-shot examples + schema, total prompt is ~8–15K tokens — well within limits. For very long pages, consider truncating non-spec sections (marketing text, feature descriptions).

**Num_predict:** Consider setting `"num_predict": 4096` to cap output length and prevent runaway generation on malformed input.

### Model alternatives

If Qwen2.5:3b proves insufficient:

| Model | Size | Trade-off |
|-------|------|-----------|
| `qwen2.5:3b` | 1.9 GB | Current — fast, fits 8GB |
| `qwen2.5:7b` | 4.7 GB | Better accuracy, still fits 8GB with overhead |
| `llama3.2:3b` | 2.0 GB | Alternative 3B model, good at structured output |
| `qwen2.5:14b` | 8.9 GB | Requires 16GB RAM, significantly better accuracy |
| `gemma3:4b` | 3.3 GB | Google model, strong at table extraction |

To test a different model:
```bash
ollama pull qwen2.5:7b
# Then in config or adapter:
adapter = OllamaAdapter(model="qwen2.5:7b")
```

---

## 7. Prompt Engineering Guidelines

### Current prompt structure

The adapter builds prompts in `OllamaAdapter._build_prompt()` with two modes:

1. **With manufacturer instructions** (from YAML config `extraction.llm.prompt`):
   ```
   {instructions}
   Return a JSON object matching this schema:
   ```json
   {schema}
   ```
   MARKDOWN CONTENT:
   {markdown}
   ```

2. **Default prompt** (no config instructions):
   ```
   Extract the paraglider technical specifications...
   Return a JSON object matching this schema:
   {schema}
   RULES:
   - Extract ONLY factual technical data
   - All numeric values must be plain numbers
   - ...
   MARKDOWN CONTENT:
   {markdown}
   ```

### Prompt improvement opportunities

**A. Add few-shot examples** (highest priority):
Insert 2–3 example pairs between the rules and the markdown content. See Strategy 1 above.

**B. Add negative examples:**
Show the LLM what NOT to do:
```
WRONG: {"flat_area_m2": "23.5 m²"}     ← includes units
RIGHT: {"flat_area_m2": 23.5}          ← plain number

WRONG: {"ptv_min_kg": "55-75"}         ← range as string
RIGHT: {"ptv_min_kg": 55, "ptv_max_kg": 75}  ← split into two fields
```

**C. Handle EU decimal commas:**
Ozone (and most European manufacturers) use commas as decimal separators in their spec tables. The markdown parser handles this, but the LLM prompt should mention it:
```
NOTE: European pages use commas as decimal separators (e.g. "22,05" = 22.05).
Always convert to period-separated decimals in the output.
```

**D. Structural hints for multi-size tables:**
```
The specs table has one column per size. Each column (XS, S, M, ML, L, XL)
should become a separate entry in the "sizes" array. Do NOT merge sizes.
```

---

## 8. Data Flow Summary

```
                    ┌─────────────────────────────────────────────────┐
                    │           EXISTING DATA ASSETS                  │
                    │                                                 │
                    │  ozone_enrichment.csv ──→ Few-shot examples    │
                    │         (111 models)      + Validation truth    │
                    │                                                 │
                    │  fredvol_raw.csv ────────→ Cross-brand         │
                    │         (1,805 models)     validation           │
                    │                                                 │
                    │  manufacturers.csv ─────→ DB seeding           │
                    │         (24 brands)        + YAML generation    │
                    │                                                 │
                    │  dhv_unmatched.csv ─────→ Gap identification   │
                    │  dhv_gap_report.md         + cert validation    │
                    │                                                 │
                    │  dhv_cache/ ────────────→ Future: URL feed     │
                    │         (2,892 pages)      for DHV detail pages │
                    └─────────────────────────────────────────────────┘
                                         │
                                         ▼
              ┌──────────────────────────────────────────────┐
              │            EXTRACTION PIPELINE               │
              │                                              │
              │  1. Crawl page → markdown                   │
              │  2. LLM extract (with few-shot examples)    │
              │     ↳ fallback: markdown parser              │
              │  3. Normalize (certs, sizes, slugs)         │
              │  4. Validate vs. reference data             │
              │  5. Store (SQLite + CSV)                    │
              └──────────────────────────────────────────────┘
                                         │
                                         ▼
              ┌──────────────────────────────────────────────┐
              │              OUTPUT                          │
              │                                              │
              │  SQLite DB (5 tables, provenance tracking)  │
              │  CSV export (27 columns, 1 row per size)    │
              │  Accuracy report (vs. reference data)       │
              └──────────────────────────────────────────────┘
```

---

## 9. Action Items

| # | Action | Priority | Depends on |
|---|--------|----------|-----------|
| 1 | Set temperature to 0.0 in OllamaAdapter | High | None |
| 2 | Build 2–3 few-shot examples from ozone_enrichment + crawled markdown | High | Ollama running |
| 3 | Inject few-shot examples into `_build_prompt()` | High | #2 |
| 4 | Run Ozone validation: LLM output vs. ozone_enrichment.csv | High | #3 |
| 5 | Measure per-field accuracy and identify weak spots | High | #4 |
| 6 | Tune prompt based on accuracy results | Medium | #5 |
| 7 | Import manufacturers_enrichment.csv into DB | Medium | None |
| 8 | Create YAML configs for P1 manufacturers (Advance, Nova, Gin, Niviuk) | Medium | #7 |
| 9 | Build a validation script comparing LLM output vs. fredvol for non-Ozone brands | Low | #8 |
| 10 | Evaluate qwen2.5:7b as potential accuracy upgrade | Low | #5 |

---

## 10. Key Principles

- **The LLM doesn't learn** — it's frozen. All improvement comes through better prompts, examples, and validation.
- **Few-shot > zero-shot** — even 2 examples make a measurable difference with small models.
- **Manufacturer website is authoritative** — when fredvol or DHV disagrees with the manufacturer's page, the page wins (for non-certification data).
- **DHV is authoritative for certification** — it's the actual testing body.
- **Temperature 0 for extraction** — we want deterministic facts, not creative interpretation.
- **Validate everything** — never trust LLM output without comparison to known data.
