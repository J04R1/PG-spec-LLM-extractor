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
from .validator import (
    Action,
    ValidationLog,
    format_model_issues,
    format_validation_summary,
    validate_database,
)

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
    url: str = typer.Option(None, "--url", "-u", help="Single URL to extract"),
    db_path: str = typer.Option(None, "--db", help="Database to store results (required with --url)"),
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
        _run_single_url(url, dry_run=dry_run, config=cfg, db_path=db_path)
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


@app.command()
def validate(
    db_path: str = typer.Option(..., "--db", help="Path to database to validate"),
    resume: bool = typer.Option(False, "--resume", help="Resume from previous validation log"),
    auto_skip: bool = typer.Option(False, "--auto-skip", help="Auto-skip all issues (non-interactive)"),
    show_clean: bool = typer.Option(False, "--show-clean", help="Also show models with no issues"),
) -> None:
    """Validate data quality and prompt for actions on problematic models."""
    db_p = Path(db_path)
    if not db_p.exists():
        typer.echo(f"ERROR: Database not found: {db_p}", err=True)
        raise typer.Exit(1)

    log_path = db_p.with_suffix(".validation.json")

    if resume and log_path.exists():
        vlog = ValidationLog.load(log_path)
        typer.echo(f"Resumed validation log from {log_path.name}")
        typer.echo(f"  Previous run: {vlog.timestamp}")
    else:
        typer.echo(f"Validating {db_p.name}...")
        vlog = validate_database(db_p)

    typer.echo(format_validation_summary(vlog))
    typer.echo("")

    pending = vlog.pending_models
    if not pending:
        typer.echo("No models pending review.")
        _show_re_extract_summary(vlog)
        return

    typer.echo(f"{len(pending)} model(s) need review:\n")

    for i, mv in enumerate(pending, 1):
        typer.echo(format_model_issues(mv))
        typer.echo("")

        if auto_skip:
            mv.action = Action.skip
            vlog.save()
            continue

        # Interactive prompt
        typer.echo("  Actions:")
        typer.echo("    [r] Re-extract — re-crawl and re-extract this model")
        typer.echo("    [s] Skip — accept data as-is")
        typer.echo("    [m] Manual fix — mark for manual correction later")
        typer.echo("    [q] Quit — save progress and exit")

        while True:
            choice = typer.prompt(f"  ({i}/{len(pending)}) Choose action", default="s")
            choice = choice.strip().lower()
            if choice == "r":
                mv.action = Action.re_extract
                typer.echo("  → Marked for re-extraction")
                break
            elif choice == "s":
                mv.action = Action.skip
                typer.echo("  → Skipped")
                break
            elif choice == "m":
                mv.action = Action.manual_fix
                typer.echo("  → Marked for manual fix")
                break
            elif choice == "q":
                vlog.save()
                typer.echo(f"\nProgress saved to {log_path.name}")
                typer.echo("Resume with: --resume")
                _show_re_extract_summary(vlog)
                raise typer.Exit(0)
            else:
                typer.echo("  Invalid choice. Use r/s/m/q.")

        # Save after each decision so progress survives crashes
        vlog.save()

    typer.echo(f"\nValidation complete. Log saved to {log_path.name}")
    _show_re_extract_summary(vlog)


