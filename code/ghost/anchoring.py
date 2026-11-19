"""Activity-cluster anchoring: attach records that carry no identifier through the deletion worker's log.

One deletion request makes the worker touch a person's account first and then their other records within a few
hours.  An account-deletion activity close to the reported time is therefore an anchor, and the worker events in a
window after it are candidate records of the same person.  This is weak evidence (see settings.LINK_SCORES) and
is never used when another user's exact identifiers already claim the resource.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from .context import CaseContext
from .settings import DEL_EVENTS
from .store import Row
from .timeutil import format_ts, parse_ts
from .timing import phase_pick

CONTESTED = "cluster_contested"
WINDOW_BEFORE = timedelta(minutes=5)
WINDOW_AFTER = timedelta(hours=3.2)
BARE_WINDOW = timedelta(hours=2)
ANON_MIN_GAP, ANON_MAX_GAP = 600, 3600  # seconds between the account delete and its analytics anonymization

ClusterMembers = dict[str, tuple[Row, bool]]


def _is_account(rid: str) -> bool:
    return rid.startswith("account_")


def _is_anonymization(event: Row) -> bool:
    return event["resource_id"].startswith("analytics_") and event["event_type"] == "ANONYMIZE_RECORD"


def _near_accounts(ctx: CaseContext, accounts: list[Row], reported: datetime) -> list[Row]:
    """Unclaimed account deletions inside the anchor window around reported_at, narrowed by the reported status."""
    lo, hi = ctx.settings.anchor_window
    near = [
        a
        for a in accounts
        if lo <= (parse_ts(a["event_time"]) - reported).total_seconds() / 3600 <= hi
        and not ctx.claimed_other(a["resource_id"])
    ]
    if ctx.settings.status_filter:
        # the workflow's reported status is the summary of the account deletion's own result
        accepted = ctx.settings.status_results.get(ctx.case["reported_status"], ())
        near = [a for a in near if a["reported_result"] in accepted] or near
    return near


def _choose_anchors(ctx: CaseContext, near: list[Row], strong_rids: set[str]) -> tuple[list[Row], str]:
    """Pick the anchor account(s) and say how sure the choice is (the link type of the cluster)."""
    strong_near = [a for a in near if a["resource_id"] in strong_rids]
    if strong_near:
        return [min(strong_near, key=lambda a: a["event_time"])], "cluster_anchored"
    if len(near) == 1:
        return near, "activity_cluster"
    if len(near) > 1 and ctx.settings.phase_resolve and ctx.timing.phase:
        picked = phase_pick(near, strong_rids, ctx.store, ctx.timing.phase)
        if picked:
            return [picked], "phase_resolved"
    return near, CONTESTED  # several unclaimed candidate accounts -> ambiguous


def _windows(anchors: list[Row], reported: datetime) -> list[tuple[str, str, Row | None]]:
    """Time windows in which worker events count as the anchor's cluster (a bare window when there is no anchor)."""
    if not anchors:
        return [(format_ts(reported - BARE_WINDOW), format_ts(reported + BARE_WINDOW), None)]
    return [
        (format_ts(parse_ts(a["event_time"]) - WINDOW_BEFORE), format_ts(parse_ts(a["event_time"]) + WINDOW_AFTER), a)
        for a in anchors
    ]


def _anonymization_fits(ctx: CaseContext, events: list[Row], anchor: Row, event: Row) -> bool:
    """True when `event` is the one unclaimed analytics anonymization at the learned second offset after the anchor."""
    t_anchor = parse_ts(anchor["event_time"])
    fit = []
    for other in events:
        if not _is_anonymization(other) or ctx.claimed_other(other["resource_id"]):
            continue
        gap = (parse_ts(other["event_time"]) - t_anchor).total_seconds()
        if ANON_MIN_GAP <= gap <= ANON_MAX_GAP and int(gap) % 60 in ctx.timing.anon_phase:
            fit.append(other)
    return len(fit) == 1 and fit[0]["resource_id"] == event["resource_id"]


def _competing_account(ctx: CaseContext, accounts: list[Row], anchor: Row | None, event: Row) -> bool:
    """True when another unclaimed account deletion shortly precedes `event`, so the event may belong to it."""
    lower = format_ts(parse_ts(event["event_time"]) - WINDOW_AFTER)
    return any(
        (anchor is None or other["activity_id"] != anchor["activity_id"])
        and lower <= other["event_time"] <= event["event_time"]
        and not ctx.claimed_only_by_user(other["resource_id"])
        for other in accounts
    )


def _contested(
    ctx: CaseContext, events: list[Row], accounts: list[Row], anchor: Row | None, kind: str, event: Row
) -> bool:
    """Whether the cluster link of `event` is ambiguous."""
    if kind == CONTESTED:
        return True
    settings = ctx.settings
    if (
        settings.phase_resolve
        and ctx.timing.anon_phase
        and anchor is not None
        and _is_anonymization(event)
        and _anonymization_fits(ctx, events, anchor, event)
    ):
        return False
    if _is_account(event["resource_id"]):
        return False
    return _competing_account(ctx, accounts, anchor, event)


def _worker_events(ctx: CaseContext) -> list[Row]:
    return [
        a
        for a in ctx.store.act
        if a["source_system"] == "deletion_worker" and a["event_type"] in DEL_EVENTS and a["event_time"] <= ctx.audit_at
    ]


def _belongs_to_window(ctx: CaseContext, event: Row, anchor: Row | None, lo: str, hi: str) -> bool:
    """Whether a worker event falls in the anchor's window and may be attached to this person."""
    rid = event["resource_id"]
    if _is_account(rid) and (anchor is None or event["activity_id"] != anchor["activity_id"]):
        return False  # other accounts are never part of this cluster
    return lo <= event["event_time"] <= hi and not ctx.claimed_other(rid)


def anchor_clusters(ctx: CaseContext, strong_rids: set[str]) -> tuple[ClusterMembers, str]:
    """Return ({resource_id: (worker event, contested)}, link type) of the case's activity cluster."""
    reported = parse_ts(ctx.case["reported_at"])
    events = _worker_events(ctx)
    accounts = [a for a in events if _is_account(a["resource_id"])]
    near = _near_accounts(ctx, accounts, reported)
    anchors, kind = _choose_anchors(ctx, near, strong_rids)
    members: ClusterMembers = {}
    for lo, hi, anchor in _windows(anchors, reported):
        for event in events:
            if not _belongs_to_window(ctx, event, anchor, lo, hi):
                continue
            contested = _contested(ctx, events, accounts, anchor, kind, event)
            previous = members.get(event["resource_id"])
            members[event["resource_id"]] = (event, contested if previous is None else contested and previous[1])
    return members, kind
