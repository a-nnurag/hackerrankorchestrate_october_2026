"""Identity linking: which observed resources belong to the person named in a deletion request.

`link_case` runs named steps in a fixed order, each adding (link type, score, observation id, detail) tuples to the
per-resource link lists:

    1. direct identifiers   exact email / user id / hash on the record itself, plus phone and name (weak)
    2. catalog links        the resource catalog states that the resource belongs to the person
    3. attachment links     files whose owner, according to the catalog, is the person
    4. source propagation   a record that cites another resource inherits its owner (both directions)
    5. activity clusters    records with no identifier attached through the deletion worker's log (anchoring.py)
"""

from __future__ import annotations

import collections
from collections.abc import Mapping
from typing import Any, NamedTuple

from .anchoring import anchor_clusters
from .context import CaseContext
from .identity import Identity
from .settings import ROLE_FACTOR, STRONG, LinkSettings
from .store import Row, Store
from .timing import TimingModel

Link = tuple[str, float, int, str]
Resources = dict[str, dict[str, list[Link]]]


class LinkResult(NamedTuple):
    """Outcome of linking one request."""

    user: str
    subject: dict[str, Any]
    res: Resources
    conflicts: set[Any]
    cluster: dict[str, tuple[Row, bool]]


def file_ok(obs: Row, audit_at: str) -> bool:
    """The file holding the observation was exported at or before audit_at (so it may be cited)."""
    return obs["file_captured_at"] <= audit_at


def rec_ok(obs: Row, audit_at: str) -> bool:
    """The record itself was observed at or before audit_at."""
    return (obs["observed_at"] or "") <= audit_at


# identifier type -> (link type, subject key, whether a different value contradicts the person)
_MEMBER_OF_SET = {"hash": ("hash", "hashes", True), "phone": ("phone", "phones", False)}
_EQUAL_TO = {"user": ("user_id", "user", True), "name": ("name_only", "name", False)}


def _classify_identifier(id_type: str, value: str, subject: dict[str, Any]) -> tuple[str | None, bool]:
    """-> (link type or None, conflict).  A conflict is a strong-type identifier that is NOT the person's."""
    if id_type == "email":
        if value in subject["emails_cur"]:
            return "email_current", False
        return ("email_historical", False) if value in subject["emails_hist"] else (None, True)
    if id_type in _MEMBER_OF_SET:
        link_type, key, strict = _MEMBER_OF_SET[id_type]
        matched = value in subject[key]
    elif id_type in _EQUAL_TO:
        link_type, key, strict = _EQUAL_TO[id_type]
        matched = value == subject[key]
    else:
        return None, False
    return (link_type, False) if matched else (None, strict)


def direct_links(obs: Row, subject: dict[str, Any]) -> tuple[list[tuple[str, float, str]], bool]:
    """Links implied by the identifiers printed on one observation, and whether any identifier contradicts them."""
    links: list[tuple[str, float, str]] = []
    conflict = False
    for id_type, value, role in obs["ids"]:
        link_type, mismatch = _classify_identifier(id_type, value, subject)
        if link_type:
            links.append((link_type, ROLE_FACTOR.get(role, 1.0), role))
        conflict = conflict or mismatch
    return links, conflict


def _new_entry() -> dict[str, list[Link]]:
    return {"links": []}


def has_strong(entry: Mapping[str, list[Link]]) -> bool:
    """True when a resource has at least one exact-identifier link."""
    return any(link[0] in STRONG for link in entry["links"])


