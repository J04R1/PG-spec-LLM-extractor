"""Tests for src/fredvol_import.py — fredvol CSV adapter."""

from __future__ import annotations

import csv
import tempfile
from pathlib import Path

import pytest

from src.db import Database
from src.fredvol_import import (
    _infer_category,
    _map_certification,
    _slugify_manufacturer,
    import_fredvol_csv,
)
from src.models import CertStandard, WingCategory, WingSubType


# ── Manufacturer slug normalization ───────────────────────────────────────────


class TestSlugifyManufacturer:
    """Test manufacturer name → slug normalization."""

    @pytest.mark.parametrize(
        "name, expected",
        [
            ("Ozone", "ozone"),
            ("ozone", "ozone"),
            ("Advance", "advance"),
            ("advance", "advance"),
            ("Nova", "nova"),
            ("nova", "nova"),
            ("Gin", "gin"),
            ("Dudek", "dudek"),
            ("Niviuk", "niviuk"),
            ("Skywalk", "skywalk"),
            ("Swing", "swing"),
            ("Up", "up"),
            ("U-Turn", "u-turn"),
            ("uturn", "u-turn"),
            ("Bruce Goldsmith Design", "bgd"),
            ("Triple Seven", "triple-seven"),
            ("tripleseven", "triple-seven"),
            ("AirDesign", "airdesign"),
            ("Phi", "phi"),
            ("Flow", "flow"),
            ("Aircross", "aircross"),
            ("Icaro", "icaro"),
            ("Axis", "axis"),
            # Fallback slugification for unknown brands
            ("windtech", "windtech"),
            ("firebird", "firebird"),
            ("edel", "edel"),
        ],
    )
    def test_known_manufacturers(self, name: str, expected: str):
        assert _slugify_manufacturer(name) == expected

    def test_strips_whitespace(self):
        assert _slugify_manufacturer("  Ozone  ") == "ozone"


# ── Certification mapping ────────────────────────────────────────────────────


class TestCertificationMapping:
    """Test certification extraction from fredvol rows."""

    def _make_row(self, **kwargs) -> dict:
        base = {
            "certif_EN": "", "certif_DHV": "", "certif_AFNOR": "",
            "certif_MISC": "", "certification": "",
        }
        base.update(kwargs)
        return base

    def test_en_column_priority(self):
        row = self._make_row(certif_EN="B", certification="C")
        result = _map_certification(row)
        assert result == (CertStandard.EN, "B")

    def test_dhv_column(self):
        row = self._make_row(certif_DHV="2")
        result = _map_certification(row)
        assert result == (CertStandard.LTF, "2")

    def test_afnor_column(self):
        row = self._make_row(certif_AFNOR="Perf")
        result = _map_certification(row)
        assert result == (CertStandard.AFNOR, "Perf")

    def test_misc_column(self):
        row = self._make_row(certif_MISC="Load")
        result = _map_certification(row)
        assert result == (CertStandard.other, "Load")

    @pytest.mark.parametrize(
        "cert_value, expected_std, expected_class",
        [
            ("A", CertStandard.EN, "A"),
            ("B", CertStandard.EN, "B"),
            ("C", CertStandard.EN, "C"),
            ("D", CertStandard.EN, "D"),
            ("DHV_1", CertStandard.LTF, "1"),
            ("DHV_2", CertStandard.LTF, "2"),
            ("DHV_3", CertStandard.LTF, "3"),
            ("AFNOR_Standard", CertStandard.AFNOR, "Standard"),
            ("AFNOR_Perf", CertStandard.AFNOR, "Performance"),
            ("AFNOR_Compet", CertStandard.AFNOR, "Competition"),
            ("AFNOR_Biplace", CertStandard.AFNOR, "Biplace"),
            ("DGAC", CertStandard.DGAC, None),
            ("CCC", CertStandard.CCC, "CCC"),
        ],
    )
    def test_consolidated_column(self, cert_value, expected_std, expected_class):
        row = self._make_row(certification=cert_value)
        result = _map_certification(row)
        assert result is not None
        assert result[0] == expected_std
        assert result[1] == expected_class

    def test_pending_returns_none(self):
        row = self._make_row(certification="pending")
        assert _map_certification(row) is None

    def test_not_cert_returns_none(self):
        row = self._make_row(certification="not_cert")
        assert _map_certification(row) is None

    def test_empty_returns_none(self):
        row = self._make_row()
        assert _map_certification(row) is None


