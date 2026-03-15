"""End-to-end tests — full pipeline flow with strict data quality verification.

Each test exercises: parse → extract → normalize → DB store → read back → verify.
No network, no Ollama, no Crawl4AI browser required.
"""

import csv
import tempfile
from pathlib import Path

from src.db import Database
from src.extractor import extract_specs
from src.markdown_parser import parse_specs_from_markdown
from src.models import EntityType, Manufacturer
from src.normalizer import normalize_extraction
from src.pipeline import _CSV_COLUMNS, _export_csv

from conftest import (
    ADVANCE_IOTA_DLS_MARKDOWN,
    FailingAdapter,
    IOTA_DLS_EXPECTED,
    MockAdapter,
    SWIFT6_EXPECTED,
    SWIFT6_MARKDOWN,
    assert_spec_field,
)


SWIFT6_URL = "https://flyozone.com/paragliders/products/gliders/swift-6"
IOTA_DLS_URL = "https://advance.swiss/en/paragliders/iota-dls"


def _setup_full_pipeline(tmp_path, markdown, url, mfr_slug, mfr_name, mfr_country):
    """Helper: run the full pipeline and return (db, mfr_id, model_id, size_ids)."""
    result = extract_specs(None, markdown, {}, url=url)
    assert result is not None, f"extract_specs returned None for {url}"

    wing, sizes, certs = normalize_extraction(result, mfr_slug, source_url=url)

    db = Database(tmp_path / "test.db")
    db.connect()

    mfr = Manufacturer(name=mfr_name, slug=mfr_slug, country=mfr_country)
    mfr_id = db.upsert_manufacturer(mfr)
    model_id = db.upsert_model(wing, mfr_id)

    size_ids = {}
    for i, sv in enumerate(sizes):
        sv_id = db.upsert_size_variant(sv, model_id)
        size_ids[sv.size_label] = sv_id
        if i < len(certs):
            db.insert_certification(certs[i], sv_id)
        db.record_provenance(EntityType.size_variant, sv_id, url, mfr_slug)

    db.record_provenance(EntityType.model, model_id, url, mfr_slug)

    return db, mfr_id, model_id, size_ids, result


class TestE2ESwift6:
    """Full pipeline: Swift 6 markdown → extract → normalize → DB → verify."""

    def test_manufacturer_exists(self, tmp_path):
        db, mfr_id, _, _, _ = _setup_full_pipeline(
            tmp_path, SWIFT6_MARKDOWN, SWIFT6_URL, "ozone", "Ozone", "FR"
        )
        row = db.conn.execute(
            "SELECT slug FROM manufacturers WHERE id = ?", (mfr_id,)
        ).fetchone()
        assert row["slug"] == "ozone"
        db.close()

    def test_model_slug(self, tmp_path):
        db, _, model_id, _, _ = _setup_full_pipeline(
            tmp_path, SWIFT6_MARKDOWN, SWIFT6_URL, "ozone", "Ozone", "FR"
        )
        row = db.conn.execute(
            "SELECT slug FROM models WHERE id = ?", (model_id,)
        ).fetchone()
        assert row["slug"] == "ozone-swift-6"
        db.close()

    def test_five_sizes_in_db(self, tmp_path):
        db, _, model_id, size_ids, _ = _setup_full_pipeline(
            tmp_path, SWIFT6_MARKDOWN, SWIFT6_URL, "ozone", "Ozone", "FR"
        )
        count = db.conn.execute(
            "SELECT COUNT(*) FROM size_variants WHERE model_id = ?", (model_id,)
        ).fetchone()[0]
        assert count == 5
        db.close()

    def test_five_certs_in_db(self, tmp_path):
        db, _, _, size_ids, _ = _setup_full_pipeline(
            tmp_path, SWIFT6_MARKDOWN, SWIFT6_URL, "ozone", "Ozone", "FR"
        )
        count = db.conn.execute("SELECT COUNT(*) FROM certifications").fetchone()[0]
        assert count == 5
        db.close()

    def test_provenance_records_exist(self, tmp_path):
        db, _, _, size_ids, _ = _setup_full_pipeline(
            tmp_path, SWIFT6_MARKDOWN, SWIFT6_URL, "ozone", "Ozone", "FR"
        )
        count = db.conn.execute("SELECT COUNT(*) FROM data_sources").fetchone()[0]
        # 5 size_variant + 1 model = 6
        assert count >= 6
        db.close()

    def test_strict_spec_values_from_db(self, tmp_path):
        """Read back every size from DB and verify all 9 key spec fields."""
        db, _, model_id, _, _ = _setup_full_pipeline(
            tmp_path, SWIFT6_MARKDOWN, SWIFT6_URL, "ozone", "Ozone", "FR"
        )
        rows = db.conn.execute(
            "SELECT * FROM size_variants WHERE model_id = ?", (model_id,)
        ).fetchall()

        for row in rows:
            label = row["size_label"]
            expected = SWIFT6_EXPECTED.get(label)
            assert expected is not None, f"Unexpected size label: {label}"

            assert_spec_field(row["flat_area_m2"], expected["flat_area_m2"], f"{label}.flat_area_m2")
            assert_spec_field(row["flat_span_m"], expected["flat_span_m"], f"{label}.flat_span_m")
            assert_spec_field(row["flat_aspect_ratio"], expected["flat_aspect_ratio"], f"{label}.flat_aspect_ratio")
            assert_spec_field(row["proj_area_m2"], expected["proj_area_m2"], f"{label}.proj_area_m2")
            assert_spec_field(row["proj_span_m"], expected["proj_span_m"], f"{label}.proj_span_m")
            assert_spec_field(row["proj_aspect_ratio"], expected["proj_aspect_ratio"], f"{label}.proj_aspect_ratio")
            assert_spec_field(row["wing_weight_kg"], expected["wing_weight_kg"], f"{label}.wing_weight_kg")
            assert_spec_field(row["ptv_min_kg"], expected["ptv_min_kg"], f"{label}.ptv_min_kg")
            assert_spec_field(row["ptv_max_kg"], expected["ptv_max_kg"], f"{label}.ptv_max_kg")

        db.close()


