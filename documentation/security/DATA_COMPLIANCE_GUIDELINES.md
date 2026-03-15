# Data Compliance Guidelines — PG Spec Extractor

This document defines the legal and ethical guardrails for data handling in
the paraglider spec extraction pipeline. It serves as a compliance baseline
for all contributors, AI agents, and automated processes.

---

## 1. Legal Framework

### 1.1 Copyright — Facts Are Not Copyrightable

**US (Feist doctrine):** Factual data (dimensions, weights, certifications) cannot
be copyrighted. Only creative expression (descriptions, marketing copy, photos)
is protected. The pipeline extracts **facts only**.

**EU (Directive 96/9/EC — Sui Generis Database Right):** Even uncopyrightable facts
can be protected when assembled into a database with "substantial investment."
This applies to manufacturer databases. Mitigation:

- Extract from **publicly available product pages** (not behind paywalls/logins)
- Never replicate the **structure or organization** of a source database
- Store data in our own independent schema
- Never extract a "substantial part" of any single database in one operation

### 1.2 GDPR — No Personal Data

The pipeline processes only **technical product specifications**. No personal data
(pilot names, user accounts, GPS tracks) is collected or stored. If personal data
is encountered during crawling, it must be discarded immediately.

### 1.3 Terms of Service

Before adding a new manufacturer, check their website ToS for:

- Explicit prohibition of automated scraping
- Data use restrictions
- API availability (prefer API over scraping when available)

Document ToS review results in the manufacturer YAML config file.

---

## 2. Scraper Ethics

### 2.1 robots.txt

The crawler **MUST** fetch and enforce `robots.txt` before crawling any domain.
If a path is disallowed, it must not be crawled — no exceptions.

### 2.2 User-Agent

Always use an honest, identifiable User-Agent string:
```
PG-Spec/1.0 (+)
```

Never use fake or browser-mimicking User-Agent strings for crawling.

### 2.3 Rate Limiting

- Configurable delay between requests (default: 1500ms)
- Random jitter added to avoid bot-like patterns (default: 0–1000ms)
- Exponential backoff on 429 (Too Many Requests) and 503 (Service Unavailable)
- Maximum 1 request per second to any single domain

### 2.4 Minimal Footprint

- Only crawl pages needed for spec extraction (product pages)
- Do not crawl: user forums, news, blogs, images, PDFs
- Cache crawled content to avoid redundant requests
- Support `--dry-run` mode for testing without actual HTTP requests

---

## 3. Data Classification

### 3.1 Extractable (Facts)

These fields contain factual, non-copyrightable technical data:

| Field | Example | Source |
|-------|---------|--------|
| Model name | Rush 6 | Product page |
| Certification | EN-B | Test lab report |
| Weight range | 85-105 kg | Spec table |
| Wing weight | 4.5 kg | Spec table |
| Flat area/span | 25.5 m² / 11.2 m | Spec table |
| Projected area/span | 21.3 m² / 8.9 m | Spec table |
| Aspect ratio | 5.4 | Spec table |
| Cell count | 48 | Spec table |
| Line material | Dyneema | Spec table |
| Speed (trim/max) | 38 / 52 km/h | Spec table |
| Glide ratio | 9.5 | Spec table |
| Min sink rate | 1.05 m/s | Spec table |

### 3.2 Not Extractable (Protected)

| Content | Reason | Action |
|---------|--------|--------|
| Marketing descriptions | Creative expression (copyright) | Do NOT extract |
| Product photos/images | Copyright | Link only — never download/host |
| PDF test reports | Copyright (document) | Link to URL — never host |
| Video content | Copyright | Ignore |
| User reviews/comments | Copyright + potential personal data | Ignore |
| Website design/layout | Copyright + trade dress | Do not replicate |

### 3.3 Description Field Guard

The `description` field in the database is reserved for brief factual notes only.
The pipeline applies this validation:

- Reject any `description` value longer than 200 characters
- Reject content that contains marketing language patterns
- If no factual description is available, leave the field NULL

