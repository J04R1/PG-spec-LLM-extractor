"""Re-crawl the 6 models whose proj_area_m2 was missing due to parser bugs,
update staged JSON, and re-import to DB.

Fixed bugs:
  1. Trailing footnote `n` on unit suffixes: "Projected area (m2)n" → matched
  2. Abbreviated Mojo table labels: "Proj.Area", "Area"
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.crawler import Crawler
from src.markdown_parser import parse_specs_from_markdown

OUTPUT_FILE = Path("output/ozone_previous_staged.json")

TARGETS = {
    "ozone-swift-4":   "https://flyozone.com/paragliders/products/gliders/swift-4",
    "ozone-element-3": "https://flyozone.com/paragliders/products/gliders/element-3",
    "ozone-mojo":      "https://flyozone.com/paragliders/products/gliders/mojo",
    "ozone-lm6":       "https://flyozone.com/paragliders/products/gliders/lm6",
    "ozone-mag2lite":  "https://flyozone.com/paragliders/products/gliders/mag2lite",
    "ozone-mantra-m6": "https://flyozone.com/paragliders/products/gliders/mantra-m6",
}

# Explicit category overrides
_CAT_OVERRIDE = {
    "ozone-lm6":      "paramotor",
    "ozone-mojo":     "paraglider",
    "ozone-mag2lite": "tandem",
    "ozone-mantra-m6": "paraglider",
}


async def update_all(data: dict) -> None:
    c = Crawler()
    for slug, url in TARGETS.items():
        print(f"  Crawling {slug} ...", end=" ", flush=True)
        try:
            md = await c.render_page(url)
        except Exception as e:
            print(f"CRAWL ERROR: {e}")
            continue

        result = parse_specs_from_markdown(md, url, "Ozone")
        if not (result and result.sizes):
            print("PARSE FAILED")
            continue

        cat = _CAT_OVERRIDE.get(slug, data.get(slug, {}).get("category", "paraglider"))
        record = {
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
        data[slug] = record
        sample_proj = result.sizes[0].proj_area_m2
        print(f"OK  {len(result.sizes)} sizes  proj_area[0]={sample_proj}")


def main() -> None:
    data: dict = json.loads(OUTPUT_FILE.read_text())

    asyncio.run(update_all(data))

    OUTPUT_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    print(f"\nSaved → {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
