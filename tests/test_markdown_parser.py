"""Tests for the deterministic markdown parser — strict data quality assertions.

Every test that parses real fixture data asserts ALL 10 key spec fields
(flat_area_m2, flat_span_m, flat_aspect_ratio, proj_area_m2, proj_span_m,
proj_aspect_ratio, wing_weight_kg, ptv_min_kg, ptv_max_kg, + cell_count)
against verified ground truth values from ozone_enrichment.csv and fredvol_raw.csv.
"""

from src.markdown_parser import parse_specs_from_markdown

from conftest import (
    ADVANCE_IOTA_DLS_MARKDOWN,
    BUZZ_CELL_COUNT,
    BUZZ_EXPECTED,
    BUZZ_MARKDOWN,
    IOTA_DLS_CELL_COUNT,
    IOTA_DLS_EXPECTED,
    RUSH6_EXPECTED,
    RUSH6_MARKDOWN,
    SWIFT6_CELL_COUNT,
    SWIFT6_EXPECTED,
    SWIFT6_MARKDOWN,
    assert_size_specs,
    assert_spec_field,
)


SWIFT6_URL = "https://flyozone.com/paragliders/products/gliders/swift-6"
RUSH6_URL = "https://flyozone.com/paragliders/en/products/gliders/rush-6/info/"
IOTA_DLS_URL = "https://advance.swiss/en/paragliders/iota-dls"
BUZZ_URL = "https://flyozone.com/paragliders/products/gliders/buzz"


class TestSwift6FullExtraction:
    """Parse Swift 6 markdown and verify ALL key spec fields for ALL 5 sizes."""

    def test_swift6_parses_successfully(self):
        result = parse_specs_from_markdown(SWIFT6_MARKDOWN, SWIFT6_URL)
        assert result is not None, "Parser returned None for Swift 6 table"

    def test_swift6_model_metadata(self):
        result = parse_specs_from_markdown(SWIFT6_MARKDOWN, SWIFT6_URL)
        assert result.cell_count == SWIFT6_CELL_COUNT

    def test_swift6_size_count(self):
        result = parse_specs_from_markdown(SWIFT6_MARKDOWN, SWIFT6_URL)
        assert len(result.sizes) == 5, f"Expected 5 sizes, got {len(result.sizes)}"

    def test_swift6_size_labels(self):
        result = parse_specs_from_markdown(SWIFT6_MARKDOWN, SWIFT6_URL)
        labels = [s.size_label for s in result.sizes]
        assert labels == ["XS", "S", "MS", "ML", "L"]

    def test_swift6_xs_specs(self):
        result = parse_specs_from_markdown(SWIFT6_MARKDOWN, SWIFT6_URL)
        xs = next(s for s in result.sizes if s.size_label == "XS")
        assert_size_specs(xs, SWIFT6_EXPECTED["XS"], "XS")

    def test_swift6_s_specs(self):
        result = parse_specs_from_markdown(SWIFT6_MARKDOWN, SWIFT6_URL)
        s = next(s for s in result.sizes if s.size_label == "S")
        assert_size_specs(s, SWIFT6_EXPECTED["S"], "S")

    def test_swift6_ms_specs(self):
        result = parse_specs_from_markdown(SWIFT6_MARKDOWN, SWIFT6_URL)
        ms = next(s for s in result.sizes if s.size_label == "MS")
        assert_size_specs(ms, SWIFT6_EXPECTED["MS"], "MS")

    def test_swift6_ml_specs(self):
        result = parse_specs_from_markdown(SWIFT6_MARKDOWN, SWIFT6_URL)
        ml = next(s for s in result.sizes if s.size_label == "ML")
        assert_size_specs(ml, SWIFT6_EXPECTED["ML"], "ML")

    def test_swift6_l_specs(self):
        result = parse_specs_from_markdown(SWIFT6_MARKDOWN, SWIFT6_URL)
        l_size = next(s for s in result.sizes if s.size_label == "L")
        assert_size_specs(l_size, SWIFT6_EXPECTED["L"], "L")

    def test_swift6_certifications(self):
        result = parse_specs_from_markdown(SWIFT6_MARKDOWN, SWIFT6_URL)
        for s in result.sizes:
            assert s.certification is not None, f"{s.size_label} missing certification"
            assert "B" in s.certification.upper(), f"{s.size_label} cert should be B"


