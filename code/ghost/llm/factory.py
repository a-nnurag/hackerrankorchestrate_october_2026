"""Provider selection for the LLM clients."""

from __future__ import annotations

import os

from .groq import GroqLLM
from .ollama import LLM


def make_llm(provider: str | None = None, model: str | None = None) -> LLM | GroqLLM:
    """provider: ollama (default) or groq."""
    provider = (provider or os.environ.get("GHOST_LLM_PROVIDER", "ollama")).lower()
    return GroqLLM(model=model) if provider == "groq" else LLM(model=model)
