"""State conclusion: what is the state of each linked resource at audit_at, and which file proves it.

For every linked resource the latest usable observation decides the state.  When there is none, a replica-drift
note, a covering snapshot that omits the resource, or the bare activity record decides (see `conclude`).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from .identity import Identity
from .ingest import res_of
from .linking import file_ok, link_case, rec_ok
from .settings import NONCOMPLIANT, LinkSettings
from .store import Row, Store
from .timing import TimingModel

# Record categories whose absence a later snapshot of the primary store can prove.
DERIVABLE_CATEGORIES = ("USER_PROFILE", "SEARCH_INDEX_ENTRY", "USER_EXPORT")

Conclusions = dict[tuple[str, str], dict[str, Any]]


def covering_files(store: Store, system: str, after: str, audit_at: str) -> list[Row]:
    """Full or empty snapshots of `system` taken after `after` and exported at or before audit_at, oldest first."""
    out = [
        c
        for c in store.cov
        if c["system_id"] == system
        and after < c["scope_time"] <= audit_at
        and store.captured_at(c["file_id"], c["scope_time"]) <= audit_at
    ]
    out.sort(key=lambda c: c["scope_time"])
    return out


def _observation_order(obs: Row) -> tuple[str, str]:
    return (obs["observed_at"] or "", obs["file_captured_at"])


def _latest(observations: list[Row]) -> list[Row]:
    """The observations made at the latest moment (ties are resolved by the caller)."""
    newest = max(_observation_order(o) for o in observations)
    return [o for o in observations if _observation_order(o) == newest]


def _candidates(store: Store, rid: str, audit_at: str, relaxed: bool, since: str) -> list[Row]:
    """Observations of a resource that may inform its state (not older than the request, not after audit_at)."""
    current = [o for o in store.by_rid.get(rid, []) if (o["observed_at"] or "") >= since and rec_ok(o, audit_at)]
    cand = [o for o in current if file_ok(o, audit_at)]
    if relaxed and all(o["kind"] == "absence_vs_replica" for o in cand):
        return current  # fall back to later-exported files (uncited)
    return cand


def _later_snapshot(out: dict[str, Any], obs: Row, store: Store, rid: str, audit_at: str) -> Row | None:
    """The last snapshot of the observation's system taken after it, in a file that does not list the resource."""
    covering = [
        c
        for c in covering_files(store, out["sys"], obs["observed_at"] or obs["file_captured_at"], audit_at)
        if c["file_id"] != obs["file_id"]
    ]
    if not covering or any(x["file_id"] == covering[-1]["file_id"] for x in store.by_rid.get(rid, [])):
        return None
    return covering[-1]


def _derived_absence(
    out: dict[str, Any], obs: Row, extras: dict[str, Any], store: Store, rid: str, audit_at: str
) -> None:
    """Mark a PRESENT primary-store record as gone when a later snapshot covering its system omits it."""
    snapshot = _later_snapshot(out, obs, store, rid, audit_at)
    # a replica copy is not removed by a later snapshot of the primary store (replication drift)
    in_replica = "replica" in extras.get("table", "")
    if snapshot and not in_replica and obs["category"] in DERIVABLE_CATEGORIES:
        out.update(derived_absent_by=snapshot["file_id"])


def _from_observation(out: dict[str, Any], newest: list[Row], store: Store, rid: str, audit_at: str) -> None:
    """State of the latest observation (a violation wins ties between observations of the same moment)."""
    obs = sorted(newest, key=lambda o: (o["state"] not in NONCOMPLIANT, o["obs_id"]))[0]
    extras = json.loads(obs["extras"] or "{}")
    out.update(
        state=obs["state"],
        category=obs["category"] or out["category"],
        cite=(obs["file_id"] if file_ok(obs, audit_at) else None),
        kind=obs["kind"],
        t=obs["observed_at"],
        ref=obs["source_ref"],
        late=not file_ok(obs, audit_at),
        extras=extras,
        ids=obs["ids"],
    )
    if obs["state"] == "ABSENT":
        out["abs_basis"] = "explicit_404" if obs["kind"].startswith("lookup") else "explicit_other"
    elif obs["state"] == "PRESENT":
        _derived_absence(out, obs, extras, store, rid, audit_at)


