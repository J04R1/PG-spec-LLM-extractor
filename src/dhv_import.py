"""
DHV adapter — enrich existing DB records with DHV certification data.

Reads dhv_unmatched.csv and adds certification records to models that
already exist in the database, or creates minimal model records for
DHV-only entries.

Usage:
    python -m src.pipeline import-dhv --db output/ozone.db --manufacturer ozone
"""

from __future__ import annotations

import csv
import logging
import re
from datetime import date, datetime, timezone
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

# Valid certification classifications (same as validator._VALID_CLASSES)
_VALID_CERT_CLASSES = {
    "EN": {"A", "B", "C", "D"},
    "LTF": {"A", "B", "C", "D", "1", "1-2", "2", "2-3", "3"},
    "AFNOR": {"Standard", "Performance", "Competition"},
}

# ── DHV manufacturer legal name → slug mapping ───────────────────────────────

_DHV_MANUFACTURER_MAP: dict[str, str] = {
    # Exact slug matches (already lowercased in match_failure_reason)
    # Legal entity names from DHV database
    "OZONE Gliders Ltd.": "ozone",
    "ADVANCE Thun AG": "advance",
    "NOVA Vertriebsgesellschaft m.b.H.": "nova",
    "NOVA International": "nova",
    "GIN Gliders Inc.": "gin",
    "UP International GmbH": "up",
    "Swing Flugsportgeräte GmbH": "swing",
    "Skywalk GmbH & Co. KG": "skywalk",
    "MAC Para Technology": "macpara",
    "PRO-DESIGN, Hofbauer GmbH": "prodesign",
    "Fly market Flugsport-Zubehör GmbH": "skyman",
    "SynAIRgy GmbH": "skyman",
    "NORTEC, S.L. - WINDTECH": "windtech",
    "Turn2Fly GmbH": "u-turn",
    "U-Turn GmbH": "u-turn",
    "Kontest GmbH - AirCross": "aircross",
    "Sol Sports Ind. E Comérico LTDA": "sol",
    "Firebird International AG": "firebird",
    "ICARO paragliders - Fly & more GmbH": "icaro",
    "FreeX GmbH": "freex",
    "freeX air sports GmbH": "freex",
    "Comet Sportartikel GmbH & Co KG": "comet",
    "Flight Design GmbH": "flightdesign",
    "Airwave Villinger Ges.m.b.H.": "airwave",
    "Airwave Paragliders Ltda.": "airwave",
    "Edel Korea, HISPO Co.Ltd": "edel",
    "PARATECH AG": "paratech",
    "Apco Aviation Ltd.": "apco",
    "ITV Parapentes": "itv",
    "Trekking-parapentes": "trekking",
    "Flying Planet": "flyingplanet",
    "Skyline Flight Gear GmbH & Co. KG": "skyline",
    "Papesh GmbH": "phi",
    "Ailes de K": "ailesdek",
    "ZOOM Vertriebs GmbH": "zoom",
    "Delta Fly Hans Madreiter": "deltafly",
    "KRILO d.o.o.": "krilo",
    "Davinci Products INC": "davinci",
}


def _resolve_dhv_manufacturer(manufacturer: str, match_failure_reason: str) -> str:
    """Resolve DHV manufacturer name to canonical slug.

    First checks match_failure_reason for an already-extracted slug (from
    the original DHV matching run), then falls back to the legal name map,
    then to simple slugification.
    """
    # Try to extract slug from match_failure_reason
    m = re.search(r"mfr: ([\w-]+)", match_failure_reason)
    if m:
        return m.group(1)

    # Try the legal name map
    manufacturer = manufacturer.strip()
    if manufacturer in _DHV_MANUFACTURER_MAP:
        return _DHV_MANUFACTURER_MAP[manufacturer]

    # Fallback: slugify the name
    slug = re.sub(r"[^a-z0-9]+", "-", manufacturer.lower()).strip("-")
    return slug


# ── Model name normalization ──────────────────────────────────────────────────

# Common prefixes to strip from DHV model names
_STRIP_PREFIXES = [
    r"^Gliders\s+",       # "Gliders Buzz Z3" → "Buzz Z3"
    r"^Thun AG\s+",       # "Thun AG Sigma 8" → "Sigma 8"
    r"^PHI\s+",           # "PHI MAESTRO 3 light" → "MAESTRO 3 light"
]

_STRIP_RE = re.compile("|".join(f"({p})" for p in _STRIP_PREFIXES), re.IGNORECASE)


def _normalize_model_name(name: str) -> str:
    """Normalize a DHV model name for matching.

    Strips common manufacturer prefixes and normalizes spacing.
    """
    name = name.strip()
    name = _STRIP_RE.sub("", name)
    # Normalize multiple spaces
    name = re.sub(r"\s+", " ", name).strip()
    return name


# ── Import function ───────────────────────────────────────────────────────────

def _parse_date(val: str) -> Optional[date]:
    """Parse date from YYYY-MM-DD string."""
    val = val.strip() if val else ""
    if not val:
        return None
    try:
        return date.fromisoformat(val)
    except ValueError:
        return None


