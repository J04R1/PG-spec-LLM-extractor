"""Tests for validator — per-model data validation and action log."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.db import Database
from src.seed_import import import_enrichment_csv
from src.validator import (
    Action,
    ModelIssue,
    ModelValidation,
    Severity,
    ValidationLog,
    validate_database,
    validate_model_data,
)


# ── Test CSV data ──────────────────────────────────────────────────────────────

HEADER = (
    "manufacturer_slug,name,year,category,target_use,is_current,cell_count,"
    "line_material,riser_config,manufacturer_url,description,size_label,"
    "flat_area_m2,flat_span_m,flat_aspect_ratio,proj_area_m2,proj_span_m,"
    "proj_aspect_ratio,wing_weight_kg,ptv_min_kg,ptv_max_kg,"
    "speed_trim_kmh,speed_max_kmh,glide_ratio_best,min_sink_ms,"
    "cert_standard,cert_classification,cert_test_lab,cert_test_date,cert_report_url"
)

# Clean model — all fields populated, consistent data
ROW_CLEAN = (
    "test,CleanWing,2023,paraglider,xc,true,55,,"
    "3-liner,https://example.com/clean,,M,"
    "25.0,11.2,5.018,21.0,8.5,3.44,4.8,80,100,"
    "38,52,10.2,1.05,"
    "EN,B,,,"
)

# Sparse model — missing year, cell_count, cert
ROW_SPARSE = (
    "test,SparseWing,,,leisure,true,,,"
    ",,,S,"
    "22.0,,,,,,3.5,70,90,"
    ",,,,,,,"
)

# Bad consistency — ptv_min > ptv_max, proj > flat
ROW_BAD_CONSISTENCY = (
    "test,BadWing,2023,paraglider,xc,true,55,,"
    ",https://example.com/bad,,L,"
    "20.0,10.0,5.0,25.0,9.0,3.2,4.5,120,80,"  # ptv_min > ptv_max, proj > flat
    ",,,,EN,B,,,"
)

# Invalid cert classification
ROW_BAD_CERT = (
    "test,BadCert,2023,paraglider,xc,true,45,,"
    ",https://example.com/badcert,,M,"
    "25.0,11.2,5.018,21.0,8.5,3.44,4.8,80,100,"
    ",,,,EN,EN-B,,,"  # "EN-B" instead of "B"
)


def _write_csv(tmp_path: Path, rows: list[str]) -> Path:
    csv_path = tmp_path / "test.csv"
    csv_path.write_text(HEADER + "\n" + "\n".join(rows) + "\n")
    return csv_path


def _seed_db(tmp_path: Path, rows: list[str]) -> Path:
    csv_path = _write_csv(tmp_path, rows)
    db_path = tmp_path / "test.db"
    db = Database(db_path)
    db.connect()
    import_enrichment_csv(csv_path, db, validate=False)
    db.close()
    return db_path


# ── ModelIssue unit tests ──────────────────────────────────────────────────────


class TestModelIssue:
    def test_basic(self):
        issue = ModelIssue(
            check="missing_year",
            severity=Severity.warning,
            message="Missing year_released",
            field="year_released",
        )
        assert issue.severity == Severity.warning
        assert issue.field == "year_released"


# ── ModelValidation unit tests ─────────────────────────────────────────────────


class TestModelValidation:
    def test_score_clean(self):
        mv = ModelValidation(
            model_id=1, model_slug="test-wing",
            model_name="TestWing", manufacturer_slug="test",
            manufacturer_url=None,
        )
        assert mv.score == "✓"

    def test_score_warning(self):
        mv = ModelValidation(
            model_id=1, model_slug="test-wing",
            model_name="TestWing", manufacturer_slug="test",
            manufacturer_url=None,
            issues=[ModelIssue("x", Severity.warning, "msg")],
        )
        assert mv.score == "△"

    def test_score_critical(self):
        mv = ModelValidation(
            model_id=1, model_slug="test-wing",
            model_name="TestWing", manufacturer_slug="test",
            manufacturer_url=None,
            issues=[ModelIssue("x", Severity.critical, "msg")],
        )
        assert mv.score == "✗"

    def test_to_dict_roundtrip(self):
        mv = ModelValidation(
            model_id=1, model_slug="test-wing",
            model_name="TestWing", manufacturer_slug="test",
            manufacturer_url="https://example.com",
            size_count=3,
            action=Action.re_extract,
            issues=[ModelIssue("check1", Severity.warning, "msg1", "field1", "M")],
        )
        d = mv.to_dict()
        mv2 = ModelValidation.from_dict(d)
        assert mv2.model_slug == "test-wing"
        assert mv2.action == Action.re_extract
        assert len(mv2.issues) == 1
        assert mv2.issues[0].check == "check1"
        assert mv2.issues[0].size_label == "M"


# ── ValidationLog tests ───────────────────────────────────────────────────────


class TestValidationLog:
    def test_save_load_roundtrip(self, tmp_path):
        log_path = tmp_path / "test.validation.json"
        vlog = ValidationLog(
            log_path=log_path,
            timestamp="2026-03-15T12:00:00Z",
            db_path="test.db",
        )
        mv = ModelValidation(
            model_id=1, model_slug="test-wing",
            model_name="TestWing", manufacturer_slug="test",
            manufacturer_url=None, action=Action.skip,
        )
        vlog.models["test-wing"] = mv
        vlog.save()

        loaded = ValidationLog.load(log_path)
        assert loaded.timestamp == "2026-03-15T12:00:00Z"
        assert "test-wing" in loaded.models
        assert loaded.models["test-wing"].action == Action.skip

    def test_pending_models(self):
        vlog = ValidationLog(log_path=Path("/dev/null"))
        vlog.models["a"] = ModelValidation(
            model_id=1, model_slug="a", model_name="A",
            manufacturer_slug="t", manufacturer_url=None,
            action=Action.pending,
            issues=[ModelIssue("x", Severity.warning, "msg")],
        )
        vlog.models["b"] = ModelValidation(
            model_id=2, model_slug="b", model_name="B",
            manufacturer_slug="t", manufacturer_url=None,
            action=Action.skip,
            issues=[ModelIssue("x", Severity.warning, "msg")],
        )
        assert len(vlog.pending_models) == 1
        assert vlog.pending_models[0].model_slug == "a"

    def test_re_extract_models(self):
        vlog = ValidationLog(log_path=Path("/dev/null"))
        vlog.models["a"] = ModelValidation(
            model_id=1, model_slug="a", model_name="A",
            manufacturer_slug="t", manufacturer_url=None,
            action=Action.re_extract,
        )
        assert len(vlog.re_extract_models) == 1

    def test_summary(self):
        vlog = ValidationLog(log_path=Path("/dev/null"))
        vlog.models["clean"] = ModelValidation(
            model_id=1, model_slug="clean", model_name="Clean",
            manufacturer_slug="t", manufacturer_url=None,
        )
        vlog.models["issue"] = ModelValidation(
            model_id=2, model_slug="issue", model_name="Issue",
            manufacturer_slug="t", manufacturer_url=None,
            issues=[ModelIssue("x", Severity.critical, "msg")],
        )
        s = vlog.summary()
        assert s["total_models"] == 2
        assert s["clean"] == 1
        assert s["with_issues"] == 1
        assert s["critical"] == 1


# ── Integration: validate_database ─────────────────────────────────────────────


class TestValidateDatabase:
    def test_clean_model_no_issues(self, tmp_path):
        db_path = _seed_db(tmp_path, [ROW_CLEAN])
        vlog = validate_database(db_path)
        assert len(vlog.models) == 1
        mv = list(vlog.models.values())[0]
        assert mv.score == "✓"
        assert len(mv.issues) == 0

    def test_sparse_model_has_warnings(self, tmp_path):
        db_path = _seed_db(tmp_path, [ROW_SPARSE])
        vlog = validate_database(db_path)
        mv = list(vlog.models.values())[0]
        assert mv.has_warning
        checks = {i.check for i in mv.issues}
        assert "missing_year_released" in checks
        assert "missing_cell_count" in checks

    def test_bad_consistency_detected(self, tmp_path):
        db_path = _seed_db(tmp_path, [ROW_BAD_CONSISTENCY])
        vlog = validate_database(db_path)
        mv = list(vlog.models.values())[0]
        assert mv.has_critical
        checks = {i.check for i in mv.issues}
        assert "ptv_min_gte_max" in checks
        assert "proj_gte_flat" in checks

    def test_bad_cert_detected(self, tmp_path):
        """Invalid cert classification in DB is flagged by validator.

        Use ROW_CLEAN to seed a valid model, then manually insert a bad cert
        directly (bypassing normalizer which would strip it).
        """
        db_path = _seed_db(tmp_path, [ROW_CLEAN])
        # Insert invalid cert directly into DB, bypassing normalizer
        db = Database(db_path)
        db.connect()
        # Get the size_variant_id for the first size
        row = db.conn.execute(
            "SELECT id FROM size_variants LIMIT 1"
        ).fetchone()
        sv_id = row[0]
        db.conn.execute(
            "INSERT INTO certifications (size_variant_id, standard, classification) "
            "VALUES (?, 'EN', 'X')",
            (sv_id,),
        )
        db.conn.commit()
        db.close()

        vlog = validate_database(db_path)
        mv = list(vlog.models.values())[0]
        checks = {i.check for i in mv.issues}
        assert "invalid_en_classification" in checks

    def test_log_file_created(self, tmp_path):
        db_path = _seed_db(tmp_path, [ROW_CLEAN])
        validate_database(db_path)
        log_path = db_path.with_suffix(".validation.json")
        assert log_path.exists()
        data = json.loads(log_path.read_text())
        assert "models" in data
        assert "timestamp" in data

    def test_missing_db_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            validate_database(tmp_path / "nope.db")

    def test_multiple_models_all_validated(self, tmp_path):
        db_path = _seed_db(tmp_path, [ROW_CLEAN, ROW_SPARSE, ROW_BAD_CERT])
        vlog = validate_database(db_path)
        assert len(vlog.models) == 3
        s = vlog.summary()
        assert s["total_models"] == 3
        assert s["clean"] >= 1


# ── validate_model_data parameter tests ────────────────────────────────────────

from src.models import WingModel, SizeVariant, Certification, CertStandard, WingCategory


class TestValidateModelDataParams:
    """Tests for plausibility_overrides and skip_missing_warnings."""

    def _make_wing(self, year=2023, cell_count=55, category=WingCategory.paraglider):
        return WingModel(
            name="TestWing", slug="test-testwing",
            category=category, year_released=year,
            is_current=True, cell_count=cell_count,
            manufacturer_url="https://example.com/test",
        )

    def _make_size(self, ptv_min=80, ptv_max=100, area=25.0, span=11.2, ar=5.018):
        return SizeVariant(
            size_label="M",
            flat_area_m2=area, flat_span_m=span, flat_aspect_ratio=ar,
            ptv_min_kg=ptv_min, ptv_max_kg=ptv_max,
        )

    def test_default_year_1985_fails(self):
        """Year 1985 fails with default plausibility (1990-2026)."""
        wing = self._make_wing(year=1985)
        sizes = [self._make_size()]
        certs = [Certification(standard=CertStandard.EN, classification="B")]
        mv = validate_model_data(wing, sizes, certs, "test")
        checks = {i.check for i in mv.issues}
        assert "implausible_year_released" in checks
        assert mv.has_critical

    def test_override_year_1985_passes(self):
        """Year 1985 passes with overridden range (1980-2026)."""
        wing = self._make_wing(year=1985)
        sizes = [self._make_size()]
        certs = [Certification(standard=CertStandard.EN, classification="B")]
        mv = validate_model_data(
            wing, sizes, certs, "test",
            plausibility_overrides={"year_released": (1980, 2026)},
        )
        checks = {i.check for i in mv.issues}
        assert "implausible_year_released" not in checks

    def test_override_year_1979_still_fails(self):
        """Year 1979 still fails even with overridden range (1980-2026)."""
        wing = self._make_wing(year=1979)
        sizes = [self._make_size()]
        certs = [Certification(standard=CertStandard.EN, classification="B")]
        mv = validate_model_data(
            wing, sizes, certs, "test",
            plausibility_overrides={"year_released": (1980, 2026)},
        )
        checks = {i.check for i in mv.issues}
        assert "implausible_year_released" in checks

    def test_skip_missing_suppresses_warnings(self):
        """skip_missing_warnings suppresses missing_* checks."""
        wing = WingModel(
            name="Sparse", slug="test-sparse",
            category=None, year_released=None,
            is_current=True, cell_count=None,
            manufacturer_url=None,
        )
        sizes = [SizeVariant(size_label="M", flat_area_m2=None, ptv_min_kg=None, ptv_max_kg=None)]
        certs = []
        mv = validate_model_data(wing, sizes, certs, "test", skip_missing_warnings=True)
        missing_checks = [i.check for i in mv.issues if i.check.startswith("missing_")]
        assert len(missing_checks) == 0
        # no_certifications is also suppressed
        assert "no_certifications" not in {i.check for i in mv.issues}

    def test_skip_missing_keeps_critical(self):
        """skip_missing_warnings does NOT suppress critical issues."""
        wing = self._make_wing()
        sizes = [self._make_size(ptv_min=120, ptv_max=80)]  # ptv_min > ptv_max
        certs = [Certification(standard=CertStandard.EN, classification="B")]
        mv = validate_model_data(wing, sizes, certs, "test", skip_missing_warnings=True)
        assert mv.has_critical
        checks = {i.check for i in mv.issues}
        assert "ptv_min_gte_max" in checks

    def test_combined_fredvol_profile(self):
        """Simulates the fredvol validation profile: relaxed year + no missing warnings."""
        wing = WingModel(
            name="OldWing", slug="test-oldwing",
            category=WingCategory.paraglider, year_released=1985,
            is_current=False, cell_count=None,
            manufacturer_url=None,
        )
        sizes = [SizeVariant(
            size_label="M", flat_area_m2=25.0, flat_span_m=11.2,
            flat_aspect_ratio=5.018, ptv_min_kg=80, ptv_max_kg=100,
        )]
        certs = []
        mv = validate_model_data(
            wing, sizes, certs, "test",
            plausibility_overrides={"year_released": (1980, 2026)},
            skip_missing_warnings=True,
        )
        # No critical issues — year 1985 accepted, missing fields suppressed
        assert not mv.has_critical
        # No missing_* warnings
        missing_checks = [i.check for i in mv.issues if i.check.startswith("missing_")]
        assert len(missing_checks) == 0

    def test_default_params_unchanged(self):
        """Default behavior unchanged when no overrides provided."""
        wing = self._make_wing()
        sizes = [self._make_size()]
        certs = [Certification(standard=CertStandard.EN, classification="B")]
        mv = validate_model_data(wing, sizes, certs, "test")
        assert not mv.has_critical
        assert mv.score == "✓"