def _from_drift(out: dict[str, Any], drift: list[Row]) -> None:
    """The primary store dropped the record but a replica snapshot still lists it: absent, explicitly."""
    obs = drift[-1]
    out.update(
        state="ABSENT",
        category=obs["category"],
        cite=obs["file_id"],
        kind="absence_vs_replica",
        t=obs["observed_at"],
        abs_basis="explicit_other",
        ref=obs["source_ref"],
    )


def _from_activity(out: dict[str, Any], store: Store, rid: str, system: str, audit_at: str, since: str) -> bool:
    """State from activity alone: absent when a covering snapshot omits the resource, else unknown."""
    # activity from before the request belongs to an earlier request of the same person, not to this one
    acts = [a for a in store.act_by_rid.get(rid, []) if since <= a["event_time"] <= audit_at]
    category = out["category"]
    if not (acts and category):
        return False
    covering = covering_files(store, system, min(a["event_time"] for a in acts), audit_at)
    if covering:
        c = covering[-1]
        out.update(
            state="ABSENT",
            category=category,
            cite=c["file_id"],
            kind="covered_omission",
            t=c["scope_time"],
            abs_basis=("empty_collection" if c["level"] == "EMPTY" else "covered_scope_snapshot"),
            ref=c["source_ref"],
        )
    else:
        out.update(state=None, category=category, cite=None, kind="activity_only", abs_basis="omission_only")
    return True


def _base_conclusion(rid: str, system: str, rinfo: Mapping[str, list[tuple[str, float, int, str]]]) -> dict[str, Any]:
    """The part of a conclusion that comes from the links: best link, link types and the id's category."""
    links = rinfo["links"]
    best = max(links, key=lambda link: link[1]) if links else None
    resource = res_of(rid)
    return {
        "rid": rid,
        "sys": system,
        "link_score": best[1] if best else 0,
        "link_type": best[0] if best else None,
        "link_types": sorted({link[0] for link in links}),
        "late": False,
        "category": resource[1] if resource else None,
    }


def conclude(
    rid: str,
    system: str,
    rinfo: Mapping[str, list[tuple[str, float, int, str]]],
    store: Store,
    audit_at: str,
    relaxed: bool = False,
    since: str = "",
) -> dict[str, Any] | None:
    """Conclude the state of one linked resource at audit_at, or None when nothing usable is known.

    Observations older than `since` (the request time) cannot show the state after the deletion workflow ran.
    """
    cand = _candidates(store, rid, audit_at, relaxed, since)
    nodrift = [o for o in cand if o["kind"] != "absence_vs_replica"]
    out = _base_conclusion(rid, system, rinfo)
    if nodrift:
        _from_observation(out, _latest(nodrift), store, rid, audit_at)
        return out
    drift = [o for o in cand if o["kind"] == "absence_vs_replica"]
    if drift:
        _from_drift(out, drift)
        return out
    return out if _from_activity(out, store, rid, system, audit_at, since) else None


def all_conclusions(
    case: Row,
    ident: Identity,
    store: Store,
    settings: LinkSettings | None = None,
    claims: Mapping[str, set[str]] | None = None,
    timing: TimingModel | None = None,
) -> tuple[str, dict[str, Any], Conclusions, set[Any], dict[str, Any]] | None:
    """Link a request, then conclude every linked resource: (user, subject, conclusions, conflicts, clusters)."""
    settings = settings or LinkSettings()
    linked = link_case(case, ident, store, settings, claims, timing)
    if linked is None:
        return None
    since = case["requested_at"] if settings.since_request else ""
    conclusions: Conclusions = {}
    for rid, rinfo in linked.res.items():
        resource = res_of(rid)
        if not resource:
            continue
        concluded = conclude(
            rid, resource[0], rinfo, store, case["audit_at"], relaxed=(settings.mode == "relaxed"), since=since
        )
        if concluded:
            conclusions[(rid, resource[0])] = concluded
    return linked.user, linked.subject, conclusions, linked.conflicts, linked.cluster
