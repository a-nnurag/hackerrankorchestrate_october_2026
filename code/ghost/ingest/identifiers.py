"""Extraction of (type, value, role) identifier triples from JSON/SQL records and free text."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from .vocab import EMAIL_RE, HASH_RE, USER_RE, classify, digits, norm_email

Identifier = tuple[str, str, str]  # (id_type, value, role)

# JSON/SQL field name -> (value type, role the identifier plays for the record)
FIELD_ROLES = {
    "email": ("email", "subject"),
    "owner_email": ("email", "owner"),
    "requester_email": ("email", "requester"),
    "customer_email": ("email", "subject"),
    "uploaded_by": ("email", "uploader"),
    "subject_selector": ("email", "selector"),
    "lookup_value": ("any", "lookup"),
    "lookup_key": ("any", "lookup"),
    "subject_reference": ("any", "subject"),
    "customer_reference": ("any", "subject"),
    "user_id": ("any", "subject"),
    "phone": ("phone", "subject"),
    "owner_phone": ("phone", "owner"),
    "requester_phone": ("phone", "requester"),
    "email_hash": ("hash", "subject"),
    "full_name": ("name", "subject"),
    "display_name": ("name", "subject"),
    "requester_name": ("name", "requester"),
    "name": ("name", "subject"),
    "matched_value": ("any", "matched"),
    "source_resource_id": ("resource", "source"),
    "subject_ref": ("any", "subject"),
    "subject_key": ("any", "lookup"),
    "match_key": ("any", "lookup"),
    "scan_key": ("any", "lookup"),
    "owner_key": ("any", "lookup"),
    "correlation_key": ("any", "correlation"),
}
# Fields that name the record itself or an internal storage key, never the data subject.
SKIP_FIELDS = frozenset({"integrity_seal", "resource_id", "ticket_id", "object_key", "archive_key", "archive_path"})
FILE_FIELDS = ("file_name", "file")
TEXT_FIELDS = ("message_text", "message_excerpt")

# A record "names the subject directly" when one of these is filled in ...
DIRECT_FIELDS = frozenset(
    {
        "email",
        "phone",
        "email_hash",
        "full_name",
        "name",
        "display_name",
        "requester_email",
        "requester_name",
        "requester_phone",
        "owner_email",
        "owner_phone",
        "customer_email",
    }
)
# ... and "points at the subject indirectly" through one of these.
REFERENCE_FIELDS = frozenset({"user_id", "customer_reference", "subject_reference"})
_EMPTY = (None, "", "null")


def ident_from_value(value: object, role: str) -> list[Identifier]:
    """Identifier triple for a single free-string value (empty list when it is not recognisable)."""
    found = classify(value)
    return [(found[0], found[1], role)] if found else []


def idents_from_text(text: str | None, role: str) -> list[Identifier]:
    """E-mail addresses, user ids and SHA-256 hashes mentioned in free text."""
    text = text or ""
    out: list[Identifier] = [("email", norm_email(m), role) for m in EMAIL_RE.findall(text)]
    out += [("user", m, role) for m in USER_RE.findall(text)]
    out += [("hash", m, role) for m in HASH_RE.findall(text.lower())]
    return out


def flatten(node: Any) -> Iterator[tuple[str, Any]]:
    """Yield (leaf key, scalar value) pairs of nested JSON; scalars inside bare lists are ignored."""
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(value, (dict, list)):
                yield from flatten(value)
            else:
                yield key, value
    elif isinstance(node, list):
        for item in node:
            yield from flatten(item)


def _typed_identifiers(kind: str, role: str, value: Any) -> list[Identifier]:
    """Identifier triples for one field whose expected value type is `kind`."""
    if kind == "name":
        name = str(value).strip()
        # the dataset masks names as "[REDACTED]": that is not an identifier
        return [("name", name.lower(), role)] if name and name.upper() != "[REDACTED]" else []
    if kind == "phone":
        return [("phone", digits(value), role)] if digits(value) else []
    if kind == "resource":
        return [("resource", str(value), role)]
    found = classify(value)
    if found:
        return [(found[0], found[1], role)]
    if kind == "email" and value:
        return [("email_malformed", str(value), role)]  # keep broken addresses: they may still identify the subject
    return []


def idents_from_record(record: Any) -> list[Identifier]:
    """All identifier triples carried by the fields of a (possibly nested) record."""
    out: list[Identifier] = []
    for key, value in flatten(record):
        if key in SKIP_FIELDS or value is None or isinstance(value, (bool, int, float)):
            continue
        if key in FILE_FIELDS:
            if value:
                out.append(("file", str(value).lower(), "attachment_file"))
        elif key in TEXT_FIELDS:
            out += idents_from_text(value, "in_text")
        elif key in FIELD_ROLES:
            kind, role = FIELD_ROLES[key]
            out += _typed_identifiers(kind, role, value)
    return out


def _has_filled(record: Any, fields: frozenset[str]) -> bool:
    return any(key in fields and value not in _EMPTY for key, value in flatten(record))


def has_direct(record: Any) -> bool:
    """True when the record names the data subject directly (e-mail, phone, hash, name ...)."""
    return _has_filled(record, DIRECT_FIELDS)


def has_any_ref(record: Any) -> bool:
    """True when the record at least references the subject (user id / customer reference)."""
    return _has_filled(record, REFERENCE_FIELDS)
