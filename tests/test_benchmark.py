"""Tests for benchmark — quality, completeness, and accuracy scoring."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.benchmark import (
    BenchmarkReport,
    ConsistencyCheck,
    FieldScore,
    TableScore,
    benchmark_database,
)
from src.db import Database
from src.seed_import import import_enrichment_csv


# ── Test CSV fixture ───────────────────────────────────────────────────────────

HEADER = (
    "manufacturer_slug,name,year,category,target_use,is_current,cell_count,"
    "line_material,riser_config,manufacturer_url,description,size_label,"
    "flat_area_m2,flat_span_m,flat_aspect_ratio,proj_area_m2,proj_span_m,"
    "proj_aspect_ratio,wing_weight_kg,ptv_min_kg,ptv_max_kg,"
    "speed_trim_kmh,speed_max_kmh,glide_ratio_best,min_sink_ms,"
    "cert_standard,cert_classification,cert_test_lab,cert_test_date,cert_report_url"
)

# Good data: consistent geometry, valid cert
ROW_GOOD = (
    "test,GoodWing,2023,paraglider,xc,true,55,Liros PPSL,"
    "3-liner,https://example.com/goodwing,,M,"
    "25.0,11.2,5.018,21.0,8.5,3.44,4.8,80,100,"
    "38,52,10.2,1.05,"
    "EN,B,,,"
)

# Sparse data: missing most optional fields
ROW_SPARSE = (
    "test,SparseWing,,,leisure,true,,,"
    ",,,S,"
    "22.0,,,,,,3.5,70,90,"
    ",,,,EN,A,,,"
)

# Bad data: implausible values
ROW_BAD = (
    "test,BadWing,2023,paraglider,xc,true,5,,,"  # 5 cells = implausible
    "https://example.com/bad,,L,"
    "100.0,30.0,9.0,95.0,28.0,8.0,20.0,10,500,"  # all out of range
    "50,40,20.0,0.1,"  # trim > max, glide/sink out of range
    "EN,Z,,,"  # Z is not a valid EN classification
)


@pytest.fixture
def seeded_db(tmp_path):
    """Create a DB with good + sparse data."""
    csv_path = tmp_path / "test.csv"
    csv_path.write_text(HEADER + "\n" + ROW_GOOD + "\n" + ROW_SPARSE + "\n")
    db = Database(tmp_path / "test.db")
    db.connect()
    import_enrichment_csv(csv_path, db)
    db.close()
    return tmp_path / "test.db"


@pytest.fixture
def bad_db(tmp_path):
    """Create a DB with implausible data."""
    csv_path = tmp_path / "bad.csv"
    csv_path.write_text(HEADER + "\n" + ROW_BAD + "\n")
    db = Database(tmp_path / "test.db")
    db.connect()
    import_enrichment_csv(csv_path, db)
    db.close()
    return tmp_path / "test.db"


# ── FieldScore unit tests ─────────────────────────────────────────────────────


class TestFieldScore:
    def test_completeness(self):
        fs = FieldScore(field_name="x", total=10, populated=7, plausible=7)
        assert fs.completeness == pytest.approx(0.7)

    def test_quality_all_plausible(self):
        fs = FieldScore(field_name="x", total=10, populated=5, plausible=5)
        assert fs.quality == pytest.approx(1.0)

    def test_quality_none_populated(self):
        fs = FieldScore(field_name="x", total=10, populated=0, plausible=0)
        assert fs.quality == pytest.approx(1.0)  # vacuous truth

    def test_quality_partial(self):
        fs = FieldScore(field_name="x", total=10, populated=10, plausible=8)
        assert fs.quality == pytest.approx(0.8)


class TestConsistencyCheck:
    def test_accuracy(self):
        cc = ConsistencyCheck(check_name="test", total=10, passed=9)
        assert cc.accuracy == pytest.approx(0.9)

    def test_accuracy_zero_total(self):
        cc = ConsistencyCheck(check_name="test", total=0, passed=0)
        assert cc.accuracy == pytest.approx(1.0)


class TestTableScore:
    def test_aggregate_completeness(self):
        ts = TableScore(table_name="test", record_count=10)
        ts.field_scores["a"] = FieldScore("a", total=10, populated=10, plausible=10)
        ts.field_scores["b"] = FieldScore("b", total=10, populated=5, plausible=5)
        assert ts.completeness == pytest.approx(0.75)

    def test_aggregate_quality(self):
        ts = TableScore(table_name="test", record_count=10)
        ts.field_scores["a"] = FieldScore("a", total=10, populated=10, plausible=10)
        ts.field_scores["b"] = FieldScore("b", total=10, populated=10, plausible=8)
        assert ts.quality == pytest.approx(0.9)


# ── Integration: benchmark on seeded DB ────────────────────────────────────────


class TestBenchmarkReport:
    def test_summary_keys(self, seeded_db):
        report = benchmark_database(seeded_db)
        summary = report.summary()
        assert "completeness" in summary
        assert "quality" in summary
        assert "accuracy" in summary
        assert "tables" in summary

    def test_model_count(self, seeded_db):
        report = benchmark_database(seeded_db)
        assert report.model_count == 2

    def test_size_count(self, seeded_db):
        report = benchmark_database(seeded_db)
        assert report.size_count == 2

    def test_completeness_between_0_and_1(self, seeded_db):
        report = benchmark_database(seeded_db)
        assert 0.0 <= report.completeness <= 1.0

    def test_quality_between_0_and_1(self, seeded_db):
        report = benchmark_database(seeded_db)
        assert 0.0 <= report.quality <= 1.0

    def test_accuracy_between_0_and_1(self, seeded_db):
        report = benchmark_database(seeded_db)
        assert 0.0 <= report.accuracy <= 1.0

    def test_format_report_is_string(self, seeded_db):
        report = benchmark_database(seeded_db)
        text = report.format_report()
        assert isinstance(text, str)
        assert "Benchmark Report" in text

    def test_tables_scored(self, seeded_db):
        report = benchmark_database(seeded_db)
        assert "models" in report.table_scores
        assert "size_variants" in report.table_scores
        assert "certifications" in report.table_scores

    def test_extraction_method_captured(self, seeded_db):
        report = benchmark_database(seeded_db)
        assert report.extraction_method == "llm_enrichment_csv"


class TestBenchmarkBadData:
    def test_quality_lower_with_bad_data(self, bad_db):
        report = benchmark_database(bad_db)
        # Bad data should have lower quality due to implausible values
        sv = report.table_scores["size_variants"]
        assert sv.quality < 1.0

    def test_cell_count_implausible(self, bad_db):
        report = benchmark_database(bad_db)
        models = report.table_scores["models"]
        assert models.field_scores["cell_count"].plausible == 0

    def test_missing_db_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            benchmark_database(tmp_path / "nope.db")
