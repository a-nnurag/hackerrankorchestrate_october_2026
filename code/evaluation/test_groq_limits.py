"""Offline simulation of the Groq free-tier limits (fake clock, fake HTTP: no network, no key, no waiting).

    python code/evaluation/test_groq_limits.py

Checks that the client never exceeds, in any sliding 60-second window, 80% of the requests-per-minute or
tokens-per-minute limit; stops before the daily budget; survives a restart; honours retry-after and the
x-ratelimit headers; and never sends a request that could not fit.
"""

import io
import json
import os
import sys
import tempfile
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from ghost import llm as groq  # noqa: E402

START = 1_800_000_000.0


class FakeClock(groq.Clock):
    """Simulated time: sleeping advances the clock instantly."""

    def __init__(self, t=START):
        self.t = t

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += s


class Resp(io.BytesIO):
    def __init__(self, payload, headers):
        super().__init__(payload)
        self.headers = headers

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class Server:
    """Fake endpoint: records (time, reserved tokens, body) per request and plays a script of events."""

    def __init__(self, clock, tokens_per_call=300, script=None, headers=None):
        self.clock, self.tokens, self.script, self.headers = clock, tokens_per_call, list(script or []), headers or {}
        self.calls = []

    def __call__(self, req, timeout=None):
        body = json.loads(req.data)
        self.calls.append((self.clock.now(), self.tokens, body))
        if self.script:
            ev = self.script.pop(0)
            if ev is not None:
                raise urllib.error.HTTPError(
                    req.full_url, ev["code"], "limit", ev.get("headers", {}), io.BytesIO(b"{}")
                )
        payload = json.dumps(
            {
                "choices": [{"message": {"content": json.dumps({"ok": True})}}],
                "usage": {"prompt_tokens": self.tokens - 20, "completion_tokens": 20, "total_tokens": self.tokens},
            }
        ).encode()
        return Resp(payload, self.headers)


def window_max(times_vals, width=60.0):
    """Largest sum of values inside any sliding window of `width` seconds."""
    best = 0
    for i, (t0, _v) in enumerate(times_vals):
        best = max(best, sum(v for t, v in times_vals[i:] if t - t0 < width))
    return best


def make(model="openai/gpt-oss-120b", limits=None, clock=None, server=None, path=None):
    urllib.request.urlopen = server
    return groq.GroqLLM(
        model=model, use_cache=False, limits=limits, budget_path=path or tempfile.mktemp(suffix=".json"), clock=clock
    )


def check(name, ok, detail=""):
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f"   ({detail})" if detail else ""))
    return 0 if ok else 1


def test_rpm():
    """1  requests per minute: 100 small calls."""
    c = FakeClock()
    s = Server(c, tokens_per_call=60)
    g = make(clock=c, server=s)
    for i in range(100):
        g.chat_json("s", f"u{i}", {}, max_tokens=40)
    peak = window_max([(t, 1) for t, _, _ in s.calls])
    return check(
        "RPM: never more than 80% of 30 requests in any 60 s",
        len(s.calls) == 100 and peak <= 24,
        f"{len(s.calls)} calls, peak {peak} per minute, simulated {c.t - START:.0f} s",
    )


def test_tpm():
    """2  tokens per minute: 3,000-token calls against 8,000 TPM."""
    c = FakeClock()
    s = Server(c, tokens_per_call=3000)
    g = make(clock=c, server=s)
    for i in range(12):
        g.chat_json("s", f"u{i}", {}, max_tokens=2900)
    peak = window_max([(t, tk) for t, tk, _ in s.calls])
    return check(
        "TPM: never more than 80% of 8,000 tokens in any 60 s",
        len(s.calls) == 12 and peak <= 6400,
        f"{len(s.calls)} calls, peak {peak} tokens per minute, simulated {c.t - START:.0f} s",
    )


def test_daily_budget():
    """3  daily budget: 10 requests a day, then stop; a restart remembers; the next day resets."""
    c = FakeClock()
    path = tempfile.mktemp(suffix=".json")
    s = Server(c, tokens_per_call=100)
    g = make(clock=c, server=s, limits={"rpd": 10}, path=path)
    answers = [g.chat_json("s", f"u{i}", {}, max_tokens=50) for i in range(12)]
    bad = check(
        "daily budget: stops at 90% of the daily requests",
        sum(a is not None for a in answers) == 9 and g.budget_exhausted,
        f"{sum(a is not None for a in answers)} answered",
    )
    n_before = len(s.calls)
    g2 = make(clock=c, server=s, limits={"rpd": 10}, path=path)
    r = g2.chat_json("s", "again", {}, max_tokens=50)
    bad += check(
        "daily budget survives a restart (no request sent)",
        r is None and g2.budget_exhausted and len(s.calls) == n_before,
    )
    c.t += 86400
    g3 = make(clock=c, server=s, limits={"rpd": 10}, path=path)
    bad += check("daily budget resets the next UTC day", g3.chat_json("s", "tomorrow", {}, max_tokens=50) is not None)
    return bad


