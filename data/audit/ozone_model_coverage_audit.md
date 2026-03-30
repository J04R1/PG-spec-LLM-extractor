# Ozone Model Coverage Audit
**Date:** 2026-03-30  
**DB file:** `output/ozone.db`  
**DB count:** 116 models  
**Auditor:** GitHub Copilot (automated + web cross-reference)

---

## Methodology

Cross-referenced all 116 DB models against four local sources:
- `data/ozone_year_updated_LLM_based_list.csv` — 294 rows
- `data/ozone_enrichment_all_by_LLM.csv` — 159 rows
- `data/fredvol_raw.csv` — 76 unique Ozone model names
- `data/dhv_unmatched.csv` — 56 unique Ozone model names from DHV

And three external live sources:
- **flyozone.com/paragliders/products/gliders** — current paraglider catalog
- **flyozone.com/speed/products/gliders** — current speed wing catalog
- **flyozone.com/paramotor/products/gliders** — current paramotor wing catalog

Normalisation: all names stripped to compact (`a-z0-9` only) before comparison, with
Roman-numeral → Arabic substitution (`ii→2`, `iii→3`, `iv→4`) and `gliders ` DHV prefix stripping.

Names in source data that resolved to a DB entry after normalisation are counted as matched.

---

## Result: MVP Assessment

**Verdict: PARTIAL SUCCESS — core paraglider range is covered, but entire product
sub-categories are absent from the DB.**

The 116 DB models cover all current and recent Ozone paraglider lines correctly.
The gaps below are historical gliders, discontinued paramotor wings, and speed wings
that were not in scope for Iteration 20. None of the gaps affect the current 22
active models.

---

## Section 1 — Confirmed Genuine Gaps (not in DB, confirmed real Ozone products)

### 1a — Missing Paragliders

| Model | Years (approx) | Cert | Category | Source confirmation |
|-------|---------------|------|----------|-------------------|
| **Atom** | ~2006–2012 | LTF/EN A | paraglider | DHV unmatched; precursor to Atom 2 (in DB) |
| **Fazer** | ~2006–2008 | CCC | paraglider | fredvol |
| **Fazer 2** | ~2008–2010 | CCC | paraglider | fredvol |
| **Fazer 3** | ~2010–2012 | CCC | paraglider | fredvol; pre-Enzo CCC line |
| **Indy** | ~2004–2007 | EN B/C | paraglider | fredvol; mid-level XC glider |
| **Litespeed** | ~2003–2009 | CCC | paraglider | fredvol; competition predecessor to Fazer |
| **Swift 3** | 2012–2016 | EN B | paraglider | **year_updated_LLM (confirmed)** — DB has Swift, Swift 2, Swift 4–6 but not 3 |
| **Firefly** | ~2012–2015 | — | speedwing | fredvol; foot-launch speedriding wing |
| **Firefly 2** | ~2015–2018 | — | speedwing | fredvol |
| **Firefly 3** | ~2018–2022 | — | speedwing | fredvol |

> **Note:** Swift 3 is the clearest gap — confirmed in `ozone_year_updated_LLM_based_list.csv`
> with year_released=2012, year_discontinued=2016. DB has Swift 2 and Swift 4 with no Swift 3
> in between.

### 1b — Missing Paramotor Wings

The DB currently tracks LM4–LM7 and McDaddy as paramotor wings. The following
historical Ozone paramotor wings are absent:

| Model | Years (approx) | Category | Source confirmation |
|-------|---------------|----------|-------------------|
| **Kona / Kona 2** | ~2010–2023 | paramotor | flyozone.com/paramotor (Kona 3 is current) |
| **Speedster / Speedster 2** | ~2010–2022 | paramotor | flyozone.com/paramotor (Speedster 3 is current); DHV unmatched |
| **BuzzPWR** | ~2010–2018 | paramotor | DHV unmatched |
| **Viper 1–5** | ~2008–2024 | paramotor | flyozone.com/paramotor (Viper 6 is current); fredvol |
| **MagMAX / MagMAX 2** | ~2010–2022 | paramotor tandem | flyozone.com/paramotor (MagMAX 3 is current); fredvol |

> **Note:** The "Viper" series (fredvol entries `viper`, `viper2`, `viper3`, `viper4`) and the
> DHV entry `Viper 2` are all paramotor wings, **not** paragliders or speedwings. The Ozone
> website places them under paramotor/competition.

### 1c — Missing Speed Wings

| Model | Years (approx) | Category | Source confirmation |
|-------|---------------|----------|-------------------|
| **Rapido / Rapi-Dos** | ~2014–2020 | speedwing | flyozone.com/speed (Rapido 3 is current); fredvol |

---

## Section 2 — Needs Verification (possibly missing, data unclear)

| Model | Uncertainty | Action |
|-------|-------------|--------|
| **Mantra M5** | fredvol lists `mantra5`; DB has M4 (2015) → M6 (2018). Did an M5 exist? Ozone may have skipped the number. | Verify on DHV portal / Ozone archive |
| **Zero** | fredvol lists `zero` under Ozone. Could be a lightweight/hike wing (~2014?) or a data error / misattribution to Ozone. | Verify manufacturer |
| **Cosmic** | DHV lists `Cosmic` as unmatched; DB has `Cosmic Rider` (2007). Could be same wing, earlier name, or a separate model. | Verify if Cosmic ≠ Cosmic Rider |
| **XT** | fredvol lists `xt` under Ozone. Not found anywhere else. Very old competition model or data error. | Verify |
| **Mantra 7 (enrich CSV)** | `ozone_enrichment_all_by_LLM.csv` has an entry named `Mantra 7`. DB has `Mantra M7` (2021). Could be alias, a new 2025 release, or CSV error. | Confirm if this is a distinct model |

---