@app.command()
def fix(
    db_path: str = typer.Option(..., "--db", help="Path to database"),
    model_slug: str = typer.Option(None, "--model", "-m", help="Specific model slug to fix"),
    config: str = typer.Option(None, "--config", "-c", help="Manufacturer config YAML"),
) -> None:
    """Re-extract a model from its URL, preview changes, then confirm before writing to DB."""
    db_p = Path(db_path)
    if not db_p.exists():
        typer.echo(f"ERROR: Database not found: {db_p}", err=True)
        raise typer.Exit(1)

    log_path = db_p.with_suffix(".validation.json")

    # Pick the model to fix
    if model_slug:
        # Direct slug provided
        url, mfr_slug, model_name = _lookup_model_url(db_p, model_slug)
    elif log_path.exists():
        # Pick from validation log — first pending model with issues
        vlog = ValidationLog.load(log_path)
        pending = vlog.pending_models
        if not pending:
            typer.echo("No models pending review in validation log.")
            raise typer.Exit(0)

        # Show list and let user pick
        typer.echo(f"{len(pending)} model(s) with issues:\n")
        for i, mv in enumerate(pending[:20], 1):
            sev = mv.score
            typer.echo(f"  {i:2d}. {sev} {mv.model_name} — {len(mv.issues)} issues")

        if len(pending) > 20:
            typer.echo(f"  ... and {len(pending) - 20} more")

        choice = typer.prompt("\nPick a number (or q to quit)", default="1")
        if choice.strip().lower() == "q":
            raise typer.Exit(0)
        try:
            idx = int(choice) - 1
            if not (0 <= idx < len(pending)):
                typer.echo("Invalid choice.")
                raise typer.Exit(1)
        except ValueError:
            typer.echo("Invalid choice.")
            raise typer.Exit(1)

        selected = pending[idx]
        model_slug = selected.model_slug
        url = selected.manufacturer_url
        mfr_slug = selected.manufacturer_slug
        model_name = selected.model_name

        if not url:
            typer.echo(f"ERROR: No URL for {model_name}")
            raise typer.Exit(1)

        typer.echo(f"\nSelected: {model_name}")
        typer.echo(f"URL: {url}")

        # Show existing issues
        from .validator import format_model_issues
        typer.echo(format_model_issues(selected))
    else:
        typer.echo("No validation log found. Run validate first:")
        typer.echo(f"  python -m src.pipeline validate --db {db_path}")
        raise typer.Exit(1)

    if not url:
        typer.echo(f"ERROR: No URL for model {model_slug}")
        raise typer.Exit(1)

    # ── Step 1: Show current DB state ──────────────────────────────────
    typer.echo("\n── Current DB state ──")
    old_data = _read_model_from_db(db_p, model_slug)
    if old_data:
        _print_model_data(old_data)
    else:
        typer.echo("  (not found in DB)")

    # ── Step 2: Re-extract from URL ────────────────────────────────────
    typer.echo(f"\n── Re-extracting from {url} ──")
    crawler = Crawler()
    markdown = asyncio.run(crawler.render_page(url))
    if not markdown:
        typer.echo("Failed to render page.")
        raise typer.Exit(1)

    typer.echo(f"Rendered {len(markdown)} chars")

    adapter = _get_adapter()
    cfg = load_config(config) if config else {}
    result = extract_specs(adapter, markdown, cfg, url=url)
    if not result:
        typer.echo("Extraction returned no data.")
        raise typer.Exit(1)

    # ── Step 3: Normalize and preview ──────────────────────────────────
    wing, sizes, certs, perfs = normalize_extraction(
        result, mfr_slug, is_current=True, source_url=url,
    )

    typer.echo("\n── New extraction result ──")
    new_data = {
        "model_name": wing.name,
        "year_released": wing.year_released,
        "cell_count": wing.cell_count,
        "category": wing.category.value if wing.category else None,
        "riser_config": wing.riser_config,
        "sizes": [],
    }
    for i, sv in enumerate(sizes):
        size_info: dict = {
            "size_label": sv.size_label,
            "flat_area_m2": sv.flat_area_m2,
            "flat_span_m": sv.flat_span_m,
            "flat_aspect_ratio": sv.flat_aspect_ratio,
            "wing_weight_kg": sv.wing_weight_kg,
            "ptv_min_kg": sv.ptv_min_kg,
            "ptv_max_kg": sv.ptv_max_kg,
        }
        if i < len(certs):
            size_info["cert"] = f"{certs[i].standard.value}/{certs[i].classification}" if certs[i].standard else None
        new_data["sizes"].append(size_info)

    _print_model_data(new_data)

    # ── Step 4: Show diff ──────────────────────────────────────────────
    if old_data:
        typer.echo("\n── Changes ──")
        _print_diff(old_data, new_data)

    # ── Step 5: Confirm ────────────────────────────────────────────────
    choice = typer.prompt("\nCommit to DB? [y]es / [n]o / [j]son", default="n")
    choice = choice.strip().lower()

    if choice == "j":
        typer.echo(json.dumps(result.model_dump(exclude_none=True), indent=2))
        choice = typer.prompt("\nCommit to DB? [y]es / [n]o", default="n")
        choice = choice.strip().lower()

    if choice in ("y", "yes"):
        _store_single_result(result, url, db_path, cfg)

        # Update validation log
        if log_path.exists():
            vlog = ValidationLog.load(log_path)
            if model_slug in vlog.models:
                vlog.models[model_slug].action = Action.re_extract
                vlog.save()
                typer.echo(f"Validation log updated: {model_slug} → re_extract")
    else:
        typer.echo("Discarded — DB unchanged.")