class TestE2EAdvanceStyle:
    """Full pipeline: Advance IOTA DLS numeric sizes → DB → verify."""

    def test_numeric_size_labels_stored(self, tmp_path):
        db, _, model_id, size_ids, _ = _setup_full_pipeline(
            tmp_path, ADVANCE_IOTA_DLS_MARKDOWN, IOTA_DLS_URL, "advance", "Advance", "CH"
        )
        rows = db.conn.execute(
            "SELECT size_label FROM size_variants WHERE model_id = ? ORDER BY size_label",
            (model_id,),
        ).fetchall()
        labels = [r["size_label"] for r in rows]
        assert labels == ["21", "23", "25", "27", "29"]
        db.close()

    def test_strict_spec_values_from_db(self, tmp_path):
        db, _, model_id, _, _ = _setup_full_pipeline(
            tmp_path, ADVANCE_IOTA_DLS_MARKDOWN, IOTA_DLS_URL, "advance", "Advance", "CH"
        )
        rows = db.conn.execute(
            "SELECT * FROM size_variants WHERE model_id = ?", (model_id,)
        ).fetchall()

        for row in rows:
            label = row["size_label"]
            expected = IOTA_DLS_EXPECTED.get(label)
            assert expected is not None, f"Unexpected size label: {label}"

            assert_spec_field(row["flat_area_m2"], expected["flat_area_m2"], f"{label}.flat_area_m2")
            assert_spec_field(row["flat_span_m"], expected["flat_span_m"], f"{label}.flat_span_m")
            assert_spec_field(row["flat_aspect_ratio"], expected["flat_aspect_ratio"], f"{label}.flat_aspect_ratio")
            assert_spec_field(row["proj_area_m2"], expected["proj_area_m2"], f"{label}.proj_area_m2")
            assert_spec_field(row["proj_span_m"], expected["proj_span_m"], f"{label}.proj_span_m")
            assert_spec_field(row["proj_aspect_ratio"], expected["proj_aspect_ratio"], f"{label}.proj_aspect_ratio")
            assert_spec_field(row["wing_weight_kg"], expected["wing_weight_kg"], f"{label}.wing_weight_kg")
            assert_spec_field(row["ptv_min_kg"], expected["ptv_min_kg"], f"{label}.ptv_min_kg")
            assert_spec_field(row["ptv_max_kg"], expected["ptv_max_kg"], f"{label}.ptv_max_kg")

        db.close()


