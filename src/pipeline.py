"""
Pipeline orchestrator — CLI entry point.

Wires all modules together: config → crawl → extract → normalize → store.
Uses Typer for the CLI interface.

Usage:
    python -m src.pipeline run --config config/manufacturers/ozone.yaml
    python -m src.pipeline run --url https://flyozone.com/.../rush-5
    python -m src.pipeline status
"""

from __future__ import annotations

import asyncio
import csv
import json
import logging
import sys
from pathlib import Path

import typer
from dotenv import load_dotenv

from .adapters.ollama import OllamaAdapter
from .benchmark import benchmark_database
from .config import load_config, get_output_paths
from .crawler import Crawler, deduplicate_urls
from .db import Database
from .extractor import extract_specs
from .models import ExtractionResult, Manufacturer, TargetUse
from .normalizer import normalize_certification, normalize_extraction
from .seed_import import import_enrichment_csv

load_dotenv()

app = typer.Typer(
    name="pg-extract",
    help="Paraglider spec extraction pipeline",
    no_args_is_help=True,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


@app.command()
def run(
    config: str = typer.Option(None, "--config", "-c", help="Path to manufacturer YAML config"),
    url: str = typer.Option(None, "--url", "-u", help="Single URL to extract (test mode)"),
    map_only: bool = typer.Option(False, "--map-only", help="URL discovery only — no extraction"),
    convert_only: bool = typer.Option(False, "--convert-only", help="JSON → CSV conversion only"),
    retry_failed: bool = typer.Option(False, "--retry-failed", help="Re-extract failed URLs"),
    refresh_urls: bool = typer.Option(False, "--refresh-urls", help="Clear URL cache before discovery"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would happen without making requests"),
) -> None:
    """Run the extraction pipeline."""
    if not config and not url:
        typer.echo("ERROR: Provide --config or --url", err=True)
        raise typer.Exit(1)

    if url:
        cfg = load_config(config) if config else None
        _run_single_url(url, dry_run=dry_run, config=cfg)
        return

    cfg = load_config(config)  # type: ignore[arg-type]
    slug = cfg["manufacturer"]["slug"]
    paths = get_output_paths(slug)

    logger.info("Pipeline: %s (%s)", cfg["manufacturer"]["name"], slug)
    logger.info("Output:   %s", paths["raw_json"])

    if map_only:
        all_urls, url_metadata = _discover_all_urls(cfg, paths, refresh=refresh_urls)
        typer.echo(f"\nDiscovered {len(all_urls)} product URLs total")
        for url in all_urls:
            meta = url_metadata.get(url, {})
            current_flag = " [current]" if meta.get("is_current") else ""
            typer.echo(f"  {url}{current_flag}")
        raise typer.Exit(0)

    if convert_only:
        raw_json_path = Path(paths["raw_json"])
        if not raw_json_path.exists():
            typer.echo(f"ERROR: No raw JSON at {raw_json_path}", err=True)
            raise typer.Exit(1)
        with open(raw_json_path, encoding="utf-8") as f:
            results = json.load(f)
        _store_to_db(results, Path(paths["db"]), cfg)
        _export_csv(results, Path(paths["csv"]), slug)
        typer.echo(
            f"Converted {len(results)} records → DB + CSV"
        )
        raise typer.Exit(0)

    # Full pipeline: discover → extract → normalize → store
    all_urls, url_metadata = _discover_all_urls(cfg, paths, refresh=refresh_urls)
    if not all_urls:
        typer.echo("No product URLs found — nothing to extract.")
        raise typer.Exit(0)

    # --retry-failed: copy finalized results to partial so _extract_all
    # re-processes URLs that didn't produce results last time
    if retry_failed:
        raw_json_path = Path(paths["raw_json"])
        partial_path = Path(paths["partial"])
        if raw_json_path.exists() and not partial_path.exists():
            import shutil
            shutil.copy2(raw_json_path, partial_path)
            logger.info("Loaded %s as partial for retry", raw_json_path)

    adapter = None
    if not dry_run:
        adapter = _get_adapter()
        if not adapter:
            logger.info("Ollama unavailable — will use markdown parser fallback")

    _extract_all(adapter, cfg, all_urls, url_metadata, paths, dry_run=dry_run)


@app.command()
def status() -> None:
    """Show extraction status for all known manufacturers."""
    config_dir = Path("config/manufacturers")
    if not config_dir.exists():
        typer.echo("No manufacturer configs found.")
        return

    for yaml_file in sorted(config_dir.glob("*.yaml")):
        cfg = load_config(str(yaml_file))
        slug = cfg["manufacturer"]["slug"]
        name = cfg["manufacturer"]["name"]
        paths = get_output_paths(slug)

        raw_json_path = Path(paths["raw_json"])
        partial_path = Path(paths["partial"])
        csv_path = Path(paths["csv"])
        db_path = Path(paths["db"])

        model_count = 0
        if raw_json_path.exists():
            with open(raw_json_path, encoding="utf-8") as f:
                model_count = len(json.load(f))

        partial_count = 0
        if partial_path.exists():
            with open(partial_path, encoding="utf-8") as f:
                partial_count = len(json.load(f))

        typer.echo(f"\n{name} ({slug}):")
        typer.echo(f"  Raw JSON:  {model_count} models" if raw_json_path.exists() else "  Raw JSON:  —")
        if partial_path.exists():
            typer.echo(f"  Partial:   {partial_count} models (in progress)")
        typer.echo(f"  CSV:       {'✓' if csv_path.exists() else '—'}")
        typer.echo(f"  SQLite DB: {'✓' if db_path.exists() else '—'}")


@app.command()
def reset(
    config: str = typer.Option(..., "--config", "-c", help="Path to manufacturer YAML config"),
) -> None:
    """Clear partial/cache files for a manufacturer."""
    cfg = load_config(config)
    slug = cfg["manufacturer"]["slug"]
    paths = get_output_paths(slug)

    for key in ("partial", "urls"):
        p = paths[key]
        if p.exists():
            p.unlink()
            typer.echo(f"Removed: {p}")
        else:
            typer.echo(f"Not found: {p}")


@app.command()
def seed(
    csv_file: str = typer.Option(..., "--csv", help="Path to enrichment CSV"),
    db_path: str = typer.Option("output/seed.db", "--db", help="Output database path"),
    method: str = typer.Option("llm_enrichment_csv", "--method", help="Extraction method label"),
) -> None:
    """Import an enrichment CSV as seed data into the database."""
    csv_p = Path(csv_file)
    if not csv_p.exists():
        typer.echo(f"ERROR: CSV not found: {csv_p}", err=True)
        raise typer.Exit(1)

    db = Database(db_path)
    db.connect()
    try:
        counts = import_enrichment_csv(csv_p, db, extraction_method=method)
    finally:
        db.close()

    typer.echo(f"Imported from {csv_p.name}:")
    for key, val in counts.items():
        typer.echo(f"  {key}: {val}")
    typer.echo(f"Database: {db_path}")


@app.command()
def benchmark(
    db_path: str = typer.Option(..., "--db", help="Path to database to benchmark"),
    json_output: bool = typer.Option(False, "--json", help="Output JSON instead of text"),
) -> None:
    """Score a database for completeness, quality, and accuracy."""
    db_p = Path(db_path)
    if not db_p.exists():
        typer.echo(f"ERROR: Database not found: {db_p}", err=True)
        raise typer.Exit(1)

    report = benchmark_database(db_p)

    if json_output:
        import json as json_mod
        typer.echo(json_mod.dumps(report.summary(), indent=2))
    else:
        typer.echo(report.format_report())


def _run_single_url(url: str, dry_run: bool = False, config: dict | None = None) -> None:
    """Extract specs from a single URL (test mode)."""
    if dry_run:
        typer.echo(f"DRY RUN: Would extract from {url}")
        return

    crawler = Crawler()
    markdown = asyncio.run(crawler.render_page(url))
    if not markdown:
        typer.echo(f"Failed to render: {url}")
        raise typer.Exit(1)

    typer.echo(f"Rendered {len(markdown)} chars of markdown from {url}")

    adapter = _get_adapter()
    # adapter may be None — extract_specs will fallback to markdown parser

    cfg = config or {}
    result = extract_specs(adapter, markdown, cfg, url=url)
    if not result:
        typer.echo("Extraction failed — no valid data returned")
        raise typer.Exit(1)

    output = result.model_dump(exclude_none=True)
    typer.echo(json.dumps(output, indent=2))


def _get_adapter() -> OllamaAdapter | None:
    """Create and verify an OllamaAdapter instance."""
    adapter = OllamaAdapter()
    if not adapter.is_available():
        typer.echo(
            "ERROR: Ollama not available. Start with: ollama serve\n"
            f"Then pull the model: ollama pull {adapter.model}",
            err=True,
        )
        return None
    logger.info("Using %s via Ollama at %s", adapter.model, adapter.endpoint)
    return adapter


def _extract_all(
    adapter: OllamaAdapter | None,
    cfg: dict,
    urls: list[str],
    url_metadata: dict[str, dict],
    paths: dict,
    dry_run: bool = False,
) -> None:
    """Extract specs from all discovered URLs with crash recovery."""
    partial_path = paths["partial"]
    raw_json_path = paths["raw_json"]

    # Load partial progress if exists
    results: list[dict] = Crawler.load_partial(partial_path) or []
    done_urls = {r["product_url"] for r in results if r.get("product_url")}
    remaining = [u for u in urls if u not in done_urls]

    if done_urls:
        logger.info("Resuming: %d already done, %d remaining", len(done_urls), len(remaining))

    if not remaining:
        typer.echo("All URLs already extracted.")
        _finalize_results(results, raw_json_path)
        return

    crawler = Crawler()
    total = len(urls)
    failed = 0

    for i, url in enumerate(remaining, start=len(done_urls) + 1):
        meta = url_metadata.get(url, {})
        logger.info("[%d/%d] %s", i, total, url)

        if dry_run:
            typer.echo(f"  DRY RUN: would extract {url}")
            continue

        markdown = asyncio.run(crawler.render_page(url))
        if not markdown:
            logger.warning("  Failed to render — skipping")
            failed += 1
            continue

        result = extract_specs(adapter, markdown, cfg, url=url)
        if not result:
            logger.warning("  Extraction failed — skipping")
            failed += 1
            continue

        record = result.model_dump(exclude_none=True)
        # Attach metadata from discovery
        if meta.get("is_current") is not None:
            record["is_current"] = meta["is_current"]

        results.append(record)
        Crawler.save_partial(results, partial_path)

        logger.info(
            "  Extracted: %s — %d sizes",
            result.model_name,
            len(result.sizes),
        )

    if not dry_run:
        _finalize_results(results, raw_json_path)

        # Normalize → SQLite + CSV
        slug = cfg["manufacturer"]["slug"]
        _store_to_db(results, Path(paths["db"]), cfg)
        _export_csv(results, Path(paths["csv"]), slug)

        typer.echo(
            f"\nExtraction complete: {len(results)} succeeded, {failed} failed"
        )
        # Clean up partial file
        if partial_path.exists():
            partial_path.unlink()


def _finalize_results(results: list[dict], output_path: Path) -> None:
    """Write final results JSON."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    logger.info("Saved %d results to %s", len(results), output_path)


# ── CSV export ─────────────────────────────────────────────────────────────────

_CSV_COLUMNS = [
    "manufacturer_slug", "name", "year", "category", "target_use", "is_current",
    "cell_count", "line_material", "riser_config", "manufacturer_url",
    "size_label", "flat_area_m2", "flat_span_m", "flat_aspect_ratio",
    "proj_area_m2", "proj_span_m", "proj_aspect_ratio",
    "wing_weight_kg", "ptv_min_kg", "ptv_max_kg",
    "speed_trim_kmh", "speed_max_kmh", "glide_ratio_best", "min_sink_ms",
    "cert_standard", "cert_classification",
]


def _export_csv(results: list[dict], csv_path: Path, manufacturer_slug: str) -> None:
    """Flatten extraction results to one CSV row per (model × size)."""
    rows: list[dict] = []

    for model in results:
        model_name = model.get("model_name", "").strip()
        if not model_name:
            continue
        sizes = model.get("sizes", [])
        if not sizes:
            continue

        model_fields = {
            "manufacturer_slug": manufacturer_slug,
            "name": model_name,
            "category": model.get("category", ""),
            "target_use": model.get("target_use", ""),
            "is_current": str(model.get("is_current", True)).lower(),
            "cell_count": model.get("cell_count", ""),
            "line_material": model.get("line_material", ""),
            "riser_config": model.get("riser_config", ""),
            "manufacturer_url": model.get("product_url", ""),
        }

        for size in sizes:
            row: dict = {col: "" for col in _CSV_COLUMNS}
            row.update(model_fields)

            for field in (
                "size_label", "flat_area_m2", "flat_span_m", "flat_aspect_ratio",
                "proj_area_m2", "proj_span_m", "proj_aspect_ratio",
                "wing_weight_kg", "ptv_min_kg", "ptv_max_kg",
                "speed_trim_kmh", "speed_max_kmh", "glide_ratio_best", "min_sink_ms",
            ):
                val = size.get(field, "")
                if isinstance(val, float):
                    row[field] = str(int(val)) if val == int(val) else str(val)
                elif isinstance(val, int):
                    row[field] = str(val)
                else:
                    row[field] = val

            cert = size.get("certification", "")
            if cert:
                standard, classification = normalize_certification(cert)
                row["cert_standard"] = standard.value
                row["cert_classification"] = classification

            rows.append(row)

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    logger.info("Exported %d CSV rows to %s", len(rows), csv_path)


# ── SQLite storage ─────────────────────────────────────────────────────────────


def _store_to_db(
    results: list[dict],
    db_path: Path,
    cfg: dict,
) -> None:
    """Normalize extraction results and store in SQLite with provenance."""
    mfr_cfg = cfg["manufacturer"]
    manufacturer_slug = mfr_cfg["slug"]

    db = Database(db_path)
    db.connect()

    try:
        # Ensure manufacturer exists
        mfr = Manufacturer(
            name=mfr_cfg["name"],
            slug=manufacturer_slug,
            country_code=mfr_cfg.get("country"),
            website=mfr_cfg.get("website"),
        )
        mfr_id = db.upsert_manufacturer(mfr)

        stored = 0
        for record in results:
            model_name = record.get("model_name", "").strip()
            if not model_name or not record.get("sizes"):
                continue

            extraction = ExtractionResult.model_validate(record)
            is_current = record.get("is_current", True)
            source_url = record.get("product_url")

            wing, sizes, certs, perfs = normalize_extraction(
                extraction, manufacturer_slug,
                is_current=is_current, source_url=source_url,
            )

            model_id = db.upsert_model(wing, mfr_id)

            # Store target_use from extraction (single → junction table)
            if extraction.target_use:
                try:
                    target = TargetUse(extraction.target_use)
                    db.upsert_model_target_use(model_id, target)
                except ValueError:
                    pass

            # Record provenance
            db.record_provenance(
                model_id, source_url, manufacturer_slug,
            )

            for i, sv in enumerate(sizes):
                sv_id = db.upsert_size_variant(sv, model_id)

                if i < len(certs):
                    db.insert_certification(certs[i], sv_id)

                if i < len(perfs):
                    db.insert_performance_data(perfs[i], sv_id)

            stored += 1

        logger.info("Stored %d models in %s", stored, db_path)
    finally:
        db.close()


def _discover_all_urls(
    cfg: dict,
    paths: dict,
    refresh: bool = False,
) -> tuple[list[str], dict[str, dict]]:
    """Discover URLs from all sources in the config, with cross-source dedup."""
    sources = cfg.get("sources", {})
    if not sources:
        logger.warning("No sources defined in config")
        return [], {}

    cache_path = paths.get("urls")
    if refresh and cache_path and cache_path.exists():
        cache_path.unlink()
        logger.info("Cleared URL cache: %s", cache_path)

    crawler = Crawler()
    url_groups: dict[str, list[str]] = {}

    for source_key, source_cfg in sources.items():
        label = source_key.replace("_", " ")
        logger.info("Discovering URLs for: %s", label)

        urls = asyncio.run(
            crawler.discover_urls(source_key, source_cfg, cache_path=cache_path)
        )
        url_groups[source_key] = urls

        if urls:
            logger.info("  %s: %d product URLs", label, len(urls))
        else:
            logger.warning("  %s: no product URLs found", label)

    return deduplicate_urls(url_groups, sources)


if __name__ == "__main__":
    app()
