"""
fredvol adapter — import fredvol_raw.csv into the v2 schema.

Transforms rows from the fredvol/Paraglider_specs_studies CSV into the
seed import format and stores via the existing DB upsert infrastructure.

Usage:
    python -m src.pipeline import-fredvol --db output/ozone.db --manufacturer ozone
    python -m src.pipeline import-fredvol --db output/legacy.db --tier legacy
"""

from __future__ import annotations

import csv
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .db import Database
from .models import (
    Certification,
    CertStandard,
    Manufacturer,
    Provenance,
    SizeVariant,
    WingCategory,
    WingModel,
)
from .normalizer import make_model_slug, normalize_size_label
from .validator import validate_model_data, ModelValidation

logger = logging.getLogger(__name__)

# ── Manufacturer name → slug mapping ──────────────────────────────────────────

# Maps fredvol manufacturer names (case-sensitive as they appear in CSV)
# to canonical slugs. Includes both cased and lowercase variants.
_MANUFACTURER_ALIASES: dict[str, str] = {
    # T1 active major — case variants
    "Advance": "advance",
    "Ozone": "ozone",
    "Nova": "nova",
    "Gin": "gin",
    "Niviuk": "niviuk",
    "Skywalk": "skywalk",
    "Swing": "swing",
    "Dudek": "dudek",
    "Up": "up",
    "Phi": "phi",
    "Axis": "axis",
    "Icaro": "icaro",
    "Flow": "flow",
    "Aircross": "aircross",
    "AirDesign": "airdesign",
    # Compound names
    "Bruce Goldsmith Design": "bgd",
    "Triple Seven": "triple-seven",
    "U-Turn": "u-turn",
    "Papillon Paragliders": "papillon-paragliders",
    # Lowercase variants that differ from slug
    "uturn": "u-turn",
    "tripleseven": "triple-seven",
}


def _slugify_manufacturer(name: str) -> str:
    """Normalize a fredvol manufacturer name to a canonical slug.

    Checks the alias table first, then falls back to lowercasing
    and stripping non-alphanumeric characters.
    """
    name = name.strip()
    if name in _MANUFACTURER_ALIASES:
        return _MANUFACTURER_ALIASES[name]
    # Fallback: lowercase, replace spaces/special chars with hyphen
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug


# ── Certification mapping ─────────────────────────────────────────────────────

_CERT_MAPPING: dict[str, tuple[Optional[CertStandard], Optional[str]]] = {
    # EN letter classes
    "A": (CertStandard.EN, "A"),
    "B": (CertStandard.EN, "B"),
    "C": (CertStandard.EN, "C"),
    "D": (CertStandard.EN, "D"),
    # DHV numeric classes → LTF standard
    "DHV_1": (CertStandard.LTF, "1"),
    "DHV_2": (CertStandard.LTF, "2"),
    "DHV_3": (CertStandard.LTF, "3"),
    # AFNOR categories
    "AFNOR_Standard": (CertStandard.AFNOR, "Standard"),
    "AFNOR_Perf": (CertStandard.AFNOR, "Performance"),
    "AFNOR_Compet": (CertStandard.AFNOR, "Competition"),
    "AFNOR_Biplace": (CertStandard.AFNOR, "Biplace"),
    # Other standards
    "DGAC": (CertStandard.DGAC, None),
    "CCC": (CertStandard.CCC, "CCC"),
    "DUVL": (CertStandard.other, "DUVL"),
    "Load": (CertStandard.other, "Load"),
    # Skip these
    "pending": (None, None),
    "not_cert": (None, None),
}


