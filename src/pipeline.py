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

import logging
import sys
from pathlib import Path

import typer
from dotenv import load_dotenv

from .config import load_config, get_output_paths
from .models import ExtractionResult

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
        _run_single_url(url, dry_run=dry_run)
        return

    cfg = load_config(config)  # type: ignore[arg-type]
    slug = cfg["manufacturer"]["slug"]
    paths = get_output_paths(slug)

    logger.info("Pipeline: %s (%s)", cfg["manufacturer"]["name"], slug)
    logger.info("Output:   %s", paths["raw_json"])

    if map_only:
        typer.echo("--map-only: URL discovery (Iteration 2)")
        raise typer.Exit(0)

    if convert_only:
        typer.echo("--convert-only: JSON → CSV conversion (Iteration 5)")
        raise typer.Exit(0)

    # TODO: Iteration 2+ — full pipeline implementation
    typer.echo("Full pipeline — implement in Iterations 2-6")


@app.command()
def status() -> None:
    """Show extraction status (partial files, counts)."""
    # TODO: Iteration 6 — scan output/ for state files
    typer.echo("Status: not yet implemented (Iteration 6)")


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


def _run_single_url(url: str, dry_run: bool = False) -> None:
    """Extract specs from a single URL (test mode)."""
    if dry_run:
        typer.echo(f"DRY RUN: Would extract from {url}")
        return

    # TODO: Iteration 3 — wire adapter + extractor
    typer.echo(f"Single URL extraction — implement in Iteration 3")
    typer.echo(f"URL: {url}")


if __name__ == "__main__":
    app()
