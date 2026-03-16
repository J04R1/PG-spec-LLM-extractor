"""Tests for src/dhv_import.py — DHV certification enrichment adapter."""

from __future__ import annotations

import csv
import tempfile
from pathlib import Path

import pytest

from src.db import Database
from src.dhv_import import (
    _normalize_model_name,
    _resolve_dhv_manufacturer,
    import_dhv_csv,
)
from src.fredvol_import import import_fredvol_csv
from src.models import Manufacturer, SizeVariant, WingCategory, WingModel
from src.normalizer import make_model_slug


# ── DHV manufacturer resolution ──────────────────────────────────────────────


class TestResolveDhvManufacturer:
    """Test DHV manufacturer legal name → slug resolution."""

    def test_slug_from_match_failure(self):
        assert _resolve_dhv_manufacturer(
            "Some Company",
            "model not found: 'Rush 5' (mfr: ozone)",
        ) == "ozone"

    def test_legal_name_map(self):
        assert _resolve_dhv_manufacturer(
            "OZONE Gliders Ltd.", ""
        ) == "ozone"

    def test_nova_legal(self):
        assert _resolve_dhv_manufacturer(
            "NOVA Vertriebsgesellschaft m.b.H.", ""
        ) == "nova"

    def test_gin_legal(self):
        assert _resolve_dhv_manufacturer(
            "GIN Gliders Inc.", ""
        ) == "gin"

    def test_up_legal(self):
        assert _resolve_dhv_manufacturer(
            "UP International GmbH", ""
        ) == "up"

    def test_swing_legal(self):
        assert _resolve_dhv_manufacturer(
            "Swing Flugsportgeräte GmbH", ""
        ) == "swing"

    def test_macpara_legal(self):
        assert _resolve_dhv_manufacturer(
            "MAC Para Technology", ""
        ) == "macpara"

    def test_prodesign_legal(self):
        assert _resolve_dhv_manufacturer(
            "PRO-DESIGN, Hofbauer GmbH", ""
        ) == "prodesign"

    def test_turn2fly_maps_to_uturn(self):
        assert _resolve_dhv_manufacturer(
            "Turn2Fly GmbH", ""
        ) == "u-turn"

    def test_fallback_slugification(self):
        assert _resolve_dhv_manufacturer(
            "Unknown Brand GmbH", ""
        ) == "unknown-brand-gmbh"


# ── Model name normalization ─────────────────────────────────────────────────


class TestNormalizeModelName:
    def test_strip_gliders_prefix(self):
        assert _normalize_model_name("Gliders Buzz Z3") == "Buzz Z3"

    def test_strip_thun_ag_prefix(self):
        assert _normalize_model_name("Thun AG Sigma 8") == "Sigma 8"

    def test_strip_phi_prefix(self):
        assert _normalize_model_name("PHI MAESTRO 3 light") == "MAESTRO 3 light"

    def test_no_stripping_needed(self):
        assert _normalize_model_name("Rush 5") == "Rush 5"

    def test_normalize_spaces(self):
        assert _normalize_model_name("  Rush   5  ") == "Rush 5"


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
def sample_dhv_csv(tmp_path: Path) -> Path:
    """Create a small sample DHV CSV for testing."""
    csv_path = tmp_path / "dhv_sample.csv"
    rows = [
        {
            "dhv_url": "https://service.dhv.de/db1/test1",
            "manufacturer": "Ozone Gliders",
            "model": "Rush 5",
            "size": "S",
            "equipment_class": "B",
            "test_centre": "Air Turquoise",
            "test_date": "2019-06-15",
            "report_url": "https://service.dhv.de/report1",
            "match_failure_reason": "model not found: 'Rush 5' (mfr: ozone)",
        },
        {
            "dhv_url": "https://service.dhv.de/db1/test2",
            "manufacturer": "Ozone Gliders",
            "model": "Rush 5",
            "size": "M",
            "equipment_class": "B",
            "test_centre": "Air Turquoise",
            "test_date": "2019-06-15",
            "report_url": "https://service.dhv.de/report1",
            "match_failure_reason": "model not found: 'Rush 5' (mfr: ozone)",
        },
        {
            "dhv_url": "https://service.dhv.de/db1/test3",
            "manufacturer": "GIN Gliders Inc.",
            "model": "Bolero 7",
            "size": "S",
            "equipment_class": "A",
            "test_centre": "",
            "test_date": "2022-05-18",
            "report_url": "",
            "match_failure_reason": "",
        },
        {
            "dhv_url": "https://service.dhv.de/db1/test4",
            "manufacturer": "ADVANCE Thun AG",
            "model": "Thun AG Sigma 8",
            "size": "23",
            "equipment_class": "C",
            "test_centre": "",
            "test_date": "2011-03-07",
            "report_url": "",
            "match_failure_reason": "",
        },
    ]

    fieldnames = list(rows[0].keys())
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    return csv_path


