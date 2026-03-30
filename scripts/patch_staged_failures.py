"""Manually patch the 4 parse-failed models into ozone_previous_staged.json.

Models fixed:
  - ozone-roadrunner  (2-col label|value table, ground handling trainer)
  - ozone-groundhog   (2-col label|value table, ground handling trainer)
  - ozone-mantrar07   (multi-size table with abbreviated column names)
  - ozone-vulcan      (multi-size table, partial data only)

Run: python3 scripts/patch_staged_failures.py
"""
from __future__ import annotations

import json
from pathlib import Path

OUTPUT_FILE = Path("output/ozone_previous_staged.json")

# ── Manually-extracted patch data ─────────────────────────────────────────────

PATCHES: dict[str, dict] = {

    "ozone-roadrunner": {
        "_status":  "ok",
        "_url":     "https://flyozone.com/paragliders/products/gliders/roadrunner",
        "_layout":  "two_col_label_value",
        "_note":    "Ground handling trainer — no PTV, no certification, not for flight",
        "model_name": "Roadrunner",
        "category": "paraglider",   # no "groundhandler" enum value; closest is paraglider
        "cell_count": 27,
        "sizes": {
            "14": {
                "proj_area_m2":      12.1,
                "flat_area_m2":      14.0,
                "proj_span_m":       6.06,
                "flat_span_m":       7.74,
                "proj_aspect_ratio": 3.0,
                "flat_aspect_ratio": 4.3,
                "root_chord_m":      2.36,
                "wing_weight_kg":    3.0,
            }
        },
    },

    "ozone-groundhog": {
        "_status":  "ok",
        "_url":     "https://flyozone.com/paragliders/products/gliders/groundhog",
        "_layout":  "two_col_label_value",
        "_note":    "Ground handling trainer — no PTV, no certification, not for flight",
        "model_name": "GroundHog",
        "category": "paraglider",
        "cell_count": 20,
        "sizes": {
            "14m": {
                "proj_area_m2":      12.4,
                "flat_area_m2":      14.0,
                "proj_span_m":       5.9,
                "flat_span_m":       6.9,
                "proj_aspect_ratio": 2.8,
                "flat_aspect_ratio": 3.49,
                "root_chord_m":      2.3,
                "wing_weight_kg":    2.8,
            }
        },
    },

    "ozone-mantrar07": {
        "_status":  "ok",
        "_url":     "https://flyozone.com/paragliders/products/gliders/mantrar07",
        "_layout":  "multi_size",
        "_note":    "Old table layout with abbreviated column names; no cert shown on page",
        "model_name": "Mantra R07",
        "category": "paraglider",
        "cell_count": 81,
        "sizes": {
            "24": {
                "proj_area_m2":      20.92,
                "flat_area_m2":      24.2,
                "proj_span_m":       10.55,
                "flat_span_m":       13.2,
                "proj_aspect_ratio": 5.32,
                "flat_aspect_ratio": 7.2,
                "root_chord_m":      2.32,
                "wing_weight_kg":    5.3,
                "ptv_min_kg":        90.0,
                "ptv_max_kg":        100.0,
            },
            "26": {
                "proj_area_m2":      22.48,
                "flat_area_m2":      26.0,
                "proj_span_m":       10.94,
                "flat_span_m":       13.68,
                "proj_aspect_ratio": 5.32,
                "flat_aspect_ratio": 7.2,
                "root_chord_m":      2.40,
                "wing_weight_kg":    5.6,
                "ptv_min_kg":        100.0,
                "ptv_max_kg":        110.0,
            },
            "28": {
                "proj_area_m2":      24.39,
                "flat_area_m2":      28.2,
                "proj_span_m":       11.39,
                "flat_span_m":       14.2,
                "proj_aspect_ratio": 5.32,
                "flat_aspect_ratio": 7.2,
                "root_chord_m":      2.50,
                "wing_weight_kg":    5.9,
                "ptv_min_kg":        110.0,
                "ptv_max_kg":        120.0,
            },
        },
    },

    "ozone-vulcan": {
        "_status":  "ok",
        "_url":     "https://flyozone.com/paragliders/products/gliders/vulcan",
        "_layout":  "multi_size",
        "_note":    "Old page — partial data only (no proj_span, no proj_ar, no root_chord, no weight, no cert)",
        "model_name": "Vulcan",
        "category": "paraglider",
        "cell_count": 56,
        "sizes": {
            "XS": {
                "proj_area_m2":  19.3,
                "flat_area_m2":  22.6,
                "flat_span_m":   11.04,
                "flat_aspect_ratio": 5.4,
                "ptv_min_kg":    55.0,
                "ptv_max_kg":    70.0,
            },
            "S": {
                "proj_area_m2":  21.6,
                "flat_area_m2":  25.0,
                "flat_span_m":   11.61,
                "flat_aspect_ratio": 5.4,
                "ptv_min_kg":    65.0,
                "ptv_max_kg":    85.0,
            },
            "M": {
                "proj_area_m2":  23.5,
                "flat_area_m2":  27.1,
                "flat_span_m":   12.09,
                "flat_aspect_ratio": 5.4,
                "ptv_min_kg":    80.0,
                "ptv_max_kg":    100.0,
            },
            "L": {
                "proj_area_m2":  25.5,
                "flat_area_m2":  29.3,
                "flat_span_m":   12.57,
                "flat_aspect_ratio": 5.4,
                "ptv_min_kg":    95.0,
                "ptv_max_kg":    115.0,
            },
            "XL": {
                "proj_area_m2":  27.9,
                "flat_area_m2":  32.0,
                "flat_span_m":   13.14,
                "flat_aspect_ratio": 5.4,
                "ptv_min_kg":    110.0,
                "ptv_max_kg":    135.0,
            },
        },
    },
}


def main() -> None:
    data: dict = json.loads(OUTPUT_FILE.read_text())

    patched = 0
    for slug, patch in PATCHES.items():
        old_status = data.get(slug, {}).get("_status", "missing")
        data[slug] = patch
        print(f"  ✓ {slug:<30s}  {old_status} → ok")
        patched += 1

    OUTPUT_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    print(f"\n  Patched {patched} models → {OUTPUT_FILE}")
    print(f"  Re-run audit: python3 scripts/audit_staged_json.py")


if __name__ == "__main__":
    main()
