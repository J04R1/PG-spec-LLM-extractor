"""
Shared fixtures and ground truth data for the PG Spec Extractor test suite.

Ground truth values verified against:
  - ozone_enrichment.csv (Ozone Swift 6: 5 sizes XS/S/MS/ML/L)
  - fredvol_raw.csv (Advance Iota 2: numeric sizes 23/25/27/29)
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from src.adapters.base import LLMAdapter
from src.db import Database
from src.models import ExtractionResult, Manufacturer, SizeSpec


# ── Strict float comparison helper ─────────────────────────────────────────


def assert_spec_field(actual, expected, field_name: str, tolerance: float = 0.01):
    """Assert a spec field matches expected value within tolerance.

    For int fields (cell_count), exact match is required.
    For float fields, tolerance is ±0.01 by default.
    """
    if expected is None:
        return  # skip optional fields
    if actual is None:
        raise AssertionError(
            f"{field_name}: got None, expected {expected}"
        )
    if isinstance(expected, int):
        assert actual == expected, (
            f"{field_name}: got {actual}, expected {expected} (exact int)"
        )
    else:
        assert abs(actual - expected) <= tolerance, (
            f"{field_name}: got {actual}, expected {expected} (±{tolerance})"
        )


def assert_size_specs(actual_size, expected: dict, size_label: str):
    """Assert all 10 key spec fields for a size variant against ground truth."""
    fields = [
        "flat_area_m2", "flat_span_m", "flat_aspect_ratio",
        "proj_area_m2", "proj_span_m", "proj_aspect_ratio",
        "wing_weight_kg", "ptv_min_kg", "ptv_max_kg",
    ]
    for field in fields:
        if field in expected:
            actual_val = getattr(actual_size, field, None)
            assert_spec_field(actual_val, expected[field], f"{size_label}.{field}")


# ── Ground truth: Ozone Swift 6 ───────────────────────────────────────────

SWIFT6_EXPECTED = {
    "XS": {
        "flat_area_m2": 20.05, "flat_span_m": 10.69, "flat_aspect_ratio": 5.7,
        "proj_area_m2": 17.0, "proj_span_m": 8.43, "proj_aspect_ratio": 4.18,
        "wing_weight_kg": 3.57, "ptv_min_kg": 55.0, "ptv_max_kg": 72.0,
    },
    "S": {
        "flat_area_m2": 22.54, "flat_span_m": 11.34, "flat_aspect_ratio": 5.7,
        "proj_area_m2": 19.11, "proj_span_m": 8.94, "proj_aspect_ratio": 4.18,
        "wing_weight_kg": 3.88, "ptv_min_kg": 65.0, "ptv_max_kg": 85.0,
    },
    "MS": {
        "flat_area_m2": 24.04, "flat_span_m": 11.71, "flat_aspect_ratio": 5.7,
        "proj_area_m2": 20.38, "proj_span_m": 9.23, "proj_aspect_ratio": 4.18,
        "wing_weight_kg": 4.11, "ptv_min_kg": 75.0, "ptv_max_kg": 95.0,
    },
    "ML": {
        "flat_area_m2": 25.38, "flat_span_m": 12.03, "flat_aspect_ratio": 5.7,
        "proj_area_m2": 21.52, "proj_span_m": 9.49, "proj_aspect_ratio": 4.18,
        "wing_weight_kg": 4.27, "ptv_min_kg": 85.0, "ptv_max_kg": 105.0,
    },
    "L": {
        "flat_area_m2": 26.7, "flat_span_m": 12.34, "flat_aspect_ratio": 5.7,
        "proj_area_m2": 22.64, "proj_span_m": 9.73, "proj_aspect_ratio": 4.18,
        "wing_weight_kg": 4.41, "ptv_min_kg": 95.0, "ptv_max_kg": 115.0,
    },
}

SWIFT6_CELL_COUNT = 62


# ── Ground truth: Advance IOTA DLS (from advance_enrichment_all.csv) ────────

IOTA_DLS_EXPECTED = {
    "21": {
        "flat_area_m2": 21.78, "flat_span_m": 11.04, "flat_aspect_ratio": 5.6,
        "proj_area_m2": 18.57, "proj_span_m": 8.63, "proj_aspect_ratio": 4.01,
        "wing_weight_kg": 3.9, "ptv_min_kg": 60.0, "ptv_max_kg": 77.0,
    },
    "23": {
        "flat_area_m2": 23.48, "flat_span_m": 11.47, "flat_aspect_ratio": 5.6,
        "proj_area_m2": 19.94, "proj_span_m": 8.96, "proj_aspect_ratio": 4.03,
        "wing_weight_kg": 4.1, "ptv_min_kg": 70.0, "ptv_max_kg": 88.0,
    },
    "25": {
        "flat_area_m2": 25.18, "flat_span_m": 11.87, "flat_aspect_ratio": 5.6,
        "proj_area_m2": 21.39, "proj_span_m": 9.27, "proj_aspect_ratio": 4.02,
        "wing_weight_kg": 4.35, "ptv_min_kg": 80.0, "ptv_max_kg": 100.0,
    },
    "27": {
        "flat_area_m2": 27.23, "flat_span_m": 12.35, "flat_aspect_ratio": 5.6,
        "proj_area_m2": 23.13, "proj_span_m": 9.64, "proj_aspect_ratio": 4.02,
        "wing_weight_kg": 4.6, "ptv_min_kg": 92.0, "ptv_max_kg": 114.0,
    },
    "29": {
        "flat_area_m2": 29.24, "flat_span_m": 12.8, "flat_aspect_ratio": 5.6,
        "proj_area_m2": 24.83, "proj_span_m": 9.99, "proj_aspect_ratio": 4.02,
        "wing_weight_kg": 4.9, "ptv_min_kg": 105.0, "ptv_max_kg": 128.0,
    },
}

IOTA_DLS_CELL_COUNT = 59


# ── Markdown fixtures ──────────────────────────────────────────────────────

SWIFT6_MARKDOWN = """\
# Swift 6