class TestImportDhvCSV:
    def test_import_creates_models(self, tmp_db: Database, sample_dhv_csv: Path):
        counts = import_dhv_csv(sample_dhv_csv, tmp_db, create_missing=True)

        assert counts["manufacturers"] >= 2
        assert counts["certifications"] >= 3
        assert counts["models_created"] >= 2

    def test_manufacturer_filter(self, tmp_db: Database, sample_dhv_csv: Path):
        counts = import_dhv_csv(
            sample_dhv_csv, tmp_db, manufacturer_filter="ozone",
        )

        assert counts["manufacturers"] == 1
        assert counts["certifications"] == 2  # Rush 5 S + M

    def test_enrichment_adds_certs(self, tmp_db: Database, sample_dhv_csv: Path):
        """Test that DHV enriches an existing model with certifications."""
        # Pre-populate with a model
        mfr = Manufacturer(name="Ozone", slug="ozone")
        mfr_id = tmp_db.upsert_manufacturer(mfr)
        wing = WingModel(
            name="Rush 5",
            slug="ozone-rush-5",
            category=WingCategory.paraglider,
            is_current=True,
        )
        model_id = tmp_db.upsert_model(wing, mfr_id)
        sv = SizeVariant(size_label="S", flat_area_m2=22.0)
        tmp_db.upsert_size_variant(sv, model_id)

        # Now import DHV — should match existing model
        counts = import_dhv_csv(
            sample_dhv_csv, tmp_db, manufacturer_filter="ozone",
        )

        assert counts["models_matched"] >= 1

        # Check cert was added
        cert = tmp_db.conn.execute(
            """SELECT c.* FROM certifications c
               JOIN size_variants sv ON c.size_variant_id = sv.id
               JOIN models m ON sv.model_id = m.id
               WHERE m.slug = 'ozone-rush-5' AND sv.size_label = 'S'"""
        ).fetchone()
        assert cert is not None
        assert cert["standard"] == "EN"
        assert cert["classification"] == "B"
        assert cert["test_date"] == "2019-06-15"

    def test_no_create_missing(self, tmp_db: Database, sample_dhv_csv: Path):
        counts = import_dhv_csv(
            sample_dhv_csv, tmp_db, create_missing=False,
        )
        # Nothing pre-populated, so nothing should be created
        assert counts["models_created"] == 0

    def test_model_name_normalization_strips_prefix(self, tmp_db: Database, sample_dhv_csv: Path):
        """The DHV entry 'Thun AG Sigma 8' should create model named 'Sigma 8'."""
        import_dhv_csv(sample_dhv_csv, tmp_db, create_missing=True)

        # Should find model with normalized name
        row = tmp_db.conn.execute(
            "SELECT name FROM models WHERE slug LIKE '%sigma-8%'"
        ).fetchone()
        assert row is not None
        assert row["name"] == "Sigma 8"