def _map_equipment_class(eclass: str) -> Optional[tuple[CertStandard, str]]:
    """Map DHV equipment_class to (standard, classification)."""
    eclass = eclass.strip().upper()
    if eclass in ("A", "B", "C", "D"):
        return CertStandard.EN, eclass
    return None


def import_dhv_csv(
    csv_path: str | Path,
    db: Database,
    *,
    manufacturer_filter: Optional[str] = None,
    create_missing: bool = True,
    validate: bool = True,
) -> dict:
    """Import DHV certification data into the database.

    Matches DHV records against existing models in the DB and adds
    certification records. Optionally creates minimal model records
    for DHV entries that don't match any existing model.

    Args:
        csv_path: Path to dhv_unmatched.csv
        db: Connected Database instance
        manufacturer_filter: If set, only import rows for this manufacturer slug
        create_missing: If True, create minimal model records for unmatched DHV entries
        validate: If True, validate cert classifications before inserting

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

    mfr_ids: dict[str, int] = {}
    cert_count = 0
    matched_count = 0
    created_count = 0
    skipped_count = 0
    invalid_certs = 0
    models_enriched: set[str] = set()

    for row in rows:
        manufacturer_raw = row.get("manufacturer", "").strip()
        model_name_raw = row.get("model", "").strip()
        size_raw = row.get("size", "").strip()
        equipment_class = row.get("equipment_class", "").strip()
        test_date_str = row.get("test_date", "").strip()
        report_url = row.get("report_url", "").strip()
        dhv_url = row.get("dhv_url", "").strip()
        match_failure = row.get("match_failure_reason", "").strip()

        if not manufacturer_raw or not model_name_raw:
            skipped_count += 1
            continue

        # Resolve manufacturer slug
        mfr_slug = _resolve_dhv_manufacturer(manufacturer_raw, match_failure)

        if manufacturer_filter and mfr_slug != manufacturer_filter:
            continue

        # Normalize model name
        model_name = _normalize_model_name(model_name_raw)
        model_slug = make_model_slug(mfr_slug, model_name)

        # Map certification
        cert_data = _map_equipment_class(equipment_class)
        if not cert_data:
            skipped_count += 1
            continue

        standard, classification = cert_data

        # Validate cert classification before inserting
        if validate and standard and classification:
            std_name = standard.value
            if std_name in _VALID_CERT_CLASSES:
                if classification not in _VALID_CERT_CLASSES[std_name]:
                    logger.debug(
                        "Skipping invalid cert %s/%s for %s",
                        std_name, classification, model_name_raw,
                    )
                    invalid_certs += 1
                    continue

        # Ensure manufacturer exists
        if mfr_slug not in mfr_ids:
            mfr = Manufacturer(name=mfr_slug.title(), slug=mfr_slug)
            mfr_ids[mfr_slug] = db.upsert_manufacturer(mfr)

        mfr_id = mfr_ids[mfr_slug]

        # Check if model exists in DB
        existing = db.conn.execute(
            "SELECT id FROM models WHERE slug = ?", (model_slug,)
        ).fetchone()

        if existing:
            model_id = existing["id"]
            matched_count += 1
        elif create_missing:
            # Create minimal model record
            wing = WingModel(
                name=model_name,
                slug=model_slug,
                category=WingCategory.paraglider,
                is_current=False,
            )
            model_id = db.upsert_model(wing, mfr_id)
            created_count += 1

            # Provenance for new model
            db.insert_provenance(
                Provenance(
                    source_name="dhv_geraeteportal",
                    source_url=dhv_url or None,
                    accessed_at=datetime.now(timezone.utc),
                    extraction_method="dhv_cert_import",
                    notes="Model created from DHV certification record (no specs)",
                ),
                model_id,
            )
        else:
            skipped_count += 1
            continue

        # Ensure size variant exists
        if not size_raw:
            skipped_count += 1
            continue
        size_label = normalize_size_label(size_raw)
        sv = SizeVariant(size_label=size_label)
        sv_id = db.upsert_size_variant(sv, model_id)

        # Insert certification
        cert = Certification(
            standard=standard,
            classification=classification,
            test_date=_parse_date(test_date_str),
            report_url=report_url or None,
        )
        db.upsert_certification(cert, sv_id)
        cert_count += 1
        models_enriched.add(model_slug)

        # Provenance for enrichment (only once per model)
        if existing and model_slug not in models_enriched:
            db.insert_provenance(
                Provenance(
                    source_name="dhv_geraeteportal",
                    source_url=dhv_url or None,
                    accessed_at=datetime.now(timezone.utc),
                    extraction_method="dhv_cert_import",
                    notes="DHV certification enrichment",
                ),
                model_id,
            )

    return {
        "manufacturers": len(mfr_ids),
        "certifications": cert_count,
        "models_enriched": len(models_enriched),
        "models_matched": matched_count,
        "models_created": created_count,
        "invalid_certs": invalid_certs,
        "skipped": skipped_count,
    }


def _empty_result() -> dict:
    return {
        "manufacturers": 0,
        "certifications": 0,
        "models_enriched": 0,
        "models_matched": 0,
        "models_created": 0,
        "invalid_certs": 0,
        "skipped": 0,
    }