def _map_certification(row: dict) -> Optional[tuple[CertStandard, Optional[str]]]:
    """Extract certification from a fredvol row.

    Checks individual certif_* columns first, then falls back to the
    consolidated `certification` column.
    """
    # Priority 1: specific certification columns
    en = row.get("certif_EN", "").strip()
    if en:
        return CertStandard.EN, en.upper()

    dhv = row.get("certif_DHV", "").strip()
    if dhv:
        return CertStandard.LTF, dhv

    afnor = row.get("certif_AFNOR", "").strip()
    if afnor:
        return CertStandard.AFNOR, afnor

    misc = row.get("certif_MISC", "").strip()
    if misc:
        return CertStandard.other, misc

    # Priority 2: consolidated certification column
    cert_val = row.get("certification", "").strip()
    if not cert_val:
        return None

    mapping = _CERT_MAPPING.get(cert_val)
    if mapping and mapping[0] is not None:
        return mapping
    return None


# ── Category inference ─────────────────────────────────────────────────────────

_TANDEM_PATTERNS = re.compile(
    r"\b(tandem|biplace|bi[- ]?beta|bibeta|bi[- ]?pax|double|twin)\b",
    re.IGNORECASE,
)
_MOTOR_PATTERNS = re.compile(r"\bmotor\b", re.IGNORECASE)


def _infer_category(name: str, certification: str) -> WingCategory:
    """Infer wing category from model name and certification value."""
    if _MOTOR_PATTERNS.search(name):
        return WingCategory.paramotor
    if _TANDEM_PATTERNS.search(name):
        return WingCategory.tandem
    if certification in ("AFNOR_Biplace", "Load"):
        return WingCategory.tandem
    if certification == "DGAC" or certification == "DUVL":
        return WingCategory.paramotor
    return WingCategory.paraglider


# ── Import function ───────────────────────────────────────────────────────────

def _safe_float(val: str) -> Optional[float]:
    """Parse float, returning None for empty/invalid."""
    val = val.strip() if val else ""
    if not val:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _safe_int(val: str) -> Optional[int]:
    """Parse int from string, returning None for empty/invalid."""
    val = val.strip() if val else ""
    if not val:
        return None
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return None


