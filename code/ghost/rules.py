"""Policy as data: (data category, observed state) -> required treatment and step operations.

Derived from dataset/deletion_rules.csv and checked against the 32 sample answers.  Each entry:
    kind         violation | compliant | retained
    finding      FINDING operation (violations only)
    remediation  REMEDIATION operation (violations only)
    verification VERIFICATION operation proving the required final state
"""

from __future__ import annotations

from typing import Any

FINDING_OPS = ["REPORT_REMAINING_RECORD", "REPORT_EXPOSED_PII", "REPORT_ACTIVE_DATA_FLOW", "REPORT_RESTORE_RISK"]
REMEDIATION_OPS = ["DISABLE_DATA_FLOW", "BLOCK_RESTORE", "DELETE_RECORD", "REDACT_RECORD", "ANONYMIZE_RECORD"]
VERIFICATION_OPS = [
    "VERIFY_RECORD_ABSENT",
    "VERIFY_RECORD_PRESENT",
    "VERIFY_RECORD_REDACTED",
    "VERIFY_RECORD_ANONYMIZED",
    "VERIFY_DATA_FLOW_DISABLED",
    "VERIFY_RESTORE_BLOCKED",
]

OP_STATE = {
    "REPORT_REMAINING_RECORD": "PRESENT",
    "REPORT_EXPOSED_PII": "PRESENT",
    "REPORT_ACTIVE_DATA_FLOW": "ACTIVE",
    "REPORT_RESTORE_RISK": "ACTIVE",
    "DISABLE_DATA_FLOW": "DISABLED",
    "BLOCK_RESTORE": "BLOCKED",
    "DELETE_RECORD": "ABSENT",
    "REDACT_RECORD": "REDACTED",
    "ANONYMIZE_RECORD": "ANONYMIZED",
    "VERIFY_RECORD_ABSENT": "ABSENT",
    "VERIFY_RECORD_PRESENT": "PRESENT",
    "VERIFY_RECORD_REDACTED": "REDACTED",
    "VERIFY_RECORD_ANONYMIZED": "ANONYMIZED",
    "VERIFY_DATA_FLOW_DISABLED": "DISABLED",
    "VERIFY_RESTORE_BLOCKED": "BLOCKED",
}
PHASE_OPS = {"FINDING": FINDING_OPS, "REMEDIATION": REMEDIATION_OPS, "VERIFICATION": VERIFICATION_OPS}
PHASE_ORDER = ["FINDING", "REMEDIATION", "VERIFICATION"]


def _delete(cat_rule: str) -> dict[str, str]:
    return dict(
        kind="violation",
        finding="REPORT_REMAINING_RECORD",
        remediation="DELETE_RECORD",
        verification="VERIFY_RECORD_ABSENT",
        rule=cat_rule,
    )


def _redact(cat_rule: str) -> dict[str, str]:
    return dict(
        kind="violation",
        finding="REPORT_EXPOSED_PII",
        remediation="REDACT_RECORD",
        verification="VERIFY_RECORD_REDACTED",
        rule=cat_rule,
    )


def _anonymize(cat_rule: str) -> dict[str, str]:
    return dict(
        kind="violation",
        finding="REPORT_EXPOSED_PII",
        remediation="ANONYMIZE_RECORD",
        verification="VERIFY_RECORD_ANONYMIZED",
        rule=cat_rule,
    )


_ABSENT = dict(kind="compliant", verification="VERIFY_RECORD_ABSENT")