class TestAdvanceStyleNumericSizes:
    """Parse Advance IOTA DLS table with numeric size labels (21, 23, 25, 27, 29)."""

    def test_iota_dls_parses_successfully(self):
        result = parse_specs_from_markdown(ADVANCE_IOTA_DLS_MARKDOWN, IOTA_DLS_URL)
        assert result is not None, "Parser returned None for IOTA DLS table"

    def test_iota_dls_size_count(self):
        result = parse_specs_from_markdown(ADVANCE_IOTA_DLS_MARKDOWN, IOTA_DLS_URL)
        assert len(result.sizes) == 5, f"Expected 5 sizes, got {len(result.sizes)}"

    def test_iota_dls_size_labels(self):
        result = parse_specs_from_markdown(ADVANCE_IOTA_DLS_MARKDOWN, IOTA_DLS_URL)
        labels = [s.size_label for s in result.sizes]
        assert labels == ["21", "23", "25", "27", "29"]

    def test_iota_dls_cell_count(self):
        result = parse_specs_from_markdown(ADVANCE_IOTA_DLS_MARKDOWN, IOTA_DLS_URL)
        assert result.cell_count == IOTA_DLS_CELL_COUNT

    def test_iota_dls_size21_specs(self):
        result = parse_specs_from_markdown(ADVANCE_IOTA_DLS_MARKDOWN, IOTA_DLS_URL)
        s21 = next(s for s in result.sizes if s.size_label == "21")
        assert_size_specs(s21, IOTA_DLS_EXPECTED["21"], "21")

    def test_iota_dls_size23_specs(self):
        result = parse_specs_from_markdown(ADVANCE_IOTA_DLS_MARKDOWN, IOTA_DLS_URL)
        s23 = next(s for s in result.sizes if s.size_label == "23")
        assert_size_specs(s23, IOTA_DLS_EXPECTED["23"], "23")

    def test_iota_dls_size25_specs(self):
        result = parse_specs_from_markdown(ADVANCE_IOTA_DLS_MARKDOWN, IOTA_DLS_URL)
        s25 = next(s for s in result.sizes if s.size_label == "25")
        assert_size_specs(s25, IOTA_DLS_EXPECTED["25"], "25")

    def test_iota_dls_size27_specs(self):
        result = parse_specs_from_markdown(ADVANCE_IOTA_DLS_MARKDOWN, IOTA_DLS_URL)
        s27 = next(s for s in result.sizes if s.size_label == "27")
        assert_size_specs(s27, IOTA_DLS_EXPECTED["27"], "27")

    def test_iota_dls_size29_specs(self):
        result = parse_specs_from_markdown(ADVANCE_IOTA_DLS_MARKDOWN, IOTA_DLS_URL)
        s29 = next(s for s in result.sizes if s.size_label == "29")
        assert_size_specs(s29, IOTA_DLS_EXPECTED["29"], "29")


class TestRush6BackwardCompat:
    """Verify Rush 6 fixture still parses correctly (same as validate_pipeline.py)."""

    def test_rush6_parses(self):
        result = parse_specs_from_markdown(RUSH6_MARKDOWN, RUSH6_URL)
        assert result is not None

    def test_rush6_cell_count(self):
        result = parse_specs_from_markdown(RUSH6_MARKDOWN, RUSH6_URL)
        assert result.cell_count == 52

    def test_rush6_five_sizes(self):
        result = parse_specs_from_markdown(RUSH6_MARKDOWN, RUSH6_URL)
        assert len(result.sizes) == 5

    def test_rush6_spec_values(self):
        result = parse_specs_from_markdown(RUSH6_MARKDOWN, RUSH6_URL)
        for size in result.sizes:
            expected = RUSH6_EXPECTED.get(size.size_label)
            if expected:
                assert_size_specs(size, expected, size.size_label)