def import_fredvol_csv(
    csv_path: str | Path,
    db: Database,
    *,
    manufacturer_filter: Optional[str] = None,
    tier_filter: Optional[str] = None,
    tier_config: Optional[dict[str, str]] = None,
    validate: bool = True,
) -> dict:
    """Import fredvol_raw.csv into the database.

    Args:
        csv_path: Path to fredvol_raw.csv
        db: Connected Database instance
        manufacturer_filter: If set, only import rows for this manufacturer slug
        tier_filter: If set ("t1", "t2", "legacy"), only import manufacturers in that tier
        tier_config: Optional dict mapping manufacturer slugs to tier labels
        validate: If True, validate each model before storing (relaxed profile)

    Returns:
        Summary dict with counts.
    """
    csv_path = Path(csv_path)
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV not found: {csv_path}")

    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        return _empty_result()

    # Group rows by (slug, model_name) → list of size rows
    grouped: dict[tuple[str, str], list[dict]] = {}
    skipped_rows = 0

    for row in rows:
        mfr_name = row.get("manufacturer", "").strip()
        model_name = row.get("name", "").strip()
        if not mfr_name or not model_name:
            skipped_rows += 1
            continue

        slug = _slugify_manufacturer(mfr_name)

        # Apply manufacturer filter
        if manufacturer_filter and slug != manufacturer_filter:
            continue

        # Apply tier filter
        if tier_filter and tier_config:
            mfr_tier = tier_config.get(slug, "legacy")
            if tier_filter != mfr_tier:
                continue

        key = (slug, model_name)
        grouped.setdefault(key, []).append(row)

    # Import grouped data
    mfr_ids: dict[str, int] = {}
    model_count = 0
    size_count = 0
    cert_count = 0
    skipped: list[ModelValidation] = []

    # fredvol relaxed plausibility: year data starts from 1982
    _FREDVOL_PLAUSIBILITY = {"year_released": (1980, 2026)}

    for (mfr_slug, model_name), size_rows in grouped.items():
        first = size_rows[0]

        # Infer category
        cert_val = first.get("certification", "").strip()
        category = _infer_category(model_name, cert_val)
        source = first.get("source", "").strip()

        # Build WingModel
        model_slug = make_model_slug(mfr_slug, model_name)
        wing = WingModel(
            name=model_name,
            slug=model_slug,
            category=category,
            year_released=_safe_int(first.get("year", "")),
            is_current=False,
        )

        # Build sizes and certs for validation
        sizes = []
        certs_for_validation = []
        for row in size_rows:
            size_label = row.get("size", "").strip()
            if not size_label:
                continue
            sv = SizeVariant(
                size_label=normalize_size_label(size_label),
                flat_area_m2=_safe_float(row.get("flat_area")),
                flat_span_m=_safe_float(row.get("flat_span")),
                flat_aspect_ratio=_safe_float(row.get("flat_AR")),
                proj_area_m2=_safe_float(row.get("proj_area")),
                proj_span_m=_safe_float(row.get("proj_span")),
                proj_aspect_ratio=_safe_float(row.get("proj_AR")),
                wing_weight_kg=_safe_float(row.get("weight")),
                ptv_min_kg=_safe_float(row.get("ptv_mini")),
                ptv_max_kg=_safe_float(row.get("ptv_maxi")),
            )
            sizes.append(sv)
            cert_result = _map_certification(row)
            if cert_result:
                standard, classification = cert_result
                certs_for_validation.append(Certification(
                    standard=standard, classification=classification,
                ))

        # Validation gate
        if validate:
            mv = validate_model_data(
                wing, sizes, certs_for_validation, mfr_slug,
                plausibility_overrides=_FREDVOL_PLAUSIBILITY,
                skip_missing_warnings=True,
            )
            if mv.has_critical:
                logger.info("Skipping %s: %d critical issues", model_name,
                            sum(1 for i in mv.issues if i.severity.value == "critical"))
                skipped.append(mv)
                continue

        # Ensure manufacturer exists
        if mfr_slug not in mfr_ids:
            mfr = Manufacturer(name=mfr_slug.title(), slug=mfr_slug)
            mfr_ids[mfr_slug] = db.upsert_manufacturer(mfr)

        mfr_id = mfr_ids[mfr_slug]
        model_id = db.upsert_model(wing, mfr_id)
        model_count += 1

        # Provenance
        db.insert_provenance(
            Provenance(
                source_name="fredvol/Paraglider_specs_studies",
                source_url="https://github.com/fredvol/Paraglider_specs_studies",
                accessed_at=datetime.now(timezone.utc),
                extraction_method="fredvol_csv_import",
                notes=f"Source: {source}, from {csv_path.name}",
            ),
            model_id,
        )

        # Insert each size variant (reuse already-built sizes)
        for i, sv in enumerate(sizes):
            sv_id = db.upsert_size_variant(sv, model_id)
            size_count += 1

        # Insert certifications from rows (need per-row mapping)
        for row in size_rows:
            size_label = row.get("size", "").strip()
            if not size_label:
                continue
            size_label = normalize_size_label(size_label)
            # Look up via upsert (idempotent — returns existing id)
            sv_lookup = SizeVariant(size_label=size_label)
            sv_id = db.upsert_size_variant(sv_lookup, model_id)

            cert_result = _map_certification(row)
            if cert_result:
                standard, classification = cert_result
                cert = Certification(
                    standard=standard,
                    classification=classification,
                )
                db.upsert_certification(cert, sv_id)
                cert_count += 1

    return {
        "manufacturers": len(mfr_ids),
        "models": model_count,
        "sizes": size_count,
        "certifications": cert_count,
        "skipped_rows": skipped_rows,
        "skipped": len(skipped),
        "skipped_models": skipped,
    }


def _empty_result() -> dict:
    return {
        "manufacturers": 0,
        "models": 0,
        "sizes": 0,
        "certifications": 0,
        "skipped_rows": 0,
        "skipped": 0,
        "skipped_models": [],
    }