class CaseLinker:
    """Runs the linking steps for one request and holds their shared state."""

    def __init__(self, ctx: CaseContext) -> None:
        self.ctx = ctx
        audit_at = ctx.audit_at
        relaxed_files = ctx.settings.mode in ("record", "relaxed")
        self.linkable = [
            o for o in ctx.store.obs.values() if rec_ok(o, audit_at) and (file_ok(o, audit_at) or relaxed_files)
        ]
        self.res: Resources = collections.defaultdict(_new_entry)
        self.conflicts: set[Any] = set()
        self._own_emails = ctx.subject["emails_cur"] | ctx.subject["emails_hist"]

    def _add(self, rid: str, link_type: str, obs_id: int, detail: str, factor: float = 1.0) -> None:
        score = self.ctx.settings.link_scores[link_type] * factor
        self.res[rid]["links"].append((link_type, score, obs_id, detail))

    def run(self) -> LinkResult:
        """Run all steps in order and return the links."""
        self.link_direct_identifiers()
        self.link_catalog()
        self.link_attachments()
        for _ in range(2):  # source_resource_id propagation, both directions
            self.propagate_sources()
        cluster: dict[str, tuple[Row, bool]] = {}
        if self.ctx.settings.cluster:
            cluster = self.link_clusters()
        return LinkResult(self.ctx.user, self.ctx.subject, self.res, self.conflicts, cluster)

    def link_direct_identifiers(self) -> None:
        """Step 1: exact identifiers on the observation; observations contradicting the person are conflicts."""
        for obs in self.linkable:
            links, conflict = direct_links(obs, self.ctx.subject)
            if conflict and not any(link_type in STRONG for link_type, _, _ in links):
                self.conflicts.add(obs["obs_id"])
                continue
            for link_type, factor, role in links:
                self._add(obs["resource_id"], link_type, obs["obs_id"], role, factor)

    def _is_mine(self, edge: Row) -> bool:
        """Catalog edge naming one of the person's emails or the person's user id."""
        if edge["id_type"] == "email":
            return edge["value"] in self._own_emails
        return edge["id_type"] == "user" and edge["value"] == self.ctx.user

    def link_catalog(self) -> None:
        """Step 2: the resource catalog links the resource to one of the person's identifiers."""
        audit_at = self.ctx.audit_at
        for edge in self.ctx.store.edges:
            if edge["edge_kind"] == "linked" and edge["event_time"] <= audit_at and self._is_mine(edge):
                self._add(edge["resource_id"], "catalog_link", -1, "activity")

    def _owned_files(self) -> set[str]:
        """File ids that the catalog says belong to the person."""
        store, audit_at = self.ctx.store, self.ctx.audit_at
        return {
            e["value"]
            for e in store.edges
            if e["edge_kind"] == "attachment_owner"
            and e["event_time"] <= audit_at
            and any(self._is_mine(x) for x in store.edges_by_act[e["activity_id"]])
        }

    def link_attachments(self) -> None:
        """Step 3: observations of files that the catalog says the person owns."""
        owned = self._owned_files()
        if not owned:
            return
        for obs in self.linkable:
            if obs["obs_id"] in self.conflicts:
                continue
            if any(id_type == "file" and value in owned for id_type, value, _ in obs["ids"]):
                self._add(obs["resource_id"], "attachment_catalog", obs["obs_id"], "file")

    def _has_source_link(self, rid: str) -> bool:
        return any(link[0] == "source_resource_id" for link in self.res[rid]["links"])

    def propagate_sources(self) -> None:
        """Step 4: a record naming a source resource shares its owner with that resource, in both directions."""
        for obs in self.linkable:
            sources = [value for id_type, value, _ in obs["ids"] if id_type == "resource"]
            if sources:
                self._share_owner_up(obs, sources)
                self._share_owner_down(obs, sources)

    def _share_owner_up(self, obs: Row, sources: list[str]) -> None:
        """The record is the person's, so is the resource it was derived from."""
        own = self.res.get(obs["resource_id"])
        if own and has_strong(own):
            for source in sources:
                if not self._has_source_link(source):
                    self._add(source, "source_resource_id", obs["obs_id"], "source")

    def _share_owner_down(self, obs: Row, sources: list[str]) -> None:
        """The source is the person's, so is the record derived from it."""
        rid = obs["resource_id"]
        for source in sources:
            if source in self.res and has_strong(self.res[source]) and rid not in self.res:
                self._add(rid, "source_resource_id", obs["obs_id"], "source")

    def link_clusters(self) -> dict[str, tuple[Row, bool]]:
        """Step 5: attach activity-cluster members that no exact identifier already settles."""
        strong_rids = {rid for rid, entry in self.res.items() if has_strong(entry)}
        members, kind = anchor_clusters(self.ctx, strong_rids)
        by_rid = self.ctx.store.by_rid
        for rid, (event, contested) in members.items():
            if rid in self.res and has_strong(self.res[rid]):
                continue
            if any(o["obs_id"] in self.conflicts for o in by_rid.get(rid, [])):
                continue
            self._add(rid, "cluster_contested" if contested else kind, -2, event["activity_id"])
        return members


def link_case(
    case: Row,
    ident: Identity,
    store: Store,
    settings: LinkSettings | None = None,
    claims: Mapping[str, set[str]] | None = None,
    timing: TimingModel | None = None,
) -> LinkResult | None:
    """Link observations to the person a request names, as of the request's audit_at.

    Returns None when the email resolves to no known user.  `claims` maps resource ids to the users whose exact
    identifiers claim them (used to keep clusters from taking another person's records); `timing` holds the learned
    second-offset tables.
    """
    settings = settings or LinkSettings()
    users = ident.resolve(case["email"], case["audit_at"])
    if not users:
        return None
    user = users[0]
    subject = ident.asof(user, case["audit_at"])
    ctx = CaseContext(case, user, subject, store, settings, claims, timing or TimingModel())
    return CaseLinker(ctx).run()