class TestParserEdgeCases:
    def test_eu_decimal_handling(self):
        """Verify EU decimal notation (comma) is parsed correctly."""
        md = """\
## Specifications

| | S |
|---|---|
| Flat area (m2) | 20,14 |
| In-flight weight range (kg) | 55-75 |
"""
        result = parse_specs_from_markdown(md, "https://example.com/test-wing")
        assert result is not None
        s = result.sizes[0]
        assert_spec_field(s.flat_area_m2, 20.14, "flat_area_m2")

    def test_weight_range_splitting_dash(self):
        """55-72 → (55.0, 72.0)"""
        md = """\
## Specifications

| | M |
|---|---|
| In-flight weight range (kg) | 55-72 |
"""
        result = parse_specs_from_markdown(md, "https://example.com/test")
        assert result is not None
        assert_spec_field(result.sizes[0].ptv_min_kg, 55.0, "ptv_min_kg")
        assert_spec_field(result.sizes[0].ptv_max_kg, 72.0, "ptv_max_kg")

    def test_weight_range_splitting_en_dash(self):
        """65 – 85 → (65.0, 85.0)"""
        md = """\
## Specifications

| | M |
|---|---|
| Certified weight range (kg) | 65 – 85 |
"""
        result = parse_specs_from_markdown(md, "https://example.com/test")
        assert result is not None
        assert_spec_field(result.sizes[0].ptv_min_kg, 65.0, "ptv_min_kg")
        assert_spec_field(result.sizes[0].ptv_max_kg, 85.0, "ptv_max_kg")

    def test_no_spec_table_returns_none(self):
        md = "# About Us\n\nWe make great gliders.\n\nContact us at info@example.com"
        result = parse_specs_from_markdown(md, "https://example.com/about")
        assert result is None

    def test_model_name_from_url_slug(self):
        md = """\
## Specifications

| | S |
|---|---|
| Flat area (m2) | 20.0 |
| Weight range (kg) | 55-75 |
"""
        result = parse_specs_from_markdown(md, "https://example.com/products/alpha-7")
        assert result is not None
        assert result.model_name == "Alpha 7"


class TestBuzzDHVAndCellCount:
    """Test Ozone Buzz: 'No of cells' label and DHV certification parsing (Iteration 19)."""

    def test_buzz_parses_successfully(self):
        result = parse_specs_from_markdown(BUZZ_MARKDOWN, BUZZ_URL)
        assert result is not None, "Parser returned None for Buzz table"

    def test_buzz_model_name(self):
        result = parse_specs_from_markdown(BUZZ_MARKDOWN, BUZZ_URL)
        assert result.model_name == "Buzz"

    def test_buzz_no_of_cells_extraction(self):
        """Verify 'No of cells' label is recognized and parsed."""
        result = parse_specs_from_markdown(BUZZ_MARKDOWN, BUZZ_URL)
        assert result.cell_count == BUZZ_CELL_COUNT, (
            f"Expected cell_count={BUZZ_CELL_COUNT}, got {result.cell_count}"
        )

    def test_buzz_size_count(self):
        result = parse_specs_from_markdown(BUZZ_MARKDOWN, BUZZ_URL)
        assert len(result.sizes) == 5, f"Expected 5 sizes, got {len(result.sizes)}"

    def test_buzz_size_labels(self):
        result = parse_specs_from_markdown(BUZZ_MARKDOWN, BUZZ_URL)
        labels = [s.size_label for s in result.sizes]
        assert labels == ["XS", "S", "M", "L", "XL"]

    def test_buzz_xs_specs(self):
        result = parse_specs_from_markdown(BUZZ_MARKDOWN, BUZZ_URL)
        xs = next(s for s in result.sizes if s.size_label == "XS")
        assert_size_specs(xs, BUZZ_EXPECTED["XS"], "XS")

    def test_buzz_s_specs(self):
        result = parse_specs_from_markdown(BUZZ_MARKDOWN, BUZZ_URL)
        s = next(s for s in result.sizes if s.size_label == "S")
        assert_size_specs(s, BUZZ_EXPECTED["S"], "S")

    def test_buzz_m_specs(self):
        result = parse_specs_from_markdown(BUZZ_MARKDOWN, BUZZ_URL)
        m = next(s for s in result.sizes if s.size_label == "M")
        assert_size_specs(m, BUZZ_EXPECTED["M"], "M")

    def test_buzz_l_specs(self):
        result = parse_specs_from_markdown(BUZZ_MARKDOWN, BUZZ_URL)
        l_size = next(s for s in result.sizes if s.size_label == "L")
        assert_size_specs(l_size, BUZZ_EXPECTED["L"], "L")

    def test_buzz_xl_specs(self):
        result = parse_specs_from_markdown(BUZZ_MARKDOWN, BUZZ_URL)
        xl = next(s for s in result.sizes if s.size_label == "XL")
        assert_size_specs(xl, BUZZ_EXPECTED["XL"], "XL")

    def test_buzz_dhv_certifications(self):
        """Verify DHV label is recognized and certifications are per-size."""
        result = parse_specs_from_markdown(BUZZ_MARKDOWN, BUZZ_URL)
        for s in result.sizes:
            assert s.certification is not None, (
                f"{s.size_label} missing certification from DHV label"
            )
            # DHV 1-2 is preserved by normalizer as LTF 1-2 (see normalizer.py)
            assert "1-2" in s.certification, (
                f"{s.size_label} cert should contain '1-2', got '{s.certification}'"
            )

