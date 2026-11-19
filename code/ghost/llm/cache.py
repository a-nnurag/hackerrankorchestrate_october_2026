"""Small helpers shared by the LLM clients: the on-disk cache location, JSON cache files and cache keys."""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(HERE)), ".cache")
CACHE_PATH = os.path.join(CACHE_DIR, "llm_cache.json")


def cache_key(*parts: Any) -> str:
    """SHA-256 of the JSON encoding of the request parts (model, prompts, schema, ...)."""
    return hashlib.sha256(json.dumps(list(parts), sort_keys=True).encode()).hexdigest()


def load_cache(path: str) -> dict[str, Any]:
    """Read a JSON cache file; an absent or unreadable file gives an empty cache."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_cache(path: str, data: dict[str, Any], indent: int | None = None) -> None:
    """Write a JSON cache file, creating its directory."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=indent, sort_keys=True)