class TestE2ECsvExport:
    def test_csv_has_correct_columns(self, tmp_path):
        result = extract_specs(None, SWIFT6_MARKDOWN, {}, url=SWIFT6_URL)
        results = [result.model_dump()]
        csv_path = tmp_path / "test.csv"
        _export_csv(results, csv_path, "ozone")

        with open(csv_path, "r") as f:
            reader = csv.DictReader(f)
            assert set(reader.fieldnames) == set(_CSV_COLUMNS)

    def test_csv_row_count(self, tmp_path):
        result = extract_specs(None, SWIFT6_MARKDOWN, {}, url=SWIFT6_URL)
        results = [result.model_dump()]
        csv_path = tmp_path / "test.csv"
        _export_csv(results, csv_path, "ozone")

        with open(csv_path, "r") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == 5  # one per size

    def test_csv_spec_values(self, tmp_path):
        result = extract_specs(None, SWIFT6_MARKDOWN, {}, url=SWIFT6_URL)
        results = [result.model_dump()]
        csv_path = tmp_path / "test.csv"
        _export_csv(results, csv_path, "ozone")

        with open(csv_path, "r") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        xs_row = next(r for r in rows if r["size_label"] == "XS")
        assert_spec_field(float(xs_row["flat_area_m2"]), 20.05, "csv.flat_area_m2")
        assert_spec_field(float(xs_row["wing_weight_kg"]), 3.57, "csv.wing_weight_kg")

    def test_csv_has_cert_columns(self, tmp_path):
        result = extract_specs(None, SWIFT6_MARKDOWN, {}, url=SWIFT6_URL)
        results = [result.model_dump()]
        csv_path = tmp_path / "test.csv"
        _export_csv(results, csv_path, "ozone")

        with open(csv_path, "r") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        xs_row = next(r for r in rows if r["size_label"] == "XS")
        assert xs_row["cert_standard"] == "EN"
        assert xs_row["cert_classification"] == "B"


class TestE2EIdempotency:
    def test_no_duplicates_on_rerun(self, tmp_path):
        """Run the full pipeline twice — no duplicate records."""
        db_path = tmp_path / "test.db"
        url = SWIFT6_URL
        mfr = Manufacturer(name="Ozone", slug="ozone", country="FR")

        for _ in range(2):
            result = extract_specs(None, SWIFT6_MARKDOWN, {}, url=url)
            wing, sizes, certs = normalize_extraction(result, "ozone", source_url=url)

            db = Database(db_path)
            db.connect()
            mfr_id = db.upsert_manufacturer(mfr)
            model_id = db.upsert_model(wing, mfr_id)
            for i, sv in enumerate(sizes):
                sv_id = db.upsert_size_variant(sv, model_id)
            db.close()

        db = Database(db_path)
        db.connect()
        assert db.conn.execute("SELECT COUNT(*) FROM manufacturers").fetchone()[0] == 1
        assert db.conn.execute("SELECT COUNT(*) FROM models").fetchone()[0] == 1
        assert db.conn.execute("SELECT COUNT(*) FROM size_variants").fetchone()[0] == 5
        db.close()


class TestE2EMockAdapter:
    def test_mock_llm_full_pipeline(self, tmp_path):
        result = extract_specs(MockAdapter(), "ignored markdown", {}, url=SWIFT6_URL)
        assert result is not None

        wing, sizes, certs = normalize_extraction(result, "ozone", source_url=SWIFT6_URL)
        db = Database(tmp_path / "test.db")
        db.connect()

        mfr = Manufacturer(name="Ozone", slug="ozone")
        mfr_id = db.upsert_manufacturer(mfr)
        model_id = db.upsert_model(wing, mfr_id)

        for i, sv in enumerate(sizes):
            sv_id = db.upsert_size_variant(sv, model_id)
            if i < len(certs):
                db.insert_certification(certs[i], sv_id)

        count = db.conn.execute("SELECT COUNT(*) FROM size_variants").fetchone()[0]
        assert count == 2  # MockAdapter returns XS and S only

        # Verify XS round-trip
        row = db.conn.execute(
            "SELECT * FROM size_variants WHERE size_label = 'XS'"
        ).fetchone()
        assert_spec_field(row["flat_area_m2"], 20.05, "mock.XS.flat_area_m2")
        assert_spec_field(row["wing_weight_kg"], 3.57, "mock.XS.wing_weight_kg")

        db.close()
