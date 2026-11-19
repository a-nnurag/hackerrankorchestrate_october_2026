"""Derivation of an observation state (PRESENT, IDENTIFIABLE, ACTIVE ...) from a JSON/SQL record."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .identifiers import has_any_ref, has_direct
from .vocab import EMAIL_RE

Record = dict[str, Any]
Extras = dict[str, Any]
StateAndExtras = tuple[str, Extras]

_TRUE_TEXT = ("1", "true")


def is_truthy(value: object) -> bool:
    """True for the 1/true spellings used by SQL integer flags and JSON booleans."""
    return str(value).lower() in _TRUE_TEXT


def analytics_state(record: Record) -> str:
    """An analytics profile that still holds any subject reference is identifiable, else anonymised."""
    return "IDENTIFIABLE" if (has_direct(record) or has_any_ref(record)) else "ANONYMIZED"


def _data_flow(record: Record) -> StateAndExtras:
    enabled = is_truthy(record.get("enabled"))
    mode = record.get("mode") or record.get("last_delivery_status")
    return ("ACTIVE" if enabled else "DISABLED"), {"enabled": enabled, "mode": mode}


def _backup(record: Record) -> StateAndExtras:
    allowed = is_truthy(record.get("restore_allowed"))
    return ("ACTIVE" if allowed else "BLOCKED"), {"restore_allowed": allowed}


def _analytics(record: Record) -> StateAndExtras:
    return analytics_state(record), {}


def _support_message(record: Record) -> StateAndExtras:
    text = record.get("message_text") or record.get("message_excerpt") or ""
    direct = has_direct(record) or bool(EMAIL_RE.search(text))
    extras: Extras = {"text": text[:500]} if text else {}
    return ("IDENTIFIABLE" if direct else "REDACTED"), extras


def _tombstone(record: Record) -> StateAndExtras:
    return ("IDENTIFIABLE" if has_direct(record) else "REDACTED"), {"account_status": record.get("account_status")}


def _profile(record: Record) -> StateAndExtras:
    return "PRESENT", {"account_status": record.get("account_status")}


def _export(record: Record) -> StateAndExtras:
    available = record.get("download_available")
    return "PRESENT", ({} if available is None else {"download_available": available})


def _audit(record: Record) -> StateAndExtras:
    extras = {
        "event": record.get("event_name") or record.get("event_code"),
        "retention_until": record.get("retention_until"),
    }
    return "PRESENT", extras


def _legal_hold(record: Record) -> StateAndExtras:
    return "PRESENT", {"retained_until": record.get("retained_until")}


_STATE_RULES: dict[str, Callable[[Record], StateAndExtras]] = {
    "DATA_FLOW": _data_flow,
    "BACKUP_ARCHIVE": _backup,
    "ANALYTICS_PROFILE": _analytics,
    "SUPPORT_MESSAGE": _support_message,
    "ACCOUNT_TOMBSTONE": _tombstone,
    "USER_PROFILE": _profile,
    "USER_EXPORT": _export,
    "SECURITY_AUDIT_LOG": _audit,
    "LEGAL_HOLD_RECORD": _legal_hold,
}


def state_for_record(category: str | None, record: Record) -> StateAndExtras:
    """(state, extras) of a record of the given category; categories without a rule are simply PRESENT."""
    rule = _STATE_RULES.get(category or "")
    return rule(record) if rule else ("PRESENT", {})
