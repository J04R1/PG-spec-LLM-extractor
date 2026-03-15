"""Tests for Pydantic models — validation, round-trips, enums."""

import pytest
from pydantic import ValidationError

from src.models import (
    CertStandard,
    ExtractionResult,
    Manufacturer,
    PerformanceData,
    PerformanceSourceType,
    SizeSpec,
    SizeVariant,
    TargetUse,
    WingCategory,
    WingModel,
)


class TestExtractionResult:
    def test_valid_round_trip(self):
        data = {
            "model_name": "Swift 6",
            "category": "paraglider",
            "target_use": "xc",
            "cell_count": 62,
            "sizes": [
                {"size_label": "S", "flat_area_m2": 22.54, "ptv_min_kg": 65.0},
            ],
        }
        result = ExtractionResult.model_validate(data)
        dumped = result.model_dump()
        assert dumped["model_name"] == "Swift 6"
        assert dumped["cell_count"] == 62
        assert len(dumped["sizes"]) == 1
        assert dumped["sizes"][0]["flat_area_m2"] == 22.54

    def test_missing_model_name_raises(self):
        with pytest.raises(ValidationError):
            ExtractionResult.model_validate({"sizes": []})

    def test_empty_sizes_is_valid(self):
        result = ExtractionResult(model_name="Test Wing")
        assert result.sizes == []

    def test_optional_fields_default_none(self):
        result = ExtractionResult(model_name="Test")
        assert result.category is None
        assert result.target_use is None
        assert result.cell_count is None
        assert result.year is None


class TestSizeSpec:
    def test_only_size_label_required(self):
        spec = SizeSpec(size_label="M")
        assert spec.size_label == "M"
        assert spec.flat_area_m2 is None

    def test_full_spec(self):
        spec = SizeSpec(
            size_label="S",
            flat_area_m2=22.54,
            flat_span_m=11.34,
            flat_aspect_ratio=5.7,
            proj_area_m2=19.11,
            proj_span_m=8.94,
            proj_aspect_ratio=4.18,
            wing_weight_kg=3.88,
            ptv_min_kg=65.0,
            ptv_max_kg=85.0,
        )
        assert spec.flat_area_m2 == 22.54
        assert spec.ptv_max_kg == 85.0


class TestEnums:
    def test_wing_category_values(self):
        assert WingCategory.paraglider.value == "paraglider"
        assert WingCategory.tandem.value == "tandem"
        assert WingCategory.miniwing.value == "miniwing"

    def test_target_use_values(self):
        assert TargetUse.xc.value == "xc"
        assert TargetUse.competition.value == "competition"
        assert TargetUse.hike_and_fly.value == "hike_and_fly"

    def test_cert_standard_values(self):
        assert CertStandard.EN.value == "EN"
        assert CertStandard.LTF.value == "LTF"
        assert CertStandard.CCC.value == "CCC"

    def test_performance_source_type_values(self):
        assert PerformanceSourceType.manufacturer_stated.value == "manufacturer_stated"
        assert PerformanceSourceType.test_report.value == "test_report"


class TestDomainModels:
    def test_manufacturer(self):
        mfr = Manufacturer(name="Ozone", slug="ozone", country_code="FR")
        assert mfr.name == "Ozone"
        assert mfr.id is None

    def test_wing_model(self):
        wing = WingModel(name="Swift 6", slug="ozone-swift-6")
        assert wing.is_current is True
        assert wing.manufacturer_id is None
        assert wing.year_released is None
        assert wing.year_discontinued is None

    def test_size_variant(self):
        sv = SizeVariant(size_label="M", flat_area_m2=24.04)
        assert sv.model_id is None
        assert sv.flat_area_m2 == 24.04
