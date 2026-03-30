"""Import staged previous-glider JSON into ozone.db.

Reads output/ozone_previous_staged.json (produced by crawl_previous_to_json.py,
reviewed via audit_staged_json.py) and upserts into ozone.db.

Only imports records with _status=ok that pass audit (no critical issues).
Skips parse failures and models with critical issues unless --force is used.

Usage:
    python3 scripts/import_staged_to_db.py --dry-run   # preview only
    python3 scripts/import_staged_to_db.py             # commit to DB
    python3 scripts/import_staged_to_db.py --slug ozone-buzz-z6  # single model
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.audit_staged_json import audit_model

STAGED_FILE = Path("output/ozone_previous_staged.json")
DB_FILE     = Path("output/ozone.db")

# Years from enrichment CSVs (known values for previous models)
# Extend this dict as more years are confirmed.
_KNOWN_YEARS: dict[str, int] = {
    "ozone-buzz-z6":    2021, "ozone-buzz-z5":    2019, "ozone-buzz-z4":    2017,
    "ozone-buzz-z3":    2015, "ozone-buzz-z":     2012, "ozone-buzz":       2009,
    "ozone-delta-4":    2021, "ozone-delta-3":    2018, "ozone-delta-2":    2015,
    "ozone-delta":      2012,
    "ozone-rush-5":     2019, "ozone-rush-4":     2016, "ozone-rush-3":     2013,
    "ozone-rush-2":     2010, "ozone-rush":       2007,
    "ozone-alpina-4":   2021, "ozone-alpina-3":   2018, "ozone-alpina-2":   2015,
    "ozone-alpina":     2012,
    "ozone-zeno":       2018,
    "ozone-enzo":       2012, "ozone-enzo-2":     2015,
    "ozone-zeolite":    2019, "ozone-zeolite-gt": 2019,
    "ozone-ultralite":  2012, "ozone-ultralite-3":2016, "ozone-ultralite-4":2020,
    "ozone-swift":      2013, "ozone-swift-2":    2016, "ozone-swift-4":    2020,
    "ozone-swift-5":    2021,
    "ozone-swiftmax":   2018,
    "ozone-geo":        2010, "ozone-geo-4":      2015, "ozone-geo-5":      2018,
    "ozone-geo-6":      2021, "ozone-geo-ii":     2008, "ozone-geo-iii":    2010,
    "ozone-mantra":     2009, "ozone-mantra-m2":  2011, "ozone-mantra-m3":  2013,
    "ozone-mantra-m4":  2015, "ozone-mantra-m6":  2018, "ozone-mantra-m7":  2021,
    "ozone-mantrar07":  2007, "ozone-mantra-r09": 2009, "ozone-mantra-r10": 2010,
    "ozone-mantra-r11": 2011, "ozone-mantra-r12": 2012,
    "ozone-mojo":       2008, "ozone-mojo-2":     2011, "ozone-mojo-3":     2013,
    "ozone-mojo-4":     2015, "ozone-mojo-5":     2017, "ozone-mojo-6":     2020,
    "ozone-element":    2008, "ozone-element-2":  2011, "ozone-element-3":  2014,
    "ozone-addict":     2015, "ozone-addict-2":   2018,
    "ozone-flx":        2014, "ozone-flx-2":      2017, "ozone-flx-3":      2020,
    "ozone-octane":     2012, "ozone-octane-2":   2016, "ozone-octane-flx": 2019,
    "ozone-magnum":     2008, "ozone-magnum-2009":2009, "ozone-magnum-2":   2012,
    "ozone-magnum-3":   2016,
    "ozone-proton":     2015, "ozone-proton-gt":  2018,
    "ozone-xxlite":     2016, "ozone-xxlite-2":   2019,
    "ozone-trickster":  2014, "ozone-trickster-2":2018,
    "ozone-atom-2":     2012, "ozone-atom-3":     2015,
    "ozone-lm4":        2012, "ozone-lm5":        2015, "ozone-lm6":        2018,
    "ozone-lm7":        2021,
    "ozone-z-alps":     2018,
    "ozone-peak":       2009,
    "ozone-vibe":       2017,
    "ozone-wisp":       2019,
    "ozone-cosmic-rider":2007, "ozone-groundhog": 2016,
    "ozone-mag2lite":   2015, "ozone-jomo":       2009, "ozone-jomo-2":     2012,
    "ozone-vulcan":     2010, "ozone-electron":   2014, "ozone-mcdaddy":    2010,
}

# Explicit slug-based overrides — staged_cat from crawl content-sniff is unreliable
# because Ozone nav links include "Tandem" on every page.
_TANDEM_SLUGS   = {
    "ozone-magnum","ozone-magnum-2009","ozone-magnum-2","ozone-magnum-3","ozone-magnum-4",
    "ozone-cosmic-rider",
    "ozone-swiftmax","ozone-swiftmax-2",
    "ozone-wisp","ozone-wisp-2",
    "ozone-mag2lite",
}
_ACRO_SLUGS     = {"ozone-trickster","ozone-trickster-2","ozone-session",
                   "ozone-addict","ozone-addict-2"}
_PARAMOTOR_SLUGS= {"ozone-lm4","ozone-lm5","ozone-lm6","ozone-lm7","ozone-mcdaddy"}
_SPEEDWING_SLUGS= {"ozone-xxlite","ozone-xxlite-2"}


def _resolve_category(slug: str, staged_cat: str) -> str:
    if slug in _TANDEM_SLUGS:    return "tandem"
    if slug in _ACRO_SLUGS:      return "acro"
    if slug in _PARAMOTOR_SLUGS: return "paramotor"
    if slug in _SPEEDWING_SLUGS: return "speedwing"
    return "paraglider"  # don't trust content-sniffed staged_cat; proton/proton-gt are XC wings


def _normalize_cert(raw: str | None) -> tuple[str, str] | None:
    """Return (standard, classification) or None if unparseable."""
    if not raw or raw.strip() in ("-", "—", ""):
        return None
    raw = raw.strip().rstrip("*")

    if re.match(r"(?:CIVL\s*)?CCC", raw, re.IGNORECASE):
        return ("CCC", "CCC")
    m = re.match(r"(?:EN\s*/\s*LTF|LTF\s*/\s*EN)\s*([A-D])", raw, re.IGNORECASE)
    if m:
        return ("EN", m.group(1).upper())
    m = re.match(r"DHV\s*(\d(?:-\d)?)", raw, re.IGNORECASE)
    if m:
        return ("LTF", m.group(1))
    m = re.match(r"(?:EN|LTF|AFNOR)\s*[-/]?\s*([A-D]|\d(?:-\d)?)", raw, re.IGNORECASE)
    if m:
        std = re.match(r"(EN|LTF|AFNOR)", raw, re.IGNORECASE).group(1).upper()
        return (std, m.group(1).upper())
    m = re.match(r"([A-D])$", raw.strip(), re.IGNORECASE)
    if m:
        return ("EN", m.group(1).upper())
    if raw.lower() == "load test":
        return ("other", "Load test")
    return ("other", raw)


def import_record(cur: sqlite3.Cursor, slug: str, record: dict,
                  mfr_id: int, dry_run: bool) -> str:
    """Insert one model from staged JSON. Returns 'inserted'/'updated'/'skipped'."""

    name = record.get("model_name") or slug.replace("ozone-", "").replace("-", " ").title()
    category = _resolve_category(slug, record.get("category", "paraglider"))
    cell_count = record.get("cell_count")
    year = _KNOWN_YEARS.get(slug)
    url = record.get("_url", f"https://flyozone.com/paragliders/products/gliders/{slug.replace('ozone-','')}")
    sizes = record.get("sizes", {})

    if dry_run:
        n = len(sizes)
        certs = list({sv.get("certification","") for sv in sizes.values() if sv.get("certification")})
        print(f"  [DRY] {slug:<35s} {n}sz  cat={category:<10s} cells={cell_count}  yr={year}  cert={certs}")
        return "dry_run"

    # Upsert model
    cur.execute("SELECT id FROM models WHERE slug=?", (slug,))
    row = cur.fetchone()
    if row:
        model_id = row[0]
        cur.execute("""UPDATE models SET
            category=COALESCE(NULLIF(category,''), ?),
            cell_count=COALESCE(cell_count, ?),
            year_released=COALESCE(year_released, ?),
            manufacturer_url=COALESCE(manufacturer_url, ?),
            is_current=0
            WHERE id=?""",
            (category, cell_count, year, url, model_id))
        action = "updated"
    else:
        cur.execute("""INSERT INTO models
            (manufacturer_id, name, slug, category, cell_count, is_current,
             year_released, manufacturer_url)
            VALUES (?,?,?,?,?,0,?,?)""",
            (mfr_id, name, slug, category, cell_count, year, url))
        model_id = cur.lastrowid
        action = "inserted"

    # Upsert size variants + certifications
    for size_label, sv in sizes.items():
        cur.execute(
            "SELECT id FROM size_variants WHERE model_id=? AND size_label=?",
            (model_id, size_label)
        )
        sv_row = cur.fetchone()
        if sv_row:
            sv_id = sv_row[0]
            cur.execute("""UPDATE size_variants SET
                flat_area_m2=COALESCE(flat_area_m2,?), flat_span_m=COALESCE(flat_span_m,?),
                flat_aspect_ratio=COALESCE(flat_aspect_ratio,?),
                proj_area_m2=COALESCE(proj_area_m2,?), proj_span_m=COALESCE(proj_span_m,?),
                proj_aspect_ratio=COALESCE(proj_aspect_ratio,?),
                wing_weight_kg=COALESCE(wing_weight_kg,?),
                ptv_min_kg=COALESCE(ptv_min_kg,?), ptv_max_kg=COALESCE(ptv_max_kg,?)
                WHERE id=?""",
                (sv.get("flat_area_m2"), sv.get("flat_span_m"), sv.get("flat_aspect_ratio"),
                 sv.get("proj_area_m2"), sv.get("proj_span_m"), sv.get("proj_aspect_ratio"),
                 sv.get("wing_weight_kg"), sv.get("ptv_min_kg"), sv.get("ptv_max_kg"),
                 sv_id))
        else:
            cur.execute("""INSERT INTO size_variants
                (model_id, size_label, flat_area_m2, flat_span_m, flat_aspect_ratio,
                 proj_area_m2, proj_span_m, proj_aspect_ratio, wing_weight_kg,
                 ptv_min_kg, ptv_max_kg)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (model_id, size_label,
                 sv.get("flat_area_m2"), sv.get("flat_span_m"), sv.get("flat_aspect_ratio"),
                 sv.get("proj_area_m2"), sv.get("proj_span_m"), sv.get("proj_aspect_ratio"),
                 sv.get("wing_weight_kg"), sv.get("ptv_min_kg"), sv.get("ptv_max_kg")))
            sv_id = cur.lastrowid

        # Certification (upsert by size_variant_id + standard)
        cert_raw = sv.get("certification")
        cert = _normalize_cert(cert_raw)
        if cert:
            standard, classification = cert
            cur.execute(
                "SELECT id FROM certifications WHERE size_variant_id=? AND standard=?",
                (sv_id, standard)
            )
            if not cur.fetchone():
                cur.execute("""INSERT INTO certifications
                    (size_variant_id, standard, classification)
                    VALUES (?,?,?)""",
                    (sv_id, standard, classification))

    # Provenance
    cur.execute("SELECT id FROM provenance WHERE model_id=?", (model_id,))
    if not cur.fetchone():
        cur.execute("""INSERT INTO provenance (model_id, source_name, source_url, extraction_method)
            VALUES (?,?,?,?)""",
            (model_id, "Ozone website", url, "markdown_parser_iter20"))

    return action


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing to DB")
    parser.add_argument("--force",   action="store_true", help="Import even models with audit issues")
    parser.add_argument("--slug",    type=str, default="",  help="Import only this slug")
    args = parser.parse_args()

    if not STAGED_FILE.exists():
        print(f"Staged file not found: {STAGED_FILE}")
        sys.exit(1)

    records = json.loads(STAGED_FILE.read_text())

    # Filter to importable records
    to_import = {}
    skipped_status = []
    skipped_issues = []

    for slug, record in sorted(records.items()):
        if args.slug and slug != args.slug:
            continue
        if record.get("_status") != "ok":
            skipped_status.append(slug)
            continue
        issues = audit_model(slug, record)
        critical = [i for i in issues if "implausible" in i or "ptv_min_gte" in i]
        if critical and not args.force:
            skipped_issues.append((slug, critical))
            continue
        to_import[slug] = record

    print(f"\nImport plan: {len(to_import)} models")
    if skipped_status:
        print(f"  Skipping {len(skipped_status)} (not staged/parse failed): "
              f"{', '.join(skipped_status[:5])}{'...' if len(skipped_status)>5 else ''}")
    if skipped_issues:
        print(f"  Skipping {len(skipped_issues)} (critical issues — use --force to override):")
        for slug, issues in skipped_issues:
            print(f"    {slug}: {issues[0]}")

    if not to_import:
        print("Nothing to import.")
        return

    conn = sqlite3.connect(DB_FILE)
    cur  = conn.cursor()
    cur.execute("SELECT id FROM manufacturers WHERE slug='ozone'")
    mfr_id = cur.fetchone()[0]

    counts = {"inserted": 0, "updated": 0, "dry_run": 0}
    for slug, record in to_import.items():
        action = import_record(cur, slug, record, mfr_id, args.dry_run)
        counts[action] = counts.get(action, 0) + 1

    if not args.dry_run:
        conn.commit()
        print(f"\n  ✓ Inserted: {counts['inserted']}")
        print(f"  ✓ Updated:  {counts['updated']}")
        print(f"\n  Run benchmark: python -m src.pipeline benchmark --db {DB_FILE}")
    else:
        print(f"\n  [DRY RUN] {counts['dry_run']} models would be imported. Re-run without --dry-run to commit.")

    conn.close()


if __name__ == "__main__":
    main()
