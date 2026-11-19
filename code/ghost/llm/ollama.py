"""Optional local LLM client (Ollama).  The pipeline works without it; it only adjudicates cases the
deterministic rules flag as conflicting.

Safety design
    * The model never decides alone: its answer must validate against a schema and every quoted
      span must appear verbatim in the input, otherwise the answer is discarded.
    * Untrusted text (request_text, evidence) is passed as data inside tags; the system prompt says
      it must never be followed as instructions.
    * temperature 0, thinking disabled, small context: deterministic enough and fits a 6 GB GPU.
    * Responses are cached on disk (key = model + prompt + schema), so reruns make no calls.
    * Usage (calls, prompt and output tokens) is accumulated for evaluation/usage_report.md.

Configuration (environment variables)
    GHOST_LLM            "off" to disable (default: on when the Ollama server answers)
    GHOST_LLM_MODEL      default qwen3.5:4b (about 3.3 GB, fits a 6 GB card with room for context)
    GHOST_OLLAMA_HOST    default http://localhost:11434
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from .cache import CACHE_PATH, cache_key, load_cache, save_cache

DEFAULT_MODEL = "qwen3.5:4b"
DEFAULT_HOST = "http://localhost:11434"


class LLM:
    """Ollama chat client returning schema-constrained JSON, with an on-disk response cache and usage counters."""

    def __init__(self, model: str | None = None, host: str | None = None, timeout: int = 120, use_cache: bool = True):
        self.model = model or os.environ.get("GHOST_LLM_MODEL", DEFAULT_MODEL)
        self.host = (host or os.environ.get("GHOST_OLLAMA_HOST", DEFAULT_HOST)).rstrip("/")
        self.timeout = timeout
        self.use_cache = use_cache
        self.usage = {"calls": 0, "cache_hits": 0, "prompt_tokens": 0, "output_tokens": 0, "failures": 0}
        self._cache = load_cache(CACHE_PATH) if use_cache else {}

    @staticmethod
    def available(host: str | None = None, timeout: float = 2) -> bool:
        """True when the Ollama server answers (and GHOST_LLM is not "off")."""
        if os.environ.get("GHOST_LLM", "").lower() == "off":
            return False
        host = (host or os.environ.get("GHOST_OLLAMA_HOST", DEFAULT_HOST)).rstrip("/")
        try:
            with urllib.request.urlopen(host + "/api/tags", timeout=timeout) as r:
                return r.status == 200
        except (urllib.error.URLError, OSError, ValueError):
            return False

    def _save_cache(self) -> None:
        if self.use_cache:
            save_cache(CACHE_PATH, self._cache, indent=0)

    def chat_json(self, system: str, user: str, schema: dict[str, Any], num_ctx: int = 2048) -> Any:
        """Return the parsed JSON object, or None on any failure (caller falls back to rules)."""
        key = cache_key(self.model, system, user, schema)
        if key in self._cache:
            self.usage["cache_hits"] += 1
            return self._cache[key]
        body = {
            "model": self.model,
            "stream": False,
            "think": False,
            "format": schema,
            "options": {"temperature": 0, "seed": 7, "num_ctx": num_ctx, "num_predict": 300},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        req = urllib.request.Request(
            self.host + "/api/chat", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                resp = json.loads(r.read().decode("utf-8"))
            out = json.loads(resp["message"]["content"])
        except (urllib.error.URLError, OSError, ValueError, KeyError):
            self.usage["failures"] += 1
            return None
        self.usage["calls"] += 1
        self.usage["prompt_tokens"] += resp.get("prompt_eval_count", 0)
        self.usage["output_tokens"] += resp.get("eval_count", 0)
        self._cache[key] = out
        self._save_cache()
        return out
