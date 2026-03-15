#!/usr/bin/env python3
"""
Iteration 08 — Advance Validation Run

Validates the pipeline with Advance.swiss current models, comparing extraction
results against the baseline (data/advance_enrichment_all.csv).

Usage:
    python -m tests.validate_advance

    # Include LLM comparison (requires Ollama running):
    python -m tests.validate_advance --llm
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.crawler import Crawler
from src.extractor import extract_specs
from src.models import ExtractionResult
from src.normalizer import normalize_certification

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("validate_advance")

# ── Validation sample ───────────────────────────────────────────────────────

VALIDATION_URLS = [
    "https://www.advance.swiss/en/products/paragliders/alpha-series/alpha",
    "https://www.advance.swiss/en/products/paragliders/alpha-series/alpha-dls",
    "https://www.advance.swiss/en/products/paragliders/epsilon-dls",
    "https://www.advance.swiss/en/products/paragliders/sigma-dls",
    "https://www.advance.swiss/en/products/paragliders/omega-uls",
    "https://www.advance.swiss/en/products/paragliders/pi-uls",
    "https://www.advance.swiss/en/products/paragliders/bibeta-6",
    "https://www.advance.swiss/en/products/paragliders/iota-dls",
]

BASELINE_CSV = Path(__file__).resolve().parent.parent / "data" / "advance_enrichment_all.csv"

NUMERIC_FIELDS = [
    "flat_area_m2", "flat_span_m", "flat_aspect_ratio",
    "proj_area_m2", "proj_span_m", "proj_aspect_ratio",
    "wing_weight_kg", "ptv_min_kg", "ptv_max_kg",
]

CERT_FIELDS = ["cert_standard", "cert_classification"]

NUMERIC_TOLERANCE = 0.1


# ── Data structures ─────────────────────────────────────────────────────────

@dataclass
class SizeRow:
    model_name: str
    size_label: str
    fields: dict[str, float | str | None] = field(default_factory=dict)


@dataclass
class ModelResult:
    model_name: str
    url: str
    baseline_sizes: int = 0
    extracted_sizes: int = 0
    fields_compared: int = 0
    fields_matched: int = 0
    mismatches: list[str] = field(default_factory=list)
    extraction_time_s: float = 0.0
    error: str | None = None

    @property
    def match_pct(self) -> float:
        if self.fields_compared == 0:
            return 0.0
        return 100.0 * self.fields_matched / self.fields_compared


# ── Baseline loader ─────────────────────────────────────────────────────────

def load_baseline(csv_path: Path) -> dict[str, list[SizeRow]]:
    baseline: dict[str, list[SizeRow]] = {}
    seen: set[tuple[str, str]] = set()

    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row.get("name", "").strip()
            if not name:
                continue

            size_label = row.get("size_label", "").strip()
            key = (name, size_label)
            if key in seen:
                continue
            seen.add(key)

            fields: dict[str, float | str | None] = {}
            for nf in NUMERIC_FIELDS:
                val = row.get(nf, "").strip()
                if val:
                    try:
                        fields[nf] = float(val)
                    except ValueError:
                        fields[nf] = None
                else:
                    fields[nf] = None

            fields["cert_standard"] = row.get("cert_standard", "").strip() or None
            fields["cert_classification"] = row.get("cert_classification", "").strip() or None

            cell_count = row.get("cell_count", "").strip()
            if cell_count:
                try:
                    fields["cell_count"] = float(cell_count)
                except ValueError:
                    pass

            sr = SizeRow(model_name=name, size_label=size_label, fields=fields)
            baseline.setdefault(name, []).append(sr)

    return baseline


def extraction_to_size_rows(result: ExtractionResult) -> list[SizeRow]:
    rows = []
    for size in result.sizes:
        fields: dict[str, float | str | None] = {}
        for nf in NUMERIC_FIELDS:
            val = getattr(size, nf, None)
            fields[nf] = float(val) if val is not None else None

        cert_str = size.certification or ""
        if cert_str:
            standard, classification = normalize_certification(cert_str)
            fields["cert_standard"] = standard.value
            fields["cert_classification"] = classification
        else:
            fields["cert_standard"] = None
            fields["cert_classification"] = None

        if result.cell_count is not None:
            fields["cell_count"] = float(result.cell_count)

        label = (size.size_label or "").strip().upper()
        rows.append(SizeRow(model_name=result.model_name, size_label=label, fields=fields))
    return rows


# ── URL → baseline name mapping ─────────────────────────────────────────────

# Advance uses different URL patterns: /alpha-series/alpha → "ALPHA"
_URL_NAME_MAP = {
    "alpha-series/alpha": "ALPHA",
    "alpha-series/alpha-dls": "ALPHA DLS",
    "epsilon-dls": "EPSILON DLS",
    "sigma-dls": "SIGMA DLS",
    "omega-uls": "OMEGA ULS",
    "pi-uls": "PI ULS",
    "bibeta-6": "BIBETA 6",
    "iota-dls": "IOTA DLS",
    "theta-uls": "THETA ULS",
    "tau-dls": "TAU DLS",
    "pibi": "PIBI",
}


def url_to_baseline_name(url: str, baseline: dict[str, list[SizeRow]]) -> str | None:
    path = url.rstrip("/")
    for suffix, name in _URL_NAME_MAP.items():
        if path.endswith(suffix):
            if name in baseline:
                return name
    # Fallback: slug-based
    slug = path.split("/")[-1]
    name_guess = slug.replace("-", " ").upper()
    for name in baseline:
        if name == name_guess:
            return name
    return None


# ── Comparison ──────────────────────────────────────────────────────────────

def compare_model(
    baseline_rows: list[SizeRow],
    extracted_rows: list[SizeRow],
    model_name: str,
    url: str,
) -> ModelResult:
    mr = ModelResult(model_name=model_name, url=url)
    mr.baseline_sizes = len(baseline_rows)
    mr.extracted_sizes = len(extracted_rows)

    baseline_by_size = {r.size_label: r for r in baseline_rows}
    extracted_by_size = {r.size_label: r for r in extracted_rows}

    all_labels = set(baseline_by_size.keys()) | set(extracted_by_size.keys())

    for label in sorted(all_labels):
        bl = baseline_by_size.get(label)
        ex = extracted_by_size.get(label)

        if bl and not ex:
            mr.mismatches.append(f"  {label}: missing from extraction")
            for nf in NUMERIC_FIELDS + CERT_FIELDS:
                if bl.fields.get(nf) is not None:
                    mr.fields_compared += 1
            continue

        if ex and not bl:
            mr.mismatches.append(f"  {label}: extra in extraction (not in baseline)")
            continue

        if not bl or not ex:
            continue

        for nf in NUMERIC_FIELDS:
            bl_val = bl.fields.get(nf)
            ex_val = ex.fields.get(nf)

            if bl_val is None and ex_val is None:
                continue

            mr.fields_compared += 1

            if bl_val is None and ex_val is not None:
                mr.fields_matched += 1
                continue

            if bl_val is not None and ex_val is None:
                mr.mismatches.append(f"  {label}/{nf}: baseline={bl_val}, extracted=None")
                continue

            if abs(bl_val - ex_val) <= NUMERIC_TOLERANCE:
                mr.fields_matched += 1
            else:
                mr.mismatches.append(
                    f"  {label}/{nf}: baseline={bl_val}, extracted={ex_val}"
                )

        for cf in CERT_FIELDS:
            bl_val = bl.fields.get(cf)
            ex_val = ex.fields.get(cf)

            if bl_val is None and ex_val is None:
                continue

            mr.fields_compared += 1

            if bl_val is not None and ex_val is not None:
                bl_norm = str(bl_val).strip().upper()
                ex_norm = str(ex_val).strip().upper()
                if bl_norm == ex_norm:
                    mr.fields_matched += 1
                else:
                    mr.mismatches.append(
                        f"  {label}/{cf}: baseline={bl_val}, extracted={ex_val}"
                    )
            elif bl_val is None and ex_val is not None:
                mr.fields_matched += 1
            else:
                mr.mismatches.append(
                    f"  {label}/{cf}: baseline={bl_val}, extracted=None"
                )

    return mr


# ── Main validation ─────────────────────────────────────────────────────────

def run_validation(urls: list[str], use_llm: bool = False) -> list[ModelResult]:
    baseline = load_baseline(BASELINE_CSV)
    logger.info("Loaded baseline: %d models, %d total rows",
                len(baseline), sum(len(v) for v in baseline.values()))

    config_path = Path(__file__).resolve().parent.parent / "config" / "manufacturers" / "advance.yaml"
    import yaml
    with open(config_path, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    adapter = None
    if use_llm:
        from src.adapters.ollama import OllamaAdapter
        adapter = OllamaAdapter()
        if not adapter.is_available():
            logger.error("Ollama not available")
            adapter = None

    crawler = Crawler()
    cache_dir = Path(__file__).resolve().parent.parent / "output" / "md_cache"
    results: list[ModelResult] = []

    for i, url in enumerate(urls, 1):
        baseline_name = url_to_baseline_name(url, baseline)
        slug = url.rstrip("/").split("/")[-1]
        display_name = baseline_name or slug

        logger.info("[%d/%d] %s (%s)", i, len(urls), display_name, url)

        # Try file cache first
        markdown = Crawler.load_markdown_cache(url, cache_dir)

        if not markdown:
            try:
                start = time.time()
                markdown = asyncio.run(crawler.render_page(url))
                crawl_time = time.time() - start
            except Exception as e:
                mr = ModelResult(model_name=display_name, url=url, error=str(e))
                results.append(mr)
                logger.error("  CRAWL ERROR: %s", e)
                continue

            if not markdown:
                mr = ModelResult(model_name=display_name, url=url, error="Empty markdown")
                results.append(mr)
                continue

            Crawler.save_markdown_cache(url, markdown, cache_dir)
            logger.info("  Crawled %d chars", len(markdown))
        else:
            logger.info("  Using cached markdown (%d chars)", len(markdown))

        # Extract
        start = time.time()
        result = extract_specs(adapter, markdown, config, url)
        extract_time = time.time() - start

        if not result:
            mr = ModelResult(model_name=display_name, url=url, error="Extraction returned None")
            results.append(mr)
            continue

        if not baseline_name:
            logger.warning("  No baseline match for %s", url)
            mr = ModelResult(model_name=display_name, url=url)
            mr.extracted_sizes = len(result.sizes)
            mr.error = "No baseline match"
            results.append(mr)
            continue

        bl_rows = baseline.get(baseline_name, [])
        ex_rows = extraction_to_size_rows(result)

        mr = compare_model(bl_rows, ex_rows, baseline_name, url)
        mr.extraction_time_s = extract_time
        results.append(mr)

        status = "PASS" if mr.match_pct >= 90 else "WARN" if mr.match_pct >= 70 else "FAIL"
        logger.info("  %s: %d/%d fields match (%.1f%%) — %d sizes vs %d baseline",
                     status, mr.fields_matched, mr.fields_compared, mr.match_pct,
                     mr.extracted_sizes, mr.baseline_sizes)

        if mr.mismatches:
            for m in mr.mismatches:
                logger.info("    %s", m)

    return results


def print_summary(results: list[ModelResult], strategy: str) -> None:
    print(f"\n{'='*70}")
    print(f"  Advance Validation — {strategy}")
    print(f"{'='*70}\n")

    total_compared = 0
    total_matched = 0

    for mr in results:
        if mr.error:
            print(f"  {mr.model_name:25s}  ERROR: {mr.error}")
            continue

        status = "PASS" if mr.match_pct >= 90 else "WARN" if mr.match_pct >= 70 else "FAIL"
        print(f"  {mr.model_name:25s}  {status}  {mr.fields_matched:3d}/{mr.fields_compared:3d} "
              f"({mr.match_pct:5.1f}%)  sizes: {mr.extracted_sizes}/{mr.baseline_sizes}")
        total_compared += mr.fields_compared
        total_matched += mr.fields_matched

    overall = 100.0 * total_matched / total_compared if total_compared else 0
    print(f"\n  {'OVERALL':25s}       {total_matched:3d}/{total_compared:3d} ({overall:5.1f}%)")
    print(f"{'='*70}\n")


def main():
    parser = argparse.ArgumentParser(description="Advance validation run")
    parser.add_argument("--llm", action="store_true", help="Include LLM extraction")
    parser.add_argument("--model", type=str, help="Test specific model slug")
    args = parser.parse_args()

    urls = VALIDATION_URLS
    if args.model:
        urls = [u for u in urls if args.model.lower() in u.lower()]
        if not urls:
            print(f"No URL matches '{args.model}'")
            sys.exit(1)

    # Markdown parser validation
    results_md = run_validation(urls, use_llm=False)
    print_summary(results_md, "Markdown Parser")

    if args.llm:
        results_llm = run_validation(urls, use_llm=True)
        print_summary(results_llm, "LLM (Ollama)")


if __name__ == "__main__":
    main()
