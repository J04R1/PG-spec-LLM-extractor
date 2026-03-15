#!/usr/bin/env python3
"""
Iteration 07 — Ozone Validation Run

Validates the pipeline with a 10-model sample, comparing extraction results
against the known-good POC baseline (data/ozone_enrichment.csv).

Usage:
    # Markdown parser only (no Ollama needed):
    python -m tests.validate_ozone

    # Include LLM comparison (requires Ollama running):
    python -m tests.validate_ozone --llm

    # Specific model only:
    python -m tests.validate_ozone --model moxie
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

# Add project root to path
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
logger = logging.getLogger("validate_ozone")

# ── Validation sample ───────────────────────────────────────────────────────

VALIDATION_URLS = [
    "https://flyozone.com/paragliders/products/gliders/moxie",
    "https://flyozone.com/paragliders/products/gliders/buzz-z7",
    "https://flyozone.com/paragliders/products/gliders/delta-5",
    "https://flyozone.com/paragliders/products/gliders/zeno-2",
    "https://flyozone.com/paragliders/products/gliders/enzo-3",
    "https://flyozone.com/paragliders/products/gliders/ultralite-5",
    "https://flyozone.com/paragliders/products/gliders/magnum-4",
    "https://flyozone.com/paragliders/products/gliders/session",
    "https://flyozone.com/paragliders/products/gliders/buzz-z6",
    "https://flyozone.com/paragliders/products/gliders/mantra-m7",
]

BASELINE_CSV = Path(__file__).resolve().parent.parent / "data" / "ozone_enrichment.csv"

# Fields to compare (numeric spec fields)
NUMERIC_FIELDS = [
    "flat_area_m2", "flat_span_m", "flat_aspect_ratio",
    "proj_area_m2", "proj_span_m", "proj_aspect_ratio",
    "wing_weight_kg", "ptv_min_kg", "ptv_max_kg",
]

CERT_FIELDS = ["cert_standard", "cert_classification"]

# Tolerance for floating-point comparison (0.1 allows rounding differences)
NUMERIC_TOLERANCE = 0.1


# ── Data structures ─────────────────────────────────────────────────────────

@dataclass
class SizeRow:
    """One (model × size) row from the baseline or extraction."""
    model_name: str
    size_label: str
    fields: dict[str, float | str | None] = field(default_factory=dict)


@dataclass
class ModelResult:
    """Comparison result for a single model."""
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
    """Load POC baseline CSV into {model_name: [SizeRow, ...]}.

    Deduplicates by (name, size_label) — the baseline CSV may have each size
    twice when a model appears on both current and previous listing pages.
    """
    baseline: dict[str, list[SizeRow]] = {}
    seen: set[tuple[str, str]] = set()

    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row.get("name", "").strip()
            if not name:
                continue

            size_label = row.get("size_label", "").strip()

            # Deduplicate by (model, size)
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

            # Also store cell_count at model level (same for all sizes)
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
    """Convert an ExtractionResult into comparable SizeRow list."""
    rows = []
    for size in result.sizes:
        fields: dict[str, float | str | None] = {}

        for nf in NUMERIC_FIELDS:
            val = getattr(size, nf, None)
            fields[nf] = float(val) if val is not None else None

        # Normalize certification
        cert_str = size.certification or ""
        if cert_str:
            standard, classification = normalize_certification(cert_str)
            fields["cert_standard"] = standard.value
            fields["cert_classification"] = classification
        else:
            fields["cert_standard"] = None
            fields["cert_classification"] = None

        # Cell count from model level
        if result.cell_count is not None:
            fields["cell_count"] = float(result.cell_count)

        label = (size.size_label or "").strip().upper()
        rows.append(SizeRow(model_name=result.model_name, size_label=label, fields=fields))

    return rows


# ── Comparison ──────────────────────────────────────────────────────────────

def compare_model(
    baseline_rows: list[SizeRow],
    extracted_rows: list[SizeRow],
    model_name: str,
    url: str,
) -> ModelResult:
    """Compare extracted rows against baseline for one model."""
    mr = ModelResult(model_name=model_name, url=url)
    mr.baseline_sizes = len(baseline_rows)
    mr.extracted_sizes = len(extracted_rows)

    # Match by size_label
    baseline_by_size = {r.size_label: r for r in baseline_rows}
    extracted_by_size = {r.size_label: r for r in extracted_rows}

    all_labels = set(baseline_by_size.keys()) | set(extracted_by_size.keys())

    for label in sorted(all_labels):
        bl = baseline_by_size.get(label)
        ex = extracted_by_size.get(label)

        if bl and not ex:
            mr.mismatches.append(f"  {label}: missing from extraction")
            # Count all baseline fields as missed
            for nf in NUMERIC_FIELDS + CERT_FIELDS:
                if bl.fields.get(nf) is not None:
                    mr.fields_compared += 1
            continue

        if ex and not bl:
            mr.mismatches.append(f"  {label}: extra in extraction (not in baseline)")
            continue

        if not bl or not ex:
            continue

        # Compare numeric fields
        for nf in NUMERIC_FIELDS:
            bl_val = bl.fields.get(nf)
            ex_val = ex.fields.get(nf)

            if bl_val is None and ex_val is None:
                continue  # Both empty — not a field to compare

            mr.fields_compared += 1

            if bl_val is None and ex_val is not None:
                mr.fields_matched += 1  # Extraction found more data — acceptable
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

        # Compare cert fields
        for cf in CERT_FIELDS:
            bl_val = bl.fields.get(cf)
            ex_val = ex.fields.get(cf)

            if bl_val is None and ex_val is None:
                continue

            mr.fields_compared += 1

            if bl_val is not None and ex_val is not None:
                # Normalize for comparison (e.g., "EN-C" vs "C")
                bl_norm = str(bl_val).strip().upper()
                ex_norm = str(ex_val).strip().upper()
                if bl_norm == ex_norm:
                    mr.fields_matched += 1
                else:
                    mr.mismatches.append(
                        f"  {label}/{cf}: baseline={bl_val}, extracted={ex_val}"
                    )
            elif bl_val is None and ex_val is not None:
                mr.fields_matched += 1  # Extra data is acceptable
            else:
                mr.mismatches.append(
                    f"  {label}/{cf}: baseline={bl_val}, extracted=None"
                )

    return mr


# ── URL → model name mapping ────────────────────────────────────────────────

def url_to_baseline_name(url: str, baseline: dict[str, list[SizeRow]]) -> str | None:
    """Map a URL to the matching baseline model name."""
    slug = url.rstrip("/").split("/")[-1]
    # Convert slug to title case: "buzz-z7" → "Buzz Z7"
    name_guess = slug.replace("-", " ").title()

    # Try exact match
    if name_guess in baseline:
        return name_guess

    # Try case-insensitive match
    for name in baseline:
        if name.lower() == name_guess.lower():
            return name

    # Try slug-based fuzzy match
    for name in baseline:
        name_slug = name.lower().replace(" ", "-")
        if name_slug == slug:
            return name

    return None


# ── Main validation ─────────────────────────────────────────────────────────

def run_validation(
    urls: list[str],
    use_llm: bool = False,
    markdown_cache: dict[str, str] | None = None,
) -> tuple[list[ModelResult], dict[str, str]]:
    """Run extraction on each URL and compare against baseline.

    Args:
        urls: URLs to validate.
        use_llm: Whether to use Ollama LLM adapter.
        markdown_cache: Pre-crawled {url: markdown} dict. URLs found here
            won't be re-crawled, avoiding duplicate requests.

    Returns:
        (results, updated_cache) — results plus the cache with any
        newly crawled markdown added.
    """
    if markdown_cache is None:
        markdown_cache = {}

    baseline = load_baseline(BASELINE_CSV)
    logger.info("Loaded baseline: %d models, %d total rows",
                len(baseline), sum(len(v) for v in baseline.values()))

    # Load config for extraction
    config_path = Path(__file__).resolve().parent.parent / "config" / "manufacturers" / "ozone.yaml"
    if config_path.exists():
        import yaml
        with open(config_path, encoding="utf-8") as f:
            config = yaml.safe_load(f)
    else:
        config = {}

    # Set up adapter
    adapter = None
    if use_llm:
        from src.adapters.ollama import OllamaAdapter
        adapter = OllamaAdapter()
        if not adapter.is_available():
            logger.error("Ollama not available — run: ollama serve && ollama pull qwen2.5:3b")
            logger.info("Falling back to markdown parser only")
            adapter = None

    crawler = Crawler()
    # Use file-based cache dir for persistence across runs
    cache_dir = Path(__file__).resolve().parent.parent / "output" / "md_cache"
    results: list[ModelResult] = []

    for i, url in enumerate(urls, 1):
        baseline_name = url_to_baseline_name(url, baseline)
        slug = url.rstrip("/").split("/")[-1]
        display_name = baseline_name or slug

        logger.info("[%d/%d] %s (%s)", i, len(urls), display_name, url)

        # Check in-memory cache first, then file cache, then crawl
        markdown = markdown_cache.get(url)
        if markdown:
            logger.info("  Using in-memory cached markdown (%d chars)", len(markdown))
        else:
            markdown = Crawler.load_markdown_cache(url, cache_dir)

        if not markdown:
            # Actually crawl — only happens once per URL
            try:
                start = time.time()
                markdown = asyncio.run(crawler.render_page(url))
                render_time = time.time() - start
            except Exception as e:
                mr = ModelResult(model_name=display_name, url=url, error=f"Render failed: {e}")
                results.append(mr)
                continue

            if not markdown:
                mr = ModelResult(model_name=display_name, url=url, error="Empty markdown")
                results.append(mr)
                continue

            logger.info("  Rendered %d chars in %.1fs", len(markdown), render_time)
            # Save to both caches
            Crawler.save_markdown_cache(url, markdown, cache_dir)
        
        markdown_cache[url] = markdown

        # Extract
        start = time.time()
        result = extract_specs(adapter, markdown, config, url=url)
        extract_time = time.time() - start

        if not result:
            mr = ModelResult(model_name=display_name, url=url, error="Extraction returned None")
            results.append(mr)
            continue

        logger.info("  Extracted: %s — %d sizes in %.1fs",
                     result.model_name, len(result.sizes), extract_time)

        # Compare
        extracted_rows = extraction_to_size_rows(result)
        baseline_rows = baseline.get(baseline_name, []) if baseline_name else []

        if not baseline_rows:
            logger.warning("  No baseline data for %s — skipping comparison", display_name)
            mr = ModelResult(
                model_name=result.model_name, url=url,
                extracted_sizes=len(result.sizes),
                extraction_time_s=extract_time,
            )
            results.append(mr)
            continue

        mr = compare_model(baseline_rows, extracted_rows, result.model_name, url)
        mr.extraction_time_s = extract_time
        results.append(mr)

    return results, markdown_cache


def print_report(results: list[ModelResult], strategy: str) -> None:
    """Print a summary report of validation results."""
    print(f"\n{'=' * 72}")
    print(f"  OZONE VALIDATION REPORT — {strategy}")
    print(f"{'=' * 72}\n")

    total_compared = 0
    total_matched = 0
    total_sizes_bl = 0
    total_sizes_ex = 0
    total_time = 0.0

    for mr in results:
        status = "OK" if mr.match_pct >= 95 else ("WARN" if mr.match_pct >= 80 else "FAIL")
        if mr.error:
            status = "ERR"

        print(f"  [{status:4s}] {mr.model_name:<20s}  "
              f"sizes: {mr.baseline_sizes}→{mr.extracted_sizes}  "
              f"fields: {mr.fields_matched}/{mr.fields_compared} "
              f"({mr.match_pct:.0f}%)  "
              f"{mr.extraction_time_s:.1f}s")

        if mr.error:
            print(f"         Error: {mr.error}")

        if mr.mismatches:
            for m in mr.mismatches:
                print(f"         {m}")

        total_compared += mr.fields_compared
        total_matched += mr.fields_matched
        total_sizes_bl += mr.baseline_sizes
        total_sizes_ex += mr.extracted_sizes
        total_time += mr.extraction_time_s

    pct = 100.0 * total_matched / total_compared if total_compared else 0.0
    discrepancy = 100.0 - pct

    print(f"\n{'─' * 72}")
    print(f"  TOTALS:")
    print(f"    Models:      {len(results)}")
    print(f"    Size rows:   {total_sizes_bl} baseline → {total_sizes_ex} extracted")
    print(f"    Fields:      {total_matched}/{total_compared} matched ({pct:.1f}%)")
    print(f"    Discrepancy: {discrepancy:.1f}%")
    print(f"    Total time:  {total_time:.1f}s")
    print(f"    TARGET:      ≤5% discrepancy → {'PASS ✓' if discrepancy <= 5 else 'FAIL ✗'}")
    print(f"{'─' * 72}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Ozone validation run (Iteration 07)")
    parser.add_argument("--llm", action="store_true", help="Also test with Ollama LLM")
    parser.add_argument("--model", type=str, help="Test a specific model slug (e.g. moxie)")
    parser.add_argument("--output", type=str, help="Save results JSON to file")
    args = parser.parse_args()

    urls = VALIDATION_URLS
    if args.model:
        slug = args.model.lower().strip()
        urls = [u for u in urls if u.rstrip("/").split("/")[-1] == slug]
        if not urls:
            print(f"Model '{args.model}' not in validation sample. Available:")
            for u in VALIDATION_URLS:
                print(f"  {u.split('/')[-1]}")
            sys.exit(1)

    # Run markdown parser validation (crawls pages, populates cache)
    print("\n▶ Running markdown parser validation...")
    md_results, md_cache = run_validation(urls, use_llm=False)
    print_report(md_results, "MARKDOWN PARSER")

    # Run LLM validation if requested — reuses cached markdown, zero re-crawling
    llm_results = None
    if args.llm:
        print("\n▶ Running LLM (Ollama) validation (using cached markdown — no re-crawl)...")
        llm_results, _ = run_validation(urls, use_llm=True, markdown_cache=md_cache)
        print_report(llm_results, "LLM (Qwen2.5:3B)")

    # Save results if requested
    if args.output:
        output = {
            "markdown": [
                {
                    "model": r.model_name, "url": r.url,
                    "baseline_sizes": r.baseline_sizes,
                    "extracted_sizes": r.extracted_sizes,
                    "fields_compared": r.fields_compared,
                    "fields_matched": r.fields_matched,
                    "match_pct": round(r.match_pct, 1),
                    "time_s": round(r.extraction_time_s, 1),
                    "error": r.error,
                    "mismatches": r.mismatches,
                }
                for r in md_results
            ],
        }
        if llm_results:
            output["llm"] = [
                {
                    "model": r.model_name, "url": r.url,
                    "baseline_sizes": r.baseline_sizes,
                    "extracted_sizes": r.extracted_sizes,
                    "fields_compared": r.fields_compared,
                    "fields_matched": r.fields_matched,
                    "match_pct": round(r.match_pct, 1),
                    "time_s": round(r.extraction_time_s, 1),
                    "error": r.error,
                    "mismatches": r.mismatches,
                }
                for r in llm_results
            ]
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(output, indent=2, fp=f)
        print(f"Results saved to {args.output}")


if __name__ == "__main__":
    main()
