"""
Abstract base class for LLM extraction adapters.

All LLM calls are routed through this interface. Switching models requires
only a config change — no pipeline code changes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class LLMAdapter(ABC):
    """Base interface for LLM extraction adapters."""

    @abstractmethod
    def extract(
        self,
        markdown: str,
        schema: dict,
        instructions: str | None = None,
    ) -> dict:
        """Extract structured data from markdown using the given JSON schema.

        Args:
            markdown: Rendered page content as markdown.
            schema: JSON schema describing the expected output structure.
            instructions: Optional manufacturer-specific extraction instructions.

        Returns:
            Parsed extraction result as a dict matching the schema.
        """

    @abstractmethod
    def is_available(self) -> bool:
        """Check if the adapter's backend is reachable and ready."""
