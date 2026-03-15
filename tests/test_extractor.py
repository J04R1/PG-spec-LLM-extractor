"""Tests for the extraction bridge — LLM path, markdown fallback, schema."""

from src.extractor import extract_specs, get_extraction_schema

from conftest import (
    FailingAdapter,
    MockAdapter,
    SWIFT6_EXPECTED,
    SWIFT6_MARKDOWN,
    assert_size_specs,
)


SWIFT6_URL = "https://flyozone.com/paragliders/products/gliders/swift-6"


class TestGetExtractionSchema:
    def test_schema_has_properties(self):
        schema = get_extraction_schema()
        assert "properties" in schema

    def test_schema_requires_model_name(self):
        schema = get_extraction_schema()
        assert "model_name" in schema["properties"]

    def test_schema_has_sizes(self):
        schema = get_extraction_schema()
        assert "sizes" in schema["properties"]


class TestExtractSpecsFallback:
    def test_adapter_none_uses_markdown_parser(self):
        result = extract_specs(None, SWIFT6_MARKDOWN, {}, url=SWIFT6_URL)
        assert result is not None
        assert len(result.sizes) == 5

    def test_adapter_none_strict_first_size(self):
        result = extract_specs(None, SWIFT6_MARKDOWN, {}, url=SWIFT6_URL)
        xs = next(s for s in result.sizes if s.size_label == "XS")
        assert_size_specs(xs, SWIFT6_EXPECTED["XS"], "XS")

    def test_adapter_none_no_url_returns_none(self):
        result = extract_specs(None, SWIFT6_MARKDOWN, {})
        assert result is None


class TestExtractSpecsWithMock:
    def test_mock_adapter_returns_result(self):
        result = extract_specs(MockAdapter(), "some markdown", {}, url=SWIFT6_URL)
        assert result is not None
        assert result.model_name == "Swift 6"

    def test_mock_adapter_preserves_data(self):
        result = extract_specs(MockAdapter(), "some markdown", {}, url=SWIFT6_URL)
        xs = next(s for s in result.sizes if s.size_label == "XS")
        assert_size_specs(xs, SWIFT6_EXPECTED["XS"], "XS")

    def test_mock_adapter_size_count(self):
        result = extract_specs(MockAdapter(), "some markdown", {}, url=SWIFT6_URL)
        assert len(result.sizes) == 2  # MockAdapter only returns XS and S


class TestExtractSpecsFailingAdapter:
    def test_failing_adapter_falls_back_to_markdown(self):
        result = extract_specs(
            FailingAdapter(), SWIFT6_MARKDOWN, {}, url=SWIFT6_URL
        )
        assert result is not None
        assert len(result.sizes) == 5

    def test_failing_adapter_fallback_strict_values(self):
        result = extract_specs(
            FailingAdapter(), SWIFT6_MARKDOWN, {}, url=SWIFT6_URL
        )
        s = next(s for s in result.sizes if s.size_label == "S")
        assert_size_specs(s, SWIFT6_EXPECTED["S"], "S")
