"""Conditions attached to policy rules (deletion_rules.csv), decided by rules first, an LLM second.

    rule_05  SUPPORT_MESSAGE     redact when the conversation holds shared customer/agent/order context
    rule_06  SUPPORT_ATTACHMENT  delete only when the attachment belongs only to the subject
    rule_12  SECURITY_AUDIT_LOG  retain only within the retention period
    rule_13  LEGAL_HOLD_RECORD   retain only while the hold is active

Each function returns a replacement state (or the unchanged one) plus a note.  Order of authority:
  1. structured fields (dates, uploader identity) and fixed phrases decide whenever they are present;
  2. only when the evidence is free text the rules cannot classify is the local LLM asked, and its
     answer must quote the text verbatim (ghost.llm guards); without a model, or on an invalid
     answer, the conservative default applies;
  3. every non-default outcome is reported so it appears in the review file.
"""

from __future__ import annotations

import re
from typing import Any

from .store import Store

CONTEXT_RE = re.compile(
    r"\b(order|orders|delivery|shipment|shipping|parcel|package|invoice|refund|return|ticket|case|agent|"
    r"tracking|purchase|payment)\b",
    re.I,
)
OWNED_ONLY_RE = re.compile(r"belongs only to|only (?:this|the) (?:subject|customer)|no other subject is linked", re.I)
SHARED_RE = re.compile(
    r"\bshared\b|also linked to|other (?:subject|customer)s? (?:is|are) linked(?! to)|multiple (?:subjects|customers)",
    re.I,
)


def _utc(value: str | None) -> str:
    """Normalise a date or datetime string to YYYY-MM-DDTHH:MM:SSZ for string comparison."""
    v = (value or "").strip()
    if len(v) == 10:  # a bare date: valid through the end of that day
        return v + "T23:59:59Z"
    return v


def retention_expired(category: str, extras: dict[str, Any] | None, audit_at: str) -> bool:
    """True when a retained record is past its stated retention/hold end at audit_at."""
    field = {"SECURITY_AUDIT_LOG": "retention_until", "LEGAL_HOLD_RECORD": "retained_until"}.get(category)
    end = _utc((extras or {}).get(field)) if field else ""
    return bool(end) and end < audit_at


def _ownership_from_catalog_text(text: str) -> tuple[str, str] | None:
    """Ownership stated by the catalog's own phrases, or None when the text says neither."""
    if OWNED_ONLY_RE.search(text):
        return "subject_only", "catalog says it belongs only to the subject"
    if SHARED_RE.search(text):
        return "shared", "catalog says it is shared"
    return None


def _ownership_from_llm(snippets: list[str], llm: Any) -> tuple[str, str] | None:
    """Ask the model about catalog text the phrases could not classify; None when it gives no valid verdict."""
    from .llm import adjudicate_ownership

    for text in snippets:
        verdict, why = adjudicate_ownership(llm, text)
        if verdict is not None:
            return ("subject_only" if verdict else "shared"), why
    return None


def _other_uploader(c: dict[str, Any], subject_emails: set[str]) -> str | None:
    """First uploader email of the attachment that is not one of the subject's, or None."""
    uploaders = [v for t, v, role in (c.get("ids") or []) if t == "email" and role == "uploader"]
    return next((u for u in uploaders if u not in subject_emails), None)


def _catalog_texts(store: Store, rid: str, audit_at: str) -> list[str]:
    """Free-text details of the catalog events that linked the resource to an identity, up to audit_at."""
    return [
        a["details"]
        for a in store.act_by_rid.get(rid, [])
        if a["event_type"] == "LINK_RESOURCE_IDENTITY" and a["event_time"] <= audit_at
    ]


def attachment_ownership(
    c: dict[str, Any], subject_emails: set[str], store: Store, rid: str, audit_at: str, llm: Any = None
) -> tuple[str, str]:
    """-> ("subject_only" | "shared", note).  Default is subject_only (the record is linked to the subject)."""
    other = _other_uploader(c, subject_emails)
    if other:
        return "shared", f"uploaded by {other}, not the subject"
    snippets = _catalog_texts(store, rid, audit_at)
    verdicts = (_ownership_from_catalog_text(text) for text in snippets)
    verdict = next((v for v in verdicts if v), None)
    if verdict is None and llm is not None:  # free text the phrases above do not classify
        verdict = _ownership_from_llm(snippets, llm)
    return verdict or ("subject_only", "no ownership evidence against the subject")


def message_has_shared_context(c: dict[str, Any], llm: Any = None) -> tuple[bool, str]:
    """-> (bool, note).  Default True: keep the conversation and redact it (the cautious choice)."""
    text = (c.get("extras") or {}).get("text") or ""
    if not text.strip():
        return True, "no message text available"
    if CONTEXT_RE.search(text):
        return True, "message mentions an order, delivery or agent context"
    if llm is not None:
        from .llm import adjudicate_shared_context

        verdict, why = adjudicate_shared_context(llm, text)
        if verdict is not None:
            return verdict, why
    return True, "no context words and no model verdict; default keeps the record and redacts it"
