# Data Compliance Guidelines — PG Spec LLM Extractor

**Created:** March 2026 | **Applies to:** All pipeline code, configs, and output

---

## 1. Core Principle: Facts Only

This pipeline extracts and stores **only uncopyrightable factual data**.

### Safe to Extract (Facts)
- Technical specs: weight, area, span, aspect ratio, cell count, PTV range
- Certification records: EN/LTF class, test lab name, test date
- Brand and model names (identifiers)
- Physical dimensions, line materials, riser configurations
- Year of manufacture/release

### Never Extract (Copyrighted)
- Marketing descriptions, handling narratives, "feel" text
- Product images, 3D renderings, photos, logos
- Proprietary diagrams (e.g., SharkNose schematics)
- PDF test reports (store the URL reference only)
- Expert reviews or curated editorial content

**Legal basis:** Feist Publications v. Rural Telephone (US, 1991) — facts are not copyrightable. EU Directive 96/9/EC — individual facts are free, but substantial extraction from a protected database is restricted.

---

## 2. "Link, Don't Host"

Instead of downloading copyrighted content, store a reference URL:

- `manufacturer_url` → links to the product page (drives traffic to manufacturer)
- `test_report_url` → links to the official certification report (never host PDFs)
- `logo_url` → links to manufacturer-hosted logo (never store locally)

This avoids copyright infringement entirely and keeps data fresh.

---

## 3. Provenance — Every Record Must Be Traceable

Every record in `manufacturers`, `models`, `size_variants`, and `certifications` **must** have at least one corresponding entry in `data_sources`.

| Field | Purpose |
|---|---|
| `entity_type` | Which table: `manufacturer`, `model`, `size_variant`, `certification` |
| `entity_id` | Primary key in that table |
| `source_name` | Origin identifier: `manufacturer_website`, `dhv_portal`, `fredvol_github`, `community` |
| `source_url` | Direct URL to the original data source |
| `contributed_by` | Import script name or human contributor username |
| `verified` | Has this been cross-checked against another source? Default: false |

### Provenance Orphan Check

Run regularly to ensure compliance:

```sql
SELECT 'model' AS type, m.id FROM models m
  LEFT JOIN data_sources ds ON ds.entity_type = 'model' AND ds.entity_id = m.id
  WHERE ds.id IS NULL
UNION ALL
SELECT 'size_variant', sv.id FROM size_variants sv
  LEFT JOIN data_sources ds ON ds.entity_type = 'size_variant' AND ds.entity_id = sv.id
  WHERE ds.id IS NULL;
-- Expected: 0 rows