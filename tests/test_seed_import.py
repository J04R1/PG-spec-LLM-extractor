"""Tests for seed_import — CSV → database import."""

from __future__ import annotations

import csv
import tempfile
from pathlib import Path

import pytest

from src.db import Database
from src.seed_import import (
    _build_certification,
    _build_performance_data,
    _build_size_variant,
    _build_wing_model,
    _safe_bool,
    _safe_float,
    _safe_int,
    import_enrichment_csv,
)


# ── Helper to write test CSVs ─────────────────────────────────────────────────

HEADER = (
    "manufacturer_slug,name,year,category,target_use,is_current,cell_count,"
    "line_material,riser_config,manufacturer_url,description,size_label,"
    "flat_area_m2,flat_span_m,flat_aspect_ratio,proj_area_m2,proj_span_m,"
    "proj_aspect_ratio,wing_weight_kg,ptv_min_kg,ptv_max_kg,"
    "speed_trim_kmh,speed_max_kmh,glide_ratio_best,min_sink_ms,"
    "cert_standard,cert_classification,cert_test_lab,cert_test_date,cert_report_url"
)

OZONE_ROW = (
    "ozone,Rush 6,2023,paraglider,xc,true,55,Liros PPSL/Edelrid,"
    "3-liner,https://flyozone.com/rush-6,Intermediate XC wing,M,"
    "25.0,11.2,5.02,21.5,8.8,3.6,4.8,80,100,"
    "38,52,10.2,1.05,"
    "EN,B,,,"
)

ADVANCE_ROW = (
    "advance,SIGMA 11,2024,paraglider,xc,true,64,Liros PPSL,"
    "3-liner,https://advance.swiss/sigma-11,High-end XC,25,"
    "24.5,11.0,4.94,20.8,8.6,3.56,4.5,85,105,"
    ",,,,EN,C,,2024-06-15,https://advance.ch/cert/sigma11.pdf"
)


def _write_csv(tmp_dir: Path, rows: list[str], filename: str = "test.csv") -> Path:
    csv_path = tmp_dir / filename
    csv_path.write_text(HEADER + "\n" + "\n".join(rows) + "\n")
    return csv_path


# ── Unit tests for parsers ─────────────────────────────────────────────────────


class TestSafeInt:
    def test_valid(self):
        assert _safe_int("42") == 42

    def test_float_string(self):
        assert _safe_int("42.0") == 42

    def test_empty(self):
        assert _safe_int("") is None

    def test_none(self):
        assert _safe_int(None) is None

    def test_invalid(self):
        assert _safe_int("abc") is None


class TestSafeFloat:
    def test_valid(self):
        assert _safe_float("3.14") == pytest.approx(3.14)

    def test_empty(self):
        assert _safe_float("") is None

    def test_none(self):
        assert _safe_float(None) is None


class TestSafeBool:
    def test_true_default(self):
        assert _safe_bool("") is True

    def test_true_explicit(self):
        assert _safe_bool("true") is True

    def test_false(self):
        assert _safe_bool("false") is False

    def test_zero(self):
        assert _safe_bool("0") is False


# ── Unit tests for model builders ──────────────────────────────────────────────


class TestBuildWingModel:
    def test_basic(self):
        row = {"name": "Rush 6", "year": "2023", "category": "paraglider",
               "is_current": "true", "cell_count": "55",
               "riser_config": "3-liner",
               "manufacturer_url": "https://flyozone.com/rush-6"}
        wing = _build_wing_model(row, "ozone")
        assert wing.name == "Rush 6"
        assert wing.slug == "ozone-rush-6"
        assert wing.year_released == 2023
        assert wing.cell_count == 55
        assert wing.is_current is True

    def test_missing_optional(self):
        row = {"name": "Test Wing", "year": "", "category": "",
               "is_current": "", "cell_count": "",
               "riser_config": "",
               "manufacturer_url": ""}
        wing = _build_wing_model(row, "test")
        assert wing.name == "Test Wing"
        assert wing.year_released is None
        assert wing.category is None
        assert wing.cell_count is None


