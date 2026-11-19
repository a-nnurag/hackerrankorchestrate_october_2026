"""Free-tier rate limiting for the Groq client.

Groq limits each model per organisation on four axes: requests per minute (RPM), requests per day (RPD), tokens per
minute (TPM) and tokens per day (TPD); a request over any of them gets HTTP 429.  The base limits published for the
Developer plan at the time of writing are 30 RPM, 1,000 RPD, 8,000 TPM and 200,000 TPD for openai/gpt-oss-120b,
gpt-oss-20b and qwen/qwen3.8-27b; the limits of your own organisation are on console.groq.com/settings/limits and can
be set with GHOST_GROQ_LIMITS="rpm=30,rpd=1000,tpm=8000,tpd=200000".  The client therefore
  * keeps a rolling 60-second window of requests and tokens and sleeps until the next call fits (SAFETY = 80% of
    the limit), reserving the prompt estimate plus max_completion_tokens before the call and correcting it with the
    real usage afterwards (reasoning tokens of gpt-oss count as output);
  * counts requests and tokens per UTC day in code/.cache/groq_budget.json (and the last minute, so a quick restart
    cannot overshoot) and stops cleanly, with budget_exhausted set, before the daily budget (90%) is spent;
  * reads x-ratelimit-remaining-tokens / -reset-tokens / -remaining-requests and retry-after, and waits when the
    server says the minute is nearly used up;
  * on 429 waits for retry-after (else exponential backoff with jitter) and slows its own pacing;
  * caches every answer on disk so reruns cost nothing, and never sends a request that alone exceeds TPM.

This module holds the limiter (RateLimiter) and the duration parser; the client is in groq.py.  Time is read and
slept only through an injectable Clock, so tests can simulate minutes and days instantly.
"""

from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Callable, Mapping
from typing import Any

from .cache import CACHE_DIR
from .clock import Clock
from .groq_models import GROQ_DEFAULT_LIMITS

SAFETY_MINUTE = 0.80
SAFETY_DAY = 0.90
_UNIT_SECONDS = {"h": 3600, "m": 60, "s": 1, "ms": 0.001}


def parse_duration(text: Any) -> float | None:
    """'2m59.56s' -> 179.56, '7.66s' -> 7.66, '1h2m' -> 3720, '30ms' -> 0.03; None if unparsable."""
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        pass
    total, found = 0.0, False
    for num, unit in re.findall(r"([\d.]+)(ms|h|m|s)", str(text)):
        found = True
        total += float(num) * _UNIT_SECONDS[unit]
    return total if found else None


def _limits_from_env(limits: Mapping[str, int] | None) -> dict[str, int]:
    """Defaults, then the `limits` argument, then GHOST_GROQ_LIMITS="rpm=..,tpm=.." from the environment."""
    lim = dict(GROQ_DEFAULT_LIMITS)
    lim.update(limits or {})
    for part in os.environ.get("GHOST_GROQ_LIMITS", "").split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            if k.strip() in lim and v.strip().isdigit():
                lim[k.strip()] = int(v)
    return lim