TREATMENT = {
    # whole-record deletion rules
    ("USER_PROFILE", "PRESENT"): _delete("rule_01"),
    ("SECONDARY_IDENTIFIER", "PRESENT"): _delete("rule_02"),
    ("SEARCH_INDEX_ENTRY", "PRESENT"): _delete("rule_03"),
    ("CACHE_ENTRY", "PRESENT"): _delete("rule_04"),
    ("SUPPORT_ATTACHMENT", "PRESENT"): _delete("rule_06"),
    ("SUPPORT_RECORD", "PRESENT"): _delete("rule_06"),
    ("USER_EXPORT", "PRESENT"): _delete("rule_09"),
    ("MARKETING_PROFILE", "PRESENT"): _delete("rule_10"),
    ("OBJECT_BLOB", "PRESENT"): _delete("rule_06"),
    # an analytics-looking record that is merely PRESENT (e.g. an opt-in contact record) is deleted
    ("ANALYTICS_PROFILE", "PRESENT"): _delete("rule_10"),
    # redact: keep the record, remove identifiers
    ("SUPPORT_MESSAGE", "IDENTIFIABLE"): _redact("rule_05"),
    ("SUPPORT_MESSAGE", "PRESENT"): _redact("rule_05"),
    ("EMAIL_DELIVERY_LOG", "IDENTIFIABLE"): _redact("rule_11"),
    ("ACCOUNT_TOMBSTONE", "IDENTIFIABLE"): _redact("rule_15"),
    # anonymize
    ("ANALYTICS_PROFILE", "IDENTIFIABLE"): _anonymize("rule_07"),
    ("PRODUCT_TELEMETRY", "IDENTIFIABLE"): _anonymize("rule_08"),
    # conditions of rules 05/06/12/13 decided in ghost/conditions.py
    ("SUPPORT_ATTACHMENT", "SHARED"): _redact("rule_06 (not subject-only)"),
    ("SUPPORT_MESSAGE", "NO_SHARED_CONTEXT"): _delete("rule_05 (no shared context)"),
    ("SECURITY_AUDIT_LOG", "EXPIRED"): _delete("rule_12 (retention period over)"),
    ("LEGAL_HOLD_RECORD", "EXPIRED"): _delete("rule_13 (hold no longer active)"),
    # recreation risks
    ("DATA_FLOW", "ACTIVE"): dict(
        kind="violation",
        finding="REPORT_ACTIVE_DATA_FLOW",
        remediation="DISABLE_DATA_FLOW",
        verification="VERIFY_DATA_FLOW_DISABLED",
        rule="active data flow",
    ),
    ("BACKUP_ARCHIVE", "ACTIVE"): dict(
        kind="violation",
        finding="REPORT_RESTORE_RISK",
        remediation="BLOCK_RESTORE",
        verification="VERIFY_RESTORE_BLOCKED",
        rule="rule_14",
    ),
    # already compliant
    ("SUPPORT_MESSAGE", "REDACTED"): dict(kind="compliant", verification="VERIFY_RECORD_REDACTED"),
    ("EMAIL_DELIVERY_LOG", "REDACTED"): dict(kind="compliant", verification="VERIFY_RECORD_REDACTED"),
    ("ACCOUNT_TOMBSTONE", "REDACTED"): dict(kind="compliant", verification="VERIFY_RECORD_REDACTED"),
    ("ANALYTICS_PROFILE", "ANONYMIZED"): dict(kind="compliant", verification="VERIFY_RECORD_ANONYMIZED"),
    ("PRODUCT_TELEMETRY", "ANONYMIZED"): dict(kind="compliant", verification="VERIFY_RECORD_ANONYMIZED"),
    ("DATA_FLOW", "DISABLED"): dict(kind="compliant", verification="VERIFY_DATA_FLOW_DISABLED"),
    ("BACKUP_ARCHIVE", "BLOCKED"): dict(kind="compliant", verification="VERIFY_RESTORE_BLOCKED"),
    # retained by policy: must still exist
    ("SECURITY_AUDIT_LOG", "PRESENT"): dict(kind="retained", verification="VERIFY_RECORD_PRESENT", rule="rule_12"),
    ("LEGAL_HOLD_RECORD", "PRESENT"): dict(kind="retained", verification="VERIFY_RECORD_PRESENT", rule="rule_13"),
}


def treatment(category: str | None, state: str) -> dict[str, Any] | None:
    """Return the treatment dict for an observed (category, state), or None when no rule applies."""
    if state == "ABSENT":
        return _ABSENT if category else None
    if category is None:
        return None
    return TREATMENT.get((category, state))