def _lookup_model_url(db_path: Path, slug: str) -> tuple[str | None, str, str]:
    """Look up a model's URL and manufacturer from the database."""
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    row = conn.execute("""
        SELECT m.name, m.manufacturer_url, mfr.slug as mfr_slug
        FROM models m
        JOIN manufacturers mfr ON m.manufacturer_id = mfr.id
        WHERE m.slug = ?
    """, (slug,)).fetchone()
    conn.close()
    if not row:
        return None, "unknown", slug
    return row["manufacturer_url"], row["mfr_slug"], row["name"]


def _read_model_from_db(db_path: Path, slug: str) -> dict | None:
    """Read current model data from the database for comparison."""
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    model = conn.execute("SELECT * FROM models WHERE slug = ?", (slug,)).fetchone()
    if not model:
        conn.close()
        return None

    sizes = conn.execute("""
        SELECT sv.*, c.standard as cert_standard, c.classification as cert_classification
        FROM size_variants sv
        LEFT JOIN certifications c ON c.size_variant_id = sv.id
        WHERE sv.model_id = ?
        ORDER BY sv.size_label
    """, (model["id"],)).fetchall()
    conn.close()

    data: dict = {
        "model_name": model["name"],
        "year_released": model["year_released"],
        "cell_count": model["cell_count"],
        "category": model["category"],
        "riser_config": model["riser_config"],
        "sizes": [],
    }
    for sv in sizes:
        size_info: dict = {
            "size_label": sv["size_label"],
            "flat_area_m2": sv["flat_area_m2"],
            "flat_span_m": sv["flat_span_m"],
            "flat_aspect_ratio": sv["flat_aspect_ratio"],
            "wing_weight_kg": sv["wing_weight_kg"],
            "ptv_min_kg": sv["ptv_min_kg"],
            "ptv_max_kg": sv["ptv_max_kg"],
        }
        if sv["cert_standard"]:
            size_info["cert"] = f"{sv['cert_standard']}/{sv['cert_classification']}"
        data["sizes"].append(size_info)

    return data


def _print_model_data(data: dict) -> None:
    """Print model data in a readable table format."""
    typer.echo(f"  Model: {data['model_name']}")
    typer.echo(f"  Year: {data.get('year_released', '—')}")
    typer.echo(f"  Cells: {data.get('cell_count', '—')}")
    typer.echo(f"  Category: {data.get('category', '—')}")
    typer.echo(f"  Risers: {data.get('riser_config', '—')}")

    sizes = data.get("sizes", [])
    if sizes:
        typer.echo(f"  Sizes ({len(sizes)}):")
        typer.echo(f"    {'Label':>6} {'Area':>7} {'Span':>6} {'AR':>5} {'Wt':>5} {'PTV':>11} {'Cert':>6}")
        for s in sizes:
            area = f"{s.get('flat_area_m2', 0) or 0:.1f}" if s.get("flat_area_m2") else "—"
            span = f"{s.get('flat_span_m', 0) or 0:.1f}" if s.get("flat_span_m") else "—"
            ar = f"{s.get('flat_aspect_ratio', 0) or 0:.2f}" if s.get("flat_aspect_ratio") else "—"
            wt = f"{s.get('wing_weight_kg', 0) or 0:.1f}" if s.get("wing_weight_kg") else "—"
            ptv_min = s.get("ptv_min_kg")
            ptv_max = s.get("ptv_max_kg")
            ptv = f"{ptv_min:.0f}–{ptv_max:.0f}" if ptv_min and ptv_max else "—"
            cert = s.get("cert", "—")
            typer.echo(f"    {s['size_label']:>6} {area:>7} {span:>6} {ar:>5} {wt:>5} {ptv:>11} {cert:>6}")


