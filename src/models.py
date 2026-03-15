"""
Pydantic models matching the OpenParaglider database schema (v2).

These models serve as both:
  1. Extraction target schema (passed to LLM as JSON schema)
  2. Validation layer before SQLite insertion

Schema v2 changes (Iteration 10):
  - Removed description from WingModel (facts-only policy)
  - Moved target_use from WingModel to ModelTargetUse junction
  - Separated performance data from SizeVariant into PerformanceData
  - Enhanced Certification with certified weight range, report_number, status
  - Replaced polymorphic DataSource with per-model Provenance
  - Renamed year → year_released, country → country_code
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ── Enums matching CHECK constraints ───────────────────────────────────────────


class WingCategory(str, Enum):
    paraglider = "paraglider"
    tandem = "tandem"
    miniwing = "miniwing"
    single_skin = "single_skin"
    acro = "acro"
    speedwing = "speedwing"
    paramotor = "paramotor"


class TargetUse(str, Enum):
    school = "school"
    leisure = "leisure"
    xc = "xc"
    competition = "competition"
    hike_and_fly = "hike_and_fly"
    vol_biv = "vol_biv"
    acro = "acro"
    speedflying = "speedflying"


class CertStandard(str, Enum):
    EN = "EN"
    LTF = "LTF"
    AFNOR = "AFNOR"
    DGAC = "DGAC"
    CCC = "CCC"
    other = "other"


class PerformanceSourceType(str, Enum):
    manufacturer_stated = "manufacturer_stated"
    test_report = "test_report"
    independent_test = "independent_test"


class CertificationStatus(str, Enum):
    active = "active"
    expired = "expired"
    revoked = "revoked"


# ── Domain models ──────────────────────────────────────────────────────────────


class Manufacturer(BaseModel):
    """manufacturers table — paraglider brands."""

    id: Optional[int] = None
    name: str
    slug: str
    country_code: Optional[str] = Field(None, max_length=2)
    website: Optional[str] = None
    logo_url: Optional[str] = None


class WingModel(BaseModel):
    """models table — a wing design (e.g. 'Ozone Buzz Z7')."""

    id: Optional[int] = None
    manufacturer_id: Optional[int] = None
    name: str
    slug: str = Field(..., description="Format: {manufacturer_slug}-{model_slug}")
    category: Optional[WingCategory] = None
    year_released: Optional[int] = None
    year_discontinued: Optional[int] = None
    is_current: bool = True
    cell_count: Optional[int] = None
    cell_count_closed: Optional[int] = None
    line_material: Optional[str] = None
    riser_config: Optional[str] = None
    manufacturer_url: Optional[str] = None


class ModelTargetUse(BaseModel):
    """model_target_uses junction table — wings serve multiple purposes."""

    model_id: Optional[int] = None
    target_use: TargetUse


class SizeVariant(BaseModel):
    """size_variants table — a specific size of a wing (geometry & weight only)."""

    id: Optional[int] = None
    model_id: Optional[int] = None
    size_label: str

    # Flat geometry
    flat_area_m2: Optional[float] = None
    flat_span_m: Optional[float] = None
    flat_aspect_ratio: Optional[float] = None

    # Projected geometry
    proj_area_m2: Optional[float] = None
    proj_span_m: Optional[float] = None
    proj_aspect_ratio: Optional[float] = None

    # Weight & loading
    wing_weight_kg: Optional[float] = None
    ptv_min_kg: Optional[float] = None
    ptv_max_kg: Optional[float] = None

    # Line length
    line_length_m: Optional[float] = None


class PerformanceData(BaseModel):
    """performance_data table — manufacturer-claimed or tested performance."""

    id: Optional[int] = None
    size_variant_id: Optional[int] = None
    speed_trim_kmh: Optional[float] = None
    speed_max_kmh: Optional[float] = None
    glide_ratio_best: Optional[float] = None
    min_sink_ms: Optional[float] = None
    source_type: PerformanceSourceType = PerformanceSourceType.manufacturer_stated


class Certification(BaseModel):
    """certifications table — EN/LTF/CCC certification for a size variant."""

    id: Optional[int] = None
    size_variant_id: Optional[int] = None
    standard: Optional[CertStandard] = None
    classification: Optional[str] = None
    ptv_min_kg: Optional[float] = None
    ptv_max_kg: Optional[float] = None
    test_lab: Optional[str] = None
    report_number: Optional[str] = None
    report_url: Optional[str] = None
    test_date: Optional[date] = None
    status: CertificationStatus = CertificationStatus.active


class Provenance(BaseModel):
    """provenance table — per-model source tracking (replaces data_sources)."""

    id: Optional[int] = None
    model_id: Optional[int] = None
    source_name: str
    source_url: Optional[str] = None
    accessed_at: Optional[datetime] = None
    extraction_method: Optional[str] = None
    notes: Optional[str] = None
    created_at: Optional[datetime] = None


# ── LLM extraction output schema ──────────────────────────────────────────────
# Flat structure the LLM returns, before normalization into domain models.


class SizeSpec(BaseModel):
    """Single size entry as extracted by the LLM."""

    size_label: str
    flat_area_m2: Optional[float] = None
    flat_span_m: Optional[float] = None
    flat_aspect_ratio: Optional[float] = None
    proj_area_m2: Optional[float] = None
    proj_span_m: Optional[float] = None
    proj_aspect_ratio: Optional[float] = None
    wing_weight_kg: Optional[float] = None
    ptv_min_kg: Optional[float] = None
    ptv_max_kg: Optional[float] = None
    speed_trim_kmh: Optional[float] = None
    speed_max_kmh: Optional[float] = None
    glide_ratio_best: Optional[float] = None
    min_sink_ms: Optional[float] = None
    certification: Optional[str] = None


class ExtractionResult(BaseModel):
    """Top-level output from LLM extraction for a single product page."""

    model_name: str
    category: Optional[WingCategory] = None
    target_use: Optional[TargetUse] = None
    cell_count: Optional[int] = None
    line_material: Optional[str] = None
    riser_config: Optional[str] = None
    product_url: Optional[str] = None
    year: Optional[int] = None
    sizes: list[SizeSpec] = Field(default_factory=list)
