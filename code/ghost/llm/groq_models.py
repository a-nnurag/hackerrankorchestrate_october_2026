"""Static facts about the Groq (OpenAI-compatible cloud API) models used for evaluation-time agents."""

from __future__ import annotations

import math

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
# USD per 1M tokens (input, output) from console.groq.com/docs/models when written; check before relying on it
GROQ_PRICES = {
    "openai/gpt-oss-20b": (0.075, 0.30),
    "openai/gpt-oss-120b": (0.15, 0.60),
    "qwen/qwen3.8-27b": (0.80, 4.00),
}
GROQ_STRICT_SCHEMA = {"openai/gpt-oss-20b", "openai/gpt-oss-120b", "qwen/qwen3.8-27b", "meta-models/muse-spark-open"}
GROQ_VISION = {"qwen/qwen3.8-27b", "meta-models/muse-spark-open"}
GROQ_REASONING = {"openai/gpt-oss-20b", "openai/gpt-oss-120b"}  # accept reasoning_effort / include_reasoning
GROQ_DEFAULT_LIMITS = {"rpm": 30, "rpd": 1000, "tpm": 8000, "tpd": 200000}
IMAGE_TOKENS = {"qwen/qwen3.8-27b": 2048, "meta-models/muse-spark-open": 1026}


def estimate_tokens(*texts: object, images: int = 0, model: str | None = None) -> int:
    """Conservative prompt estimate: 1 token per 3 characters plus a small overhead, images at the documented cost."""
    chars = sum(len(t) for t in texts if isinstance(t, str))
    return math.ceil(chars / 3.0) + 20 + images * IMAGE_TOKENS.get(model or "", 1100)