The Swift 6 is the next step in easy performance.

## Specifications

| | XS | S | MS | ML | L |
|---|---|---|---|---|---|
| Number of cells | 62 | 62 | 62 | 62 | 62 |
| Flat area (m2) | 20,05 | 22,54 | 24,04 | 25,38 | 26,70 |
| Flat span (m) | 10,69 | 11,34 | 11,71 | 12,03 | 12,34 |
| Flat aspect ratio | 5,70 | 5,70 | 5,70 | 5,70 | 5,70 |
| Projected area (m2) | 17,00 | 19,11 | 20,38 | 21,52 | 22,64 |
| Projected span (m) | 8,43 | 8,94 | 9,23 | 9,49 | 9,73 |
| Projected aspect ratio | 4,18 | 4,18 | 4,18 | 4,18 | 4,18 |
| Glider weight (kg) | 3,57 | 3,88 | 4,11 | 4,27 | 4,41 |
| In-flight weight range (kg) | 55-72 | 65-85 | 75-95 | 85-105 | 95-115 |
| Certification | EN B | EN B | EN B | EN B | EN B |
"""

ADVANCE_IOTA_DLS_MARKDOWN = """\
# Iota DLS

High-B XC paraglider with DLS construction.

## Specifications

| | 21 | 23 | 25 | 27 | 29 |
|---|---|---|---|---|---|
| Number of cells | 59 | 59 | 59 | 59 | 59 |
| Flat area (m2) | 21,78 | 23,48 | 25,18 | 27,23 | 29,24 |
| Flat span (m) | 11,04 | 11,47 | 11,87 | 12,35 | 12,80 |
| Flat aspect ratio | 5,60 | 5,60 | 5,60 | 5,60 | 5,60 |
| Projected area (m2) | 18,57 | 19,94 | 21,39 | 23,13 | 24,83 |
| Projected span (m) | 8,63 | 8,96 | 9,27 | 9,64 | 9,99 |
| Projected aspect ratio | 4,01 | 4,03 | 4,02 | 4,02 | 4,02 |
| Glider weight (kg) | 3,90 | 4,10 | 4,35 | 4,60 | 4,90 |
| In-flight weight range (kg) | 60-77 | 70-88 | 80-100 | 92-114 | 105-128 |
| Certification | B | B | B | B | B |
"""

# Existing Rush 6 fixture from validate_pipeline.py (kept for backward compat)
RUSH6_MARKDOWN = """\
# Rush 6

Some marketing text

## Specifications