# ── Category inference ────────────────────────────────────────────────────────


class TestCategoryInference:
    def test_motor_in_name(self):
        assert _infer_category("Alpha 6 Motor", "") == (WingCategory.paramotor, None)

    def test_tandem_in_name(self):
        assert _infer_category("Bi Beta 5", "") == (WingCategory.paraglider, WingSubType.tandem)

    def test_biplace_cert(self):
        assert _infer_category("SomeWing", "AFNOR_Biplace") == (WingCategory.paraglider, WingSubType.tandem)

    def test_load_cert(self):
        assert _infer_category("SomeWing", "Load") == (WingCategory.paraglider, WingSubType.tandem)

    def test_dgac_cert(self):
        assert _infer_category("SomeWing", "DGAC") == (WingCategory.paramotor, None)

    def test_default_paraglider(self):
        assert _infer_category("Rush 6", "B") == (WingCategory.paraglider, WingSubType.solo)


# ── Full import integration ──────────────────────────────────────────────────


@pytest.fixture
def tmp_db():
    """Create a temporary database for testing."""
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "test.db"
        db = Database(db_path)
        db.connect()
        yield db
        db.close()


@pytest.fixture
def sample_fredvol_csv(tmp_path: Path) -> Path:
    """Create a small sample fredvol CSV for testing."""
    csv_path = tmp_path / "fredvol_sample.csv"
    rows = [
        {
            "": "0", "certif_AFNOR": "", "certif_DHV": "", "certif_EN": "A",
            "certif_MISC": "", "certification": "A",
            "flat_AR": "4.8", "flat_area": "22.1", "flat_span": "10.3",
            "manufacturer": "Advance", "name": "Alpha 6",
            "proj_AR": "3.6", "proj_area": "18.9", "proj_span": "8.2",
            "ptv_maxi": "85.0", "ptv_mini": "70.0", "size": "22",
            "source": "GliderBase", "weight": "4.3", "year": "2015",
        },
        {
            "": "1", "certif_AFNOR": "", "certif_DHV": "", "certif_EN": "A",
            "certif_MISC": "", "certification": "A",
            "flat_AR": "4.8", "flat_area": "24.0", "flat_span": "10.8",
            "manufacturer": "Advance", "name": "Alpha 6",
            "proj_AR": "3.6", "proj_area": "20.6", "proj_span": "8.6",
            "ptv_maxi": "95.0", "ptv_mini": "80.0", "size": "24",
            "source": "GliderBase", "weight": "4.55", "year": "2015",
        },
        {
            "": "5", "certif_AFNOR": "", "certif_DHV": "", "certif_EN": "",
            "certif_MISC": "DGAC", "certification": "DGAC",
            "flat_AR": "", "flat_area": "", "flat_span": "",
            "manufacturer": "Advance", "name": "Alpha 6 Motor",
            "proj_AR": "", "proj_area": "", "proj_span": "",
            "ptv_maxi": "130.0", "ptv_mini": "60.0", "size": "24",
            "source": "GliderBase", "weight": "", "year": "",
        },
        {
            "": "48", "certif_AFNOR": "", "certif_DHV": "", "certif_EN": "B",
            "certif_MISC": "", "certification": "B",
            "flat_AR": "5.6", "flat_area": "23.5", "flat_span": "11.45",
            "manufacturer": "Aircross", "name": "U Cruise",
            "proj_AR": "4.19", "proj_area": "20.2", "proj_span": "9.2",
            "ptv_maxi": "85.0", "ptv_mini": "60.0", "size": "S",
            "source": "GliderBase", "weight": "5.4", "year": "2016",
        },
    ]

    fieldnames = list(rows[0].keys())
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    return csv_path


