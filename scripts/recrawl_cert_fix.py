"""Re-crawl models that had no certification data due to missing _MD_ROW_MAP variants.

Fixed in src/markdown_parser.py:
  - "EN / LTF" (spaces around slash) → was missing, now mapped
  - "LTF/EN" (reversed, no spaces)   → was missing, now mapped

Usage:
    python3 scripts/recrawl_cert_fix.py
    python3 scripts/recrawl_cert_fix.py --dry-run   # parse only, don't save
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.crawler import Crawler
from src.markdown_parser import parse_specs_from_markdown

OUTPUT_FILE = Path("output/ozone_previous_staged.json")


def _get_no_cert_slugs(data: dict) -> list[str]:
    """Return slugs where every size has certification=None."""
    result = []
    for slug, r in sorted(data.items()):
        if r.get("_status") != "ok":
            continue
        sizes = r.get("sizes", {})
        if sizes and all(s.get("certification") is None for s in sizes.values()):
            result.append(slug)
    return result


# Category overrides for targeted re-crawl slugs
_CAT_OVERRIDE = {
    "ozone-lm6":       "paramotor",
    "ozone-lm7":       "paramotor",
    "ozone-flx":       "paraglider",
    "ozone-flx-2":     "paraglider",
    "ozone-flx-3":     "paraglider",
    "ozone-trickster":  "acro",
    "ozone-trickster-2": "acro",
    "ozone-mag2lite":  "tandem",
    "ozone-magnum-2":  "tandem",
    "ozone-groundhog": "paraglider",
    "ozone-roadrunner": "paraglider",
}


async def recrawl(data: dict, dry_run: bool, force: bool = False) -> dict[str, str]:
    """Re-crawl all no-cert models and update data in-place.

    Returns a summary dict: slug → "gained_cert" | "still_no_cert" | "parse_failed"
    """
    slugs = _get_no_cert_slugs(data)
    print(f"Models with no certifications: {len(slugs)}\n")
    if force:
        print("  (cache bypassed — fetching fresh pages)\n")

    c = Crawler()
    summary: dict[str, str] = {}

    for slug in slugs:
        record = data[slug]
        url = record["_url"]
        print(f"  {slug:<35s}", end=" ", flush=True)

        try:
            md = await c.render_page(url, force=force)
        except Exception as e:
            print(f"CRAWL ERROR: {e}")
            summary[slug] = "crawl_error"
            continue

        result = parse_specs_from_markdown(md, url, "Ozone")
        if not (result and result.sizes):
            print("PARSE FAILED")
            summary[slug] = "parse_failed"
            continue

        certs = [s.certification for s in result.sizes if s.certification]
        if not certs:
            print("still no cert")
            summary[slug] = "still_no_cert"
            # Still update other fields (proj_area etc) that may have improved
        else:
            print(f"CERT: {certs[0]!r}")
            summary[slug] = "gained_cert"

        if not dry_run:
            cat = _CAT_OVERRIDE.get(slug, record.get("category", "paraglider"))
            data[slug] = {
                "_status":  "ok",
                "_url":     url,
                "_layout":  "multi_size",
                "model_name": result.model_name,
                "category":   cat,
                "cell_count": result.cell_count,
                "sizes": {
                    s.size_label: {
                        "flat_area_m2":       s.flat_area_m2,
                        "flat_span_m":        s.flat_span_m,
                        "flat_aspect_ratio":  s.flat_aspect_ratio,
                        "proj_area_m2":       s.proj_area_m2,
                        "proj_span_m":        s.proj_span_m,
                        "proj_aspect_ratio":  s.proj_aspect_ratio,
                        "wing_weight_kg":     s.wing_weight_kg,
                        "ptv_min_kg":         s.ptv_min_kg,
                        "ptv_max_kg":         s.ptv_max_kg,
                        "certification":      s.certification,
                    }
                    for s in result.sizes
                },
            }

    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Parse but don't save")
    parser.add_argument("--force",   action="store_true", help="Bypass cache, fetch fresh pages")
    args = parser.parse_args()

    data: dict = json.loads(OUTPUT_FILE.read_text())
    summary = asyncio.run(recrawl(data, args.dry_run, args.force))

    if not args.dry_run:
        OUTPUT_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    gained   = [k for k, v in summary.items() if v == "gained_cert"]
    still_no = [k for k, v in summary.items() if v == "still_no_cert"]
    failed   = [k for k, v in summary.items() if v in ("parse_failed", "crawl_error")]

    print(f"\n{'='*60}")
    print(f"  Gained certification:  {len(gained)}")
    print(f"  Still no cert (page has none): {len(still_no)}")
    if still_no:
        for s in still_no:
            print(f"    {s}")
    print(f"  Parse/crawl failures:  {len(failed)}")
    if failed:
        for s in failed:
            print(f"    {s}")

    if not args.dry_run:
        print(f"\nSaved → {OUTPUT_FILE}")
        print("Re-import: python3 scripts/import_staged_to_db.py")


if __name__ == "__main__":
    main()