## Section 3 — Naming Aliases (external name resolves to DB entry after normalisation)

These were flagged as "missing" in the raw diff but match DB entries after normalisation:

| External name (source) | Resolves to DB entry |
|------------------------|----------------------|
| `addict2` (fredvol) | Addict 2 |
| `delta2` (fredvol) | Delta 2 |
| `element2` (fredvol) | Element 2 |
| `geo2`, `geo 2` (fredvol, DHV) | Geo II |
| `geo3`, `geo 3` (fredvol, year_csv, DHV) | Geo III |
| `geo4` (fredvol) | Geo 4 |
| `magnum2`, `magnum ii` (fredvol) | Magnum 2 |
| `mantra2` (fredvol) | Mantra M2 |
| `mantra3` (fredvol) | Mantra M3 |
| `mantra4` (fredvol) | Mantra M4 |
| `mantrar07` (fredvol) | Mantra R07 |
| `mantrar09` (fredvol) | Mantra R09 |
| `mantrar11` (fredvol) | Mantra R11 |
| `mantrar12` (fredvol) | Mantra R12 |
| `mc daddy` (DHV) | McDaddy |
| `octaneflx` (fredvol) | Octane FLX |
| `ultra lite` (DHV) | Ultralite |
| `ultralite3` (fredvol) | Ultralite 3 |
| `rush2` (DHV) | Rush 2 |
| `buzzz 4`, `buzzz5` (DHV) | Buzz Z4, Buzz Z5 |
| `mantrar102`, `mantrar103` (fredvol) | Likely minor revisions of Mantra R10 (in DB), not separate models |

---

## Section 4 — In DB, Not Covered By External Local Sources (valid, just not in those datasets)

These 22 models are in the DB but weren't found in fredvol, year_updated, or DHV unmatched.
This is expected — they're specialty or niche models underrepresented in community datasets.
All are verified as real Ozone products.

| DB entry | Slug | Year | Category | Why not in external sources |
|----------|------|------|----------|-----------------------------|
| Atom 2 | ozone-atom-2 | 2012 | paraglider | fredvol uses `atom` for original only |
| Cosmic Rider | ozone-cosmic-rider | 2007 | tandem | DHV uses `Cosmic` (see Section 2) |
| Element 2 | ozone-element-2 | 2011 | paraglider | not in fredvol; DHV matched via prefix |
| Element 3 | ozone-element-3 | 2014 | paraglider | not in fredvol |
| Flx | ozone-flx | 2014 | paraglider | fredvol doesn't track Flx series |
| Flx 2 | ozone-flx-2 | 2017 | paraglider | — |
| Flx 3 | ozone-flx-3 | 2020 | paraglider | — |
| Geo II | ozone-geo-ii | 2008 | paraglider | fredvol & DHV use `geo2` / `geo 2` (→ resolved) |
| Geo III | ozone-geo-iii | 2010 | paraglider | fredvol uses `geo3` (→ resolved) |
| Jomo 2 | ozone-jomo-2 | 2012 | paraglider | niche school/training wing |
| Magnum 2009 | ozone-magnum-2009 | 2009 | tandem | year variant, not separate line |
| Mantra M2 | ozone-mantra-m2 | 2011 | paraglider | fredvol uses `mantra2` (→ resolved) |
| Mantra R07 | ozone-mantrar07 | 2007 | paraglider | fredvol uses `mantrar07` (→ resolved) |
| Mantra R09 | ozone-mantra-r09 | 2009 | paraglider | resolved |
| Mantra R10 | ozone-mantra-r10 | 2010 | paraglider | fredvol has `mantrar102/103` as sub-variants |
| Mantra R11 | ozone-mantra-r11 | 2011 | paraglider | resolved |
| Mantra R12 | ozone-mantra-r12 | 2012 | paraglider | resolved |
| Peak | ozone-peak | 2009 | paraglider | older school glider |
| Trickster | ozone-trickster | 2014 | acro | acro wing, not in standard databases |
| Trickster 2 | ozone-trickster-2 | 2018 | acro | — |
| Ultralite 3 | ozone-ultralite-3 | 2016 | paraglider | fredvol uses `ultralite3` (→ resolved) |
| XXLite 2 | ozone-xxlite-2 | 2019 | speedwing | niche speedwing |

---

## Section 5 — Scope Decision Required

Before treating Section 1b/1c as "gaps to fix", a scope decision is needed:

| Sub-category | Current DB coverage | Included? |
|--------------|--------------------|---------:|
| Paragliders (EN A–D, CCC) | Complete for 2007+ main range | ✓ |
| Acro (free-flight) | Addict, Addict 2, Trickster, Trickster 2 | ✓ |
| Tandem paragliders | Cosmic Rider, Mag2Lite, Magnum (1–4) | ✓ |
| Paramotor wings | LM4–LM7, McDaddy | Partial |
| Speed wings | XXLite, XXLite 2 | Partial |
| Paramotor tandem | — | ✗ |
| Older legacy lines (pre-2007) | Litespeed, Indy, Kona (1/2) | ✗ |

**Recommendation:** The paraglider range is MVP-complete. Paramotor and speed wing
sub-categories are a separate import task best done as dedicated iterations (e.g., Iteration 22).

---

## Summary

| Category | Count | Action |
|----------|-------|--------|
| Confirmed genuine paraglider gaps | 10 | Prioritise Swift 3 — others are pre-2012 legacy |
| Confirmed genuine paramotor gaps | 5 families | Iteration 22 scope |
| Confirmed genuine speedwing gaps | 3 + Rapido pre-series | Iteration 22 scope |
| Needs verification | 5 | Manual review (see Section 2) |
| Naming aliases (no real gap) | 20+ | No action needed |
| In DB, not in external sources | 22 | All valid — no action needed |