class TestBuildSizeVariant:
    def test_basic(self):
        row = {"size_label": "M", "flat_area_m2": "25.0",
               "flat_span_m": "11.2", "flat_aspect_ratio": "5.02",
               "proj_area_m2": "21.5", "proj_span_m": "8.8",
               "proj_aspect_ratio": "3.6", "wing_weight_kg": "4.8",
               "ptv_min_kg": "80", "ptv_max_kg": "100"}
        sv = _build_size_variant(row)
        assert sv is not None
        assert sv.size_label == "M"
        assert sv.flat_area_m2 == pytest.approx(25.0)
        assert sv.ptv_max_kg == pytest.approx(100.0)

    def test_missing_label_returns_none(self):
        row = {"size_label": "", "flat_area_m2": "25.0"}
        assert _build_size_variant(row) is None


class TestBuildCertification:
    def test_basic(self):
        row = {"cert_standard": "EN", "cert_classification": "B",
               "cert_test_lab": "", "cert_test_date": "2024-06-15",
               "cert_report_url": "https://example.com/cert.pdf"}
        cert = _build_certification(row)
        assert cert is not None
        assert cert.standard.value == "EN"
        assert cert.classification == "B"
        assert cert.test_date is not None

    def test_no_cert_data(self):
        row = {"cert_standard": "", "cert_classification": "",
               "cert_test_lab": "", "cert_test_date": "",
               "cert_report_url": ""}
        assert _build_certification(row) is None

    def test_normalizes_dhv_to_ltf(self):
        """DHV standard + numeric class should normalize to LTF."""
        row = {"cert_standard": "DHV", "cert_classification": "1-2",
               "cert_test_lab": "", "cert_test_date": "",
               "cert_report_url": ""}
        cert = _build_certification(row)
        assert cert is not None
        assert cert.standard.value == "LTF"
        assert cert.classification == "1-2"

    def test_normalizes_en_c(self):
        """EN + C stays EN/C after normalization."""
        row = {"cert_standard": "EN", "cert_classification": "C",
               "cert_test_lab": "", "cert_test_date": "",
               "cert_report_url": ""}
        cert = _build_certification(row)
        assert cert.standard.value == "EN"
        assert cert.classification == "C"

    def test_normalizes_bare_digit(self):
        """Bare '2' with no standard should normalize to LTF/2."""
        row = {"cert_standard": "", "cert_classification": "2",
               "cert_test_lab": "", "cert_test_date": "",
               "cert_report_url": ""}
        cert = _build_certification(row)
        assert cert is not None
        assert cert.standard.value == "LTF"
        assert cert.classification == "2"


class TestBuildPerformanceData:
    def test_with_data(self):
        row = {"speed_trim_kmh": "38", "speed_max_kmh": "52",
               "glide_ratio_best": "10.2", "min_sink_ms": "1.05"}
        perf = _build_performance_data(row)
        assert perf is not None
        assert perf.speed_trim_kmh == pytest.approx(38.0)

    def test_all_empty(self):
        row = {"speed_trim_kmh": "", "speed_max_kmh": "",
               "glide_ratio_best": "", "min_sink_ms": ""}
        assert _build_performance_data(row) is None


# ── Integration: full CSV import ───────────────────────────────────────────────


