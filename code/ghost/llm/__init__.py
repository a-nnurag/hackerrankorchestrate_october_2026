"""LLM helpers: an optional Ollama client, an evaluation-time Groq client and the guarded adjudicators.

The pipeline works without any of this; the adjudicators only decide cases the deterministic rules flag as
conflicting, and only with answers that validate against a schema and quote the input verbatim.
"""

from __future__ import annotations

from .adjudicate import adjudicate_ownership, adjudicate_request, adjudicate_shared_context, quote_is_verbatim
from .cache import CACHE_PATH
from .clock import Clock
from .factory import make_llm
from .groq import GroqLLM
from .groq_models import (
    GROQ_DEFAULT_LIMITS,
    GROQ_PRICES,
    GROQ_REASONING,
    GROQ_STRICT_SCHEMA,
    GROQ_VISION,
    estimate_tokens,
)
from .ollama import DEFAULT_HOST, DEFAULT_MODEL, LLM
from .prompts import CONTEXT_SYSTEM, DEFAULT_VARIANT, OWNERSHIP_SYSTEM, VARIANTS
from .ratelimit import RateLimiter, parse_duration

__all__ = [
    "CACHE_PATH",
    "CONTEXT_SYSTEM",
    "DEFAULT_HOST",
    "DEFAULT_MODEL",
    "DEFAULT_VARIANT",
    "GROQ_DEFAULT_LIMITS",
    "GROQ_PRICES",
    "GROQ_REASONING",
    "GROQ_STRICT_SCHEMA",
    "GROQ_VISION",
    "LLM",
    "OWNERSHIP_SYSTEM",
    "VARIANTS",
    "Clock",
    "GroqLLM",
    "RateLimiter",
    "adjudicate_ownership",
    "adjudicate_request",
    "adjudicate_shared_context",
    "estimate_tokens",
    "make_llm",
    "parse_duration",
    "quote_is_verbatim",
]