class TestImportFredvolCSV:
    def test_import_all(self, tmp_db: Database, sample_fredvol_csv: Path):
        counts = import_fredvol_csv(sample_fredvol_csv, tmp_db)

        assert counts["manufacturers"] == 2  # advance, aircross
        assert counts["models"] == 3  # Alpha 6, Alpha 6 Motor, U Cruise
        assert counts["sizes"] == 4
        assert counts["certifications"] == 4

    def test_manufacturer_filter(self, tmp_db: Database, sample_fredvol_csv: Path):
        counts = import_fredvol_csv(
            sample_fredvol_csv, tmp_db, manufacturer_filter="advance",
        )

        assert counts["manufacturers"] == 1
        assert counts["models"] == 2  # Alpha 6 + Alpha 6 Motor
        assert counts["sizes"] == 3

    def test_geometry_stored_correctly(self, tmp_db: Database, sample_fredvol_csv: Path):
        import_fredvol_csv(sample_fredvol_csv, tmp_db)

        # Check Advance Alpha 6, size 22
        row = tmp_db.conn.execute(
            """SELECT sv.* FROM size_variants sv
               JOIN models m ON sv.model_id = m.id
               WHERE m.slug = 'advance-alpha-6' AND sv.size_label = '22'"""
        ).fetchone()

        assert row is not None
        assert abs(row["flat_area_m2"] - 22.1) < 0.01
        assert abs(row["flat_span_m"] - 10.3) < 0.01
        assert abs(row["flat_aspect_ratio"] - 4.8) < 0.01
        assert abs(row["proj_area_m2"] - 18.9) < 0.01
        assert abs(row["ptv_min_kg"] - 70.0) < 0.01
        assert abs(row["ptv_max_kg"] - 85.0) < 0.01
        assert abs(row["wing_weight_kg"] - 4.3) < 0.01

    def test_motor_gets_paramotor_category(self, tmp_db: Database, sample_fredvol_csv: Path):
        import_fredvol_csv(sample_fredvol_csv, tmp_db)

        row = tmp_db.conn.execute(
            "SELECT category FROM models WHERE slug = 'advance-alpha-6-motor'"
        ).fetchone()
        assert row is not None
        assert row["category"] == "paramotor"

    def test_provenance_recorded(self, tmp_db: Database, sample_fredvol_csv: Path):
        import_fredvol_csv(sample_fredvol_csv, tmp_db)

        rows = tmp_db.conn.execute(
            "SELECT * FROM provenance WHERE extraction_method = 'fredvol_csv_import'"
        ).fetchall()
        assert len(rows) >= 3  # One per model

    def test_is_current_false(self, tmp_db: Database, sample_fredvol_csv: Path):
        import_fredvol_csv(sample_fredvol_csv, tmp_db)

        rows = tmp_db.conn.execute("SELECT is_current FROM models").fetchall()
        for row in rows:
            assert row["is_current"] == 0

    def test_certifications_stored(self, tmp_db: Database, sample_fredvol_csv: Path):
        import_fredvol_csv(sample_fredvol_csv, tmp_db)

        cert = tmp_db.conn.execute(
            """SELECT c.* FROM certifications c
               JOIN size_variants sv ON c.size_variant_id = sv.id
               JOIN models m ON sv.model_id = m.id
               WHERE m.slug = 'advance-alpha-6' AND sv.size_label = '22'"""
        ).fetchone()
        assert cert is not None
        assert cert["standard"] == "EN"
        assert cert["classification"] == "A"

    def test_empty_csv(self, tmp_db: Database, tmp_path: Path):
        csv_path = tmp_path / "empty.csv"
        with open(csv_path, "w") as f:
            f.write(",certif_AFNOR,certif_DHV,certif_EN,certif_MISC,certification,"
                    "flat_AR,flat_area,flat_span,manufacturer,name,proj_AR,"
                    "proj_area,proj_span,ptv_maxi,ptv_mini,size,source,weight,year\n")
        counts = import_fredvol_csv(csv_path, tmp_db)
        assert counts["models"] == 0

    def test_case_variant_merge(self, tmp_db: Database, tmp_path: Path):
        """Test that 'ozone' and 'Ozone' rows merge into same manufacturer."""
        csv_path = tmp_path / "case_test.csv"
        rows_data = [
            {
                "": "0", "certif_AFNOR": "", "certif_DHV": "", "certif_EN": "B",
                "certif_MISC": "", "certification": "B",
                "flat_AR": "5.4", "flat_area": "23.0", "flat_span": "11.1",
                "manufacturer": "ozone", "name": "Rush 5",
                "proj_AR": "", "proj_area": "", "proj_span": "",
                "ptv_maxi": "95.0", "ptv_mini": "75.0", "size": "S",
                "source": "Para2000", "weight": "4.0", "year": "2017",
            },
            {
                "": "1", "certif_AFNOR": "", "certif_DHV": "", "certif_EN": "C",
                "certif_MISC": "", "certification": "C",
                "flat_AR": "6.0", "flat_area": "22.0", "flat_span": "11.5",
                "manufacturer": "Ozone", "name": "Mantra 7",
                "proj_AR": "", "proj_area": "", "proj_span": "",
                "ptv_maxi": "100.0", "ptv_mini": "80.0", "size": "M",
                "source": "GliderBase", "weight": "4.5", "year": "2018",
            },
        ]

        fieldnames = list(rows_data[0].keys())
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows_data)

        counts = import_fredvol_csv(csv_path, tmp_db)
        assert counts["manufacturers"] == 1  # Both map to "ozone"
        assert counts["models"] == 2


