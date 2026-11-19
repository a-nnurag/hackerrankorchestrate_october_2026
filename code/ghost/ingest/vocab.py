"""Shared vocabulary: identifier regexes, resource-id prefix and collection maps, and string normalisers."""

from __future__ import annotations

import hashlib
import re

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
USER_RE = re.compile(r"\buser_\d+\b")
HASH_RE = re.compile(r"\b[0-9a-f]{64}\b")
PHONE_RE = re.compile(r"\+?[\d\s().\-]{7,}")
_RESOURCE_PREFIXES = (
    "account|search|analytics|support|export|data_flow|backup|audit_record|legal_hold|tombstone|marketing|object"
)
# A whole string that is a resource id (also accepts cache and email-delivery ids) ...
RID_RE = re.compile(rf"^({_RESOURCE_PREFIXES}|cache|email_delivery)_\d+$")
# ... versus resource ids mentioned inside free text (activity details never mention cache/email-delivery ids).
RID_FIND = re.compile(rf"\b(?:{_RESOURCE_PREFIXES})_\d+\b")
_RID_PREFIX_RE = re.compile(r"^([a-z_]+?)_\d+$")

# resource-id prefix -> (system_id, category); 'support' is refined to message/attachment by the source.
PREFIX_CAT = {
    "account": ("account_service", "USER_PROFILE"),
    "search": ("search_service", "SEARCH_INDEX_ENTRY"),
    "analytics": ("analytics_platform", "ANALYTICS_PROFILE"),
    "support": ("support_platform", "SUPPORT_RECORD"),
    "export": ("export_service", "USER_EXPORT"),
    "data_flow": ("integration_service", "DATA_FLOW"),
    "backup": ("backup_service", "BACKUP_ARCHIVE"),
    "audit_record": ("security_service", "SECURITY_AUDIT_LOG"),
    "legal_hold": ("legal_service", "LEGAL_HOLD_RECORD"),
    "tombstone": ("identity_service", "ACCOUNT_TOMBSTONE"),
    "marketing": ("marketing_platform", "MARKETING_PROFILE"),
    "object": ("object_storage", "OBJECT_BLOB"),
    "cache": ("cache_service", "CACHE_ENTRY"),
    "email_delivery": ("email_delivery_service", "EMAIL_DELIVERY_LOG"),
}

# Categories that a record_type column may name directly (the value is the category itself).
RECORD_TYPE_CATEGORIES = frozenset(
    {
        "USER_PROFILE",
        "SEARCH_INDEX_ENTRY",
        "SUPPORT_MESSAGE",
        "SUPPORT_ATTACHMENT",
        "ANALYTICS_PROFILE",
        "USER_EXPORT",
        "DATA_FLOW",
        "BACKUP_ARCHIVE",
        "SECURITY_AUDIT_LOG",
        "LEGAL_HOLD_RECORD",
        "ACCOUNT_TOMBSTONE",
    }
)

# collection / table name used by the different exports -> category
COLLECTION_CATEGORY = {
    "customer_profiles": "USER_PROFILE",
    "customer_search_documents": "SEARCH_INDEX_ENTRY",
    "search_documents_primary": "SEARCH_INDEX_ENTRY",
    "customer_analytics_reports": "ANALYTICS_PROFILE",
    "customer_analytics_profiles": "ANALYTICS_PROFILE",
    "analytics_profiles": "ANALYTICS_PROFILE",
    "support_conversations": "SUPPORT_MESSAGE",
    "support_records": "SUPPORT_MESSAGE",
    "ticket_attachments": "SUPPORT_ATTACHMENT",
    "customer_export_jobs": "USER_EXPORT",
    "customer_exports": "USER_EXPORT",
    "connector_configurations": "DATA_FLOW",
    "connector_subscriptions": "DATA_FLOW",
    "backup_catalog": "BACKUP_ARCHIVE",
    "backup_restore_entries": "BACKUP_ARCHIVE",
    "security_audit_events": "SECURITY_AUDIT_LOG",
    "security_audit_records": "SECURITY_AUDIT_LOG",
    "retained_order_records": "LEGAL_HOLD_RECORD",
    "deleted_customer_references": "ACCOUNT_TOMBSTONE",
}

_NULLISH = ("null", "none", "[redacted]", "n/a")


def norm_email(text: str) -> str:
    """Canonical form of an e-mail address: trimmed and lower-cased."""
    return text.strip().lower()


def sha(text: str) -> str:
    """SHA-256 hex digest of the normalised e-mail address (the dataset's `email_hash` convention)."""
    return hashlib.sha256(norm_email(text).encode("utf8")).hexdigest()


def digits(text: str | None) -> str:
    """Only the decimal digits of `text` (empty string for None)."""
    return re.sub(r"\D", "", text or "")


def classify(value: object) -> tuple[str, str] | None:
    """Classify a free-string identifier.

    Returns (type, normalised value) with type in email/user/hash/resource/phone, or None when the value is
    empty, a null marker, or not a recognisable identifier.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in _NULLISH:
        return None
    if EMAIL_RE.fullmatch(text):
        return ("email", norm_email(text))
    if USER_RE.fullmatch(text):
        return ("user", text)
    if HASH_RE.fullmatch(text.lower()):
        return ("hash", text.lower())
    if RID_RE.match(text):
        return ("resource", text)
    if PHONE_RE.fullmatch(text) and len(digits(text)) >= 7:
        return ("phone", digits(text))
    return None


def res_of(rid: str | None) -> tuple[str, str] | None:
    """(system_id, category) implied by a resource id's prefix, or None when the prefix is unknown."""
    match = _RID_PREFIX_RE.match(rid or "")
    return PREFIX_CAT.get(match.group(1)) if match else None


def category_of(collection: str | None, rid: str | None) -> str | None:
    """Category of a record: from its collection name when known, otherwise from its resource-id prefix."""
    known = COLLECTION_CATEGORY.get(collection or "")
    if known:
        return known
    implied = res_of(rid)
    return implied[1] if implied else None
