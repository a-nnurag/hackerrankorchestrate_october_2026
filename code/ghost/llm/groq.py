"""Groq (OpenAI-compatible cloud API) chat client for evaluation-time agents.  The pipeline itself never needs it.

Pacing, daily budgets and 429 handling follow the free-tier design described in ratelimit.py; this module builds the
request, retries transient failures and caches answers on disk.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import random
import urllib.error
import urllib.request
from collections.abc import Mapping
from typing import Any

from .cache import CACHE_DIR, cache_key, load_cache, save_cache
from .clock import Clock
from .groq_models import GROQ_PRICES, GROQ_REASONING, GROQ_STRICT_SCHEMA, GROQ_URL, GROQ_VISION, estimate_tokens
from .ratelimit import RateLimiter, parse_duration

_RETRY_CODES = (429, 500, 502, 503)
_NETWORK_ERRORS = (urllib.error.URLError, OSError, ValueError, KeyError, IndexError)


class GroqLLM:
    """Same interface as LLM (chat_json) plus optional images.  The key is read from GROQ_API_KEY only.

    Data sent to Groq leaves this machine: use it for the fictional challenge data only, never for real personal data.
    After a call returns None check `budget_exhausted` (daily budget spent: stop, rerun tomorrow, progress is cached).
    """

    def __init__(
        self,
        model: str | None = None,
        timeout: int = 120,
        use_cache: bool = True,
        max_retries: int = 4,
        limits: Mapping[str, int] | None = None,
        budget_path: str | None = None,
        clock: Clock | None = None,
    ):
        self.model = model or os.environ.get("GHOST_GROQ_MODEL", "openai/gpt-oss-120b")
        self.host = GROQ_URL
        self.timeout = timeout
        self.max_retries = max_retries
        self.use_cache = use_cache
        self.usage = {
            "calls": 0,
            "cache_hits": 0,
            "prompt_tokens": 0,
            "output_tokens": 0,
            "failures": 0,
            "retries": 0,
            "waited_s": 0.0,
            "budget_stops": 0,
        }
        self.budget_exhausted = False
        self.clock = clock or Clock()
        self.limiter = RateLimiter(self.model, limits, budget_path, self.clock)
        self._cache_path = os.path.join(CACHE_DIR, "groq_cache.json")
        self._cache = load_cache(self._cache_path) if use_cache else {}

    @staticmethod
    def available() -> bool:
        """True when GROQ_API_KEY is set in the environment."""
        return bool(os.environ.get("GROQ_API_KEY"))

    def estimated_cost(self) -> float:
        """USD cost of the tokens used so far, from the price table (0 for unknown models)."""
        pin, pout = GROQ_PRICES.get(self.model, (0.0, 0.0))
        return (self.usage["prompt_tokens"] * pin + self.usage["output_tokens"] * pout) / 1e6

    def _build_body(
        self, system: str, user: str, schema: dict[str, Any], images: list[bytes] | None, max_tokens: int
    ) -> dict[str, Any] | None:
        """The request body, or None when images are sent to a model without vision input."""
        content: Any = user
        if images:
            if self.model not in GROQ_VISION:
                return None
            content = [{"type": "text", "text": user}] + [
                {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(i).decode()}}
                for i in images
            ]
        body: dict[str, Any] = {
            "model": self.model,
            "temperature": 0,
            "max_completion_tokens": max_tokens,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}],
        }
        if self.model in GROQ_REASONING:
            body["reasoning_effort"] = "low"  # reasoning tokens count against TPM: keep them small
            body["include_reasoning"] = False
        if self.model in GROQ_STRICT_SCHEMA:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "answer", "strict": True, "schema": schema},
            }
        else:
            body["response_format"] = {"type": "json_object"}
            body["messages"][0]["content"] += "\nReturn JSON matching this schema: " + json.dumps(schema)
        return body

    def _store(self, key: str, out: Any) -> None:
        self._cache[key] = out
        if self.use_cache:
            save_cache(self._cache_path, self._cache)

    def _attempt(self, req: urllib.request.Request, reserved: int, key: str) -> Any:
        """Send one request and book its usage; raises on HTTP and parse errors (handled by the retry loop)."""
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            resp = json.loads(r.read().decode("utf-8"))
            headers = getattr(r, "headers", None)
        out = json.loads(resp["choices"][0]["message"]["content"])
        u = resp.get("usage", {})
        actual = u.get("total_tokens") or (u.get("prompt_tokens", 0) + u.get("completion_tokens", 0)) or reserved
        self.limiter.correct(reserved, actual)
        self.limiter.server_hints(headers, reserved)
        self.limiter.relax()
        self.usage["calls"] += 1
        self.usage["prompt_tokens"] += u.get("prompt_tokens", 0)
        self.usage["output_tokens"] += u.get("completion_tokens", 0)
        self._store(key, out)
        return out

    def _retry_after_http(self, err: urllib.error.HTTPError, attempt: int) -> bool:
        """After an HTTP error: wait and return True when the request is worth retrying."""
        if err.code not in _RETRY_CODES or attempt >= self.max_retries:
            return False
        ra = parse_duration(err.headers.get("retry-after")) if err.headers is not None else None
        wait = (ra if ra else min(2**attempt * 2, 30)) + random.uniform(0, 0.5)
        if err.code == 429:
            self.limiter.throttle()
        self.usage["retries"] += 1
        self.usage["waited_s"] += wait
        self.clock.sleep(wait)
        return True

    def _retry_after_network(self, attempt: int) -> bool:
        """After a network or parse error: back off and return True while retries remain."""
        if attempt >= self.max_retries:
            return False
        self.usage["retries"] += 1
        self.clock.sleep(min(2**attempt, 10))
        return True

    def _admit(self, reserved: int) -> bool:
        """Wait until the rate limiter admits the call; False (usage booked) when it can never be sent."""
        if not self.limiter.fits_ever(reserved):
            self.usage["failures"] += 1  # a single request larger than the per-minute limit can never be sent
            return False
        before = self.limiter.waited
        if not self.limiter.acquire(reserved):
            self.budget_exhausted = True
            self.usage["budget_stops"] += 1
            return False
        self.usage["waited_s"] += self.limiter.waited - before
        return True

    def _try_once(self, req: urllib.request.Request, reserved: int, key: str, attempt: int) -> tuple[bool, Any]:
        """-> (finished, result): finished is False when the failure is transient and the caller should retry."""
        try:
            return True, self._attempt(req, reserved, key)
        except urllib.error.HTTPError as e:
            self.limiter.correct(reserved, 0)  # a rejected call did not use the tokens
            retry = self._retry_after_http(e, attempt)
        except _NETWORK_ERRORS:
            self.limiter.correct(reserved, 0)
            retry = self._retry_after_network(attempt)
        if retry:
            return False, None
        self.usage["failures"] += 1
        return True, None

    def _encode(
        self, system: str, user: str, schema: dict[str, Any], images: list[bytes] | None, max_tokens: int
    ) -> tuple[bytes, dict[str, str]] | None:
        """The encoded request body and headers, or None without an API key or for images on a text-only model."""
        api_key = os.environ.get("GROQ_API_KEY")
        body = self._build_body(system, user, schema, images, max_tokens) if api_key else None
        if not api_key or body is None:
            return None
        headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer " + api_key,
            "User-Agent": "ghost-data-audit/1.0",
        }
        return json.dumps(body).encode(), headers

    def chat_json(
        self,
        system: str,
        user: str,
        schema: dict[str, Any],
        num_ctx: int | None = None,
        images: list[bytes] | None = None,
        max_tokens: int = 700,
    ) -> Any:
        """Return the parsed JSON object or None.  `images` is a list of raw PNG/JPEG bytes (vision models only)."""
        key = cache_key(self.model, system, user, schema, [hashlib.sha256(i).hexdigest() for i in images or []])
        if key in self._cache:
            self.usage["cache_hits"] += 1
            return self._cache[key]
        prepared = self._encode(system, user, schema, images, max_tokens)
        if prepared is None:
            self.usage["failures"] += 1
            return None
        data, headers = prepared
        reserved = estimate_tokens(system, user, images=len(images or []), model=self.model) + max_tokens
        for attempt in range(self.max_retries + 1):
            if not self._admit(reserved):
                return None
            req = urllib.request.Request(self.host, data=data, headers=headers)
            finished, out = self._try_once(req, reserved, key, attempt)
            if finished:
                return out
        return None
