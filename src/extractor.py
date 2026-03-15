"""
Extraction logic — schema definition and LLM prompt construction.

Bridges the LLM adapter and the Pydantic models. Responsible for:
  1. Building the JSON schema from Pydantic models
  2. Injecting manufacturer-specific llm_hints from YAML config
  3. Parsing adapter output into validated ExtractionResult
  4. Truncating markdown to spec-relevant section for small LLMs
"""

from __future__ import annotations

import logging
import re
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
        manufacturer_name = config.get("manufacturer", {}).get("name")
        result = _extract_via_markdown(markdown, url, manufacturer_name=manufacturer_name)

    return result


def _extract_via_llm(
    adapter: LLMAdapter,
    markdown: str,
    config: dict,
    url: str | None = None,
) -> Optional[ExtractionResult]:
    """Try LLM-based extraction.

    Truncates markdown to the spec-relevant section (~5K chars max) so small
    LLMs like Qwen2.5:3B can handle it within their effective context window.
    """
    schema = get_extraction_schema()

    instructions = config.get("extraction", {}).get("llm", {}).get("prompt")

    llm_hints = config.get("extraction", {}).get("llm_hints")
    if llm_hints:
        schema["description"] = (
            schema.get("description", "")
            + f"\n\nManufacturer-specific hints:\n{llm_hints}"
        )

    # Truncate to spec section — small LLMs choke on 30K+ char pages
    trimmed = _extract_spec_section(markdown)
    logger.info(
        "LLM input: %d → %d chars (%.0f%% reduction)",
        len(markdown), len(trimmed),
        100 * (1 - len(trimmed) / len(markdown)) if markdown else 0,
    )

    try:
        raw = adapter.extract(trimmed, schema, instructions=instructions)
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


# ── Markdown truncation ──────────────────────────────────────────────────────

# Context budget: keep enough for the spec table + surrounding context
_MAX_LLM_CHARS = 6000
_CONTEXT_BEFORE = 500  # chars before spec heading for model name context


def _extract_spec_section(markdown: str) -> str:
    """Extract the specifications section from page markdown.

    Small LLMs (3B params) can't handle 30K+ char inputs effectively.
    This finds the spec table and returns just that section with a small
    amount of preceding context (for model name inference).

    Falls back to the full markdown (truncated to _MAX_LLM_CHARS) if no
    spec heading is found.
    """
    lines = markdown.split("\n")

    # Find the spec heading
    spec_line = None
    for i, line in enumerate(lines):
        if re.match(r"^#+\s*specifications?\s*$", line.strip(), re.IGNORECASE):
            spec_line = i
            break

    if spec_line is not None:
        # Include some context before the heading (model name, product info)
        before_text = "\n".join(lines[:spec_line])
        if len(before_text) > _CONTEXT_BEFORE:
            before_text = before_text[-_CONTEXT_BEFORE:]

        spec_text = "\n".join(lines[spec_line:])
        combined = before_text + "\n" + spec_text

        if len(combined) > _MAX_LLM_CHARS:
            return combined[:_MAX_LLM_CHARS]
        return combined

    # No heading found — look for first pipe-delimited table
    table_start = None
    for i, line in enumerate(lines):
        if "|" in line and not re.match(r"^[\s|:-]+$", line.strip()):
            table_start = i
            break

    if table_start is not None:
        before_text = "\n".join(lines[:table_start])
        if len(before_text) > _CONTEXT_BEFORE:
            before_text = before_text[-_CONTEXT_BEFORE:]

        table_text = "\n".join(lines[table_start:])
        combined = before_text + "\n" + table_text

        if len(combined) > _MAX_LLM_CHARS:
            return combined[:_MAX_LLM_CHARS]
        return combined

    # Fallback: truncate from the start
    if len(markdown) > _MAX_LLM_CHARS:
        return markdown[:_MAX_LLM_CHARS]
    return markdown


def _extract_via_markdown(
    markdown: str,
    url: str | None = None,
    manufacturer_name: str | None = None,
) -> Optional[ExtractionResult]:
    """Try deterministic markdown table parsing."""
    if not url:
        logger.warning("Markdown parser requires a URL for model name inference")
        return None

    try:
        return parse_specs_from_markdown(markdown, url, manufacturer_name=manufacturer_name)
    except Exception:
        logger.exception("Markdown parser failed")
        return None