class TestFredvolPlusDhvIntegration:
    """Test that fredvol import followed by DHV enrichment works together."""

    def test_fredvol_then_dhv(self, tmp_db: Database, tmp_path: Path):
        # Step 1: Create a fredvol CSV with one model
        fredvol_path = tmp_path / "fredvol.csv"
        fredvol_rows = [
            {
                "": "0", "certif_AFNOR": "", "certif_DHV": "", "certif_EN": "",
                "certif_MISC": "", "certification": "",
                "flat_AR": "5.0", "flat_area": "24.0", "flat_span": "11.0",
                "manufacturer": "Gin", "name": "Bolero 7",
                "proj_AR": "", "proj_area": "", "proj_span": "",
                "ptv_maxi": "100.0", "ptv_mini": "75.0", "size": "S",
                "source": "Para2000", "weight": "5.0", "year": "2022",
            },
        ]
        fieldnames = list(fredvol_rows[0].keys())
        with open(fredvol_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(fredvol_rows)

        # Step 2: Create a DHV CSV with matching cert
        dhv_path = tmp_path / "dhv.csv"
        dhv_rows = [
            {
                "dhv_url": "https://service.dhv.de/db1/test",
                "manufacturer": "GIN Gliders Inc.",
                "model": "Bolero 7",
                "size": "S",
                "equipment_class": "A",
                "test_centre": "Air Turquoise",
                "test_date": "2022-05-18",
                "report_url": "https://service.dhv.de/report",
                "match_failure_reason": "",
            },
        ]
        fieldnames = list(dhv_rows[0].keys())
        with open(dhv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(dhv_rows)

        # Step 3: Import fredvol first
        fredvol_counts = import_fredvol_csv(fredvol_path, tmp_db)
        assert fredvol_counts["models"] == 1
        assert fredvol_counts["sizes"] == 1

        # Step 4: Import DHV second (enrichment)
        dhv_counts = import_dhv_csv(dhv_path, tmp_db)
        assert dhv_counts["models_matched"] >= 1

        # Step 5: Verify the model has BOTH geometry AND certification
        sv_row = tmp_db.conn.execute(
            """SELECT sv.* FROM size_variants sv
               JOIN models m ON sv.model_id = m.id
               WHERE m.slug = 'gin-bolero-7' AND sv.size_label = 'S'"""
        ).fetchone()
        assert sv_row is not None
        assert abs(sv_row["flat_area_m2"] - 24.0) < 0.01  # from fredvol

        cert_row = tmp_db.conn.execute(
            """SELECT c.* FROM certifications c
               WHERE c.size_variant_id = ?""",
            (sv_row["id"],),
        ).fetchone()
        assert cert_row is not None
        assert cert_row["standard"] == "EN"
        assert cert_row["classification"] == "A"
        assert cert_row["test_date"] == "2022-05-18"


# ── Cert validation tests ───────────────────────────────────────────────────


class TestDhvCertValidation:
    """Tests for cert classification validation in DHV import."""

    def _make_dhv_csv(self, tmp_path, rows_data):
        csv_path = tmp_path / "dhv_validation.csv"
        fieldnames = list(rows_data[0].keys())
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows_data)
        return csv_path

    def _dhv_row(self, model="TestWing", equipment_class="B", **overrides):
        base = {
            "dhv_url": "https://service.dhv.de/db1/test",
            "manufacturer": "Test Company",
            "model": model,
            "size": "M",
            "equipment_class": equipment_class,
            "test_centre": "Air Turquoise",
            "test_date": "2023-01-15",
            "report_url": "https://example.com/report",
            "match_failure_reason": "mfr: test",
        }
        base.update(overrides)
        return base

    def test_valid_cert_imported(self, tmp_path):
        db_path = tmp_path / "test.db"
        db = Database(db_path)
        db.connect()
        try:
            csv_path = self._make_dhv_csv(tmp_path, [self._dhv_row(equipment_class="B")])
            counts = import_dhv_csv(csv_path, db, validate=True, create_missing=True)
            assert counts["certifications"] == 1
            assert counts["invalid_certs"] == 0
        finally:
            db.close()

    def test_invalid_cert_class_skipped_by_mapper(self, tmp_path):
        """'E' is not a valid EN class — _map_equipment_class returns None, skipped."""
        db_path = tmp_path / "test.db"
        db = Database(db_path)
        db.connect()
        try:
            csv_path = self._make_dhv_csv(tmp_path, [self._dhv_row(equipment_class="E")])
            counts = import_dhv_csv(csv_path, db, validate=True, create_missing=True)
            assert counts["certifications"] == 0
            # Skipped by _map_equipment_class (returns None), not by validation
            assert counts["skipped"] == 1
        finally:
            db.close()

    def test_validate_false_allows_invalid(self, tmp_path):
        """Even with validate=False, 'E' is still skipped by _map_equipment_class."""
        db_path = tmp_path / "test.db"
        db = Database(db_path)
        db.connect()
        try:
            csv_path = self._make_dhv_csv(tmp_path, [self._dhv_row(equipment_class="E")])
            counts = import_dhv_csv(csv_path, db, validate=False, create_missing=True)
            # "E" isn't mapped by _map_equipment_class, so it's skipped regardless
            assert counts["certifications"] == 0
        finally:
            db.close()

    def test_mixed_valid_and_invalid(self, tmp_path):
        """Valid A/C imported, invalid E skipped by mapper."""
        db_path = tmp_path / "test.db"
        db = Database(db_path)
        db.connect()
        try:
            csv_path = self._make_dhv_csv(tmp_path, [
                self._dhv_row(model="Good", equipment_class="A"),
                self._dhv_row(model="Bad", equipment_class="E"),
                self._dhv_row(model="Good2", equipment_class="C"),
            ])
            counts = import_dhv_csv(csv_path, db, validate=True, create_missing=True)
            assert counts["certifications"] == 2
        finally:
            db.close()
