# Portable Extraction Prompt Kit — OpenPG

Use this kit to manually extract paraglider specifications from any manufacturer
website using **any LLM with web browsing** (ChatGPT, Gemini, Claude, etc.).

This is the "skill" that's portable across all platforms — no scripts, no setup,
just paste the prompt and get structured data back.

---

## When to Use This

- You need specs for a single wing or a small number of wings
- You don't want to set up Crawl4AI locally
- You're a contributor and want to add data for a new manufacturer
- You want to cross-check data from the automated extraction pipeline

---

## Legal Compliance (Built Into the Prompt)

The prompt explicitly instructs the LLM to:
- ✅ Extract **only factual technical data** (weight, area, cells, certification)
- ❌ NOT copy marketing descriptions, pilot reviews, or prose text
- ❌ NOT download or reference images, logos, or media
- ❌ NOT reproduce the exact table layout from the source

This aligns with US Feist doctrine (facts are not copyrightable) and EU law
(factual data points are free to aggregate).

---

## Step 1: The Prompt

Copy and paste this into ChatGPT, Gemini, Claude, or any LLM with web access:

```
Visit [PASTE_URL_HERE] and extract ONLY the factual technical specifications
from the paraglider product page. Output as JSON matching this exact schema.

RULES:
- Read the technical specs table carefully. Each column is a size variant.
- "Certified Weight Range" or "In-Flight Weight Range" → split into ptv_min_kg and ptv_max_kg (e.g. "65-85" → min=65, max=85)
- "Glider Weight" → wing_weight_kg
- "Certification" or "EN/LTF" → certification class letter (A, B, C, D, or CCC)
- "Number of Cells" → cell_count (top-level, not per-size)
- Line materials → single string (e.g. "Edelrid 8000U / Liros PPSL")
- For target_use: EN-A = "school" or "leisure", EN-B = "leisure" or "xc", EN-C = "xc", EN-D = "competition", CCC = "competition"
- For category: "tandem" for tandem wings, "acro" for acro wings, "paraglider" for everything else
- DO NOT extract marketing descriptions, reviews, or prose text
- DO NOT include image URLs or links
- All numeric values must be plain numbers (no units)
- Return one size entry per column in the specs table

JSON SCHEMA:
{
  "model_name": "string — wing name without manufacturer",
  "manufacturer": "string — brand name",
  "category": "paraglider | tandem | miniwing | single_skin | acro | speedwing | paramotor",
  "target_use": "school | leisure | xc | competition | hike_and_fly | vol_biv | acro | tandem",
  "cell_count": "integer",
  "line_material": "string",
  "product_url": "string — the page URL",
  "sizes": [
    {
      "size_label": "string — e.g. 'XS', 'S', 'M', 'L'",
      "flat_area_m2": "number",
      "flat_span_m": "number",
      "flat_aspect_ratio": "number",
      "proj_area_m2": "number",
      "proj_span_m": "number",
      "proj_aspect_ratio": "number",
      "wing_weight_kg": "number",
      "ptv_min_kg": "number",
      "ptv_max_kg": "number",
      "certification": "string — A, B, C, D, or CCC"
    }
  ]
}
```

---

## Step 2: Validate the Output

After getting the JSON back, check:

1. **model_name** — Is it correct? No manufacturer prefix?
2. **sizes** — Does the count match what's on the page?
3. **ptv ranges** — Are min/max in the right order? Reasonable values (50–180 kg)?
4. **certification** — Is it a valid class (A, B, C, D, CCC)?
5. **cell_count** — Does it match what's on the page?
6. **No descriptions** — The output should be pure data, no marketing text.

---

## Step 3: Convert to CSV (Optional)

If you want to import the data directly into the OpenPG database, convert the JSON
to CSV format with these columns:

```
manufacturer_slug, name, year, category, target_use, is_current,
cell_count, line_material, riser_config, manufacturer_url, description,
size_label, flat_area_m2, flat_span_m, flat_aspect_ratio,
proj_area_m2, proj_span_m, proj_aspect_ratio,
wing_weight_kg, ptv_min_kg, ptv_max_kg,
speed_trim_kmh, speed_max_kmh, glide_ratio_best, min_sink_ms,
cert_standard, cert_classification, cert_test_lab, cert_test_date, cert_report_url
```

**One row per model × size combination.** Leave unknown fields empty.

Then import with:
```bash
python3 scripts/import_enrichment_csv.py <your_csv_file>.csv
```

---

## Platform-Specific Tips

### ChatGPT (Free tier)
- Use GPT-4o mini with web browsing enabled
- Paste the prompt, replacing `[PASTE_URL_HERE]` with the product URL
- Works well for 1–5 URLs per session

### Google Gemini (Free tier)
- Use Gemini 2.0 Flash — generous free tier (15 RPM)
- Can process multiple URLs if you list them
- Best free option for batch extraction

### Claude (with web access)
- Paste the URL content directly if Claude doesn't have web access
- Works well for parsing specs tables from copied page content

### Custom GPT / Gemini Gem
- You can create a persistent "OpenPG Data Extractor" with the prompt pre-loaded
- Add the JSON schema as the response format
- Share with contributors for consistent data quality

---

## Example Output

**Input:** `https://flyozone.com/paragliders/products/gliders/buzz-z6`

**Expected Output:**
```json
{
  "model_name": "Buzz Z6",
  "manufacturer": "Ozone",
  "category": "paraglider",
  "target_use": "leisure",
  "cell_count": 44,
  "line_material": "Edelrid 8000U / Liros PPSL",
  "product_url": "https://flyozone.com/paragliders/products/gliders/buzz-z6",
  "sizes": [
    {
      "size_label": "XXS",
      "flat_area_m2": 20.26,
      "flat_span_m": 10.04,
      "flat_aspect_ratio": 4.97,
      "proj_area_m2": 17.22,
      "proj_span_m": 7.96,
      "proj_aspect_ratio": 3.68,
      "wing_weight_kg": 3.78,
      "ptv_min_kg": 55,
      "ptv_max_kg": 70,
      "certification": "B"
    },
    {
      "size_label": "XS",
      "flat_area_m2": 22.01,
      "flat_span_m": 10.46,
      "flat_aspect_ratio": 4.97,
      "proj_area_m2": 18.71,
      "proj_span_m": 8.30,
      "proj_aspect_ratio": 3.68,
      "wing_weight_kg": 4.08,
      "ptv_min_kg": 65,
      "ptv_max_kg": 85,
      "certification": "B"
    }
  ]
}
```
