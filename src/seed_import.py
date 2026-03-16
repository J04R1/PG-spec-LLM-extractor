"""
Seed import — load enrichment CSVs into the v2 schema.

Reads the LLM-enriched CSVs (one row per model×size) and maps them
to the 7-table schema: manufacturer → model → target_use → size_variant
→ certification → provenance.

Usage:
    python -m src.pipeline seed --csv data/ozone_enrichment_all_by_LLM.csv
"""

from __future__ import annotations

import csv
import logging
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

from .db import Database
from .models import (
    Certification,
    CertStandard,
    Manufacturer,
    PerformanceData,
    Provenance,
    SizeVariant,
    TargetUse,
    WingCategory,
    WingModel,
)
from .normalizer import normalize_size_label, normalize_certification, make_model_slug
from .validator import validate_model_data, ModelValidation

logger = logging.getLogger(__name__)

# CSV columns that map to model-level fields (same value for all sizes of a model)
_MODEL_LEVEL_FIELDS = {
    "name", "year_released", "year_discontinued", "category", "target_use",
    "is_current", "cell_count", "riser_config", "manufacturer_url",
}


def import_enrichment_csv(
    csv_path: str | Path,
    db: Database,
    *,
    extraction_method: str = "llm_enrichment_csv",
    validate: bool = True,
) -> dict:
    """
    Import an enrichment CSV into the database.

    When validate=True (default), each model is validated before storing.
    Models with critical validation issues are skipped and reported.

    Returns a summary dict with counts and skipped model details.
    """
    csv_path = Path(csv_path)
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV not found: {csv_path}")

    rows = _read_csv(csv_path)
    if not rows:
        return {"manufacturers": 0, "models": 0, "sizes": 0, "certifications": 0,
                "skipped": 0, "skipped_models": []}

    # Group rows by (manufacturer_slug, model_name) → list of size rows
    grouped: dict[tuple[str, str], list[dict]] = {}
    for row in rows:
        mfr_slug = row.get("manufacturer_slug", "").strip()
        model_name = row.get("name", "").strip()
        if not mfr_slug or not model_name:
            logger.warning("Skipping row with missing manufacturer_slug or name")
            continue
        key = (mfr_slug, model_name)
        grouped.setdefault(key, []).append(row)

    # Track counts
    mfr_ids: dict[str, int] = {}
    model_count = 0
    size_count = 0
    cert_count = 0
    perf_count = 0
    skipped: list[ModelValidation] = []

    for (mfr_slug, model_name), size_rows in grouped.items():
        # Build all data for this model first (before storing)
        first = size_rows[0]
        wing = _build_wing_model(first, mfr_slug)

        sizes = []
        certs = []
        perfs = []
        for row in size_rows:
            sv = _build_size_variant(row)
            if sv:
                sizes.append(sv)
                cert = _build_certification(row)
                if cert:
                    certs.append(cert)
                perf = _build_performance_data(row)
                if perf:
                    perfs.append(perf)

        # Validation gate: check before storing
        if validate:
            mv = validate_model_data(wing, sizes, certs, mfr_slug)
            if mv.has_critical:
                logger.info("Skipping %s: %d critical issues", model_name,
                            sum(1 for i in mv.issues if i.severity.value == "critical"))
                skipped.append(mv)
                continue

        # Ensure manufacturer exists
        if mfr_slug not in mfr_ids:
            mfr = Manufacturer(
                name=mfr_slug.title(),
                slug=mfr_slug,
            )
            mfr_ids[mfr_slug] = db.upsert_manufacturer(mfr)

        mfr_id = mfr_ids[mfr_slug]
        model_id = db.upsert_model(wing, mfr_id)
        model_count += 1

        # Target use
        target_use_str = first.get("target_use", "").strip()
        if target_use_str:
            try:
                db.upsert_model_target_use(model_id, TargetUse(target_use_str))
            except ValueError:
                logger.debug("Unknown target_use '%s' for %s", target_use_str, model_name)

        # Provenance
        source_url = first.get("manufacturer_url", "").strip() or None
        db.insert_provenance(
            Provenance(
                source_name=f"enrichment_csv_{mfr_slug}",
                source_url=source_url,
                accessed_at=datetime.now(timezone.utc),
                extraction_method=extraction_method,
                notes=f"Seed import from {csv_path.name}",
            ),
            model_id,
        )

        # Insert each size
        for i, sv in enumerate(sizes):
            sv_id = db.upsert_size_variant(sv, model_id)
            size_count += 1

            if i < len(certs):
                db.delete_certifications_for_size(sv_id)
                db.insert_certification(certs[i], sv_id)
                cert_count += 1

            if i < len(perfs):
                db.insert_performance_data(perfs[i], sv_id)
                perf_count += 1

    return {
        "manufacturers": len(mfr_ids),
        "models": model_count,
        "sizes": size_count,
        "certifications": cert_count,
        "performance_records": perf_count,
        "skipped": len(skipped),
        "skipped_models": skipped,
    }


