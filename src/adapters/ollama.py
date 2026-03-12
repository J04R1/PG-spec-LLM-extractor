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

    def extract(self, markdown: str, schema: dict) -> dict:
        """Send markdown + schema to Ollama and parse the JSON response."""
        prompt = self._build_prompt(markdown, schema)

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

    def _build_prompt(self, markdown: str, schema: dict) -> str:
        """Build the extraction prompt with schema and markdown content."""
        schema_str = json.dumps(schema, indent=2)
        return (
            "Extract the paraglider technical specifications from the following "
            "markdown content. Return a JSON object matching this schema:\n\n"
            f"```json\n{schema_str}\n```\n\n"
            "RULES:\n"
            "- Extract ONLY factual technical data (no marketing text)\n"
            "- All numeric values must be plain numbers (no units)\n"
            "- Return one entry per size in the specs table\n"
            "- If a field is not found, omit it from the output\n\n"
            "MARKDOWN CONTENT:\n\n"
            f"{markdown}"
        )
