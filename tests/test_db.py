"""Tests for SQLite database operations — schema, upserts, exact value round-trips."""

import sqlite3

import pytest

from src.db import Database
from src.models import (
    Certification,
    CertStandard,
    DataSource,
    EntityType,
    Manufacturer,
    SizeVariant,
    WingModel,
)

from conftest import SWIFT6_EXPECTED, assert_spec_field


class TestSchemaCreation:
    def test_all_five_tables_exist(self, tmp_db):
        tables = {
            row[0]
            for row in tmp_db.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        expected = {"manufacturers", "models", "size_variants", "certifications", "data_sources"}
        assert expected <= tables

    def test_foreign_keys_enabled(self, tmp_db):
        row = tmp_db.conn.execute("PRAGMA foreign_keys").fetchone()
        assert row[0] == 1


class TestUpsertManufacturer:
    def test_insert_returns_id(self, tmp_db):
        mfr = Manufacturer(name="Ozone", slug="ozone", country="FR")
        mfr_id = tmp_db.upsert_manufacturer(mfr)
        assert isinstance(mfr_id, int)
        assert mfr_id >= 1

    def test_idempotent_same_slug(self, tmp_db):
        mfr = Manufacturer(name="Ozone", slug="ozone")
        id1 = tmp_db.upsert_manufacturer(mfr)
        id2 = tmp_db.upsert_manufacturer(mfr)
        assert id1 == id2

    def test_different_slugs_different_ids(self, tmp_db):
        id1 = tmp_db.upsert_manufacturer(Manufacturer(name="Ozone", slug="ozone"))
        id2 = tmp_db.upsert_manufacturer(Manufacturer(name="Advance", slug="advance"))
        assert id1 != id2


class TestUpsertModel:
    def test_insert_returns_id(self, tmp_db, ozone_manufacturer):
        mfr_id = tmp_db.upsert_manufacturer(ozone_manufacturer)
        wing = WingModel(name="Swift 6", slug="ozone-swift-6")
        model_id = tmp_db.upsert_model(wing, mfr_id)
        assert isinstance(model_id, int)
        assert model_id >= 1

    def test_idempotent_same_slug(self, tmp_db, ozone_manufacturer):
        mfr_id = tmp_db.upsert_manufacturer(ozone_manufacturer)
        wing = WingModel(name="Swift 6", slug="ozone-swift-6")
        id1 = tmp_db.upsert_model(wing, mfr_id)
        id2 = tmp_db.upsert_model(wing, mfr_id)
        assert id1 == id2


class TestUpsertSizeVariant:
    def test_insert_and_find(self, tmp_db, ozone_manufacturer):
        mfr_id = tmp_db.upsert_manufacturer(ozone_manufacturer)
        wing = WingModel(name="Swift 6", slug="ozone-swift-6")
        model_id = tmp_db.upsert_model(wing, mfr_id)

        sv = SizeVariant(size_label="XS", flat_area_m2=20.05)
        sv_id = tmp_db.upsert_size_variant(sv, model_id)
        assert isinstance(sv_id, int)

    def test_idempotent_same_label(self, tmp_db, ozone_manufacturer):
        mfr_id = tmp_db.upsert_manufacturer(ozone_manufacturer)
        model_id = tmp_db.upsert_model(
            WingModel(name="Swift 6", slug="ozone-swift-6"), mfr_id
        )
        sv = SizeVariant(size_label="S", flat_area_m2=22.54)
        id1 = tmp_db.upsert_size_variant(sv, model_id)
        id2 = tmp_db.upsert_size_variant(sv, model_id)
        assert id1 == id2


class TestExactValueRoundTrip:
    """Verify the DB stores and returns exact spec values for Swift 6 XS."""

    def test_db_stores_exact_spec_values(self, tmp_db, ozone_manufacturer):
        mfr_id = tmp_db.upsert_manufacturer(ozone_manufacturer)
        model_id = tmp_db.upsert_model(
            WingModel(name="Swift 6", slug="ozone-swift-6", cell_count=62), mfr_id
        )

        expected = SWIFT6_EXPECTED["XS"]
        sv = SizeVariant(
            size_label="XS",
            flat_area_m2=expected["flat_area_m2"],
            flat_span_m=expected["flat_span_m"],
            flat_aspect_ratio=expected["flat_aspect_ratio"],
            proj_area_m2=expected["proj_area_m2"],
            proj_span_m=expected["proj_span_m"],
            proj_aspect_ratio=expected["proj_aspect_ratio"],
            wing_weight_kg=expected["wing_weight_kg"],
            ptv_min_kg=expected["ptv_min_kg"],
            ptv_max_kg=expected["ptv_max_kg"],
        )
        sv_id = tmp_db.upsert_size_variant(sv, model_id)

        # Read back from DB
        row = tmp_db.conn.execute(
            "SELECT * FROM size_variants WHERE id = ?", (sv_id,)
        ).fetchone()

        assert_spec_field(row["flat_area_m2"], expected["flat_area_m2"], "flat_area_m2")
        assert_spec_field(row["flat_span_m"], expected["flat_span_m"], "flat_span_m")
        assert_spec_field(row["flat_aspect_ratio"], expected["flat_aspect_ratio"], "flat_aspect_ratio")
        assert_spec_field(row["proj_area_m2"], expected["proj_area_m2"], "proj_area_m2")
        assert_spec_field(row["proj_span_m"], expected["proj_span_m"], "proj_span_m")
        assert_spec_field(row["proj_aspect_ratio"], expected["proj_aspect_ratio"], "proj_aspect_ratio")
        assert_spec_field(row["wing_weight_kg"], expected["wing_weight_kg"], "wing_weight_kg")
        assert_spec_field(row["ptv_min_kg"], expected["ptv_min_kg"], "ptv_min_kg")
        assert_spec_field(row["ptv_max_kg"], expected["ptv_max_kg"], "ptv_max_kg")


class TestInsertCertification:
    def test_stores_standard_and_classification(self, tmp_db, ozone_manufacturer):
        mfr_id = tmp_db.upsert_manufacturer(ozone_manufacturer)
        model_id = tmp_db.upsert_model(
            WingModel(name="Swift 6", slug="ozone-swift-6"), mfr_id
        )
        sv_id = tmp_db.upsert_size_variant(
            SizeVariant(size_label="XS"), model_id
        )

        cert = Certification(standard=CertStandard.EN, classification="B")
        cert_id = tmp_db.insert_certification(cert, sv_id)
        assert isinstance(cert_id, int)

        row = tmp_db.conn.execute(
            "SELECT standard, classification FROM certifications WHERE id = ?",
            (cert_id,),
        ).fetchone()
        assert row["standard"] == "EN"
        assert row["classification"] == "B"


class TestRecordProvenance:
    def test_provenance_stored(self, tmp_db, ozone_manufacturer):
        mfr_id = tmp_db.upsert_manufacturer(ozone_manufacturer)
        model_id = tmp_db.upsert_model(
            WingModel(name="Swift 6", slug="ozone-swift-6"), mfr_id
        )
        sv_id = tmp_db.upsert_size_variant(
            SizeVariant(size_label="XS"), model_id
        )

        url = "https://flyozone.com/paragliders/products/gliders/swift-6"
        tmp_db.record_provenance(EntityType.size_variant, sv_id, url, "ozone")

        row = tmp_db.conn.execute(
            "SELECT * FROM data_sources WHERE entity_id = ? AND entity_type = ?",
            (sv_id, "size_variant"),
        ).fetchone()
        assert row is not None
        assert row["source_url"] == url
        assert row["source_name"] == "manufacturer_ozone"


class TestForeignKeyEnforcement:
    def test_size_variant_invalid_model_id_raises(self, tmp_db):
        sv = SizeVariant(size_label="XS")
        with pytest.raises(sqlite3.IntegrityError):
            tmp_db.upsert_size_variant(sv, 99999)