def test_retry_after():
    """4  429 with retry-after: wait at least that long, slow down afterwards."""
    c = FakeClock()
    s = Server(c, script=[{"code": 429, "headers": {"retry-after": "7"}}, None])
    g = make(clock=c, server=s)
    out = g.chat_json("s", "u", {}, max_tokens=40)
    gap = s.calls[1][0] - s.calls[0][0]
    return check(
        "429: waits for retry-after, then succeeds, pacing slowed",
        out is not None and gap >= 7 and g.limiter.slow > 1.0,
        f"gap {gap:.1f} s",
    )


def test_header_hint():
    """5  header hint: server says 10 tokens left, resets in 12 s."""
    c = FakeClock()
    s = Server(c, headers={"x-ratelimit-remaining-tokens": "10", "x-ratelimit-reset-tokens": "12s"})
    g = make(clock=c, server=s)
    g.chat_json("s", "one", {}, max_tokens=40)
    g.chat_json("s", "two", {}, max_tokens=40)
    return check(
        "headers: waits for x-ratelimit-reset-tokens",
        s.calls[1][0] - s.calls[0][0] >= 12,
        f"gap {s.calls[1][0] - s.calls[0][0]:.1f} s",
    )


def test_too_large():
    """6  a request larger than the minute limit is never sent."""
    c = FakeClock()
    s = Server(c)
    g = make(clock=c, server=s)
    r = g.chat_json("s", "x" * 30000, {}, max_tokens=700)
    return check("too large for TPM: not sent", r is None and not s.calls and g.usage["failures"] == 1)


def test_model_parameters():
    """7  reasoning parameters only for gpt-oss; vision model reserves image tokens."""
    c = FakeClock()
    s = Server(c)
    g = make(clock=c, server=s)
    g.chat_json("s", "u", {}, max_tokens=40)
    b = s.calls[0][2]
    bad = check(
        "gpt-oss: reasoning_effort low, reasoning not returned",
        b.get("reasoning_effort") == "low" and b.get("include_reasoning") is False,
    )
    s2 = Server(c)
    gq = make(model="qwen/qwen3.8-27b", clock=c, server=s2)
    gq.chat_json("s", "u", {}, images=[b"\x89PNG"], max_tokens=300)
    bq = s2.calls[0][2]
    bad += check(
        "qwen: no reasoning parameters; image reserved at 2048 tokens",
        "reasoning_effort" not in bq and groq.estimate_tokens("s", "u", images=1, model="qwen/qwen3.8-27b") >= 2048,
    )
    return bad


def test_parse_duration():
    """8  duration parser."""
    pd = groq.parse_duration
    cases = [("2m59.56s", 179.56), ("7.66s", 7.66), ("1h2m", 3720), ("30ms", 0.03), (None, None), ("7", 7.0)]
    return check("parse_duration", all(pd(text) == want for text, want in cases))


def test_reservation_corrected():
    """9  the real usage replaces the reservation."""
    c = FakeClock()
    s = Server(c, tokens_per_call=120)
    g = make(clock=c, server=s)
    g.chat_json("s", "u", {}, max_tokens=700)
    return check(
        "reservation corrected to real usage",
        g.limiter.window[-1][1] == 120,
        f"window holds {g.limiter.window[-1][1]}",
    )


SCENARIOS = [
    test_rpm,
    test_tpm,
    test_daily_budget,
    test_retry_after,
    test_header_hint,
    test_too_large,
    test_model_parameters,
    test_parse_duration,
    test_reservation_corrected,
]


def main():
    real_open = urllib.request.urlopen
    os.environ["GROQ_API_KEY"] = "gsk_fake"
    try:
        bad = sum(scenario() for scenario in SCENARIOS)
    finally:
        urllib.request.urlopen = real_open
        os.environ.pop("GROQ_API_KEY", None)
    print(f"\n{'ALL PASS' if not bad else str(bad) + ' FAILED'}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
