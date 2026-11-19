"""Exact-identifier claims: which user owns which resource, before any weak inference is applied."""

from __future__ import annotations

import collections
from collections.abc import Iterable
from dataclasses import replace

from .identity import Identity
from .linking import has_strong, link_case
from .settings import LinkSettings
from .store import Row, Store


def strong_claims(
    store: Store, ident: Identity, cases: Iterable[Row], settings: LinkSettings | None = None
) -> dict[str, set[str]]:
    """resource_id -> users whose exact identifiers (email, user id, hash, catalog) link them to it.

    Computed from identifiers only (record mode, no clusters) so that the cluster step can refuse to hand a
    resource to a second person.
    """
    identifiers_only = replace(settings or LinkSettings(), mode="record", cluster=False)
    claims: dict[str, set[str]] = collections.defaultdict(set)
    for case in cases:
        linked = link_case(case, ident, store, identifiers_only)
        if not linked:
            continue
        for rid, entry in linked.res.items():
            if has_strong(entry):
                claims[rid].add(linked.user)
    return claims
