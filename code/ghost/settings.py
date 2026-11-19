"""Settings and fixed vocabularies of the linking stage.

`LinkSettings` replaces what used to be module-level switches that evaluation scripts toggled by assignment: every
ablation now builds its own immutable settings object and passes it down from `pipeline.Auditor`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

# Link confidence per link type.  Exact identifiers sit above 0.90, structural inference in the middle, and
# statistical guesses (event-time clusters, a name, an id pattern) low.
LINK_SCORES: Mapping[str, float] = {
    "email_current": 0.99,
    "email_historical": 0.97,
    "user_id": 0.97,
    "hash": 0.96,
    "catalog_link": 0.95,
    "attachment_catalog": 0.92,
    "source_resource_id": 0.85,
    "resource_continuity": 0.80,
    "cluster_anchored": 0.70,
    "phase_resolved": 0.70,
    "phone": 0.60,
    "activity_cluster": 0.45,
    "cluster_contested": 0.30,
    "name_only": 0.25,
    "id_pattern": 0.15,
}

# Link types that identify the person beyond doubt: the record carries the exact email, user id or hash, or the
# catalog itself links it to the person.
STRONG: frozenset[str] = frozenset(
    {"email_current", "email_historical", "user_id", "hash", "catalog_link", "attachment_catalog"}
)

# Identifier role discount: a query key or an incidental mention is weaker evidence than record content.
ROLE_FACTOR: Mapping[str, float] = {"lookup": 0.90, "correlation": 0.92, "matched": 0.95, "in_text": 0.95}

# Which delete result of the account-deletion activity each reported workflow status summarises.
STATUS_RESULTS: Mapping[str, tuple[str, ...]] = {
    "COMPLETE": ("SUCCESS",),
    "NOT_STARTED": ("FAILED",),
    "PARTIALLY_COMPLETE": ("PARTIAL", "SUCCESS"),
}

# Observed states that violate the deletion request (the record is still there in some form).
NONCOMPLIANT: frozenset[str] = frozenset({"PRESENT", "IDENTIFIABLE", "ACTIVE"})

# Activity event types written by the deletion worker.
DEL_EVENTS: frozenset[str] = frozenset(
    {
        "DELETE_RECORD",
        "ANONYMIZE_RECORD",
        "REDACT_RECORD",
        "DISABLE_DATA_FLOW",
        "BLOCK_RESTORE",
        "CHECK_DATA_FLOW",
        "CHECK_RESTORE_ACCESS",
    }
)


@dataclass(frozen=True)
class LinkSettings:
    """Immutable switches of the linking and conclusion stages (defaults are the submitted configuration)."""

    mode: str = "relaxed"
    """Which evidence may be used.  strict: only files exported at or before audit_at.  record: the same for
    state and citations, but identity links may come from later-exported files whose record time is not after
    audit_at.  relaxed: state may also come from later-exported files (never cited)."""

    cluster: bool = True
    """Link records through deletion-worker activity clusters.  The workflow log of one request touches a
    person's account, search entry, analytics profile ... within a few hours, so records with no identifier can
    still be attached.  Weak evidence (score 0.70 or less), always flagged for review."""

    since_request: bool = True
    """Conclude state only from observations at or after requested_at.  An older observation cannot show the
    state after the deletion workflow ran, and older activity belongs to an earlier request of the same person
    (switching this off costs accuracy on the public samples)."""

    status_filter: bool = True
    """Keep only anchor accounts whose delete result agrees with the case's reported_status.  The reported status
    summarises the account deletion's own result: on the public samples 16/16 COMPLETE are SUCCESS, 10/10
    NOT_STARTED are FAILED and PARTIALLY_COMPLETE is PARTIAL or SUCCESS (see STATUS_RESULTS)."""

    status_results: Mapping[str, tuple[str, ...]] = field(default_factory=lambda: STATUS_RESULTS)
    """reported_status -> accepted delete results, used when status_filter is on."""

    phase_resolve: bool = True
    """Break ties between several candidate accounts with the learned second-offset pattern (see timing.py)."""

    anchor_window: tuple[float, float] = (-1.3, 0.3)
    """Hours around reported_at in which an account-deletion activity may anchor a cluster.  Chosen on the public
    samples; the sensitivity grid in evaluation/robustness.py shows the result is flat around it."""

    link_scores: Mapping[str, float] = field(default_factory=lambda: LINK_SCORES)
    """Confidence per link type."""