class RateLimiter:
    """Sliding 60-second window for requests and tokens, plus a persisted per-day budget, per model."""

    def __init__(
        self,
        model: str,
        limits: Mapping[str, int] | None = None,
        path: str | None = None,
        clock: Clock | None = None,
    ):
        self.model, self.lim = model, _limits_from_env(limits)
        self.clock = clock or Clock()
        self.path = path or os.path.join(CACHE_DIR, "groq_budget.json")
        self.window: list[tuple[float, int]] = []  # (time, tokens) of calls in the last minute
        self.day = ""  # UTC date the counters belong to
        self.req_day = 0
        self.tok_day = 0
        self.slow = 1.0  # >1 after a 429: stretches the pacing
        self.next_ok = 0.0  # earliest time the server's headers allow the next call
        self.waited = 0.0
        self._load()

    # ---- persistence
    def _today(self) -> str:
        return time.strftime("%Y-%m-%d", time.gmtime(self.clock.now()))

    def _load(self) -> None:
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f).get(self.model, {})
        except (OSError, ValueError):
            data = {}
        self.day = data.get("day", "")
        if self.day == self._today():
            self.req_day, self.tok_day = data.get("requests", 0), data.get("tokens", 0)
        else:
            self.day, self.req_day, self.tok_day = self._today(), 0, 0
        self.window = [tuple(x) for x in data.get("window", []) if self.clock.now() - x[0] < 60]

    def _save(self) -> None:
        try:
            all_data = {}
            if os.path.exists(self.path):
                with open(self.path, encoding="utf-8") as f:
                    all_data = json.load(f)
            all_data[self.model] = {
                "day": self.day,
                "requests": self.req_day,
                "tokens": self.tok_day,
                "window": [list(x) for x in self.window],
            }
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(all_data, f)
        except (OSError, ValueError):
            pass

    # ---- admission
    def fits_ever(self, tokens: int) -> bool:
        """False when a single call of `tokens` could never fit the per-minute token limit."""
        return tokens <= self.lim["tpm"] * SAFETY_MINUTE

    def daily_ok(self, tokens: int) -> bool:
        """True while one more call of `tokens` stays inside the daily request and token budgets."""
        if self.day != self._today():
            self.day, self.req_day, self.tok_day = self._today(), 0, 0
        return (
            self.req_day + 1 <= self.lim["rpd"] * SAFETY_DAY and self.tok_day + tokens <= self.lim["tpd"] * SAFETY_DAY
        )

    def _token_wait(self, now: float, tokens: int, n_tok: int) -> float | None:
        """Seconds until enough of the window expires to make room for `tokens`, or None if it already fits."""
        cap = self.lim["tpm"] * SAFETY_MINUTE / self.slow
        if n_tok + tokens <= cap:
            return None
        need, acc = n_tok + tokens - cap, 0
        for ts, tk in self.window:
            acc += tk
            if acc >= need:
                return ts + 60 - now
        return None

    def _wait_needed(self, tokens: int) -> float:
        """Prune the window and return how long to wait before a call of `tokens` fits (<= 0 means now)."""
        now = self.clock.now()
        self.window = [x for x in self.window if now - x[0] < 60]
        n_tok = sum(x[1] for x in self.window)
        waits = [self.next_ok - now]
        if len(self.window) + 1 > self.lim["rpm"] * SAFETY_MINUTE / self.slow:
            waits.append(self.window[0][0] + 60 - now)
        token_wait = self._token_wait(now, tokens, n_tok)
        if token_wait is not None:
            waits.append(token_wait)
        return max(waits)

    def acquire(self, tokens: int) -> bool:
        """Block until a call of `tokens` (reserved) fits every limit; False if it never can or the day is spent."""
        if not self.fits_ever(tokens) or not self.daily_ok(tokens):
            return False
        while True:
            wait = self._wait_needed(tokens)
            if wait <= 0:
                break
            wait = min(wait + 0.05, 65)
            self.waited += wait
            self.clock.sleep(wait)
        self.window.append((self.clock.now(), tokens))
        self.req_day += 1
        self.tok_day += tokens
        self._save()
        return True

    def correct(self, reserved: int, actual: int) -> None:
        """Replace the reservation of the last call by the real token count."""
        if self.window:
            ts, _ = self.window[-1]
            self.window[-1] = (ts, actual)
        self.tok_day += actual - reserved
        self._save()

    def _hint_tokens(self, get: Callable[[str], Any], next_tokens: int) -> None:
        rem_tok = get("x-ratelimit-remaining-tokens")
        if rem_tok is not None and float(rem_tok) < next_tokens:
            reset = parse_duration(get("x-ratelimit-reset-tokens"))
            if reset:
                self.next_ok = max(self.next_ok, self.clock.now() + reset + 0.1)

    def _hint_requests(self, get: Callable[[str], Any]) -> None:
        rem_req = get("x-ratelimit-remaining-requests")
        lim_req = get("x-ratelimit-limit-requests")
        if rem_req is not None and lim_req is not None:
            used = int(float(lim_req)) - int(float(rem_req))
            self.req_day = max(self.req_day, used)

    def server_hints(self, headers: Any, next_tokens: int) -> None:
        """Use the rate-limit headers: wait when the server says the minute's tokens are nearly spent."""
        get = headers.get if headers is not None else (lambda _key: None)
        try:
            self._hint_tokens(get, next_tokens)
            self._hint_requests(get)
        except (TypeError, ValueError):
            pass

    def throttle(self) -> None:
        """After a 429: stretch our own pacing, up to 4x."""
        self.slow = min(self.slow * 1.5, 4.0)

    def relax(self) -> None:
        """After a success: let the pacing recover towards the nominal rate."""
        self.slow = max(1.0, self.slow * 0.9)