| | XS | S | M | ML | L |
|---|---|---|---|---|---|
| Cells | 52 | 52 | 52 | 52 | 52 |
| Flat area (m²) | 20,14 | 22,05 | 24,12 | 25,81 | 27,62 |
| Flat span (m) | 10,37 | 10,85 | 11,34 | 11,73 | 12,14 |
| Flat aspect ratio | 5,34 | 5,34 | 5,34 | 5,34 | 5,34 |
| Projected area (m²) | 16,76 | 18,35 | 20,07 | 21,48 | 22,99 |
| Projected span (m) | 8,20 | 8,58 | 8,97 | 9,28 | 9,60 |
| Projected aspect ratio | 4,01 | 4,01 | 4,01 | 4,01 | 4,01 |
| Wing weight (kg) | 4,10 | 4,40 | 4,80 | 5,05 | 5,35 |
| In-flight weight range (kg) | 55-75 | 65-85 | 80-100 | 90-110 | 100-125 |
| Certification | EN/LTF B | EN/LTF B | EN/LTF B | EN/LTF B | EN/LTF B |
| Line material | Liros TSL / DSL / PPSL | Liros TSL / DSL / PPSL | Liros TSL / DSL / PPSL | Liros TSL / DSL / PPSL | Liros TSL / DSL / PPSL |
| Risers | 12mm Kevlar | 12mm Kevlar | 12mm Kevlar | 12mm Kevlar | 12mm Kevlar |
"""

RUSH6_EXPECTED = {
    "XS": {"flat_area_m2": 20.14, "ptv_min_kg": 55.0, "ptv_max_kg": 75.0},
    "S": {"flat_area_m2": 22.05, "ptv_min_kg": 65.0, "ptv_max_kg": 85.0},
    "M": {"flat_area_m2": 24.12, "ptv_min_kg": 80.0, "ptv_max_kg": 100.0},
    "ML": {"flat_area_m2": 25.81, "ptv_min_kg": 90.0, "ptv_max_kg": 110.0},
    "L": {"flat_area_m2": 27.62, "ptv_min_kg": 100.0, "ptv_max_kg": 125.0},
}


# ── Mock LLM adapters ─────────────────────────────────────────────────────


class MockAdapter(LLMAdapter):
    """Returns a canned Swift 6 ExtractionResult for any input."""

    def __init__(self, result: dict | None = None):
        self._result = result or {
            "model_name": "Swift 6",
            "category": "paraglider",
            "target_use": "xc",
            "cell_count": 62,
            "sizes": [
                {
                    "size_label": "XS",
                    "flat_area_m2": 20.05,
                    "flat_span_m": 10.69,
                    "flat_aspect_ratio": 5.7,
                    "proj_area_m2": 17.0,
                    "proj_span_m": 8.43,
                    "proj_aspect_ratio": 4.18,
                    "wing_weight_kg": 3.57,
                    "ptv_min_kg": 55.0,
                    "ptv_max_kg": 72.0,
                    "certification": "EN B",
                },
                {
                    "size_label": "S",
                    "flat_area_m2": 22.54,
                    "flat_span_m": 11.34,
                    "flat_aspect_ratio": 5.7,
                    "proj_area_m2": 19.11,
                    "proj_span_m": 8.94,
                    "proj_aspect_ratio": 4.18,
                    "wing_weight_kg": 3.88,
                    "ptv_min_kg": 65.0,
                    "ptv_max_kg": 85.0,
                    "certification": "EN B",
                },
            ],
        }

    def extract(self, markdown: str, schema: dict, instructions: str | None = None) -> dict:
        return self._result

    def is_available(self) -> bool:
        return True


class FailingAdapter(LLMAdapter):
    """Always raises RuntimeError to test fallback paths."""

    def extract(self, markdown: str, schema: dict, instructions: str | None = None) -> dict:
        raise RuntimeError("Simulated LLM failure")

    def is_available(self) -> bool:
        return False


# ── Pytest fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def tmp_db(tmp_path):
    """Provide an isolated temp SQLite Database, auto-closed after test."""
    db = Database(tmp_path / "test.db")
    db.connect()
    yield db
    db.close()


@pytest.fixture
def sample_config():
    """Minimal manufacturer config dict."""
    return {
        "manufacturer": {"name": "Ozone", "slug": "ozone"},
        "sources": [{"url": "https://flyozone.com/paragliders/"}],
    }


@pytest.fixture
def ozone_manufacturer():
    """Ozone Manufacturer model instance."""
    return Manufacturer(
        name="Ozone",
        slug="ozone",
        country_code="FR",
        website="https://flyozone.com",
    )