# ── Row → model mappers ───────────────────────────────────────────────────────


def _read_csv(csv_path: Path) -> list[dict]:
    """Read CSV with robust handling of empty fields."""
    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader)


def _safe_int(val: str) -> Optional[int]:
    """Parse int from string, returning None for empty/invalid."""
    val = val.strip() if val else ""
    if not val:
        return None
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return None


def _safe_float(val: str) -> Optional[float]:
    """Parse float from string, returning None for empty/invalid."""
    val = val.strip() if val else ""
    if not val:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _safe_bool(val: str) -> bool:
    """Parse bool from string, defaulting to True."""
    val = val.strip().lower() if val else ""
    return val not in ("false", "0", "no")


def _parse_category(val: str) -> Optional[WingCategory]:
    """Parse WingCategory from string."""
    val = val.strip().lower() if val else ""
    if not val:
        return None
    try:
        return WingCategory(val)
    except ValueError:
        return None


def _parse_date(val: str) -> Optional[date]:
    """Parse date from YYYY-MM-DD string."""
    val = val.strip() if val else ""
    if not val:
        return None
    try:
        return date.fromisoformat(val)
    except ValueError:
        return None


def _build_wing_model(row: dict, mfr_slug: str) -> WingModel:
    """Build a WingModel from a CSV row."""
    name = row.get("name", "").strip()
    model_slug = make_model_slug(mfr_slug, name)

    # DB schema uses year_released; fall back to legacy 'year' column
    year_raw = row.get("year_released", "") or row.get("year", "")

    return WingModel(
        name=name,
        slug=model_slug,
        category=_parse_category(row.get("category", "")),
        year_released=_safe_int(year_raw),
        year_discontinued=_safe_int(row.get("year_discontinued", "")),
        is_current=_safe_bool(row.get("is_current", "")),
        cell_count=_safe_int(row.get("cell_count", "")),
        riser_config=row.get("riser_config", "").strip() or None,
        manufacturer_url=row.get("manufacturer_url", "").strip() or None,
    )


def _build_size_variant(row: dict) -> Optional[SizeVariant]:
    """Build a SizeVariant from a CSV row."""
    label = row.get("size_label", "").strip()
    if not label:
        return None
    label = normalize_size_label(label)

    return SizeVariant(
        size_label=label,
        flat_area_m2=_safe_float(row.get("flat_area_m2")),
        flat_span_m=_safe_float(row.get("flat_span_m")),
        flat_aspect_ratio=_safe_float(row.get("flat_aspect_ratio")),
        proj_area_m2=_safe_float(row.get("proj_area_m2")),
        proj_span_m=_safe_float(row.get("proj_span_m")),
        proj_aspect_ratio=_safe_float(row.get("proj_aspect_ratio")),
        wing_weight_kg=_safe_float(row.get("wing_weight_kg")),
        ptv_min_kg=_safe_float(row.get("ptv_min_kg")),
        ptv_max_kg=_safe_float(row.get("ptv_max_kg")),
    )


def _build_certification(row: dict) -> Optional[Certification]:
    """Build a Certification from a CSV row, if cert data present.

    Normalizes the cert string via normalize_certification() to ensure
    correct standard/classification mapping (e.g., DHV 2 → LTF/2).
    """
    standard_str = row.get("cert_standard", "").strip()
    classification = row.get("cert_classification", "").strip()
    if not standard_str and not classification:
        return None

    # Normalize: combine standard + classification and parse
    raw_cert = f"{standard_str} {classification}".strip()
    standard, normalized_class = normalize_certification(raw_cert)

    return Certification(
        standard=standard,
        classification=normalized_class or None,
        test_lab=row.get("cert_test_lab", "").strip() or None,
        report_url=row.get("cert_report_url", "").strip() or None,
        test_date=_parse_date(row.get("cert_test_date", "")),
    )


def _build_performance_data(row: dict) -> Optional[PerformanceData]:
    """Build PerformanceData from a CSV row, only if at least one perf value exists."""
    speed_trim = _safe_float(row.get("speed_trim_kmh"))
    speed_max = _safe_float(row.get("speed_max_kmh"))
    glide = _safe_float(row.get("glide_ratio_best"))
    sink = _safe_float(row.get("min_sink_ms"))

    if speed_trim is None and speed_max is None and glide is None and sink is None:
        return None

    return PerformanceData(
        speed_trim_kmh=speed_trim,
        speed_max_kmh=speed_max,
        glide_ratio_best=glide,
        min_sink_ms=sink,
    )
