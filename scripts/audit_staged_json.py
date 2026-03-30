"""Audit staged JSON quality before importing to ozone.db.

Reads output/ozone_previous_staged.json and reports:
  - Coverage of key fields per model
  - Models needing manual review
  - Summary table

Usage:
    python3 scripts/audit_staged_json.py
    python3 scripts/audit_staged_json.py --show-all   # include OK models
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

STAGED_FILE = Path("output/ozone_previous_staged.json")

REQUIRED_FIELDS = ["flat_area_m2", "flat_span_m", "flat_aspect_ratio",
                   "wing_weight_kg", "ptv_min_kg", "ptv_max_kg"]
OPTIONAL_FIELDS = ["proj_area_m2", "proj_span_m", "proj_aspect_ratio", "certification"]

# Known models that legitimately have no PTV (ground handlers, paramotor, etc.)
NO_PTV_OK = {"ozone-roadrunner", "ozone-groundhog", "ozone-electron"}

# Known models that legitimately have no EN certification
NO_CERT_OK = {"ozone-roadrunner", "ozone-groundhog"}


def audit_model(slug: str, record: dict) -> list[str]:
    """Return list of issues for a model record. Empty = clean."""
    issues = []
    status = record.get("_status")

    if status != "ok":
        issues.append(f"status={status}")
        return issues

    sizes = record.get("sizes", {})
    if not sizes:
        issues.append("no_sizes")
        return issues

    # Check each size for required fields
    for size_label, sv in sizes.items():
        for f in REQUIRED_FIELDS:
            if sv.get(f) is None:
                if f in ("ptv_min_kg", "ptv_max_kg") and slug in NO_PTV_OK:
                    continue
                issues.append(f"size_{size_label}:missing_{f}")

    # Check at least one cert across all sizes (if applicable)
    if slug not in NO_CERT_OK:
        all_certs = [sv.get("certification") for sv in sizes.values()]
        valid_certs = [c for c in all_certs if c and c.strip() not in ("-", "—", "")]
        if not valid_certs:
            issues.append("no_certifications")

    # Check cell_count at model level
    if not record.get("cell_count"):
        issues.append("missing_cell_count")

    # Plausibility: flat_area within reasonable range
    for size_label, sv in sizes.items():
        fa = sv.get("flat_area_m2")
        if fa is not None and not (8.0 <= fa <= 80.0):
            issues.append(f"size_{size_label}:flat_area_implausible={fa}")
        wt = sv.get("wing_weight_kg")
        if wt is not None and not (0.5 <= wt <= 20.0):
            issues.append(f"size_{size_label}:wing_weight_implausible={wt}")
        pmin = sv.get("ptv_min_kg")
        pmax = sv.get("ptv_max_kg")
        if pmin and pmax and pmin >= pmax:
            issues.append(f"size_{size_label}:ptv_min_gte_max ({pmin}>={pmax})")

    return issues


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--show-all", action="store_true", help="Show clean models too")
    args = parser.parse_args()

    if not STAGED_FILE.exists():
        print(f"No staged file found: {STAGED_FILE}")
        print("Run: python3 scripts/crawl_previous_to_json.py")
        sys.exit(1)

    records = json.loads(STAGED_FILE.read_text())

    ok_clean   = []
    ok_issues  = []
    failed     = []

    for slug, record in sorted(records.items()):
        status = record.get("_status")
        if status != "ok":
            failed.append((slug, record))
            continue
        issues = audit_model(slug, record)
        if issues:
            ok_issues.append((slug, record, issues))
        else:
            ok_clean.append((slug, record))

    # ── Print report ──────────────────────────────────────────────────────
    print(f"\n{'='*70}")
    print(f"  STAGED JSON AUDIT — {STAGED_FILE}")
    print(f"{'='*70}")
    print(f"  Total staged:   {len(records)}")
    print(f"  ✓ Clean:        {len(ok_clean)}")
    print(f"  ⚠ Has issues:   {len(ok_issues)}")
    print(f"  ✗ Not staged:   {len(failed)}")

    if ok_issues:
        print(f"\n{'─'*70}")
        print("  MODELS WITH ISSUES (need review before import):")
        print(f"{'─'*70}")
        for slug, record, issues in ok_issues:
            n_sizes = len(record.get("sizes", {}))
            cat = record.get("category", "?")
            print(f"\n  {slug}  [{cat}  {n_sizes} sizes]")
            for issue in issues:
                print(f"    ⚠  {issue}")

    if failed:
        print(f"\n{'─'*70}")
        print("  NOT STAGED / PARSE FAILURES (manual extraction needed):")
        print(f"{'─'*70}")
        for slug, record in failed:
            status = record.get("_status")
            url = record.get("_url", "")
            md_len = record.get("_markdown_len", 0)
            err = record.get("_error", "")
            detail = f"markdown={md_len}chars" if md_len else err
            print(f"  ✗  {slug:<30s}  [{status}]  {detail}")
            print(f"     {url}")

    if args.show_all and ok_clean:
        print(f"\n{'─'*70}")
        print("  CLEAN MODELS:")
        print(f"{'─'*70}")
        for slug, record in ok_clean:
            n_sizes = len(record.get("sizes", {}))
            cat = record.get("category", "?")
            cells = record.get("cell_count", "?")
            certs = list({sv.get("certification","—")
                          for sv in record.get("sizes", {}).values()
                          if sv.get("certification")})
            cert_str = ", ".join(sorted(certs)) if certs else "—"
            print(f"  ✓  {slug:<35s}  [{cat}  {n_sizes}sz  cells={cells}  cert={cert_str}]")

    print(f"\n  Ready to import: {len(ok_clean)} clean models")
    print(f"  Fix then import: {len(ok_issues)} models with issues")
    print(f"  Manual needed:   {len(failed)} models")
    print(f"\n  Next: python3 scripts/import_staged_to_db.py --dry-run")


if __name__ == "__main__":
    main()
