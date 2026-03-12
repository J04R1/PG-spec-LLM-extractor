"""
Deterministic markdown table parser — fallback extraction strategy.

Ported from the POC (extract.py, lines 477–700). Parses pipe-delimited spec
tables (Ozone-style) without any LLM call.  Produces an ExtractionResult
matching the same schema as the LLM path.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from .models import ExtractionResult, SizeSpec, TargetUse, WingCategory

logger = logging.getLogger(__name__)


# ── Label → field mapping ────────────────────────────────────────────────────
# Tuple: (field_name, is_per_size, needs_range_split)

_MD_ROW_MAP: dict[str, tuple[str, bool, bool]] = {
    # Cell count (model-level)
    "number of cells":                 ("cell_count",         False, False),
    "cells":                           ("cell_count",         False, False),
    # Flat geometry
    "flat area":                       ("flat_area_m2",       True,  False),
    "flat area (m2)":                  ("flat_area_m2",       True,  False),
    "flat area (m^2)":                 ("flat_area_m2",       True,  False),
    "projected area":                  ("proj_area_m2",       True,  False),
    "projected area (m2)":             ("proj_area_m2",       True,  False),
    "flat span":                       ("flat_span_m",        True,  False),
    "flat span (m)":                   ("flat_span_m",        True,  False),
    "projected span":                  ("proj_span_m",        True,  False),
    "projected span (m)":              ("proj_span_m",        True,  False),
    "flat aspect ratio":               ("flat_aspect_ratio",  True,  False),
    "projected aspect ratio":          ("proj_aspect_ratio",  True,  False),
    # Wing weight
    "glider weight":                   ("wing_weight_kg",     True,  False),
    "glider weight (kg)":              ("wing_weight_kg",     True,  False),
    "wing weight":                     ("wing_weight_kg",     True,  False),
    "wing weight (kg)":                ("wing_weight_kg",     True,  False),
    "weight (kg)":                     ("wing_weight_kg",     True,  False),
    # Weight range (needs_range_split → ptv_min_kg / ptv_max_kg)
    "certified weight range":          ("_ptv_range",         True,  True),
    "certified weight range (kg)":     ("_ptv_range",         True,  True),
    "in-flight weight range":          ("_ptv_range",         True,  True),
    "in-flight weight range (kg)":     ("_ptv_range",         True,  True),
    "in flight weight range":          ("_ptv_range",         True,  True),
    "weight range":                    ("_ptv_range",         True,  True),
    "weight range (kg)":               ("_ptv_range",         True,  True),
    # Certification
    "en":                              ("certification",      True,  False),
    "en/ltf":                          ("certification",      True,  False),
    "ltf / en":                        ("certification",      True,  False),
    "certification":                   ("certification",      True,  False),
    "ltf":                             ("certification",      True,  False),
    # Short label variants (older Ozone pages)
    "area flat":                       ("flat_area_m2",       True,  False),
    "area proj.":                      ("proj_area_m2",       True,  False),
    "area proj":                       ("proj_area_m2",       True,  False),
    "span flat":                       ("flat_span_m",        True,  False),
    "span proj.":                      ("proj_span_m",        True,  False),
    "span proj":                       ("proj_span_m",        True,  False),
    "ar flat":                         ("flat_aspect_ratio",  True,  False),
    "ar proj.":                        ("proj_aspect_ratio",  True,  False),
    "ar proj":                         ("proj_aspect_ratio",  True,  False),
}


_SIZE_LABEL_HINTS = {
    "xs", "s", "ms", "sm", "m", "ml", "l", "xl", "xxl",
    "xxs", "xxxl",
    "22", "23", "24", "25", "26", "27", "28", "29", "30", "31",
}


# ── Helpers ──────────────────────────────────────────────────────────────────


def _strip_md_formatting(s: str) -> str:
    """Strip markdown bold/italic markers."""
    return re.sub(r"\*{1,3}|_{1,3}", "", s).strip()


def _parse_number(s: str) -> float | None:
    """Parse a numeric string, stripping units and handling EU decimals."""
    s = s.strip().rstrip("*")
    s = re.sub(r"\s*(kg|m2|m\^2|m|m²)\s*$", "", s, flags=re.IGNORECASE)
    # EU decimal: "18,9" → "18.9"
    if "," in s and "." not in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _parse_weight_range(s: str) -> tuple[float | None, float | None]:
    """Parse '65-85' or '65 – 85' into (min, max)."""
    s = s.strip().rstrip("*")
    s = re.sub(r"\s*(kg)\s*$", "", s, flags=re.IGNORECASE)
    parts = re.split(r"\s*[-–—/]\s*", s)
    if len(parts) == 2:
        return _parse_number(parts[0]), _parse_number(parts[1])
    return None, None


def _slug_to_name(url: str) -> str:
    """Derive a model name from the URL's last path segment."""
    slug = url.rstrip("/").split("/")[-1]
    return slug.replace("-", " ").title()


def _infer_target_use(certs: list[str]) -> TargetUse:
    """Map primary certification class to target_use."""
    if not certs:
        return TargetUse.leisure

    primary = certs[0].upper()
    mapping = {
        "A": TargetUse.school,
        "B": TargetUse.xc,
        "C": TargetUse.xc,
        "D": TargetUse.competition,
        "CCC": TargetUse.competition,
    }
    return mapping.get(primary, TargetUse.leisure)


# ── Main parser ──────────────────────────────────────────────────────────────


