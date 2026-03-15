"""
Ollama LLM adapter — local extraction via Ollama + Qwen2.5:3B.

Phase 1 primary extraction strategy. Connects to a local Ollama server
and uses structured JSON output.
"""

from __future__ import annotations

import json
import logging

import httpx

from .base import LLMAdapter

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "qwen2.5:3b"
DEFAULT_ENDPOINT = "http://localhost:11434"


class OllamaAdapter(LLMAdapter):
    """Local LLM extraction via Ollama."""

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        endpoint: str = DEFAULT_ENDPOINT,
        timeout: float = 300.0,
    ):
        self.model = model
        self.endpoint = endpoint.rstrip("/")
        self.timeout = timeout

    def extract(self, markdown: str, schema: dict, instructions: str | None = None) -> dict:
        """Send markdown + schema to Ollama and parse the JSON response."""
        prompt = self._build_prompt(markdown, schema, instructions)

        response = httpx.post(
            f"{self.endpoint}/api/chat",
            json={
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "format": "json",
                "stream": False,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()

        content = response.json()["message"]["content"]
        return json.loads(content)

    def is_available(self) -> bool:
        """Check if Ollama server is running and model is available."""
        try:
            resp = httpx.get(f"{self.endpoint}/api/tags", timeout=5.0)
            resp.raise_for_status()
            models = [m["name"] for m in resp.json().get("models", [])]
            # Match with or without tag suffix (e.g. "qwen2.5:3b" matches "qwen2.5:3b")
            available = any(
                m == self.model or m.startswith(f"{self.model}:")
                for m in models
            )
            if not available:
                logger.warning(
                    "Ollama running but model '%s' not found. "
                    "Available: %s. Pull with: ollama pull %s",
                    self.model,
                    models,
                    self.model,
                )
            return available
        except (httpx.HTTPError, httpx.ConnectError):
            logger.warning("Ollama server not reachable at %s", self.endpoint)
            return False

    def _build_prompt(
        self,
        markdown: str,
        schema: dict,
        instructions: str | None = None,
    ) -> str:
        """Build the extraction prompt with a concrete example for small LLMs.

        Small models (3B) follow concrete examples better than abstract JSON
        schemas. We provide one complete example rather than the full Pydantic
        JSON schema.
        """
        example = json.dumps({
            "model_name": "Rush 6",
            "category": "paraglider",
            "target_use": "xc",
            "cell_count": 62,
            "sizes": [
                {
                    "size_label": "S",
                    "flat_area_m2": 22.54,
                    "flat_span_m": 11.34,
                    "flat_aspect_ratio": 5.7,
                    "proj_area_m2": 19.11,
                    "proj_span_m": 8.94,
                    "proj_aspect_ratio": 4.18,
                    "wing_weight_kg": 4.74,
                    "ptv_min_kg": 65,
                    "ptv_max_kg": 85,
                    "certification": "B"
                }
            ]
        }, indent=2)

        rules = (
            "RULES:\n"
            "- Extract ONLY the technical specs table — no marketing text\n"
            "- model_name: the paraglider model name (e.g. 'Rush 6', 'Moxie')\n"
            "- sizes: one entry per size column in the specs table\n"
            "- All numeric values must be plain numbers (no units, no text)\n"
            "- 'Certified Weight Range' or 'In-Flight Weight Range' 65-85 → "
            "ptv_min_kg: 65, ptv_max_kg: 85\n"
            "- 'Glider Weight' or 'Wing Weight' → wing_weight_kg\n"
            "- 'EN/LTF' or 'Certification' → certification (just the letter: A, B, C, D, or CCC)\n"
            "- 'Number of Cells' → cell_count (top-level, not per-size)\n"
            "- If a field is not in the table, omit it\n"
            "- Return ONLY the JSON object, no other text\n"
        )

        if instructions:
            return (
                f"{instructions}\n\n"
                f"{rules}\n"
                f"Example output format:\n```json\n{example}\n```\n\n"
                f"MARKDOWN CONTENT:\n\n{markdown}"
            )

        return (
            "Extract the paraglider technical specifications from this page.\n\n"
            f"{rules}\n"
            f"Example output format:\n```json\n{example}\n```\n\n"
            f"MARKDOWN CONTENT:\n\n{markdown}"
        )
