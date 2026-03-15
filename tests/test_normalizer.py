"""Tests for normalization logic — certifications, size labels, slugs, full pipeline."""

from src.markdown_parser import parse_specs_from_markdown
from src.normalizer import (
    make_model_slug,
    normalize_certification,
    normalize_extraction,
    normalize_size_label,
)
from src.models import CertStandard

from conftest import (
    SWIFT6_EXPECTED,
    SWIFT6_MARKDOWN,
    assert_size_specs,
)


SWIFT6_URL = "https://flyozone.com/paragliders/products/gliders/swift-6"


class TestCertificationNormalization:
    def test_en_b(self):
        std, cls = normalize_certification("EN B")
        assert std == CertStandard.EN
        assert cls == "B"

    def test_ltf_a(self):
        std, cls = normalize_certification("LTF A")
        assert std == CertStandard.LTF
        assert cls == "A"

    def test_ccc(self):
        std, cls = normalize_certification("CCC")
        assert std == CertStandard.CCC
        assert cls == "CCC"

    def test_civl_ccc(self):
        std, cls = normalize_certification("CIVL CCC")
        assert std == CertStandard.CCC
        assert cls == "CCC"

    def test_dhv_1_2(self):
        std, cls = normalize_certification("DHV 1-2")
        assert std == CertStandard.LTF
        assert cls == "B"

    def test_dhv_1(self):
        std, cls = normalize_certification("DHV 1")
        assert std == CertStandard.LTF
        assert cls == "A"

    def test_bare_letter_b(self):
        std, cls = normalize_certification("B")
        assert std == CertStandard.EN
        assert cls == "B"

    def test_en_dash_c(self):
        std, cls = normalize_certification("EN-C")
        assert std == CertStandard.EN
        assert cls == "C"

    def test_en_ltf_b(self):
        std, cls = normalize_certification("EN/LTF B")
        assert std == CertStandard.EN
        assert cls == "B"

    def test_en_d(self):
        std, cls = normalize_certification("EN D")
        assert std == CertStandard.EN
        assert cls == "D"


class TestSizeLabelNormalization:
    def test_extra_small(self):
        assert normalize_size_label("extra small") == "XS"

    def test_xs_preserved(self):
        assert normalize_size_label("xs") == "XS"

    def test_ms_non_standard_preserved(self):
        # MS is not in _SIZE_MAP → preserved as-is (uppercase)
        assert normalize_size_label("MS") == "MS"

    def test_ml_non_standard_preserved(self):
        assert normalize_size_label("ML") == "ML"

    def test_numeric_23_preserved(self):
        # "23" is not in default _SIZE_MAP → preserved as-is
        assert normalize_size_label("23") == "23"

    def test_numeric_29_preserved(self):
        assert normalize_size_label("29") == "29"


class TestSlugGeneration:
    def test_ozone_swift_6(self):
        assert make_model_slug("ozone", "Swift 6") == "ozone-swift-6"

    def test_advance_iota_2(self):
        assert make_model_slug("advance", "Iota 2") == "advance-iota-2"

    def test_special_characters_stripped(self):
        assert make_model_slug("ozone", "Buzz Z7!") == "ozone-buzz-z7"

    def test_multiple_spaces(self):
        assert make_model_slug("nova", "Ion  Light  2") == "nova-ion-light-2"


class TestNormalizeExtraction:
    def test_swift6_wing_slug(self):
        result = parse_specs_from_markdown(SWIFT6_MARKDOWN, SWIFT6_URL)
        wing, sizes, certs, perfs = normalize_extraction(result, "ozone", source_url=SWIFT6_URL)
        assert wing.slug == "ozone-swift-6"

    def test_swift6_produces_five_sizes(self):
        result = parse_specs_from_markdown(SWIFT6_MARKDOWN, SWIFT6_URL)
        _, sizes, _, _ = normalize_extraction(result, "ozone")
        assert len(sizes) == 5

    def test_swift6_produces_five_certs(self):
        result = parse_specs_from_markdown(SWIFT6_MARKDOWN, SWIFT6_URL)
        _, _, certs, _ = normalize_extraction(result, "ozone")
        assert len(certs) == 5

    def test_swift6_size_label_order(self):
        result = parse_specs_from_markdown(SWIFT6_MARKDOWN, SWIFT6_URL)
        _, sizes, _, _ = normalize_extraction(result, "ozone")
        labels = [s.size_label for s in sizes]
        assert labels == ["XS", "S", "MS", "ML", "L"]

    def test_normalize_preserves_spec_values(self):
        """After normalization, spec values must still match ground truth exactly."""
        result = parse_specs_from_markdown(SWIFT6_MARKDOWN, SWIFT6_URL)
        _, sizes, _, _ = normalize_extraction(result, "ozone")
        for sv in sizes:
            expected = SWIFT6_EXPECTED.get(sv.size_label)
            if expected:
                assert_size_specs(sv, expected, sv.size_label)

    def test_normalize_certs_are_en_b(self):
        result = parse_specs_from_markdown(SWIFT6_MARKDOWN, SWIFT6_URL)
        _, _, certs, _ = normalize_extraction(result, "ozone")
        for cert in certs:
            assert cert.standard == CertStandard.EN
            assert cert.classification == "B"

    def test_wing_cell_count_preserved(self):
        result = parse_specs_from_markdown(SWIFT6_MARKDOWN, SWIFT6_URL)
        wing, _, _, _ = normalize_extraction(result, "ozone")
        assert wing.cell_count == 62

    def test_wing_source_url(self):
        result = parse_specs_from_markdown(SWIFT6_MARKDOWN, SWIFT6_URL)
        wing, _, _, _ = normalize_extraction(result, "ozone", source_url=SWIFT6_URL)
        assert wing.manufacturer_url == SWIFT6_URL
