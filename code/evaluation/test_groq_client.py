"""Offline tests of the Groq client (no network, no key needed): request shape, retries, cache, key handling.

python code/evaluation/test_groq_client.py
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

SECRET = "gsk_test_SECRET_VALUE"
BUDGET = tempfile.mktemp(suffix=".json")


class NoSleepClock(groq.Clock):
    """Real time, but retries and pacing never wait."""

    def sleep(self, seconds):
        pass


CLOCK = NoSleepClock()


class FakeResp(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def make_opener(script, seen):
    """script: list of responses; an int is an HTTP error code, a dict a JSON answer."""
    it = iter(script)

    def opener(req, timeout=None):
        seen.append(req)
        item = next(it)
        if isinstance(item, int):
            raise urllib.error.HTTPError(req.full_url, item, "err", {"retry-after": "0"}, io.BytesIO(b"{}"))
        return FakeResp(
            json.dumps(
                {
                    "choices": [{"message": {"content": json.dumps(item)}}],
                    "usage": {"prompt_tokens": 100, "completion_tokens": 20},
                }
            ).encode()
        )

    return opener


def check(name, ok):
    print(f"{'PASS' if ok else 'FAIL'} {name}")
    return 0 if ok else 1


def install(script):
    """Route urlopen to a scripted fake; -> the list that collects the requests sent."""
    seen = []
    urllib.request.urlopen = make_opener(script, seen)
    return seen


def client(model=None):
    return groq.GroqLLM(model=model, use_cache=False, clock=CLOCK, budget_path=BUDGET)


def test_strict_schema():
    """1  strict schema for gpt-oss, key only in the header, usage counted."""
    seen = install([{"a": 1}])
    g = client("openai/gpt-oss-120b")
    out = g.chat_json("sys", "user", {"type": "object"})
    body = json.loads(seen[0].data)
    return (
        check("returns the parsed JSON", out == {"a": 1})
        + check("strict json_schema for gpt-oss", body["response_format"]["json_schema"]["strict"] is True)
        + check("temperature 0", body["temperature"] == 0)
        + check(
            "key is sent as a Bearer header only",
            seen[0].get_header("Authorization") == "Bearer " + SECRET and SECRET not in seen[0].data.decode(),
        )
        + check("usage counted and cost estimated", g.usage["prompt_tokens"] == 100 and g.estimated_cost() > 0)
    )


def test_json_object_fallback():
    """2  json_object fallback for a model without strict schemas."""
    seen = install([{"a": 2}])
    client("llama-3.3-70b-versatile").chat_json("sys", "user", {"type": "object"})
    body = json.loads(seen[0].data)
    return check(
        "json_object mode with the schema in the prompt otherwise",
        body["response_format"] == {"type": "json_object"} and "schema" in body["messages"][0]["content"],
    )


def test_retry_then_success():
    """3  retry on 429 then success."""
    install([429, {"a": 3}])
    g = client("openai/gpt-oss-20b")
    return check("retries after 429", g.chat_json("s", "u", {}) == {"a": 3} and g.usage["retries"] == 1)


def test_hard_error():
    """4  gives up on a hard error and returns None."""
    install([401])
    g = client("openai/gpt-oss-20b")
    return check("401 returns None without retrying", g.chat_json("s", "u", {}) is None and g.usage["failures"] == 1)


def test_images():
    """5  images: vision model gets image_url parts, text model refuses."""
    seen = install([{"ids": []}])
    client("qwen/qwen3.8-27b").chat_json("s", "u", {}, images=[b"\x89PNG"])
    parts = json.loads(seen[0].data)["messages"][1]["content"]
    return check(
        "image sent as a data URI to a vision model",
        parts[1]["type"] == "image_url" and parts[1]["image_url"]["url"].startswith("data:image/png;base64,"),
    ) + check(
        "text-only model refuses images",
        client("openai/gpt-oss-120b").chat_json("s", "u", {}, images=[b"x"]) is None,
    )


def test_no_key():
    """6  no key: no request is made."""
    del os.environ["GROQ_API_KEY"]
    seen = install([])
    return check(
        "no key means no request and None",
        client().chat_json("s", "u", {}) is None and not seen and not groq.GroqLLM.available(),
    )


def test_factory():
    """7  factory."""
    return check(
        "make_llm selects the provider",
        isinstance(groq.make_llm("groq"), groq.GroqLLM) and isinstance(groq.make_llm("ollama"), groq.LLM),
    )


SCENARIOS = [
    test_strict_schema,
    test_json_object_fallback,
    test_retry_then_success,
    test_hard_error,
    test_images,
    test_no_key,
    test_factory,
]


def main():
    real_open = urllib.request.urlopen
    os.environ["GROQ_API_KEY"] = SECRET
    try:
        bad = sum(scenario() for scenario in SCENARIOS)
    finally:
        urllib.request.urlopen = real_open
        os.environ.pop("GROQ_API_KEY", None)
    print(f"\n{'ALL PASS' if not bad else str(bad) + ' FAILED'}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