def _print_diff(old: dict, new: dict) -> None:
    """Print a comparison of old vs new model data.

    Reflects actual upsert behavior: existing non-NULL values are kept
    when the new extraction has None (upsert only fills NULLs).
    """
    has_changes = False

    # Model-level fields
    for field in ("year_released", "cell_count", "category", "riser_config"):
        old_val = old.get(field)
        new_val = new.get(field)
        if old_val != new_val:
            if old_val is None and new_val is not None:
                typer.echo(f"  + {field}: {new_val} (was empty)")
                has_changes = True
            elif old_val is not None and new_val is None:
                typer.echo(f"    {field}: {old_val} (kept — not in new extraction)")
            else:
                typer.echo(f"  ~ {field}: {old_val} → {new_val}")
                has_changes = True

    # Size-level comparison
    old_sizes = {s["size_label"]: s for s in old.get("sizes", [])}
    new_sizes = {s["size_label"]: s for s in new.get("sizes", [])}

    for label in sorted(set(old_sizes) | set(new_sizes)):
        if label not in old_sizes:
            typer.echo(f"  + Size {label} (new)")
            has_changes = True
            continue
        if label not in new_sizes:
            typer.echo(f"  - Size {label} (removed)")
            has_changes = True
            continue

        os = old_sizes[label]
        ns = new_sizes[label]
        changes = []
        for f in ("flat_area_m2", "ptv_min_kg", "ptv_max_kg", "wing_weight_kg", "cert"):
            ov = os.get(f)
            nv = ns.get(f)
            if ov != nv:
                # Cert is always replaced (delete + insert), show all changes
                if f == "cert":
                    changes.append(f"{f}: {ov}→{nv}")
                # Numeric fields: upsert only fills NULLs
                elif ov is None and nv is not None:
                    changes.append(f"{f}: →{nv} (fill)")
                elif ov is not None and nv is None:
                    pass  # kept — upsert won't overwrite
                else:
                    changes.append(f"{f}: {ov}→{nv}")
        if changes:
            typer.echo(f"  ~ Size {label}: {', '.join(changes)}")
            has_changes = True

    if not has_changes:
        typer.echo("  (no effective changes)")


def _show_re_extract_summary(vlog: ValidationLog) -> None:
    """Show models marked for re-extraction."""
    re_extract = vlog.re_extract_models
    if not re_extract:
        return
    typer.echo(f"\n{len(re_extract)} model(s) marked for re-extraction:")
    for mv in re_extract:
        url = mv.manufacturer_url or "(no URL)"
        typer.echo(f"  • {mv.model_name} — {url}")
    typer.echo(f"\nTo re-extract, run the pipeline with:")
    typer.echo(f"  python -m src.pipeline run --url <URL>")


def _run_single_url(
    url: str,
    dry_run: bool = False,
    config: dict | None = None,
    db_path: str | None = None,
) -> None:
    """Extract specs from a single URL and optionally store to DB."""
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

    if db_path:
        _store_single_result(result, url, db_path, cfg)


def _store_single_result(
    result: ExtractionResult,
    url: str,
    db_path: str,
    cfg: dict,
) -> None:
    """Normalize and store a single extraction result into the database."""
    # Infer manufacturer slug from URL or config
    mfr_cfg = (cfg or {}).get("manufacturer", {})
    mfr_slug = mfr_cfg.get("slug", "")
    if not mfr_slug:
        # Try to infer from URL (e.g., flyozone.com → ozone)
        from urllib.parse import urlparse
        host = urlparse(url).hostname or ""
        if "ozone" in host:
            mfr_slug = "ozone"
        elif "advance" in host:
            mfr_slug = "advance"
        else:
            # Use first part of hostname
            mfr_slug = host.split(".")[0] if host else "unknown"

    mfr_name = mfr_cfg.get("name", mfr_slug.title())

    wing, sizes, certs, perfs = normalize_extraction(
        result, mfr_slug, is_current=True, source_url=url,
    )

    db = Database(db_path)
    db.connect()
    try:
        mfr = Manufacturer(
            name=mfr_name,
            slug=mfr_slug,
            website=mfr_cfg.get("website"),
        )
        mfr_id = db.upsert_manufacturer(mfr)
        model_id = db.upsert_model(wing, mfr_id)

        if result.target_use:
            try:
                db.upsert_model_target_use(model_id, TargetUse(result.target_use))
            except ValueError:
                pass

        db.record_provenance(model_id, url, mfr_slug)

        for i, sv in enumerate(sizes):
            sv_id = db.upsert_size_variant(sv, model_id)
            if i < len(certs):
                db.delete_certifications_for_size(sv_id)
                db.insert_certification(certs[i], sv_id)
            if i < len(perfs):
                db.insert_performance_data(perfs[i], sv_id)

        typer.echo(f"\nStored {result.model_name} ({len(sizes)} sizes) → {db_path}")
    finally:
        db.close()


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
    "cell_count", "riser_config", "manufacturer_url",
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
                    db.delete_certifications_for_size(sv_id)
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
