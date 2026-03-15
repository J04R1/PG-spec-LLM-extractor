# Iteration 16 — fredvol + DHV Unified Import Pipeline

**Date:** 2026-03-15
**Status:** In Progress
**Domain:** data

---

## Goal

Build adapters for two major external data sources — `fredvol_raw.csv` (6,481 size-variant rows,
1,804 unique models, 233 manufacturer names, 1982–2019) and `dhv_unmatched.csv` (3,192 certification
records, ~120 manufacturer names) — and integrate them into the existing seed import infrastructure
to populate per-manufacturer DBs and a consolidated `legacy.db`.

This iteration:
1. Curates the master manufacturer list (active vs. legacy classification)
2. Builds `src/fredvol_import.py` — transforms fredvol CSV → seed import format
3. Builds `src/dhv_import.py` — enriches existing DB records with DHV certifications
4. Expands `data/manufacturers_enrichment.csv` with newly discovered manufacturers
5. Adds CLI commands: `pipeline import-fredvol` and `pipeline import-dhv`
6. Updates YAML configs with fredvol/DHV import steps for the `rebuild` command

---

## Data Source Analysis

### fredvol_raw.csv — Complete Profile

**Source:** [fredvol/Paraglider_specs_studies](https://github.com/fredvol/Paraglider_specs_studies) (GliderBase + Para2000)
**License:** Public dataset, factual data (not copyrightable under Feist doctrine)

| Metric | Value |
|--------|-------|
| Total rows | 6,481 |
| Unique (manufacturer, model) pairs | 1,804 |
| Unique manufacturer names | 233 (including case variants) |
| Deduplicated manufacturers | ~200 (after merging case variants) |
| Year range | 1982–2019 |
| Sources | Para2000: 5,531 rows (85.3%), GliderBase: 950 rows (14.7%) |

#### Column Structure (20 columns)

```
(index), certif_AFNOR, certif_DHV, certif_EN, certif_MISC, certification,
flat_AR, flat_area, flat_span, manufacturer, name, proj_AR, proj_area,
proj_span, ptv_maxi, ptv_mini, size, source, weight, year
```

#### Field Completeness

| Field | Filled | % | Quality Notes |
|-------|--------|---|---------------|
| flat_area | 6,389 | 98.6% | Excellent — primary wing geometry |
| flat_span | 6,353 | 98.0% | Excellent |
| flat_AR | 6,376 | 98.4% | Excellent — flat aspect ratio |
| ptv_maxi | 6,224 | 96.0% | Excellent — pilot weight range |
| ptv_mini | 6,223 | 96.0% | Excellent |
| year | 6,427 | 99.2% | Excellent — only 54 missing |
| weight | 5,614 | 86.6% | Good — wing weight |
| proj_area | 4,828 | 74.5% | Moderate — projected geometry |
| proj_span | 4,809 | 74.2% | Moderate |
| proj_AR | 4,832 | 74.6% | Moderate |
| certif_EN | 1,686 | 26.0% | Sparse — newer models only |
| certif_DHV | 1,178 | 18.2% | Sparse — mainly German-tested |
| certif_AFNOR | 664 | 10.2% | Sparse — mainly French-tested |
| certif_MISC | 309 | 4.8% | Very sparse |

**Key insight:** fredvol is exceptional for wing geometry (flat area/span/AR at 98%+) and weight
ranges (96%), but weak on certifications. The DHV data perfectly complements this gap.

#### Certification Values

| Value | Count | Mapping |
|-------|-------|---------|
| (empty) | 2,885 | Skip — no cert info |
| B | 881 | EN B |
| DHV_1 | 561 | LTF 1 |
| DHV_2 | 432 | LTF 2 |
| C | 339 | EN C |
| A | 291 | EN A |
| AFNOR_Standard | 279 | AFNOR Standard |
| Load | 209 | Load test — tandem/cargo flag |
| D | 175 | EN D |
| AFNOR_Perf | 153 | AFNOR Performance |
| DHV_3 | 77 | LTF 3 |
| AFNOR_Compet | 60 | AFNOR Competition |
| DGAC | 58 | French motor authority |
| AFNOR_Biplace | 33 | AFNOR Tandem |
| CCC | 22 | Competition Class |
| pending | 15 | Skip — not final |
| DUVL | 10 | German motor authority |
| not_cert | 1 | Skip — explicitly uncertified |

#### Year Distribution

| Period | Rows | % | Notes |
|--------|------|---|-------|
| 1982–1989 | 337 | 5.2% | Early paragliding era |
| 1990–1999 | 1,639 | 25.3% | Growth era |
| 2000–2009 | 2,134 | 32.9% | Peak coverage |
| 2010–2019 | 2,317 | 35.7% | Modern era (cuts off ~2017–18) |
| (empty) | 54 | 0.8% | |

#### Source Distribution

| Source | Rows | % | Quality |
|--------|------|---|---------|
| Para2000 | 5,531 | 85.3% | Historical archive, lower projected geometry coverage |
| GliderBase | 950 | 14.7% | Modern data, better completeness |

#### Top Manufacturers by Row Count (merged case variants)

| Slug | Rows | Models | Era | Notes |
|------|------|--------|-----|-------|
| ozone | 335 | 75 | 2003–2019 | Active — already configured |
| macpara | 243 | 49 | 1993–2017 | Active |
| dudek | 232 | 48 | 1993–2018 | Active |
| niviuk | 214 | 51 | 2005–2019 | Active |
| gin | 204 | 44 | 1995–2018 | Active |
| nova | 190 | 44 | 1990–2018 | Active — already configured |
| apco | 173 | 38 | 1988–2017 | Active |
| uturn | 171 | 39 | 1996–2018 | Active (U-Turn + uturn variants) |
| up | 170 | 40 | 1989–2018 | Active |
| aircross | 137 | 26 | 1991–2015 | Possibly defunct |
| itv | 132 | 37 | 1989–2010 | Legacy |
| windtech | 132 | 31 | 1991–2016 | Legacy (NORTEC S.L.) |
| airwave | 129 | 37 | 1986–2012 | Legacy — defunct ~2012 |
| skywalk | 127 | 33 | 2004–2018 | Active |
| gradient | 127 | 29 | 1994–2017 | Active |
| trekking | 116 | 32 | 1988–2008 | Legacy |
| sun | 108 | 20 | 1989–2003 | Legacy |
| skycountry | 108 | 21 | 1990–2006 | Legacy |
| swing | 107 | 29 | 1988–2018 | Active |
| paratech | 104 | 33 | 1987–2010 | Legacy |
| advance | 103 | 33 | 2015–2019 | Active — already configured |
| firebird | 99 | 27 | 1989–2010 | Legacy — defunct |
| axis | 88 | 21 | 1996–2018 | Active |
| airdesign | 86 | 20 | 2013–2019 | Active |
| sol | 86 | 28 | 1997–2017 | Active |
| prodesign | 84 | 26 | 1994–2010 | Legacy |
| icaro | 83 | 25 | 1993–2017 | Active (Icaro 2000) |
| edel | 77 | — | 1987–2004 | Legacy — defunct |
| sky | 77 | 20 | 1993–2017 | Active |
| asa | 77 | — | 1987–2001 | Legacy |
| paraavis | 71 | — | 1988–2008 | Legacy |
| flightdesign | 63 | 20 | 1989–2002 | Legacy — company pivoted to ultralights |
| ailesdek | 58 | — | 1988–1998 | Legacy |
| nervures | 54 | — | 1991–2014 | Possibly defunct |
| airsport | 52 | — | 1989–2012 | Legacy |
| freex | 47 | — | 1996–2005 | Legacy |
| bgd | 44+17 | — | 2011–2019 | Active (Bruce Goldsmith Design) |
| wingsofchange | 44 | — | 1986–1998 | Legacy |
| independence | 44 | — | 1993–2017 | Active |
| kimfly | 44 | — | 1989–2006 | Legacy |
| customsail | 38 | — | 1987–1998 | Legacy |
| paramania | 38 | — | 2002–2014 | Paramotor specialist |
| tripleseven | 36 | — | 2013–2017 | Active (Triple Seven) |
| phi | 35 | — | 2019+ | Active — very new brand |
| paradelta | 35 | — | 1986–1999 | Legacy |
| aeros | 35 | — | 1992–2006 | Legacy |
| adventure | 32 | — | 1987–1996 | Legacy |
| pegas | 32 | — | 1989–2008 | Legacy |
| comet | 31 | — | 1988–1997 | Legacy |
| condor | 31 | — | 1989–2003 | Legacy |
| skyline | 31 | — | 1989–1997 | Legacy |
| adg | 31 | — | — | Legacy |
| inferno | 30 | — | — | Legacy |
| perche | 30 | — | — | Legacy |
| flyingplanet | 29 | — | — | Legacy |
| airea | 27 | — | — | Legacy |
| e2ra | 27 | — | — | Legacy |
| jojowing | 27 | — | — | Legacy |
| artwing | 26 | — | — | Legacy |
| mcc | 26 | — | — | Legacy |
| papillonparagliders | 25 | — | — | Legacy |
| flow | 25 | — | 2016–2019 | Active (Australia) |
| airgproducts | 24 | — | — | Legacy |
| xix | 25 | — | — | Legacy |
| usvoiles | 23 | — | — | Legacy |
| aerodyne | 23 | — | — | Legacy |
| skif | 21 | — | — | Legacy |
| angel | 20 | — | — | Legacy |
| element | 20 | — | — | Legacy |

*(plus ~80 more manufacturers with <20 rows each)*

#### Case Variants Requiring Merge

| Slug | Variants in CSV | Combined Rows |
|------|----------------|---------------|
| advance | "Advance", "advance" | 103 |
| aircross | "Aircross", "aircross" | 137 |
| airdesign | "AirDesign", "airdesign" | 86 |
| axis | "Axis", "axis" | 88 |
| dudek | "Dudek", "dudek" | 232 |
| flow | "Flow", "flow" | 25 |
| gin | "Gin", "gin" | 204 |
| icaro | "Icaro", "icaro" | 83 |
| niviuk | "Niviuk", "niviuk" | 214 |
| nova | "Nova", "nova" | 190 |
| ozone | "Ozone", "ozone" | 335 |
| skywalk | "Skywalk", "skywalk" | 127 |
| swing | "Swing", "swing" | 107 |
| tripleseven | "Triple Seven", "tripleseven" | 36 |
| up | "Up", "up" | 170 |
| uturn | "U-Turn", "uturn" | 171 |

### dhv_unmatched.csv — Complete Profile

**Source:** [DHV Geräteportal](https://www.dhv.de/db1/geraete/) (German Hang Glider and Paraglider Association)
**License:** Government-adjacent certification data, public factual records

| Metric | Value |
|--------|-------|
| Total rows | 3,192 |
| Unique manufacturer entities | ~120 (many are full legal names) |
| Dedup'd manufacturer slugs | ~50 |
| Columns | 9: dhv_url, manufacturer, model, size, equipment_class, test_centre, test_date, report_url, match_failure_reason |

#### Top Manufacturers by DHV Row Count

| Slug | DHV Rows | Missing Models | Latest Test | Notes |
|------|----------|---------------|-------------|-------|
| nova | 202 | 74 | 2025-07-16 | Includes "NOVA Vertriebsgesellschaft m.b.H." (30 rows) |
| up | 194 | 60 | 2026-03-06 | Includes "UP International GmbH" (10 rows) |
| gin | 194 | 55 | 2025-12-15 | Includes "GIN Gliders Inc." (8 rows) |
| swing | 177 | 35 | 2022-07-15 | Includes "Swing Flugsportgeräte GmbH" (9 rows) |
| phi | 176 | 57 | 2026-03-02 | New brand, all data is recent |
| ozone | 173 | 54 | 2018-10-25 | Includes "OZONE Gliders Ltd." (2 rows) |
| skywalk | 157 | 41 | 2026-01-09 | Includes "Skywalk GmbH & Co. KG" (10 rows) |
| macpara | 116 | 31 | 2023-02-13 | Includes "MAC Para Technology" (10 rows) |
| advance | 105 | 39 | 2015-09-25 | |
| prodesign | 93 | — | — | "PRO-DESIGN, Hofbauer GmbH" (unmatched mfr) |
| airwave | 77 | 31 | 2012-07-31 | Includes "Airwave Villinger" (6), "Airwave Paragliders" (1) |
| u-turn | 72 | 23 | 2022-09-21 | Includes "U-Turn GmbH" (1), "Turn2Fly GmbH" (16) |
| gradient | 70 | 23 | 2019-07-31 | |
| icaro | 66 | 21 | 2023-07-28 | Includes "ICARO paragliders - Fly & more GmbH" (5) |
| niviuk | 65 | 30 | 2013-12-23 | |
| firebird | 64 | 32 | 2010-06-21 | Includes "Firebird International AG" (3) |
| sol | 63 | 17 | 2013-12-30 | Includes "Sol Sports Ind." (3) |
| sky | 59 | 17 | 2020-11-06 | |
| wingsofchange | 42 | — | — | DHV: "wings of change" |
| edel | 41 | 16 | 2004-09-13 | Includes "Edel Korea, HISPO" (4) |
| freex | 40 | 13 | 2005-07-05 | Includes "FreeX GmbH" (3), "freeX air sports" (1) |
| flightdesign | 38 | 24 | 2002-05-29 | Includes "Flight Design GmbH" (4) |
| comet | 30 | 18 | 1996-09-26 | Includes "Comet Sportartikel GmbH" (1) |
| dudek | 23 | 9 | 2013-12-27 | |
| paratech | 23 | 7 | 2009-10-12 | Includes "PARATECH AG" (1) |
| mcc | 17 | 7 | 2013-12-11 | |
| axis | 17 | 7 | 2013-11-21 | |
| apco | 15 | 5 | 2002-02-06 | Includes "Apco Aviation Ltd." (1) |

**DHV-only manufacturers (not in fredvol):**

| Manufacturer (DHV legal name) | Rows | Notes |
|-------------------------------|------|-------|
| Fly market (SynAIRgy/Skyman) | 88+39 | Modern brand under different legal entities |
| Ailes de K | 36 | Kite/paraglider manufacturer |
| ZOOM Vertriebs GmbH | 26 | Distributes various brands |
| Skydive Paramount | 23 | |
| AeroTEST GmbH | 18 | Test center, not manufacturer |
| KRILO d.o.o. | 14 | Slovenian manufacturer |
| Turn2Fly GmbH | 16 | U-Turn successor entity |
| escape | 14 | |

---

## Manufacturer Curation — Tier Classification

### Tier Criteria

| Tier | Definition | DB Strategy | Data Strategy |
|------|-----------|-------------|---------------|
| **T1 — Active Major** | Active website, current models, ≥30 models across sources | Individual `{slug}.db` | Pipeline crawl + fredvol + DHV |
| **T2 — Active Minor** | Active website, <30 models or niche market | Individual `{slug}.db` | fredvol + DHV import, selective crawl |
| **T3 — Legacy** | No active website, or no longer manufacturing paragliders | Grouped into `legacy.db` | fredvol + DHV import only |

### T1 — Active Major (individual DB + pipeline crawl)

These manufacturers have active websites, current model lines, and significant
data volume across sources. Each gets its own `{slug}.db` and a YAML config for
pipeline crawling.

| # | Slug | Country | Website | fredvol Rows | fredvol Models | DHV Rows | Config Exists | Notes |
|---|------|---------|---------|-------------|---------------|----------|--------------|-------|
| 1 | ozone | GB | flyozone.com | 335 | 75 | 175 | ✓ | Pipeline operational |
| 2 | advance | CH | advance.swiss | 103 | 33 | 105 | ✓ | Pipeline operational |
| 3 | nova | AT | nova.eu | 190 | 44 | 234 | ✓ | Config exists |
| 4 | gin | KR | gingliders.com | 204 | 44 | 202 | — | Needs config |
| 5 | niviuk | ES | niviuk.com | 214 | 51 | 65 | — | Needs config |
| 6 | skywalk | DE | skywalk.info | 127 | 33 | 167 | — | Needs config |
| 7 | swing | DE | swing.de | 107 | 29 | 186 | — | Needs config |
| 8 | dudek | PL | dudek.eu | 232 | 48 | 23 | — | Needs config |
| 9 | macpara | SK | macpara.com | 243 | 49 | 126 | — | Needs config |
| 10 | up | — | up-paragliders.com | 170 | 40 | 204 | — | Needs config |
| 11 | gradient | CZ | gradient.cx | 127 | 29 | 70 | — | Needs config |
| 12 | phi | — | phi-air.com | 35 | — | 176 | — | New brand (2019+), mostly DHV |
| 13 | u-turn | DE | u-turn.de | 171 | 39 | 89 | — | Needs config |

**Total estimated coverage:** ~2,258 fredvol rows + ~1,822 DHV rows = 520+ unique models

### T2 — Active Minor (individual DB, mostly data import)

Smaller active manufacturers. Get their own DB but won't need full pipeline
crawl configs immediately.

| # | Slug | Country | Website | fredvol Rows | DHV Rows | Notes |
|---|------|---------|---------|-------------|----------|-------|
| 14 | bgd | CH | bgd.systems | 61 | 8 | Bruce Goldsmith Design |
| 15 | triple-seven | CZ | 777.cz | 36 | 7 | |
| 16 | airdesign | AT | air-design.at | 86 | 0 | |
| 17 | sky | CZ | sky-cz.com | 77 | 59 | |
| 18 | sol | BR | solparagliders.com.br | 86 | 66 | |
| 19 | icaro | IT | icaro2000.com | 83 | 71 | Verify still active |
| 20 | apco | IL | apcoaviation.com | 173 | 16 | High fredvol, low DHV |
| 21 | axis | SK | axis-paragliders.com | 88 | 17 | |
| 22 | independence | DE | independence.aero | 44 | 0 | |
| 23 | supair | FR | supair.com | 10 | 2 | Primarily harness maker |
| 24 | flow | AU | flyflow.com.au | 25 | 0 | Australian manufacturer |
| 25 | nervures | FR | nervures.com | 54 | 0 | Verify still active |
| 26 | aircross | FR | aircross.com | 137 | 30 | Verify still active |

**Total estimated coverage:** ~960 fredvol rows + ~276 DHV rows

### T3 — Legacy (all grouped into `legacy.db`)

Defunct manufacturers, or brands that no longer produce paragliders. No website
to crawl. fredvol + DHV provides the only data we'll ever get.

| # | Slug | fredvol Rows | DHV Rows | Active Years | Notes |
|---|------|-------------|----------|-------------|-------|
| 27 | itv | 132 | 33 | 1989–2010 | French manufacturer |
| 28 | windtech | 132 | 40 | 1991–2016 | NORTEC S.L. (Spain) |
| 29 | airwave | 129 | 84 | 1986–2012 | UK — defunct |
| 30 | trekking | 116 | 4 | 1988–2008 | Trekking-parapentes |
| 31 | sun | 108 | 0 | 1989–2003 | |
| 32 | skycountry | 108 | 0 | 1990–2006 | |
| 33 | paratech | 104 | 24 | 1987–2010 | Swiss |
| 34 | firebird | 99 | 67 | 1989–2010 | |
| 35 | prodesign | 84 | 93 | 1994–2010 | PRO-DESIGN Hofbauer GmbH |
| 36 | edel | 77 | 45 | 1987–2004 | |
| 37 | asa | 77 | 0 | 1987–2001 | |
| 38 | paraavis | 71 | 0 | 1988–2008 | |
| 39 | flightdesign | 63 | 42 | 1989–2002 | Pivoted to ultralights |
| 40 | ailesdek | 58 | 36 | 1988–1998 | "Ailes de K" in DHV |
| 41 | airsport | 52 | 10 | 1989–2012 | |
| 42 | freex | 47 | 44 | 1996–2005 | |
| 43 | wingsofchange | 44 | 42 | 1986–1998 | |
| 44 | kimfly | 44 | 0 | 1989–2006 | |
| 45 | customsail | 38 | 1 | 1987–1998 | |
| 46 | paramania | 38 | 0 | 2002–2014 | Paramotor specialist |
| 47 | paradelta | 35 | 4 | 1986–1999 | |
| 48 | aeros | 35 | 9 | 1992–2006 | |
| 49 | adventure | 32 | 0 | 1987–1996 | |
| 50 | pegas | 32 | 0 | 1989–2008 | |
| 51 | comet | 31 | 31 | 1988–1997 | |
| 52 | condor | 31 | 7 | 1989–2003 | |
| 53 | skyline | 31 | 12 | 1989–1997 | |
| 54 | adg | 31 | 0 | — | |
| 55 | inferno | 30 | 0 | — | |
| 56 | perche | 30 | 0 | — | |
| 57 | flyingplanet | 29 | 5 | — | |
| + | *(~130 more)* | ~1,200 | ~300 | — | Various niche/historical brands |

**Total estimated coverage:** ~3,263 fredvol rows + ~849 DHV rows

---

## Column Mapping: fredvol → Seed Import Format

### Direct Mappings

| fredvol Column | Seed Import Column | Transform |
|---|---|---|
| `manufacturer` | `manufacturer_slug` | Normalize: lowercase, strip, merge variants, map aliases |
| `name` | `name` | Direct — preserve original model name |
| `year` | `year` | Direct (int or empty) |
| `flat_area` | `flat_area_m2` | Direct (float) |
| `flat_span` | `flat_span_m` | Direct (float) |
| `flat_AR` | `flat_aspect_ratio` | Direct (float) |
| `proj_area` | `proj_area_m2` | Direct (float) |
| `proj_span` | `proj_span_m` | Direct (float) |
| `proj_AR` | `proj_aspect_ratio` | Direct (float) |
| `weight` | `wing_weight_kg` | Direct (float) |
| `ptv_mini` | `ptv_min_kg` | Direct (float) |
| `ptv_maxi` | `ptv_max_kg` | Direct (float) |
| `size` | `size_label` | Via `normalize_size_label()` |

### Certification Mapping

The fredvol CSV has 5 certification columns. The mapping logic:

1. Check `certif_EN` → if non-empty: `cert_standard` = "EN", `cert_classification` = value
2. Else check `certif_DHV` → if non-empty: `cert_standard` = "LTF", `cert_classification` = value (map 1→"1", 2→"2", etc.)
3. Else check `certif_AFNOR` → if non-empty: `cert_standard` = "AFNOR", `cert_classification` = value
4. Else check `certif_MISC` → if non-empty: `cert_standard` = "other", `cert_classification` = value
5. Fallback: use `certification` column with `normalize_certification()` function

| fredvol `certification` | Mapping |
|------------------------|---------|
| `A`, `B`, `C`, `D` | `cert_standard="EN"`, `cert_classification=` letter |
| `DHV_1`, `DHV_2`, `DHV_3` | `cert_standard="LTF"`, `cert_classification=` number |
| `AFNOR_Standard` | `cert_standard="AFNOR"`, `cert_classification="Standard"` |
| `AFNOR_Perf` | `cert_standard="AFNOR"`, `cert_classification="Performance"` |
| `AFNOR_Compet` | `cert_standard="AFNOR"`, `cert_classification="Competition"` |
| `AFNOR_Biplace` | `cert_standard="AFNOR"`, `cert_classification="Biplace"` |
| `DGAC` | `cert_standard="DGAC"`, `cert_classification=""` |
| `CCC` | `cert_standard="CCC"`, `cert_classification=""` |
| `Load` | Category hint ← tandem/cargo. `cert_standard="other"`, `cert_classification="Load"` |
| `DUVL` | Category hint ← paramotor. Skip cert. |
| `pending`, `not_cert`, `(empty)` | No certification record |

### Derived/Inferred Fields

| Seed Import Column | Source | Rule |
|---|---|---|
| `category` | `name`, `certification` | "Motor" in name → `paramotor`; "Biplace"/"tandem"/"bi" in name or `Load` cert → `tandem`; else `paraglider` |
| `is_current` | — | Always `false` (historical data) |
| `target_use` | — | Not inferable from fredvol data (left empty) |
| `cell_count` | — | Not available |
| `riser_config` | — | Not available |
| `manufacturer_url` | — | Not available |
| `speed_trim_kmh` | — | Not available |
| `speed_max_kmh` | — | Not available |
| `glide_ratio_best` | — | Not available |
| `min_sink_ms` | — | Not available |

### Manufacturer Name Normalization Map

Built from the case variant analysis. The fredvol adapter needs a lookup table:

```python
FREDVOL_MANUFACTURER_ALIASES = {
    # Case variants (merge into canonical lowercase slug)
    "Advance": "advance",
    "Aircross": "aircross",
    "AirDesign": "airdesign",
    "Axis": "axis",
    "Bruce Goldsmith Design": "bgd",
    "Dudek": "dudek",
    "Flow": "flow",
    "Gin": "gin",
    "Icaro": "icaro",
    "Niviuk": "niviuk",
    "Nova": "nova",
    "Ozone": "ozone",
    "Papillon Paragliders": "papillon-paragliders",
    "Phi": "phi",
    "Skywalk": "skywalk",
    "Swing": "swing",
    "Triple Seven": "triple-seven",
    "U-Turn": "u-turn",
    "Up": "up",
    # Already lowercase — redundant but explicit
    "uturn": "u-turn",
    "tripleseven": "triple-seven",
    "bgd": "bgd",
    # Additional brand-specific mappings
    "paraavis": "paravis",
    ...
}
```

---

## DHV Integration Strategy

### Enrichment Model (not standalone import)

The DHV adapter operates differently from fredvol:
- fredvol creates models + sizes with geometry data
- DHV **enriches existing** records by adding certification data

### Import Order

1. **fredvol first** — creates models with `WingModel`, `SizeVariant` (geometry + weight)
2. **DHV second** — matches against existing models, adds `Certification` records
3. **Pipeline crawl third** (optional) — fills remaining gaps for current models

### DHV Matching Strategy

1. Normalize manufacturer name → slug (e.g., "OZONE Gliders Ltd." → "ozone")
2. Normalize model name (strip manufacturer prefix, fix spacing)
3. Look up model in DB by slug
4. If model exists: look up or create size variant, insert certification
5. If model doesn't exist: create minimal model + size + certification (DHV-only record)

### DHV Name Normalization Examples

| DHV `manufacturer` | Slug |
|---|---|
| OZONE Gliders Ltd. | ozone |
| ADVANCE Thun AG | advance |
| NOVA Vertriebsgesellschaft m.b.H. | nova |
| GIN Gliders Inc. | gin |
| UP International GmbH | up |
| Swing Flugsportgeräte GmbH | swing |
| Skywalk GmbH & Co. KG | skywalk |
| MAC Para Technology | macpara |
| PRO-DESIGN, Hofbauer GmbH | prodesign |
| Fly market Flugsport-Zubehör GmbH | skyman |
| SynAIRgy GmbH | skyman |
| NORTEC, S.L. - WINDTECH | windtech |
| Turn2Fly GmbH | u-turn |
| Kontest GmbH - AirCross | aircross |
| Sol Sports Ind. E Comérico LTDA | sol |
| Firebird International AG | firebird |
| ICARO paragliders - Fly & more GmbH | icaro |
| FreeX GmbH / freeX air sports GmbH | freex |
| Comet Sportartikel GmbH & Co KG | comet |
| Flight Design GmbH | flightdesign |
| Airwave Villinger Ges.m.b.H. / Airwave Paragliders | airwave |
| Edel Korea, HISPO Co.Ltd | edel |
| PARATECH AG | paratech |
| Apco Aviation Ltd. | apco |
| ITV Parapentes | itv |

---

## Implementation Plan

### New Files

| File | Purpose |
|------|---------|
| `src/fredvol_import.py` | fredvol CSV adapter — transforms + imports via existing seed infrastructure |
| `src/dhv_import.py` | DHV CSV adapter — certification enrichment for existing DB records |

### Modified Files

| File | Change |
|------|--------|
| `src/pipeline.py` | Add `import-fredvol` and `import-dhv` CLI commands |
| `data/manufacturers_enrichment.csv` | Expand from 24 → ~50 manufacturer slug mappings |
| `documentation/README.md` | Add this iteration entry |

### CLI Commands

#### `pipeline import-fredvol`

```
python -m src.pipeline import-fredvol \
    --csv data/fredvol_raw.csv \
    --db output/ozone.db \
    --manufacturer ozone
```

Options:
- `--csv` — Path to fredvol CSV (default: `data/fredvol_raw.csv`)
- `--db` — Output database path (required)
- `--manufacturer` — Filter to one manufacturer slug (optional; if omitted, imports all)
- `--legacy` — Import all T3 legacy manufacturers into the specified DB

#### `pipeline import-dhv`

```
python -m src.pipeline import-dhv \
    --csv data/dhv_unmatched.csv \
    --db output/ozone.db \
    --manufacturer ozone
```

Options:
- `--csv` — Path to DHV CSV (default: `data/dhv_unmatched.csv`)
- `--db` — Target database (must exist, enrichment only)
- `--manufacturer` — Filter to one manufacturer slug (optional)

### Provenance Tracking

Every imported record gets a `provenance` entry:

**fredvol records:**
- `source_name`: `"fredvol/Paraglider_specs_studies"`
- `source_url`: `"https://github.com/fredvol/Paraglider_specs_studies"`
- `extraction_method`: `"fredvol_csv_import"`
- `notes`: `"Imported from fredvol_raw.csv (source: {GliderBase|Para2000})"`

**DHV records:**
- `source_name`: `"dhv_geraeteportal"`
- `source_url`: the `dhv_url` column value
- `extraction_method`: `"dhv_cert_import"`
- `notes`: `"DHV certification enrichment"`

---

## Expected Outcomes

### Per-Manufacturer DB Content (after fredvol + DHV import)

| Manufacturer | fredvol Models | DHV Certs | Est. Total Models | Benchmark Completeness |
|---|---|---|---|---|
| ozone | 75 | 54 | ~120+ | ~55% (geometry yes, no cell_count/riser/performance) |
| advance | 33 | 39 | ~60+ | ~55% |
| nova | 44 | 74 | ~90+ | ~55% |
| gin | 44 | 55 | ~80+ | ~55% |
| niviuk | 51 | 30 | ~70+ | ~55% |
| dudek | 48 | 9 | ~50+ | ~55% |
| macpara | 49 | 31 | ~70+ | ~55% |
| swing | 29 | 35 | ~50+ | ~55% |
| up | 40 | 60 | ~80+ | ~55% |
| skywalk | 33 | 41 | ~60+ | ~55% |
| gradient | 29 | 23 | ~40+ | ~55% |
| u-turn | 39 | 23 | ~50+ | ~55% |
| phi | 0 | 57 | ~57 | ~15% (DHV-only: cert + classification only) |
| legacy.db | ~700+ | ~300+ | ~800+ | ~45% |

**~55% completeness estimate rationale:** fredvol provides flat_area, flat_span, flat_AR (3 fields),
proj_area, proj_span, proj_AR (3 fields, 74% complete), weight (86%), ptv_min/max (96%), year (99%).
That's 8–11 of ~20 spec fields filled. Missing: cell_count, riser_config, line_material,
manufacturer_url, speed_trim/max, glide_ratio, min_sink, line_length.

### legacy.db Profile

Expected:
- ~800+ unique models from ~130+ defunct manufacturers
- Strongest coverage: 1988–2010 era
- Primary value: historical archive of wing geometry for brands no longer operating
- Secondary value: enables historical analysis of wing design evolution (AR trends, etc.)

---

## Verification Plan

1. **Unit tests** — `tests/test_fredvol_import.py`:
   - Test manufacturer slug normalization (16 case variant pairs)
   - Test certification mapping (all 18 certification values)
   - Test column mapping for 3 representative rows (Advance Alpha 6, Ozone Mantra, legacy brand)
   - Test category inference ("Motor" → paramotor, "Bi" → tandem)
   - Test empty field handling (Para2000 rows with missing geometry)

2. **Unit tests** — `tests/test_dhv_import.py`:
   - Test DHV manufacturer name → slug normalization (25 mappings)
   - Test model name normalization ("BuzzZ5" → "Buzz Z5")
   - Test certification insertion for existing model+size
   - Test new model creation for DHV-only records

3. **Integration test** — Import fredvol + DHV for GIN:
   - Import 204 fredvol rows (44 models) → verify DB has 44 models with geometry
   - Import 202 DHV rows → verify certifications added to matching models
   - Verify no duplicate models/sizes

4. **Coverage report** — After full import, generate:
   - Models per manufacturer
   - Fields filled per model (completeness %)
   - Certification coverage (% of models with at least one cert)

---

## Decisions

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | Single `legacy.db` for all T3 manufacturers | User confirmed. Avoids 100+ tiny DBs. |
| D2 | Both sources equally important | User confirmed. fredvol for specs, DHV for certifications. |
| D3 | fredvol imported first, DHV second | fredvol creates models with geometry; DHV enriches with certs. Upsert semantics prevent conflicts. |
| D4 | All fredvol records marked `is_current=false` | Historical data (1982–2019), cannot determine if model is still in production. |
| D5 | `category` inferred from model name | "Motor" → paramotor, tandem keywords → tandem, else paraglider. |
| D6 | Para2000 rows imported despite lower quality | 85% of fredvol data. Missing projected geometry still has flat geometry and weight. |
| D7 | DHV-only models (no fredvol match) create minimal records | Better to have cert-only records than to lose certification data. |
| D8 | Reuse existing `import_enrichment_csv()` for fredvol | Avoid duplicating upsert logic. fredvol adapter transforms to seed CSV format, then calls existing import. |
| D9 | PHI handled as T1 despite zero fredvol rows | 57 DHV models, very active (tests through 2026-03). Pipeline crawl will be primary source. |
| D10 | Manufacturer slug expansion lives in CSV, not code | `data/manufacturers_enrichment.csv` is the source of truth. Code reads it at import time. |

---

## Files

| File | Purpose |
|------|---------|
| `src/fredvol_import.py` | fredvol CSV adapter (new) |
| `src/dhv_import.py` | DHV certification enrichment adapter (new) |
| `src/pipeline.py` | CLI commands for new adapters (modified) |
| `data/manufacturers_enrichment.csv` | Expanded slug mapping (modified) |
| `tests/test_fredvol_import.py` | fredvol adapter tests (new) |
| `tests/test_dhv_import.py` | DHV adapter tests (new) |
| `documentation/data/ITERATION_16_FREDVOL_DHV_UNIFIED_IMPORT.md` | This document |
| `documentation/README.md` | Updated iteration index |
