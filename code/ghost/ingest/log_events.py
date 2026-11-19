"""Event-to-state rules for service logs: one small handler per logged event, looked up in a dispatch table."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .identifiers import Identifier, idents_from_text
from .log_lines import LogFields
from .vocab import EMAIL_RE, classify, digits, res_of

# Line fields that identify the data subject on the line itself (role = the field name, except where handled below).
_SUBJECT_FIELDS = (
    "email",
    "customer_email",
    "owner_email",
    "requester_email",
    "matched_value",
    "customer_reference",
    "subject_reference",
    "subject_ref",
    "email_hash",
    "phone",
    "requester_phone",
    "correlation_key",
    "lookup_key",
    "requester_name",
)
_PHONE_FIELDS = ("phone", "requester_phone")
_REQUESTER_FIELDS = ("requester_email", "requester_name", "requester_phone")


@dataclass
class Draft:
    """What the handlers decide about one logged event before it becomes an observation."""

    category: str | None
    event: str
    level: str | None
    state: str | None = None
    kind: str = "record"
    extras: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.extras.update(event=self.event, level=self.level)


Handler = Callable[[LogFields, Draft], None]


def _flag(value: object) -> bool:
    return str(value).lower() == "true"


def _present(fields: LogFields, keys: tuple[str, ...]) -> bool:
    return any(fields.get(k) not in (None, "null") for k in keys)


def _profile_lookup(d: LogFields, draft: Draft) -> None:
    absent = d.get("rows") == "0" or d.get("http_status") == "404"
    draft.state = "ABSENT" if absent else "PRESENT"
    draft.kind = "lookup_404" if absent else "record"
    draft.extras["http_status"] = d.get("http_status")


def _index_query(d: LogFields, draft: Draft) -> None:
    miss = d.get("result") == "miss" or d.get("total_hits") == "0"
    draft.state = "ABSENT" if miss else "PRESENT"
    draft.kind = "lookup_zero_hits" if miss else "record"


def _audit_read(d: LogFields, draft: Draft) -> None:
    draft.state = "ABSENT" if d.get("rows") == "0" else "PRESENT"
    draft.extras.update(retention_until=d.get("retention_until"), event_code=d.get("event_code"))


def _connector(d: LogFields, draft: Draft) -> None:
    enabled = _flag(d.get("enabled"))
    registered = d.get("scheduler_registered")
    # a connector that is enabled but not registered with the scheduler never runs
    active = enabled and (registered is None or _flag(registered))
    draft.state = "ACTIVE" if active else "DISABLED"
    draft.extras.update(
        enabled=enabled,
        scheduler_registered=registered,
        last_run=d.get("last_run"),
        delivery=d.get("last_delivery_status"),
    )


def _restore_policy(d: LogFields, draft: Draft) -> None:
    if d.get("archive_present") == "false":
        draft.state = "ABSENT"
    else:
        draft.state = "ACTIVE" if _flag(d.get("restore_allowed")) else "BLOCKED"
    draft.extras["restore_allowed"] = d.get("restore_allowed")


def _restore_candidate(d: LogFields, draft: Draft) -> None:
    restorable = _flag(d.get("eligible")) and not _flag(d.get("deletion_block"))
    draft.state = "ACTIVE" if restorable else "BLOCKED"
    draft.extras.update(eligible=d.get("eligible"), deletion_block=d.get("deletion_block"))


def _restore_authorization(d: LogFields, draft: Draft) -> None:
    draft.state = "BLOCKED" if d.get("decision") == "deny" else "ACTIVE"
    draft.extras.update(decision=d.get("decision"), policy=d.get("policy"))


def _export_check(d: LogFields, draft: Draft) -> None:
    draft.state = "PRESENT"
    draft.extras["available"] = d.get("available")
    if d.get("available") == "false":
        draft.extras["note"] = "record exists, download unavailable"


def _message_scan(d: LogFields, draft: Draft) -> None:
    draft.category = "SUPPORT_MESSAGE"
    draft.state = "IDENTIFIABLE"


def _attachment_scan(d: LogFields, draft: Draft) -> None:
    draft.category = "SUPPORT_ATTACHMENT"
    draft.state = "PRESENT"
    draft.extras["identifiable"] = True


def _message_read(d: LogFields, draft: Draft) -> None:
    draft.category = "SUPPORT_MESSAGE"
    text = d.get("message_text") or ""
    masked = "REDACTED" in text.upper() and not EMAIL_RE.search(text)
    draft.state = "REDACTED" if masked else "IDENTIFIABLE"


def _ticket_read(d: LogFields, draft: Draft) -> None:
    draft.category = "SUPPORT_MESSAGE"
    draft.state = "IDENTIFIABLE" if _present(d, _REQUESTER_FIELDS) else "REDACTED"


def _analytics_read(d: LogFields, draft: Draft) -> None:
    draft.state = "ANONYMIZED" if d.get("direct_identifiers") == "0" else "IDENTIFIABLE"


def _analytics_scan(d: LogFields, draft: Draft) -> None:
    draft.state = "IDENTIFIABLE"


def _analytics_read_completed(d: LogFields, draft: Draft) -> None:
    direct = _present(d, ("customer_reference", "email", "phone", "email_hash"))
    draft.state = "IDENTIFIABLE" if direct else "ANONYMIZED"


def _contact_lookup(d: LogFields, draft: Draft) -> None:
    draft.state = "PRESENT"
    draft.extras["email_opt_in"] = d.get("email_opt_in")


def _retained_order(d: LogFields, draft: Draft) -> None:
    draft.state = "PRESENT"
    draft.extras["access"] = d.get("access")


def _deletion_marker(d: LogFields, draft: Draft) -> None:
    # marker_found=false means the deletion was never recorded, so the data is still there
    draft.state = "PRESENT" if d.get("marker_found") == "false" else "ABSENT"
    draft.extras.update(marker_found=d.get("marker_found"), last_write=d.get("last_write"))


def _contact_query(d: LogFields, draft: Draft) -> None:
    draft.state = "PRESENT" if d.get("rows") != "0" else "ABSENT"
    draft.extras["source"] = d.get("source")


def _thumbnail_failed(d: LogFields, draft: Draft) -> None:
    draft.category = "SUPPORT_ATTACHMENT"
    draft.state = "PRESENT"


# Dispatch table: logged event -> handler that sets the category/state/kind/extras of the observation.
HANDLERS: dict[str, Handler] = {
    "profile_lookup_completed": _profile_lookup,
    "index_query_completed": _index_query,
    "audit_record_read_completed": _audit_read,
    "connector_heartbeat": _connector,
    "connector_config_loaded": _connector,
    "connector_config_read_completed": _connector,
    "restore_policy_read_completed": _restore_policy,
    "restore_candidate_evaluated": _restore_candidate,
    "restore_authorization_completed": _restore_authorization,
    "export_download_check_completed": _export_check,
    "export_metadata_read_completed": _export_check,
    "message_pii_scan": _message_scan,
    "attachment_pii_scan": _attachment_scan,
    "message_read": _message_read,
    "support_ticket_read_completed": _ticket_read,
    "analytics_profile_read": _analytics_read,
    "analytics_identity_scan": _analytics_scan,
    "analytics_profile_read_completed": _analytics_read_completed,
    "contact_lookup_completed": _contact_lookup,
    "retained_order_loaded": _retained_order,
    "deletion_marker_check": _deletion_marker,
    "contact_query_completed": _contact_query,
    "thumbnail_failed": _thumbnail_failed,
}


def new_draft(rid: str, event: str, fields: LogFields) -> Draft:
    """Draft for a resource event: system/category implied by the id prefix, then refined by the event handler."""
    implied = res_of(rid)
    draft = Draft(implied[1] if implied else None, event, fields.get("level"))
    HANDLERS[event](fields, draft)
    return draft


def _own_identifier(key: str, value: str | None) -> list[Identifier]:
    if key == "requester_name":
        return [("name", value.lower(), "subject")] if value and value != "null" else []
    if key in _PHONE_FIELDS:
        return [("phone", digits(value), "subject")] if value and value != "null" and digits(value) else []
    found = classify(value)
    return [(found[0], found[1], key)] if found and found[0] != "resource" else []


def own_line_identifiers(fields: LogFields) -> list[Identifier]:
    """Identifiers stated on the log line itself (as opposed to those of other lines of the same trace)."""
    out: list[Identifier] = []
    for key in _SUBJECT_FIELDS:
        out += _own_identifier(key, fields.get(key))
    if fields.get("message_text"):
        out += idents_from_text(fields["message_text"], "in_text")
    file_name = fields.get("file")
    if file_name:
        out.append(("file", file_name.lower(), "attachment_file"))
    return out
