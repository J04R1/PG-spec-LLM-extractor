"""
Configuration loading and output path management.

Ported from extract.py load_config() and get_output_paths().
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "output"
CONFIG_DIR = PROJECT_ROOT / "config" / "manufacturers"


def load_config(config_path: str | Path) -> dict:
    """Load and validate a manufacturer YAML config file."""
    config_path = Path(config_path)
    if not config_path.exists():
        print(f"ERROR: Config file not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    with open(config_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    if not cfg.get("manufacturer", {}).get("slug"):
        print("ERROR: Config must define manufacturer.slug", file=sys.stderr)
        sys.exit(1)

    if not cfg.get("sources") and not cfg.get("extraction"):
        print(
            "ERROR: Config must define at least 'sources' or 'extraction'",
            file=sys.stderr,
        )
        sys.exit(1)

    return cfg


def get_output_paths(slug: str) -> dict[str, Path]:
    """Return the standard output file paths for a manufacturer slug."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return {
        "raw_json": OUTPUT_DIR / f"{slug}_raw.json",
        "partial": OUTPUT_DIR / f"{slug}_raw.json.partial",
        "csv": OUTPUT_DIR / f"{slug}_enrichment.csv",
        "urls": OUTPUT_DIR / f"{slug}_urls.json",
        "db": OUTPUT_DIR / "paragliders.db",
    }
