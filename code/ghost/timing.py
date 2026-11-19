"""Second-offset pattern: a weak link learned from how the deletion log was written.

Events of one case are written with fixed per-type second offsets: across the strongly linked (account, other
record) pairs the difference of their worker-event times modulo 60 is far from uniform (e.g. search entries: 122 of
138 pairs fall on 21 or 22).  The tables are learned from the data itself (pairs linked by exact identifiers, no
answer key) and only used to choose between candidate accounts that nothing else separates.  They describe how the
log was produced, not a semantic link, so the result is weaker evidence (0.70) and is always flagged for review.
"""

from __future__ import annotations

import collections
import math
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .store import Row, Store
from .timeutil import parse_ts, resource_type

PhaseTable = dict[str, tuple[set[int], float]]


@dataclass(frozen=True)
class TimingModel:
    """The learned offset tables of one audit run (never module state)."""

    phase: PhaseTable = field(default_factory=dict)
    """record type -> (allowed (event_time difference) mod 60 values, share of the true pairs they cover)."""

    anon_phase: frozenset[int] = frozenset()
    """Offsets (mod 60) typical between an account delete event and its analytics anonymize event."""


def worker_time(store: Store, rid: str) -> datetime | None:
    """First deletion-worker event time of a resource, or None."""
    events = [e["event_time"] for e in store.act_by_rid.get(rid, []) if e["source_system"] == "deletion_worker"]
    return parse_ts(min(events)) if events else None


def _is_account(rid: str) -> bool:
    return rid.startswith("account_")


def _rids_by_user(claims: Mapping[str, Iterable[str]]) -> dict[str, list[str]]:
    by_user: dict[str, list[str]] = collections.defaultdict(list)
    for rid, users in claims.items():
        for user in users:
            by_user[user].append(rid)
    return by_user


def _pair_offsets(store: Store, claims: Mapping[str, Iterable[str]]) -> Iterator[tuple[str, int]]:
    """(record type, offset mod 60) for every strongly linked (account, other record) pair of one user."""
    for rids in _rids_by_user(claims).values():
        others = [(r, worker_time(store, r)) for r in rids if not _is_account(r)]
        for account in (r for r in rids if _is_account(r)):
            t_account = worker_time(store, account)
            if t_account is None:
                continue
            for rid, t_other in others:
                if t_other is not None:
                    yield resource_type(rid), int((t_other - t_account).total_seconds()) % 60


def learn_phase(
    store: Store, claims: Mapping[str, Iterable[str]], min_pairs: int = 15, min_share: float = 0.04
) -> PhaseTable:
    """Learn, per record type, the few second offsets at which that type follows its account's delete event."""
    counts: dict[str, collections.Counter[int]] = collections.defaultdict(collections.Counter)
    for rtype, offset in _pair_offsets(store, claims):
        counts[rtype][offset] += 1
    table: PhaseTable = {}
    for rtype, counter in counts.items():
        total = sum(counter.values())
        if total < min_pairs:
            continue
        allowed = {v for v, k in counter.items() if k >= max(3, min_share * total)}
        share = sum(counter[v] for v in allowed) / total
        if len(allowed) <= 6 and share >= 0.6:
            table[rtype] = (allowed, share)
    return table


def _worker_event_times(store: Store, event_type: str, prefix: str) -> list[datetime]:
    return [
        parse_ts(a["event_time"])
        for a in store.act
        if a["source_system"] == "deletion_worker"
        and a["event_type"] == event_type
        and a["resource_id"].startswith(prefix)
    ]


def learn_anon_phase(
    store: Store, lo: int = 600, hi: int = 3600, ratio: float = 5.0, min_count: int = 8
) -> frozenset[int]:
    """Offsets (mod 60) at which an anonymized-analytics worker event follows an account delete event.

    Learned from every (account delete, analytics anonymize) pair 10 to 60 minutes apart in the whole activity
    stream, with no answer key: offsets that occur at least `ratio` times more often than chance.
    """
    accounts = _worker_event_times(store, "DELETE_RECORD", "account_")
    analytics = _worker_event_times(store, "ANONYMIZE_RECORD", "analytics_")
    counter: collections.Counter[int] = collections.Counter()
    for t_analytics in analytics:
        for t_account in accounts:
            gap = (t_analytics - t_account).total_seconds()
            if lo <= gap <= hi:
                counter[int(gap) % 60] += 1
    pairs = sum(counter.values())
    if pairs < 60:
        return frozenset()
    return frozenset(v for v, k in counter.items() if k >= max(min_count, ratio * pairs / 60.0))


def _log_likelihood(candidate: Row, evidence: list[tuple[str, datetime]], phase: PhaseTable) -> float:
    """Log-likelihood ratio that the candidate account is the right one given the observed second offsets."""
    t_account = parse_ts(candidate["event_time"])
    score = 0.0
    for rtype, t_record in evidence:
        allowed, share = phase[rtype]
        share = min(share, 0.97)  # never claim certainty
        chance = len(allowed) / 60.0
        hit = int((t_record - t_account).total_seconds()) % 60 in allowed
        score += math.log(share / chance) if hit else math.log((1 - share) / (1 - chance))
    return score


def phase_pick(
    candidates: list[Row], strong_rids: Iterable[str], store: Store, phase: PhaseTable, margin: float = 2.3
) -> Row | None:
    """Pick the candidate account whose second offsets to the case's strongly linked records fit the pattern.

    Returns None unless the best candidate has positive evidence and beats the runner-up by `margin`.
    """
    evidence: list[tuple[str, datetime]] = []
    for rid in strong_rids:
        if _is_account(rid) or resource_type(rid) not in phase:
            continue
        t_record = worker_time(store, rid)
        if t_record is not None:
            evidence.append((resource_type(rid), t_record))
    if not evidence:
        return None
    scores: list[tuple[float, Row]] = [(_log_likelihood(c, evidence, phase), c) for c in candidates]
    scores.sort(key=lambda pair: -pair[0])
    best = scores[0][0]
    if best > 0 and (len(scores) == 1 or best - scores[1][0] >= margin):
        return scores[0][1]
    return None


def learn_timing(store: Store, claims: Mapping[str, Any] | None, *, cluster: bool, phase: bool) -> TimingModel:
    """Learn both tables as the pipeline needs them (empty when the second-offset resolver is off)."""
    anon = learn_anon_phase(store) if phase else frozenset()
    table = learn_phase(store, claims or {}) if (cluster and phase) else {}
    return TimingModel(phase=table, anon_phase=anon)
