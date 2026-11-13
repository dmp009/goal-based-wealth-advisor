"""Provider-agnostic LLM client protocol and the Anthropic implementation."""

from __future__ import annotations

import os
from typing import Protocol

from wealthadvisor.config import load_settings

TOOL_NAME = "write_document"
MAX_TOKENS = 4000
_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "Short document title."},
        "body": {"type": "string", "description": "The document body in Markdown."},
    },
    "required": ["title", "body"],
}


class LLMClient(Protocol):
    def write_document(self, prompt: str) -> dict:
        """Return ``{"title": str, "body": str}``."""
        ...


class AnthropicClient:
    def __init__(self, model: str | None = None):
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set; cannot call the Anthropic API")
        import anthropic

        self._client = anthropic.Anthropic(api_key=key)
        self._model = model or load_settings().llm_model

    def write_document(self, prompt: str) -> dict:
        resp = self._client.messages.create(
            model=self._model,
            max_tokens=MAX_TOKENS,
            tools=[
                {
                    "name": TOOL_NAME,
                    "description": "Write the document (title and Markdown body).",
                    "input_schema": _SCHEMA,
                }
            ],
            tool_choice={"type": "tool", "name": TOOL_NAME},
            messages=[{"role": "user", "content": prompt}],
        )
        if getattr(resp, "stop_reason", None) == "max_tokens":
            raise RuntimeError(
                "Anthropic response hit max_tokens; the document is truncated and was discarded"
            )
        for block in resp.content:
            if getattr(block, "type", None) == "tool_use":
                data = dict(block.input)
                if not isinstance(data.get("title"), str) or not isinstance(data.get("body"), str):
                    raise RuntimeError("write_document returned no title/body strings")
                return data
        raise RuntimeError("Anthropic response contained no tool_use block")
