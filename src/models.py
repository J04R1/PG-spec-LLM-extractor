"""
Pydantic models matching the OpenParaglider production database schema.

These models serve as both:
  1. Extraction target schema (passed to LLM as JSON schema)
  2. Validation layer before SQLite insertion
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ── Enums matching production VARCHAR + CHECK constraints ──────────────────────


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
    tandem = "tandem"


class CertStandard(str, Enum):
    EN = "EN"
    LTF = "LTF"
    AFNOR = "AFNOR"
    DGAC = "DGAC"
    CCC = "CCC"
    other = "other"


class EntityType(str, Enum):
    manufacturer = "manufacturer"
    model = "model"
    size_variant = "size_variant"
    certification = "certification"


# ── Domain models ──────────────────────────────────────────────────────────────


class Manufacturer(BaseModel):
    """manufacturers table — paraglider brands."""

    id: Optional[int] = None
    name: str
    slug: str
    country: Optional[str] = Field(None, max_length=2)
    website: Optional[str] = None
    logo_url: Optional[str] = None


class WingModel(BaseModel):
    """models table — a wing design (e.g. 'Ozone Buzz Z7')."""

    id: Optional[int] = None
    manufacturer_id: Optional[int] = None
    name: str
    slug: str = Field(..., description="Format: {manufacturer_slug}-{model_slug}")
    category: Optional[WingCategory] = None
    target_use: Optional[TargetUse] = None
    year: Optional[int] = None
    is_current: bool = True
    cell_count: Optional[int] = None
    line_material: Optional[str] = None
    riser_config: Optional[str] = None
    manufacturer_url: Optional[str] = None
    description: Optional[str] = None


class SizeVariant(BaseModel):
    """size_variants table — a specific size of a wing."""

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

    # Performance
    speed_trim_kmh: Optional[float] = None
    speed_max_kmh: Optional[float] = None
    glide_ratio_best: Optional[float] = None
    min_sink_ms: Optional[float] = None


class Certification(BaseModel):
    """certifications table — EN/LTF/CCC certification for a size variant."""

    id: Optional[int] = None
    size_variant_id: Optional[int] = None
    standard: Optional[CertStandard] = None
    classification: Optional[str] = None
    test_lab: Optional[str] = None
    test_report_url: Optional[str] = None
    test_date: Optional[date] = None


class DataSource(BaseModel):
    """data_sources table — provenance tracker for every record."""

    id: Optional[int] = None
    entity_type: EntityType
    entity_id: int
    source_name: str
    source_url: Optional[str] = None
    contributed_by: Optional[str] = None
    verified: bool = False
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
