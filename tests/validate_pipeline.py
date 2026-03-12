"""
Validation script for the paraglider spec extraction pipeline.

Tests the full pipeline against sample data and real pages.
Usage:
    python -m tests.validate_pipeline
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

# Allow running from project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.extractor import extract_specs
from src.markdown_parser import parse_specs_from_markdown
from src.normalizer import normalize_extraction, normalize_certification
from src.db import Database
from src.models import ExtractionResult, EntityType, Manufacturer


# ── Test data ──────────────────────────────────────────────────────────────────

SAMPLE_OZONE_TABLE = """
# Rush 6

Some marketing text

| | XS | S | M | ML | L |
|---|---|---|---|---|---|
| Cells | 52 | 52 | 52 | 52 | 52 |
| Flat area (m²) | 20,14 | 22,05 | 24,12 | 25,81 | 27,62 |
| Flat span (m) | 10,37 | 10,85 | 11,34 | 11,73 | 12,14 |
| Flat aspect ratio | 5,34 | 5,34 | 5,34 | 5,34 | 5,34 |
| Projected area (m²) | 16,76 | 18,35 | 20,07 | 21,48 | 22,99 |
| Projected span (m) | 8,20 | 8,58 | 8,97 | 9,28 | 9,60 |
| Projected aspect ratio | 4,01 | 4,01 | 4,01 | 4,01 | 4,01 |
| Wing weight (kg) | 4,10 | 4,40 | 4,80 | 5,05 | 5,35 |
| In-flight weight range (kg) | 55-75 | 65-85 | 80-100 | 90-110 | 100-125 |
| Certification | EN/LTF B | EN/LTF B | EN/LTF B | EN/LTF B | EN/LTF B |
| Line material | Liros TSL / DSL / PPSL | Liros TSL / DSL / PPSL | Liros TSL / DSL / PPSL | Liros TSL / DSL / PPSL | Liros TSL / DSL / PPSL |
| Risers | 12mm Kevlar | 12mm Kevlar | 12mm Kevlar | 12mm Kevlar | 12mm Kevlar |
"""

EXPECTED = {
    "model_name": "Rush 6",
    "cell_count": 52,
    "sizes": [
        {"size_label": "XS", "flat_area_m2": 20.14, "ptv_min_kg": 55.0, "ptv_max_kg": 75.0},
        {"size_label": "S", "flat_area_m2": 22.05, "ptv_min_kg": 65.0, "ptv_max_kg": 85.0},
        {"size_label": "M", "flat_area_m2": 24.12, "ptv_min_kg": 80.0, "ptv_max_kg": 100.0},
        {"size_label": "ML", "flat_area_m2": 25.81, "ptv_min_kg": 90.0, "ptv_max_kg": 110.0},
        {"size_label": "L", "flat_area_m2": 27.62, "ptv_min_kg": 100.0, "ptv_max_kg": 125.0},
    ],
}


def test_markdown_parser() -> bool:
    """Test the deterministic markdown parser against known-good input."""
    print("Test: Markdown parser with standard Ozone table")

    url = "https://flyozone.com/paragliders/en/products/gliders/rush-6/info/"
    result = parse_specs_from_markdown(SAMPLE_OZONE_TABLE, url)

    if result is None:
        print("  FAIL: Parser returned None")
        return False

    errors = []

    if result.model_name != EXPECTED["model_name"]:
        errors.append(f"  model_name: got '{result.model_name}', expected '{EXPECTED['model_name']}'")

    if result.cell_count != EXPECTED["cell_count"]:
        errors.append(f"  cell_count: got {result.cell_count}, expected {EXPECTED['cell_count']}")

    if len(result.sizes) != len(EXPECTED["sizes"]):
        errors.append(f"  size count: got {len(result.sizes)}, expected {len(EXPECTED['sizes'])}")
    else:
        for i, (got, exp) in enumerate(zip(result.sizes, EXPECTED["sizes"])):
            if got.size_label != exp["size_label"]:
                errors.append(f"  sizes[{i}].size_label: got '{got.size_label}', expected '{exp['size_label']}'")
            if got.flat_area_m2 != exp["flat_area_m2"]:
                errors.append(f"  sizes[{i}].flat_area_m2: got {got.flat_area_m2}, expected {exp['flat_area_m2']}")
            if got.ptv_min_kg != exp["ptv_min_kg"]:
                errors.append(f"  sizes[{i}].ptv_min_kg: got {got.ptv_min_kg}, expected {exp['ptv_min_kg']}")
            if got.ptv_max_kg != exp["ptv_max_kg"]:
                errors.append(f"  sizes[{i}].ptv_max_kg: got {got.ptv_max_kg}, expected {exp['ptv_max_kg']}")

    if errors:
        print("  FAIL:")
        for e in errors:
            print(f"    {e}")
        return False

    print(f"  PASS: {result.model_name} — {len(result.sizes)} sizes extracted correctly")
    return True


def test_certification_normalization() -> bool:
    """Test certification normalization edge cases."""
    print("Test: Certification normalization")

    cases = [
        ("EN B", "EN", "B"),
        ("EN/LTF B", "EN", "B"),
        ("LTF A", "LTF", "A"),
        ("CCC", "CCC", ""),
        ("CIVL CCC", "CCC", ""),
        ("EN-C", "EN", "C"),
        ("EN D", "EN", "D"),
    ]

    errors = []
    for raw, exp_std, exp_class in cases:
        std, cls = normalize_certification(raw)
        if std.value != exp_std or cls != exp_class:
            errors.append(f"  '{raw}' → ({std.value}, '{cls}'), expected ({exp_std}, '{exp_class}')")

    if errors:
        print("  FAIL:")
        for e in errors:
            print(f"    {e}")
        return False

    print(f"  PASS: {len(cases)} certification patterns normalized correctly")
    return True


def test_normalize_and_store() -> bool:
    """Test normalize → DB round-trip."""
    print("Test: Normalize → SQLite storage")

    url = "https://flyozone.com/paragliders/en/products/gliders/rush-6/info/"
    result = parse_specs_from_markdown(SAMPLE_OZONE_TABLE, url)
    if result is None:
        print("  FAIL: Parser returned None")
        return False

    wing, sizes, certs = normalize_extraction(
        result, "ozone", is_current=True, source_url=url,
    )

    if wing.slug != "ozone-rush-6":
        print(f"  FAIL: wing.slug = '{wing.slug}', expected 'ozone-rush-6'")
        return False

    if len(sizes) != 5:
        print(f"  FAIL: {len(sizes)} sizes, expected 5")
        return False

    # Round-trip through DB
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = Database(db_path)
        db.connect()

        mfr = Manufacturer(name="Ozone", slug="ozone", country="FR", website="https://flyozone.com")
        mfr_id = db.upsert_manufacturer(mfr)
        model_id = db.upsert_model(wing, mfr_id)

        for i, sv in enumerate(sizes):
            sv_id = db.upsert_size_variant(sv, model_id)
            if i < len(certs):
                db.insert_certification(certs[i], sv_id)
            db.record_provenance(EntityType.size_variant, sv_id, url, "ozone")

        # Verify
        row = db.conn.execute("SELECT COUNT(*) FROM size_variants").fetchone()
        row_count = row[0]
        cert_row = db.conn.execute("SELECT COUNT(*) FROM certifications").fetchone()
        cert_count = cert_row[0]
        prov_row = db.conn.execute("SELECT COUNT(*) FROM data_sources").fetchone()
        prov_count = prov_row[0]

        db.close()

    if row_count != 5:
        print(f"  FAIL: {row_count} size_variants in DB, expected 5")
        return False

    if cert_count != 5:
        print(f"  FAIL: {cert_count} certifications in DB, expected 5")
        return False

    print(f"  PASS: {row_count} sizes, {cert_count} certs, {prov_count} provenance records in DB")
    return True


def test_extract_specs_fallback() -> bool:
    """Test that extract_specs falls back to markdown parser when adapter=None."""
    print("Test: extract_specs fallback (adapter=None)")

    url = "https://flyozone.com/paragliders/en/products/gliders/rush-6/info/"
    result = extract_specs(None, SAMPLE_OZONE_TABLE, {}, url=url)

    if result is None:
        print("  FAIL: extract_specs returned None")
        return False

    if result.model_name != "Rush 6":
        print(f"  FAIL: model_name = '{result.model_name}'")
        return False

    print(f"  PASS: Fallback extracted {result.model_name} — {len(result.sizes)} sizes")
    return True


def main() -> None:
    print("=" * 60)
    print("Pipeline Validation")
    print("=" * 60)
    print()

    tests = [
        test_markdown_parser,
        test_certification_normalization,
        test_extract_specs_fallback,
        test_normalize_and_store,
    ]

    passed = 0
    failed = 0

    for test_fn in tests:
        try:
            if test_fn():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"  ERROR: {e}")
            failed += 1
        print()

    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