def parse_specs_from_markdown(
    markdown: str,
    url: str,
) -> Optional[ExtractionResult]:
    """Parse a pipe-delimited spec table from rendered markdown.

    Returns an ExtractionResult on success, or None if no valid spec table
    is found.
    """
    lines = markdown.split("\n")

    # ── Phase 1: Find the spec table ─────────────────────────────────────
    spec_start = None
    for i, line in enumerate(lines):
        if re.match(r"^#+\s*specifications?\s*$", line.strip(), re.IGNORECASE):
            spec_start = i
            break

    if spec_start is None:
        for i, line in enumerate(lines):
            low = line.strip().lower()
            if any(low.startswith(k) and "|" in line for k in _MD_ROW_MAP):
                spec_start = max(0, i - 5)
                break

    if spec_start is None:
        return None

    # ── Phase 2: Collect pipe-delimited rows ─────────────────────────────
    spec_rows: list[tuple[str, list[str]]] = []
    for line in lines[spec_start:]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            if spec_rows:
                continue
            continue
        if "|" not in stripped:
            if spec_rows:
                break
            continue

        # Skip separator rows
        if re.match(r"^[\s|:-]+$", stripped):
            continue

        parts = [p.strip() for p in stripped.split("|")]
        parts = [p for p in parts if p]
        if len(parts) >= 2:
            spec_rows.append((parts[0], parts[1:]))

    if not spec_rows:
        return None

    # ── Phase 3: Detect size labels ──────────────────────────────────────
    num_sizes = max(len(vals) for _, vals in spec_rows)

    size_labels: list[str] | None = None
    first_label_clean = _strip_md_formatting(spec_rows[0][0]).lower().strip()

    if first_label_clean in ("", "size", "sizes"):
        size_labels = [_strip_md_formatting(v) for v in spec_rows[0][1]]
        spec_rows = spec_rows[1:]

    if not size_labels:
        all_cells = [spec_rows[0][0]] + list(spec_rows[0][1])
        all_clean = {_strip_md_formatting(v).lower().strip() for v in all_cells}
        if all_clean <= _SIZE_LABEL_HINTS:
            size_labels = [_strip_md_formatting(v) for v in all_cells]
            spec_rows = spec_rows[1:]
        else:
            first_vals_clean = {
                _strip_md_formatting(v).lower().strip()
                for v in spec_rows[0][1]
            } if spec_rows else set()
            if first_vals_clean & _SIZE_LABEL_HINTS:
                size_labels = [_strip_md_formatting(v) for v in spec_rows[0][1]]
                spec_rows = spec_rows[1:]

    if not size_labels:
        size_labels = [f"Size{i + 1}" for i in range(num_sizes)]

    # ── Phase 4: Parse data rows ─────────────────────────────────────────
    sizes: list[dict] = [{"size_label": sl.strip().upper()} for sl in size_labels]
    model_data: dict = {}

    for label, values in spec_rows:
        label_stripped = re.sub(r"\s*\*\w[\w\s]*$", "", label).strip()
        label_low = _strip_md_formatting(label_stripped).lower().strip()
        label_clean = re.sub(r"\s*\(.*?\)\s*$", "", label_low).strip()

        mapping = _MD_ROW_MAP.get(label_low) or _MD_ROW_MAP.get(label_clean)
        if not mapping:
            continue

        field_name, is_per_size, needs_range = mapping

        if not is_per_size:
            for v in values:
                parsed = _parse_number(v)
                if parsed is not None:
                    model_data[field_name] = (
                        int(parsed) if parsed == int(parsed) else parsed
                    )
                    break
        else:
            for j, v in enumerate(values):
                if j >= len(sizes):
                    break
                if needs_range:
                    ptv_min, ptv_max = _parse_weight_range(v)
                    if ptv_min is not None:
                        sizes[j]["ptv_min_kg"] = ptv_min
                    if ptv_max is not None:
                        sizes[j]["ptv_max_kg"] = ptv_max
                elif field_name == "certification":
                    cert = v.strip().rstrip("*")
                    if cert:
                        cert_upper = cert.upper().strip()
                        if cert_upper.startswith("CCC"):
                            cert = "CCC"
                        sizes[j]["certification"] = cert
                else:
                    parsed = _parse_number(v)
                    if parsed is not None:
                        sizes[j][field_name] = parsed

    # ── Phase 5: Validate — require weight ranges or certifications ──────
    valid_sizes = [s for s in sizes if s.get("ptv_min_kg") or s.get("certification")]
    if not valid_sizes:
        return None

    # ── Phase 6: Model name inference ────────────────────────────────────
    model_name = _slug_to_name(url)

    search_range = lines[: spec_start or 80]
    for line in search_range:
        stripped = line.strip()
        if " | " in stripped:
            parts = stripped.split(" | ")
            candidate = parts[0].strip()
            if (
                2 <= len(candidate) <= 40
                and not candidate.startswith(("[", "!", "*", "#"))
                and candidate.lower() not in ("products", "gliders", "home")
                and any(c.isalnum() for c in candidate)
            ):
                rest = " | ".join(parts[1:]).lower()
                if "ozone" in rest or "paraglider" in rest or "logo" in rest:
                    model_name = candidate
                    break

    # ── Phase 7: Infer target_use ────────────────────────────────────────
    certs = [
        s.get("certification", "").upper()
        for s in valid_sizes
        if s.get("certification")
    ]
    target_use = _infer_target_use(certs)

    # ── Phase 8: Build ExtractionResult ──────────────────────────────────
    size_specs = [SizeSpec(**s) for s in valid_sizes]

    result = ExtractionResult(
        model_name=model_name,
        category=WingCategory.paraglider,
        target_use=target_use,
        product_url=url,
        sizes=size_specs,
        **model_data,
    )

    logger.info(
        "Markdown parser extracted: %s — %d sizes",
        result.model_name,
        len(result.sizes),
    )
    return result
