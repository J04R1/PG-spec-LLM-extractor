"""Crawl all previous-glider URLs and stage specs into a JSON file.

Does NOT write to the DB. Output goes to output/ozone_previous_staged.json
so data can be reviewed and quality-checked before import.

Handles two Ozone page layouts:
  1. Standard multi-size pipe table (most wings)
  2. Two-column label/value table (single-size wings like Roadrunner, Wisp, Swiftmax)

Usage:
    python3 scripts/crawl_previous_to_json.py
    python3 scripts/crawl_previous_to_json.py --resume   # skip already-staged slugs
    python3 scripts/crawl_previous_to_json.py --limit 10 # crawl first N URLs only
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from pathlib import Path

# Ensure project root on path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.crawler import Crawler
from src.markdown_parser import parse_specs_from_markdown

URLS_FILE   = Path("output/ozone_urls.json")
OUTPUT_FILE = Path("output/ozone_previous_staged.json")
PREV_KEY    = "previous_gliders:https://flyozone.com/paragliders/products/previous-gliders"

# ── Two-column layout parser (Roadrunner-style) ──────────────────────────────

_TWO_COL_MAP: dict[str, str] = {
    "number of cells":             "cell_count",
    "no of cells":                 "cell_count",
    "projected area (m²)":         "proj_area_m2",
    "flat area (m²)":              "flat_area_m2",
    "projected span (m)":          "proj_span_m",
    "flat span (m)":               "flat_span_m",
    "projected aspect ratio":      "proj_aspect_ratio",
    "flat aspect ratio":           "flat_aspect_ratio",
    "root chord (m)":              "root_chord_m",
    "glider weight (kg)":          "wing_weight_kg",
    "glider weight (kg)*":         "wing_weight_kg",
    "certified weight range (kg)": "_ptv_range",
    "certified weight range (kg)**": "_ptv_range",
    "certification":               "certification",
}


def _parse_number(s: str) -> float | None:
    s = s.strip().rstrip("*")
    s = re.sub(r"\s*(kg|m2|m\^2|m|m²)\s*$", "", s, flags=re.IGNORECASE)
    if "," in s and "." not in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _parse_two_column_table(markdown: str, url: str) -> dict | None:
    """Parse Ozone single-size pages that use a two-column spec table.

    Handles two variants:
      A) Each row is "Label | Value" (e.g. Roadrunner, Groundhog)
      B) Two separate single-column tables: labels in table 1, values in table 2

    Returns a flat dict of field→value, or None if not found.
    """
    # Search the whole markdown — some old pages lack a "# SPECIFICATIONS" heading
    spec_match = re.search(r"#+ SPECIFICATIONS", markdown, re.IGNORECASE)
    section = markdown[spec_match.start():] if spec_match else markdown

    # Collect all pipe-table rows in the section
    table_rows: list[list[str]] = []
    for line in section.split("\n"):
        stripped = line.strip()
        if "|" not in stripped:
            continue
        if re.match(r"^[\s|:-]+$", stripped):
            continue
        parts = [p.strip() for p in stripped.split("|")]
        parts = [p for p in parts if p]
        if parts:
            table_rows.append(parts)

    if not table_rows:
        return None

    # ── Variant A: rows are [label, value] pairs ──────────────────────────
    two_cell_rows = [r for r in table_rows if len(r) == 2]
    if len(two_cell_rows) >= 4:
        result: dict = {"_layout": "two_col_label_value", "_url": url}
        size_data: dict = {}
        size_label: str | None = None
        for label, value in two_cell_rows:
            key = _TWO_COL_MAP.get(label.lower().rstrip("*"))
            if label.lower().startswith("size"):
                # "Sizes | 14" or "Sizes | 14m" — extract size label
                size_label = value.strip()
                continue
            if not key:
                continue
            if key == "_ptv_range":
                parts = re.split(r"\s*[-–]\s*", value)
                if len(parts) == 2:
                    size_data["ptv_min_kg"] = _parse_number(parts[0])
                    size_data["ptv_max_kg"] = _parse_number(parts[1])
            elif key == "certification":
                size_data["certification"] = value.strip()
            elif key == "cell_count":
                v = _parse_number(value)
                if v:
                    result["cell_count"] = int(v)
            else:
                v = _parse_number(value)
                if v is not None:
                    size_data[key] = v
        if size_data:
            result["sizes"] = {size_label or "OS": size_data}
            return result

    # ── Variant B: alternating single-cell rows (labels table / values table)
    label_rows: list[str] = []
    value_rows: list[str] = []

    for row in table_rows:
        if len(row) == 1:
            cell = row[0].strip()
            # Classify: if looks numeric or a known cert value → value, else label
            is_label = bool(re.search(r"[a-zA-Z]{2,}", cell)) and not re.match(
                r"^[\d\s.,\-–]+$", cell
            )
            # known cert strings are values
            if cell.lower() in ("en b", "en c", "en d", "en a", "ccc", "b", "c", "d", "a",
                                  "load test", "1", "1-2", "2", "2-3"):
                is_label = False
            if is_label:
                label_rows.append(cell)
            else:
                value_rows.append(cell)

    if len(label_rows) >= 4 and len(value_rows) >= 4:
        # Pair labels with values
        result: dict = {"_layout": "two_column", "_url": url}
        size_data: dict = {}
        for label, value in zip(label_rows, value_rows):
            key = _TWO_COL_MAP.get(label.lower())
            if not key:
                continue
            if key == "_ptv_range":
                parts = re.split(r"\s*[-–]\s*", value)
                if len(parts) == 2:
                    size_data["ptv_min_kg"] = _parse_number(parts[0])
                    size_data["ptv_max_kg"] = _parse_number(parts[1])
            elif key == "certification":
                size_data["certification"] = value.strip()
            elif key == "cell_count":
                v = _parse_number(value)
                if v:
                    result["cell_count"] = int(v)
            else:
                v = _parse_number(value)
                if v is not None:
                    size_data[key] = v

        if size_data:
            result["sizes"] = {"OS": size_data}
            return result

    return None


# ── Category inference ────────────────────────────────────────────────────────

_TANDEM_SLUGS = {
    "magnum", "magnum-2009", "magnum-2", "magnum-3", "magnum-4",
    "cosmic-rider", "groundhog", "swiftmax", "wisp",
}
_ACRO_SLUGS = {"trickster", "trickster-2", "session"}
_PARAMOTOR_SLUGS = {"lm4", "lm5", "lm6", "lm7", "mcdaddy"}
_SPEEDWING_SLUGS = {"xxlite", "xxlite-2"}
_MINIWING_SLUGS  = {"proton", "proton-gt"}


def _infer_category(slug: str, markdown: str) -> str:
    slug_base = slug.replace("ozone-", "").lower()
    if slug_base in _TANDEM_SLUGS:
        return "tandem"
    if slug_base in _ACRO_SLUGS:
        return "acro"
    if slug_base in _PARAMOTOR_SLUGS:
        return "paramotor"
    if slug_base in _SPEEDWING_SLUGS:
        return "speedwing"
    if slug_base in _MINIWING_SLUGS:
        return "miniwing"
    # Sniff page content for category indicators — use specific phrases to
    # avoid false positives from nav links (e.g. "Tandem" in site navigation)
    sniff = markdown[:3000].lower()
    if re.search(r'\btandem wing\b|\btandem glider\b|\bfor tandem\b|\btwo[- ]person\b', sniff):
        return "tandem"
    if re.search(r'\bacro\b|\bfreestyle\b', sniff):
        return "acro"
    if re.search(r'\bparamotor\b|\bpowered\b', sniff):
        return "paramotor"
    if re.search(r'\bspeed wing\b|\bspeedwing\b', sniff):
        return "speedwing"
    return "paraglider"


# ── Main crawl loop ───────────────────────────────────────────────────────────

async def crawl_all(urls: list[str], existing: dict, resume: bool, force: bool = False) -> dict:
    crawler = Crawler()
    results = dict(existing) if resume else {}

    total = len(urls)
    for i, url in enumerate(urls, 1):
        slug = "ozone-" + url.split("/")[-1]
        if resume and slug in results:
            print(f"  [{i:3d}/{total}] SKIP  {slug} (already staged)")
            continue

        print(f"  [{i:3d}/{total}] Crawling {slug} ...", end=" ", flush=True)
        t0 = time.time()

        try:
            markdown = await crawler.render_page(url, force=force)
        except Exception as e:
            elapsed = time.time() - t0
            print(f"CRAWL ERROR ({elapsed:.1f}s): {e}")
            results[slug] = {"_status": "crawl_error", "_error": str(e), "_url": url}
            continue

        if not markdown:
            print(f"EMPTY ({time.time()-t0:.1f}s)")
            results[slug] = {"_status": "empty_page", "_url": url}
            continue

        elapsed = time.time() - t0

        # Try standard multi-size markdown parser
        extraction = parse_specs_from_markdown(markdown, url, "Ozone")

        if extraction and extraction.sizes:
            category = _infer_category(slug, markdown)
            record = {
                "_status": "ok",
                "_url": url,
                "_layout": "multi_size",
                "model_name": extraction.model_name,
                "category": category,
                "cell_count": extraction.cell_count,
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
                    for s in extraction.sizes
                },
            }
            results[slug] = record
            n_sizes = len(extraction.sizes)
            certs = [s.certification for s in extraction.sizes if s.certification]
            cert_str = certs[0] if certs else "no cert"
            print(f"OK  {n_sizes} sizes  cert={cert_str}  ({elapsed:.1f}s)")

        else:
            # Fallback: two-column single-size layout
            two_col = _parse_two_column_table(markdown, url)
            if two_col and two_col.get("sizes"):
                category = _infer_category(slug, markdown)
                two_col["_status"] = "ok"
                two_col["model_name"] = slug.replace("ozone-", "").replace("-", " ").title()
                two_col["category"] = category
                results[slug] = two_col
                print(f"OK  two-col layout  ({elapsed:.1f}s)")
            else:
                print(f"PARSE FAIL  ({elapsed:.1f}s)")
                results[slug] = {
                    "_status": "parse_failed",
                    "_url": url,
                    "_markdown_len": len(markdown),
                }

        # Save after every URL so we can resume
        OUTPUT_FILE.write_text(json.dumps(results, indent=2, ensure_ascii=False))

    return results


def print_summary(results: dict) -> None:
    ok = [k for k, v in results.items() if v.get("_status") == "ok"]
    failed = [k for k, v in results.items() if v.get("_status") == "parse_failed"]
    errors = [k for k, v in results.items() if v.get("_status") in ("crawl_error", "empty_page")]

    print(f"\n{'='*60}")
    print(f"  STAGING COMPLETE")
    print(f"  OK:           {len(ok):3d}")
    print(f"  Parse failed: {len(failed):3d}  ← review manually")
    print(f"  Crawl errors: {len(errors):3d}")
    print(f"  TOTAL:        {len(results):3d}")

    if failed:
        print(f"\n  Parse failures (manual review needed):")
        for slug in failed:
            md_len = results[slug].get("_markdown_len", 0)
            print(f"    {slug}  (markdown: {md_len} chars)")

    if errors:
        print(f"\n  Crawl errors:")
        for slug in errors:
            print(f"    {slug}  {results[slug].get('_error','')}")

    print(f"\n  Output: {OUTPUT_FILE}")
    print(f"  Run quality check: python3 scripts/audit_staged_json.py")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resume",  action="store_true", help="Skip slugs already in staged JSON")
    parser.add_argument("--limit",   type=int, default=0,  help="Crawl only first N URLs")
    parser.add_argument("--force",   action="store_true", help="Bypass markdown cache, fetch fresh pages")
    args = parser.parse_args()

    urls_data = json.loads(URLS_FILE.read_text())
    urls = urls_data[PREV_KEY]
    if args.limit:
        urls = urls[:args.limit]

    # Load existing staged results if resuming
    existing = {}
    if args.resume and OUTPUT_FILE.exists():
        existing = json.loads(OUTPUT_FILE.read_text())
        print(f"Resuming: {len(existing)} already staged")

    print(f"Crawling {len(urls)} previous-glider URLs → {OUTPUT_FILE}\n")
    if args.force:
        print("  (--force: bypassing markdown cache)\n")
    results = asyncio.run(crawl_all(urls, existing, args.resume, args.force))
    print_summary(results)


if __name__ == "__main__":
    main()
