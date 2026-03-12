"""
Extraction logic — schema definition and LLM prompt construction.

Bridges the LLM adapter and the Pydantic models. Responsible for:
  1. Building the JSON schema from Pydantic models
  2. Injecting manufacturer-specific llm_hints from YAML config
  3. Parsing adapter output into validated ExtractionResult
"""

from __future__ import annotations

import logging
from typing import Optional

from .adapters.base import LLMAdapter
from .markdown_parser import parse_specs_from_markdown
from .models import ExtractionResult, SizeSpec

logger = logging.getLogger(__name__)


def get_extraction_schema() -> dict:
    """Return the JSON schema for LLM structured output."""
    return ExtractionResult.model_json_schema()


def extract_specs(
    adapter: LLMAdapter | None,
    markdown: str,
    config: dict,
    url: str | None = None,
) -> Optional[ExtractionResult]:
    """Extract paraglider specs from markdown using LLM with markdown fallback.

    Strategy:
      1. If an adapter is provided, try LLM extraction first.
      2. If LLM fails or no adapter, fall back to deterministic markdown parser.

    Args:
        adapter: An LLMAdapter implementation (Ollama, etc.), or None.
        markdown: Rendered page markdown content.
        config: Manufacturer YAML config dict (for llm_hints injection).
        url: Optional product URL to inject into the result.

    Returns:
        Validated ExtractionResult or None if both strategies fail.
    """
    result = None

    # Strategy 1: LLM extraction
    if adapter is not None:
        result = _extract_via_llm(adapter, markdown, config, url)

    # Strategy 2: Markdown parser fallback
    if result is None:
        if adapter is not None:
            logger.info("LLM extraction failed — trying markdown parser fallback")
        result = _extract_via_markdown(markdown, url)

    return result


def _extract_via_llm(
    adapter: LLMAdapter,
    markdown: str,
    config: dict,
    url: str | None = None,
) -> Optional[ExtractionResult]:
    """Try LLM-based extraction."""
    schema = get_extraction_schema()

    instructions = config.get("extraction", {}).get("llm", {}).get("prompt")

    llm_hints = config.get("extraction", {}).get("llm_hints")
    if llm_hints:
        schema["description"] = (
            schema.get("description", "")
            + f"\n\nManufacturer-specific hints:\n{llm_hints}"
        )

    try:
        raw = adapter.extract(markdown, schema, instructions=instructions)
        result = ExtractionResult.model_validate(raw)

        if url and not result.product_url:
            result.product_url = url

        logger.info(
            "LLM extracted: %s — %d sizes",
            result.model_name,
            len(result.sizes),
        )
        return result
    except Exception:
        logger.exception("LLM extraction failed")
        return None


def _extract_via_markdown(
    markdown: str,
    url: str | None = None,
) -> Optional[ExtractionResult]:
    """Try deterministic markdown table parsing."""
    if not url:
        logger.warning("Markdown parser requires a URL for model name inference")
        return None

    try:
        return parse_specs_from_markdown(markdown, url)
    except Exception:
        logger.exception("Markdown parser failed")
        return None
