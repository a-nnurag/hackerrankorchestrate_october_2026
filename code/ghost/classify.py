"""Request classification: does request_text authorize deletion?

Layered, deterministic first:
  0. instruction-like fragments are removed ([SYSTEM: ...], "ignore previous instructions", "answer
     NOT_APPLICABLE") so text addressed to the system can neither trigger nor suppress a decision
  1. explicit non-deletion phrases        -> NOT_APPLICABLE
  2. deletion vocabulary                  -> deletion / audit request
  3. CONFLICT: a non-deletion phrase AND a deletion verb aimed at the account/profile/data elsewhere
     in the text ("delete my account, but don't delete my invoices"), or wording the rules do not
     know at all.  Adjudicated by a local LLM when one is available (its answer must quote the
     request verbatim), by a scope rule otherwise.  Conflicts are always flagged for review.

Text is only ever matched or quoted, never executed or followed.
"""

from __future__ import annotations

import re
from typing import Any

# Explicit non-deletion intent.  Generic words like "download", "copy" or "remove" are NOT used on
# their own because deletion requests also contain them ("remove any remaining copy", "old
# download link still works").
NON_DELETION = [
    r"not asking for (?:a )?delet",
    r"not a request to (?:erase|delete)",
    r"do not (?:close|delete|remove|erase) (?:the|my) (?:account|profile)",
    r"don'?t (?:delete|close|remove|erase)",
    r"(?:leave|keep) (?:the|my) (?:account|profile)[^.]*(?:active|in place|as it is)",
    r"keep the account as it is",
    r"continue using the service",
    r"(?:marketing|mailing) lists? only",
    r"stop the promotional",
    r"download my (?:account|personal) (?:information|data)",
    r"a copy of (?:last year|the information|my data|my information)",
    r"(?:surname|name) is misspelled",
    r"replace it with the new one",
    r"change the email address used",
    r"need help resetting",
    r"what personal information you hold",
    r"without removing any of my records",
]
_NON_DELETION_RE = re.compile("|".join(NON_DELETION), re.I)

# A deletion verb aimed at the account, profile or personal data (English, Spanish, French,
# Portuguese, German).  Used to detect conflicts, not to decide on its own.
_ACCOUNT_DELETION_RE = re.compile(
    r"\b(?:delet\w*|eras\w*|remov\w*|clos\w*|wipe|purg\w*|eliminar|elimin\w*|borr\w*|supprim\w*|"
    r"effac\w*|apag\w*|exclu\w*|l[öo]sch\w*)\b[^.;!?]{0,40}"
    r"\b(?:account|profile|personal (?:data|information)|my data|cuenta|perfil|compte|conta|konto)\b",
    re.I,
)

DELETION_WORDS = re.compile(
    r"delet|eras|remov|clos(?:e|ing)|suppress|supprim|elimin|borr|apag|exclu|cancel|forget|wipe|"
    r"destroy|deactivat|terminat|discard|purg|gone|effac|cl[oô]tur|l[öo]sch|cancell|"
    r"削除|消去|삭제|탈퇴|解約|退会",
    re.I,
)

# Text that addresses the system or tells it what to answer is not part of the person's request.
_SENT = r"[^.!?\n]*"
_INJECTION_RE = re.compile(
    r"\[[^\]]*\]|\{[^}]*\}|<[^>]*>"  # bracketed / tag-like asides
    rf"|{_SENT}\b(?:ignore|disregard)\b[^.!?\n]{{0,30}}\b(?:previous|prior|above|earlier)\b{_SENT}[.!?]?"
    rf"|{_SENT}\bsystem\s*(?:prompt|message|:){_SENT}[.!?]?"
    rf"|{_SENT}\b(?:answer|respond|classify|mark|label)\b[^.!?\n]{{0,30}}"
    rf"\b(?:not_applicable|complete|incomplete|every case|this (?:request|case)){_SENT}[.!?]?",
    re.I,
)


def sanitize(text: str | None) -> tuple[str, list[str]]:
    """-> (clean_text, removed_fragments)"""
    removed = [m.group(0).strip() for m in _INJECTION_RE.finditer(text or "") if m.group(0).strip()]
    clean = " ".join(_INJECTION_RE.sub(" ", text or "").split())
    return clean, removed


def _conflict(text: str) -> bool:
    """True when an account-directed deletion verb occurs outside the non-deletion phrase(s)."""
    spans = [m.span() for m in _NON_DELETION_RE.finditer(text)]
    if not spans:
        return False
    return any(
        not any(m.start() < end and start < m.end() for start, end in spans)
        for m in _ACCOUNT_DELETION_RE.finditer(text)
    )


def _ask(llm: Any, text: str) -> tuple[bool | None, str]:
    if llm is None:
        return None, ""
    from .llm import adjudicate_request

    return adjudicate_request(llm, text)


def classify_request(text: str | None, llm: Any = None) -> tuple[bool, str]:
    """-> (is_deletion: bool, reason: str).  A reason starting with CONFLICT means: review."""
    t, removed = sanitize(text or "")
    note = f" [ignored {len(removed)} instruction-like fragment(s)]" if removed else ""
    m = _NON_DELETION_RE.search(t)
    if m:
        if _conflict(t):
            verdict, why = _ask(llm, t)
            if verdict is not None:
                return verdict, f"CONFLICT resolved by {why}{note}"
            # scope rule: the account itself is the object of a deletion verb -> deletion request
            return True, (
                f"CONFLICT (non-deletion phrase {m.group(0)!r} but account-directed deletion verb); scope rule{note}"
            )
        return False, f"non-deletion phrase: {m.group(0)!r}{note}"
    if DELETION_WORDS.search(t):
        return True, f"deletion vocabulary present{note}"
    # no deletion vocabulary and no refusal phrase: wording the rules do not know
    verdict, why = _ask(llm, t)
    if verdict is not None:
        return verdict, f"CONFLICT unknown wording resolved by {why}{note}"
    return True, f"CONFLICT no deletion vocabulary and no refusal phrase; treated as audit request{note}"
