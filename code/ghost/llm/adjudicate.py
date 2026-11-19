"""Adjudicators: ask the model a narrow question about untrusted text and accept the answer only when it is valid.

An answer is used only if it matches the schema and its quote occurs verbatim in the text; otherwise the caller gets
None and falls back to the deterministic rules.
"""

from __future__ import annotations

import unicodedata
from typing import Any

from ..classify import sanitize
from .prompts import (
    CONTEXT_SYSTEM,
    DEFAULT_VARIANT,
    OWNERSHIP_SYSTEM,
    SCHEMA_BOOL,
    SCHEMA_QUOTED_BOOL,
    SCHEMA_TRI,
    VARIANTS,
)

_TRI_DECISIONS = ("deletion", "not_deletion", "unclear")
_MALFORMED = "llm answer missing or malformed"


def _norm(s: str | None) -> str:
    s = unicodedata.normalize("NFKC", s or "").casefold()
    return " ".join(s.replace("’", "'").replace("“", '"').replace("”", '"').split())


def quote_is_verbatim(quote: str | None, text: str | None) -> bool:
    """True when the quote (or each fragment of an elided quote, in order) occurs in the text."""
    q, t = _norm(quote), _norm(text)
    if not q:
        return False
    pos = 0
    for frag in [f.strip(" .…") for f in q.replace("…", "...").split("...")]:
        if not frag:
            continue
        i = t.find(frag, pos)
        if i < 0:
            return False
        pos = i + len(frag)
    return True


def _verdict(out: dict[str, Any], tri: bool) -> tuple[bool | None, str]:
    """The verdict in a request-classification answer, or (None, reason) when it is malformed or abstains."""
    if tri:
        d = out.get("decision")
        if d not in _TRI_DECISIONS:
            return None, _MALFORMED
        if d == "unclear":
            return None, "llm abstained (unclear)"
        return d == "deletion", ""
    verdict = out.get("authorizes_account_deletion")
    if not isinstance(verdict, bool):
        return None, _MALFORMED
    return verdict, ""


def adjudicate_request(llm: Any, text: str, variant: str | None = None) -> tuple[bool | None, str]:
    """-> (True | False | None, reason).  None when the model is unavailable, abstains or fails validation."""
    variant = variant or DEFAULT_VARIANT
    tri = variant == "v2"
    out = llm.chat_json(VARIANTS[variant], f"<request>\n{text}\n</request>", SCHEMA_TRI if tri else SCHEMA_BOOL)
    if not isinstance(out, dict):
        return None, _MALFORMED
    verdict, reason = _verdict(out, tri)
    if verdict is None:
        return None, reason
    if not quote_is_verbatim(out.get("quote"), text):
        return None, "llm quote not found in request (rejected)"
    return verdict, f"llm ({llm.model}, {variant}) quote={out['quote']!r}"


def _quoted_bool(llm: Any, system: str, tag: str, text: str) -> tuple[bool | None, str]:
    text = sanitize(text)[0]  # evidence text is untrusted: instruction-like fragments never reach the model
    out = llm.chat_json(system, f"<{tag}>\n{text}\n</{tag}>", SCHEMA_QUOTED_BOOL)
    if not isinstance(out, dict) or not isinstance(out.get("answer"), bool):
        return None, _MALFORMED
    if not quote_is_verbatim(out.get("quote"), text):
        return None, "llm quote not found in text (rejected)"
    return out["answer"], f"llm ({llm.model}) quote={out['quote']!r}"


def adjudicate_ownership(llm: Any, note: str) -> tuple[bool | None, str]:
    """-> (True = belongs only to the subject | False = shared | None, reason)"""
    return _quoted_bool(llm, OWNERSHIP_SYSTEM, "note", note)


def adjudicate_shared_context(llm: Any, message: str) -> tuple[bool | None, str]:
    """-> (True = has shared context | False = only the customer's own details | None, reason)"""
    return _quoted_bool(llm, CONTEXT_SYSTEM, "message", message)