# ── Validation gate tests ────────────────────────────────────────────────────


class TestFredvolValidation:
    """Tests for per-model validation gate in fredvol import."""

    def _make_csv(self, tmp_path, rows_data):
        csv_path = tmp_path / "validation_test.csv"
        fieldnames = list(rows_data[0].keys())
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows_data)
        return csv_path

    def _row(self, name="TestWing", ptv_mini="80", ptv_maxi="100", year="2015", **overrides):
        base = {
            "": "0", "certif_AFNOR": "", "certif_DHV": "", "certif_EN": "B",
            "certif_MISC": "", "certification": "B",
            "flat_AR": "5.0", "flat_area": "25.0", "flat_span": "11.18",
            "manufacturer": "TestMfr", "name": name,
            "proj_AR": "", "proj_area": "", "proj_span": "",
            "ptv_maxi": ptv_maxi, "ptv_mini": ptv_mini, "size": "M",
            "source": "GliderBase", "weight": "4.5", "year": year,
        }
        base.update(overrides)
        return base

    def test_valid_model_imported(self, tmp_db, tmp_path):
        csv_path = self._make_csv(tmp_path, [self._row()])
        counts = import_fredvol_csv(csv_path, tmp_db, validate=True)
        assert counts["models"] == 1
        assert counts["skipped"] == 0

    def test_ptv_min_gte_max_skipped(self, tmp_db, tmp_path):
        csv_path = self._make_csv(tmp_path, [self._row(ptv_mini="120", ptv_maxi="80")])
        counts = import_fredvol_csv(csv_path, tmp_db, validate=True)
        assert counts["models"] == 0
        assert counts["skipped"] == 1
        assert len(counts["skipped_models"]) == 1
        assert counts["skipped_models"][0].has_critical

    def test_year_1985_accepted_with_fredvol_profile(self, tmp_db, tmp_path):
        csv_path = self._make_csv(tmp_path, [self._row(year="1985")])
        counts = import_fredvol_csv(csv_path, tmp_db, validate=True)
        assert counts["models"] == 1
        assert counts["skipped"] == 0

    def test_year_1975_rejected(self, tmp_db, tmp_path):
        csv_path = self._make_csv(tmp_path, [self._row(year="1975")])
        counts = import_fredvol_csv(csv_path, tmp_db, validate=True)
        assert counts["models"] == 0
        assert counts["skipped"] == 1

    def test_validate_false_imports_bad_data(self, tmp_db, tmp_path):
        csv_path = self._make_csv(tmp_path, [self._row(ptv_mini="120", ptv_maxi="80")])
        counts = import_fredvol_csv(csv_path, tmp_db, validate=False)
        assert counts["models"] == 1  # Bad data goes through
        assert counts["skipped"] == 0

    def test_mixed_good_and_bad(self, tmp_db, tmp_path):
        csv_path = self._make_csv(tmp_path, [
            self._row(name="GoodWing"),
            self._row(name="BadWing", ptv_mini="150", ptv_maxi="80"),
        ])
        counts = import_fredvol_csv(csv_path, tmp_db, validate=True)
        assert counts["models"] == 1
        assert counts["skipped"] == 1