class TestImportEnrichmentCSV:
    def test_single_model(self, tmp_path):
        csv_path = _write_csv(tmp_path, [OZONE_ROW])
        db = Database(tmp_path / "test.db")
        db.connect()
        try:
            counts = import_enrichment_csv(csv_path, db)
            assert counts["manufacturers"] == 1
            assert counts["models"] == 1
            assert counts["sizes"] == 1
            assert counts["certifications"] == 1
            assert counts["performance_records"] == 1  # has speed data
        finally:
            db.close()

    def test_multi_manufacturer(self, tmp_path):
        csv_path = _write_csv(tmp_path, [OZONE_ROW, ADVANCE_ROW])
        db = Database(tmp_path / "test.db")
        db.connect()
        try:
            counts = import_enrichment_csv(csv_path, db)
            assert counts["manufacturers"] == 2
            assert counts["models"] == 2
            assert counts["sizes"] == 2
        finally:
            db.close()

    def test_provenance_recorded(self, tmp_path):
        csv_path = _write_csv(tmp_path, [OZONE_ROW])
        db = Database(tmp_path / "test.db")
        db.connect()
        try:
            import_enrichment_csv(csv_path, db)
            row = db.conn.execute(
                "SELECT * FROM provenance WHERE source_name LIKE '%ozone%'"
            ).fetchone()
            assert row is not None
            assert row["extraction_method"] == "llm_enrichment_csv"
        finally:
            db.close()

    def test_target_use_stored(self, tmp_path):
        csv_path = _write_csv(tmp_path, [OZONE_ROW])
        db = Database(tmp_path / "test.db")
        db.connect()
        try:
            import_enrichment_csv(csv_path, db)
            row = db.conn.execute(
                "SELECT target_use FROM model_target_uses"
            ).fetchone()
            assert row is not None
            assert row["target_use"] == "xc"
        finally:
            db.close()

    def test_empty_csv(self, tmp_path):
        csv_path = _write_csv(tmp_path, [])
        db = Database(tmp_path / "test.db")
        db.connect()
        try:
            counts = import_enrichment_csv(csv_path, db)
            assert counts["models"] == 0
        finally:
            db.close()

    def test_missing_file_raises(self, tmp_path):
        db = Database(tmp_path / "test.db")
        db.connect()
        try:
            with pytest.raises(FileNotFoundError):
                import_enrichment_csv(tmp_path / "nope.csv", db)
        finally:
            db.close()

    def test_validation_gate_skips_critical(self, tmp_path):
        """Models with critical validation issues should be skipped."""
        # ptv_min > ptv_max is a critical issue
        bad_row = (
            "ozone,BadWing,2023,paraglider,xc,true,55,,"
            ",https://flyozone.com/bad,,M,"
            "25.0,11.2,5.018,21.0,8.5,3.44,4.8,200,50,"  # min=200 > max=50
            ",,,,EN,B,,,"
        )
        csv_path = _write_csv(tmp_path, [bad_row])
        db = Database(tmp_path / "test.db")
        db.connect()
        try:
            counts = import_enrichment_csv(csv_path, db, validate=True)
            assert counts["models"] == 0
            assert counts["skipped"] == 1
            assert len(counts["skipped_models"]) == 1
            assert counts["skipped_models"][0].model_name == "BadWing"
        finally:
            db.close()

    def test_validation_gate_allows_warnings(self, tmp_path):
        """Models with only warnings should still be imported."""
        # Missing year is a warning, not critical
        warn_row = (
            "ozone,WarnWing,,paraglider,xc,true,55,,"
            ",https://flyozone.com/warn,,M,"
            "25.0,11.2,5.018,21.0,8.5,3.44,4.8,80,100,"
            ",,,,EN,B,,,"
        )
        csv_path = _write_csv(tmp_path, [warn_row])
        db = Database(tmp_path / "test.db")
        db.connect()
        try:
            counts = import_enrichment_csv(csv_path, db, validate=True)
            assert counts["models"] == 1
            assert counts["skipped"] == 0
        finally:
            db.close()

    def test_validation_gate_disabled(self, tmp_path):
        """With validate=False, critical models are still imported."""
        bad_row = (
            "ozone,BadWing,2023,paraglider,xc,true,55,,"
            ",https://flyozone.com/bad,,M,"
            "25.0,11.2,5.018,21.0,8.5,3.44,4.8,200,50,"
            ",,,,EN,B,,,"
        )
        csv_path = _write_csv(tmp_path, [bad_row])
        db = Database(tmp_path / "test.db")
        db.connect()
        try:
            counts = import_enrichment_csv(csv_path, db, validate=False)
            assert counts["models"] == 1
            assert counts["skipped"] == 0
        finally:
            db.close()
