"""
Post-extraction normalization rules.

Transforms raw LLM extraction output into canonical forms matching
the database schema v2. Handles:
  - Certification normalization (EN-A, LTF B → standard + classification)
  - Size label normalization
  - Performance data separation (from SizeVariant → PerformanceData)
  - Model slug generation ({manufacturer_slug}-{model_slug})
"""

from __future__ import annotations

import re
import logging

from .models import (
    Certification,
    CertStandard,
    ExtractionResult,
    PerformanceData,
    SizeVariant,
    WingModel,
)

logger = logging.getLogger(__name__)


# ── Certification normalization ────────────────────────────────────────────────

_CERT_PATTERN = re.compile(
    r"(?P<standard>EN|LTF|AFNOR|DGAC|CCC|CIVL\s*CCC)"
    r"[\s\-/]*"
    r"(?P<class>[A-D])?",
    re.IGNORECASE,
)

_DHV_MAP = {
    "1": ("LTF", "A"),
    "1-2": ("LTF", "B"),
    "2": ("LTF", "C"),
    "2-3": ("LTF", "C"),
    "3": ("LTF", "D"),
}


def normalize_certification(raw: str) -> tuple[CertStandard, str]:
    """Parse a raw certification string into (standard, classification).

    Examples:
        'EN B'      → (CertStandard.EN, 'B')
        'LTF A'     → (CertStandard.LTF, 'A')
        'CCC'       → (CertStandard.CCC, 'CCC')
        'DHV 1-2'   → (CertStandard.LTF, 'B')
        'A'         → (CertStandard.EN, 'A')   # bare letter defaults to EN
    """
    raw = raw.strip()

    # Handle CCC variants
    if re.match(r"(?:CIVL\s*)?CCC", raw, re.IGNORECASE):
        return CertStandard.CCC, "CCC"

    # Handle combined "EN/LTF" or "LTF/EN" labels (common Ozone format)
    combined = re.match(
        r"(?:EN\s*/\s*LTF|LTF\s*/\s*EN)\s*([A-D])", raw, re.IGNORECASE
    )
    if combined:
        return CertStandard.EN, combined.group(1).upper()

    # Handle DHV numbering
    dhv_match = re.match(r"DHV\s*(\d(?:-\d)?)", raw, re.IGNORECASE)
    if dhv_match:
        key = dhv_match.group(1)
        if key in _DHV_MAP:
            std, cls = _DHV_MAP[key]
            return CertStandard(std), cls

    # Handle EN/LTF patterns
    m = _CERT_PATTERN.search(raw)
    if m:
        std_raw = m.group("standard").upper().replace(" ", "")
        if std_raw.startswith("CIVL"):
            return CertStandard.CCC, "CCC"
        standard = CertStandard(std_raw)
        classification = (m.group("class") or "").upper()
        return standard, classification

    # Bare letter (A, B, C, D) defaults to EN
    if re.match(r"^[A-Da-d]$", raw):
        return CertStandard.EN, raw.upper()

    logger.warning("Could not normalize certification: '%s'", raw)
    return CertStandard.other, raw


# ── Size label normalization ───────────────────────────────────────────────────

_SIZE_MAP = {
    "extra small": "XS", "xs": "XS", "1": "XS",
    "small": "S", "s": "S", "sm": "S", "2": "S",
    "medium": "M", "m": "M", "md": "M", "3": "M",
    "large": "L", "l": "L", "lg": "L", "4": "L",
    "extra large": "XL", "xl": "XL", "5": "XL",
}


def normalize_size_label(raw: str) -> str:
    """Normalize a size label to canonical form (XS/S/M/L/XL).

    Non-standard labels (MS, ML, SM, etc.) and numeric labels (21, 23, 25)
    are preserved as-is — they represent manufacturer-specific sizing systems.
    """
    key = raw.strip().lower()
    return _SIZE_MAP.get(key, raw.strip().upper())


# ── Slug generation ───────────────────────────────────────────────────────────


def make_model_slug(manufacturer_slug: str, model_name: str) -> str:
    """Generate a model slug in the format {manufacturer}-{model}.

    Example: make_model_slug('ozone', 'Buzz Z7') → 'ozone-buzz-z7'
    """
    clean = re.sub(r"[^a-z0-9]+", "-", model_name.lower()).strip("-")
    return f"{manufacturer_slug}-{clean}"


# ── Full normalization pipeline ────────────────────────────────────────────────


def normalize_extraction(
    result: ExtractionResult,
    manufacturer_slug: str,
    is_current: bool = True,
    source_url: str | None = None,
) -> tuple[WingModel, list[SizeVariant], list[Certification], list[PerformanceData]]:
    """Transform an ExtractionResult into domain models (schema v2).

    Returns:
        Tuple of (WingModel, list[SizeVariant], list[Certification], list[PerformanceData])
    """
    slug = make_model_slug(manufacturer_slug, result.model_name)

    wing = WingModel(
        name=result.model_name,
        slug=slug,
        category=result.category,
        year_released=result.year,
        is_current=is_current,
        cell_count=result.cell_count,
        line_material=result.line_material,
        riser_config=result.riser_config,
        manufacturer_url=source_url or result.product_url,
    )

    sizes: list[SizeVariant] = []
    certs: list[Certification] = []
    perfs: list[PerformanceData] = []

    for size_spec in result.sizes:
        sv = SizeVariant(
            size_label=normalize_size_label(size_spec.size_label),
            flat_area_m2=size_spec.flat_area_m2,
            flat_span_m=size_spec.flat_span_m,
            flat_aspect_ratio=size_spec.flat_aspect_ratio,
            proj_area_m2=size_spec.proj_area_m2,
            proj_span_m=size_spec.proj_span_m,
            proj_aspect_ratio=size_spec.proj_aspect_ratio,
            wing_weight_kg=size_spec.wing_weight_kg,
            ptv_min_kg=size_spec.ptv_min_kg,
            ptv_max_kg=size_spec.ptv_max_kg,
        )
        sizes.append(sv)

        if size_spec.certification:
            standard, classification = normalize_certification(
                size_spec.certification
            )
            cert = Certification(
                standard=standard,
                classification=classification,
            )
            certs.append(cert)

        # Extract performance data if any performance fields are present
        has_perf = any([
            size_spec.speed_trim_kmh,
            size_spec.speed_max_kmh,
            size_spec.glide_ratio_best,
            size_spec.min_sink_ms,
        ])
        if has_perf:
            perf = PerformanceData(
                speed_trim_kmh=size_spec.speed_trim_kmh,
                speed_max_kmh=size_spec.speed_max_kmh,
                glide_ratio_best=size_spec.glide_ratio_best,
                min_sink_ms=size_spec.min_sink_ms,
            )
            perfs.append(perf)

    return wing, sizes, certs, perfs