---

## 4. Provenance Tracking

### 4.1 Every Record Gets a Source

Every entity inserted into the database (manufacturer, model, size variant,
certification) **MUST** have a corresponding `data_sources` entry recording:

| Field | Purpose |
|-------|---------|
| `entity_type` | Which table (`manufacturer`, `model`, `size_variant`, `certification`) |
| `entity_id` | Primary key in the target table |
| `source_name` | Origin identifier (e.g. `manufacturer_ozone`) |
| `source_url` | Direct URL to the source page |
| `contributed_by` | `pg-spec-extractor` (automated) or a username (manual) |
| `verified` | `false` until cross-checked against another source |

### 4.2 No Orphan Records

A database integrity check must confirm:
- Every `model` has at least one `data_sources` entry
- Every `size_variant` has at least one `data_sources` entry
- Every `certification` has at least one `data_sources` entry

Orphan check query:
```sql
SELECT 'model' AS type, m.id FROM models m
  LEFT JOIN data_sources ds ON ds.entity_type = 'model' AND ds.entity_id = m.id
  WHERE ds.id IS NULL
UNION ALL
SELECT 'size_variant', sv.id FROM size_variants sv
  LEFT JOIN data_sources ds ON ds.entity_type = 'size_variant' AND ds.entity_id = sv.id
  WHERE ds.id IS NULL;
```

---

## 5. Licensing

### 5.1 Code License

The pipeline source code is licensed under **MIT License**.

### 5.2 Data License

Extracted data is licensed under **Open Database License (ODbL 1.0)**:

- **Share:** Free to copy, distribute, and use the database
- **Create:** Free to produce derivative works
- **Adapt:** Free to modify and transform
- **Attribution:** Must credit OpenParaglider as the source
- **Share-Alike:** Derivative databases must use ODbL or a compatible license

### 5.3 Static Assets

The pipeline does **not** host any static assets (images, PDFs, logos).
All references to external content use outbound URLs only ("link, don't host").

---

## 6. Compliance Audit Checklist

Run this checklist before each release or major data import:

- [ ] All new manufacturer configs have ToS review documented
- [ ] robots.txt is fetched and enforced for all crawled domains
- [ ] User-Agent string is honest and identifiable
- [ ] Rate limiting is configured and active
- [ ] No marketing text or copyrighted descriptions in database
- [ ] No images, PDFs, or binary files downloaded/stored
- [ ] All records have `data_sources` provenance entries
- [ ] No orphan records (entities without provenance)
- [ ] `description` fields pass the 200-char / marketing guard
- [ ] Data license (ODbL) is included in any published dataset
- [ ] Dormant fields reviewed (see §7)
- [ ] Non-commercial positioning is clear in README and docs

---

## 7. Dormant Field Risk Assessment

Some schema fields are currently NULL but could become compliance risks if populated:

| Field | Risk | Policy |
|-------|------|--------|
| `WingModel.description` | Copyright if filled with manufacturer prose | Only original neutral summaries (≤200 chars). Never copy-paste. Leave NULL if no factual note is available. |
| `Manufacturer.logo_url` | IP if self-hosted | Must link to manufacturer-hosted asset. Never download/store locally. |
| `DataSource.contributed_by` | GDPR if real names/emails | Use system identifiers (e.g., `pg-spec-extractor`). If community contributions are added, verify consent for username storage. |

Any new `Text` or `String` field added in future migrations must be flagged for compliance review before population.

---

## 8. Non-Commercial Use

This project is a non-commercial internal research tool:

- No revenue-generating features (ads, premium tiers, paid API)
- Public communications (README, docs) clearly state non-commercial intent
- Non-commercial status strengthens (but does not guarantee) fair use and research exemption arguments
- If donations are accepted in the future, they must be framed as maintenance support, not commercial revenue

---

*Data Compliance Guidelines v1.1 — PG Spec Extractor | March 2026*
-- Expected: 0 rows