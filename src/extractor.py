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
from .models import ExtractionResult, SizeSpec

logger = logging.getLogger(__name__)


def get_extraction_schema() -> dict:
    """Return the JSON schema for LLM structured output."""
    return ExtractionResult.model_json_schema()


def extract_specs(
    adapter: LLMAdapter,
    markdown: str,
    config: dict,
) -> Optional[ExtractionResult]:
    """Extract paraglider specs from markdown using the given LLM adapter.

    Args:
        adapter: An LLMAdapter implementation (Ollama, etc.)
        markdown: Rendered page markdown content.
        config: Manufacturer YAML config dict (for llm_hints injection).

    Returns:
        Validated ExtractionResult or None if extraction fails.
    """
    schema = get_extraction_schema()

    # Inject manufacturer-specific hints into the schema description if present
    llm_hints = config.get("extraction", {}).get("llm_hints")
    if llm_hints:
        schema["description"] = (
            schema.get("description", "")
            + f"\n\nManufacturer-specific hints:\n{llm_hints}"
        )

    try:
        raw = adapter.extract(markdown, schema)
        result = ExtractionResult.model_validate(raw)
        logger.info(
            "Extracted: %s — %d sizes",
            result.model_name,
            len(result.sizes),
        )
        return result
    except Exception:
        logger.exception("Extraction failed")
        return None
