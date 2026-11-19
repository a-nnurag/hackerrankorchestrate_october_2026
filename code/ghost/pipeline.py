"""End-to-end audit: request row -> (status, steps_json).

Flow per case
    1. classify the request text (deletion or not)
    2. resolve the email to a user and the full identifier set valid at audit_at
    3. link observations (evidence table + activity stream) to that user, with a confidence
    4. conclude each linked resource's state at audit_at
    5. map (category, state) to the policy treatment (rules.py)
    6. build ordered FINDING / REMEDIATION / VERIFICATION steps
    7. validate the output
"""

from __future__ import annotations

import csv
import json
import os
import re
from typing import Any

from .claims import strong_claims
from .classify import classify_request
from .conclusion import all_conclusions
from .conditions import attachment_ownership, message_has_shared_context, retention_expired
from .identity import Identity
from .ingest import DS
from .linking import link_case
from .rules import OP_STATE, PHASE_OPS, PHASE_ORDER, treatment
from .settings import LinkSettings
from .store import Store
from .timing import learn_timing, resource_type

Row = dict[str, Any]
Item = dict[str, Any]
Result = dict[str, Any]

DEFAULTS: dict[str, Any] = {
    "mode": "relaxed",  # strict | record | relaxed   (see settings.LinkSettings.mode)
    "cluster": True,  # use deletion-worker activity clusters as a low-confidence link
    "min_link": 0.45,  # drop items whose best link confidence is below this (0.30 = contested cluster)
    "derive_absence": False,  # off: an explicit observation outranks inference from a later snapshot (case_24)
    "propagate": True,  # remove accounts already assigned to a case from the other cases' candidates
    "phase": True,  # break ties between candidate accounts with the learned second-offset pattern
    "one_per_type": True,  # every public sample has at most one resource per data type per subject
    # ablation switches, forwarded to LinkSettings (see its field documentation)
    "since_request": True,
    "status_filter": True,
    "anchor_window": (-1.3, 0.3),
}

TIMING_LINKS = {"phase_resolved", "cluster_anchored", "activity_cluster"}
STRONG_LINK = 0.90  # exact email / user id / hash / catalog link: the record is certainly this person's
# A person has one account, one tombstone, one analytics profile and one marketing profile at a time (the
# same person's earlier request may have had another account), but can have several search entries,
# support records, exports, connectors, backups or audit records.
SINGLETON_TYPES = {"account", "tombstone", "analytics", "marketing"}
IMAGE_SUFFIXES = (".png", ".pdf", ".jpg", ".jpeg")
PROPAGATION_ROUNDS = 4


def case_key(case_id: str) -> tuple[str, int]:
    """Natural order (case_33 < case_100): the order of dataset/deletion_requests.csv."""
    head, _, num = case_id.rpartition("_")
    return (head, int(num)) if num.isdigit() else (case_id, 0)


def read_csv(path: str) -> list[Row]:
    """Read a CSV file into a list of dicts."""
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def family_of(path: str) -> str:
    """Evidence family: the file name without its date/time stamp.

    service_resource_export_20260915_114455.json -> service_resource_export.json
    """
    name = os.path.basename(path)
    stem, _, ext = name.rpartition(".")
    return re.sub(r"_?\d{8}(?:_\d{6})?", "", stem) + "." + ext


class Auditor:
    """Audits requests one by one against the evidence; construction learns what needs all requests."""

    def __init__(self, all_requests: list[Row], db_path: str | None = None, llm: Any = None, **opts: Any) -> None:
        self.opts = dict(DEFAULTS, **opts)
        self.llm = llm  # optional ghost.llm.LLM used only to adjudicate conflicting request text and conditions
        self.store = Store(db_path)
        self._load_manifest()
        self.ident = Identity()
        self.settings = LinkSettings(
            mode=self.opts["mode"],
            cluster=self.opts["cluster"],
            since_request=self.opts["since_request"],
            status_filter=self.opts["status_filter"],
            phase_resolve=bool(self.opts["phase"]),
            anchor_window=tuple(self.opts["anchor_window"]),
        )
        self.claims = (
            strong_claims(self.store, self.ident, all_requests, self.settings) if self.settings.cluster else None
        )
        self.timing = learn_timing(
            self.store, self.claims, cluster=self.settings.cluster, phase=self.settings.phase_resolve
        )
        if self.settings.cluster and self.settings.phase_resolve and self.opts["propagate"]:
            self._propagate(all_requests)

    def _load_manifest(self) -> None:
        manifest = read_csv(os.path.join(DS, "evidence_files.csv"))
        self.family = {r["file_id"]: family_of(r["file_path"]) for r in manifest}
        self.manual_files = {r["file_id"] for r in manifest if r["file_path"].lower().endswith(IMAGE_SUFFIXES)}
        # families the public sample answers cite: the ground we have validated
        self.sample_families: set[str] = set()
        gold = os.path.join(DS, "sample_output.csv")
        if os.path.exists(gold):
            for row in read_csv(gold):
                for step in json.loads(row["steps_json"]):
                    if step["evidence_id"] in self.family:
                        self.sample_families.add(self.family[step["evidence_id"]])

    def _propagate(self, all_requests: list[Row]) -> None:
        """One account belongs to one person: once a case's account is chosen by the second-offset pattern it is
        removed from the candidates of every other case, which can resolve those cases in the next round
        (the assignment constraint of record linkage).  Stops when a round adds nothing."""
        for _ in range(PROPAGATION_ROUNDS):
            if not self._propagation_round(all_requests):
                break

    def _propagation_round(self, all_requests: list[Row]) -> int:
        """Claim every phase-resolved account for its case's user; returns how many claims were new."""
        assert self.claims is not None
        new = 0
        for case in all_requests:
            linked = link_case(case, self.ident, self.store, self.settings, self.claims, self.timing)
            if not linked:
                continue
            for rid, entry in linked.res.items():
                resolved = any(link[0] == "phase_resolved" for link in entry["links"])
                if rid.startswith("account_") and resolved and linked.user not in self.claims[rid]:
                    self.claims[rid].add(linked.user)
                    new += 1
        return new

    def _activity_cite(self, rid: str, audit_at: str) -> str | None:
        acts = [a for a in self.store.act_by_rid.get(rid, []) if a["event_time"] <= audit_at]
        return max(acts, key=lambda a: a["event_time"])["activity_id"] if acts else None

    def _condition(
        self, c: Row, state: str, case: Row, subject: Row, rid: str, notes: list[str], review: list[str]
    ) -> str:
        """Apply the conditions of rules 05, 06, 12, 13 (rules first, optional LLM for free text)."""
        cat = c["category"]
        if cat in ("SECURITY_AUDIT_LOG", "LEGAL_HOLD_RECORD") and state == "PRESENT":
            if retention_expired(cat, c.get("extras"), case["audit_at"]):
                review.append(f"retention_expired:{rid}")
                notes.append(f"{rid}: retention/hold ended before audit_at, so it is no longer retained")
                return "EXPIRED"
        elif cat == "SUPPORT_ATTACHMENT" and state == "PRESENT":
            emails = subject["emails_cur"] | subject["emails_hist"]
            owner, why = attachment_ownership(c, emails, self.store, rid, case["audit_at"], self.llm)
            if owner == "shared":
                review.append(f"attachment_not_subject_only:{rid}")
                notes.append(f"{rid}: {why}")
                return "SHARED"
        elif cat == "SUPPORT_MESSAGE" and state == "IDENTIFIABLE":
            shared, why = message_has_shared_context(c, self.llm)
            if not shared:
                review.append(f"message_without_shared_context:{rid}")
                notes.append(f"{rid}: {why}")
                return "NO_SHARED_CONTEXT"
        return state

    def _build_item(
        self, rid: str, sysid: str, c: Row, case: Row, subject: Row, notes: list[str], review: list[str]
    ) -> Item | None:
        """Turn one concluded resource into a report item, or None when it yields no step."""
        state = c.get("state")
        if not state:
            return None
        cat = c["category"]
        cite = c.get("cite")
        if self.opts["derive_absence"] and c.get("derived_absent_by"):
            state, cite = "ABSENT", c["derived_absent_by"]
        state = self._condition(c, state, case, subject, rid, notes, review)
        tr = treatment(cat, state)
        if tr is None:
            return None
        sysid = c.get("sys") or sysid
        if not cite and tr["kind"] == "violation":
            # the state comes from a file exported after audit_at, which must not be cited:
            # fall back to the deletion-worker activity row that touched this resource
            cite = self._activity_cite(rid, case["audit_at"])
            if cite:
                notes.append(f"{rid}: finding cites activity {cite} (state file exported after audit_at)")
        if c["link_score"] < self.opts["min_link"]:
            review.append(f"low_link:{rid}:{c['link_type']}:{c['link_score']:.2f}")
            return None
        return {
            "rid": rid,
            "sys": sysid,
            "cat": cat,
            "state": state,
            "cite": cite,
            "tr": tr,
            "score": c["link_score"],
            "link": c["link_type"],
            "abs": c.get("abs_basis"),
        }

    def _collect_items(
        self, concl: dict[tuple[str, str], Row], case: Row, subject: Row, notes: list[str], review: list[str]
    ) -> list[Item]:
        items = []
        for (rid, sysid), c in sorted(concl.items()):
            item = self._build_item(rid, sysid, c, case, subject, notes, review)
            if item:
                items.append(item)
        return keep_best_per_type(items, review) if self.opts["one_per_type"] else items

    def _evidence_flags(self, steps: list[Row], review: list[str]) -> list[str]:
        """Review flags about the evidence the steps cite; returns the evidence families used."""
        used = sorted({s["evidence_id"] for s in steps if s["evidence_id"] in self.manual_files})
        if used:  # evidence read by a vision model, not parsed from text: always worth a human look
            review.append("relies_on_transcribed_image_or_pdf:" + ",".join(used))
        fams = sorted({self.family[x["evidence_id"]] for x in steps if x["evidence_id"] in self.family})
        unseen = [f for f in fams if f not in self.sample_families and not f.endswith((".png", ".pdf"))]
        if unseen:  # parsed by code that no sample answer exercises: review these first
            review.append("evidence_family_not_in_samples:" + ",".join(unseen))
        return fams

    def audit(self, case: Row) -> Result:
        """Audit one request -> dict(status, steps, notes, review, items, contested, families)."""
        notes: list[str] = []
        review: list[str] = []
        is_deletion, why = classify_request(case["request_text"], self.llm)
        if why.startswith("CONFLICT"):
            review.append("request_text_conflict")
        notes.append(f"classify: {why}")
        if not is_deletion:
            return {"status": "NOT_APPLICABLE", "steps": [], "notes": notes, "review": review}

        res = all_conclusions(case, self.ident, self.store, self.settings, self.claims, self.timing)
        if res is None:
            notes.append("email did not resolve to a known user")
            return {"status": "COMPLETE", "steps": [], "notes": notes, "review": ["unresolved_identity"]}
        user, subject, concl, _conflicts, clusters = res
        notes.append(f"user={user} linked_resources={len(concl)}")

        items = self._collect_items(concl, case, subject, notes, review)
        status, steps, fams = self._decide(items, review)
        contested = tuple(sorted(rid for rid, (_a, flag) in clusters.items() if flag and rid.startswith("account_")))
        if contested:
            review.append(f"contested_accounts:{len(contested)}")
        return {
            "status": status,
            "steps": steps,
            "notes": notes,
            "review": review,
            "items": items,
            "contested": contested,
            "families": fams,
        }

    def _decide(self, items: list[Item], review: list[str]) -> tuple[str, list[Row], list[str]]:
        """Items -> (status, steps, evidence families), appending the review flags the decision raises."""
        for it in items:  # linked only through the pattern of event times, never through an identifier
            if it["link"] in TIMING_LINKS:
                review.append(f"inferred_by_timing:{it['rid']}:{it['link']}")
        status = "INCOMPLETE" if any(i["tr"]["kind"] == "violation" for i in items) else "COMPLETE"
        steps = build_steps(items, status, review)
        if status == "COMPLETE" and not steps:
            review.append("no_usable_evidence")  # nothing at or before audit_at could be verified
        return status, steps, self._evidence_flags(steps, review)


def keep_best_per_type(items: list[Item], review: list[str]) -> list[Item]:
    """Limit guesses to one resource per resource type (account, search, analytics, ...) per subject.

    Every public answer has at most one resource per type, so singleton types (account, tombstone,
    analytics, marketing) keep only the best candidate.  For types a person can have several of
    (search, support, export, data flow, backup, audit record), records linked by an exact identifier
    are never dropped: dropping one would hide a leak.  Weaker candidates of such a type are dropped
    when a strong one exists, otherwise the single best is kept.
    """
    groups: dict[str, list[Item]] = {}
    for it in items:
        groups.setdefault(resource_type(it["rid"]), []).append(it)
    kept: list[Item] = []
    for rtype, grp in sorted(groups.items()):
        strong = [i for i in grp if i["score"] >= STRONG_LINK] if rtype not in SINGLETON_TYPES else []
        if strong:
            kept.extend(strong)
            rest = [i for i in grp if i["score"] < STRONG_LINK]
        else:
            grp.sort(key=lambda i: (-round(i["score"], 6), i["tr"]["kind"] != "violation", i["rid"]))
            kept.append(grp[0])
            rest = grp[1:]
        for dropped in rest:
            review.append(f"dropped_extra_{rtype}:{dropped['rid']}:{dropped['link']}:{dropped['score']:.2f}")
    return kept


def _raw_steps(items: list[Item], status: str, review: list[str]) -> list[tuple[str, str, str, str, str]]:
    """(phase, operation, system, resource, evidence) for every step the items call for, unordered."""
    raw = []
    for it in items:
        tr = it["tr"]
        if tr["kind"] == "violation":
            if not it["cite"]:
                review.append(f"violation_without_citable_evidence:{it['rid']}")
                continue
            raw.append(("FINDING", tr["finding"], it["sys"], it["rid"], it["cite"]))
            raw.append(("REMEDIATION", tr["remediation"], it["sys"], it["rid"], ""))
            raw.append(("VERIFICATION", tr["verification"], it["sys"], it["rid"], ""))
        elif status == "COMPLETE":
            if not it["cite"]:
                review.append(f"complete_verification_without_citation:{it['rid']}")
                continue
            raw.append(("VERIFICATION", tr["verification"], it["sys"], it["rid"], it["cite"]))
        else:
            raw.append(("VERIFICATION", tr["verification"], it["sys"], it["rid"], ""))
    return raw


def build_steps(items: list[Item], status: str, review: list[str]) -> list[Row]:
    """Ordered step list.  Sort key: (phase, operation order, system_id, resource_id)."""
    seen: dict[tuple[str, str, str, str], str] = {}
    for phase, op, sysid, rid, evidence in _raw_steps(items, status, review):
        seen.setdefault((phase, op, sysid, rid), evidence)
    ordered = sorted(seen, key=lambda k: (PHASE_ORDER.index(k[0]), PHASE_OPS[k[0]].index(k[1]), k[2], k[3]))
    return [
        {
            "step_no": n,
            "phase": phase,
            "system_id": sysid,
            "resource_id": rid,
            "operation": op,
            "state": OP_STATE[op],
            "evidence_id": seen[(phase, op, sysid, rid)],
        }
        for n, (phase, op, sysid, rid) in enumerate(ordered, 1)
    ]


def _check_steps(case: Row, steps: list[Row], manifest_cap: dict[str, str]) -> list[str]:
    """Invariants every step list must satisfy whatever the status."""
    errs = []
    phases = [s["phase"] for s in steps]
    if phases != sorted(phases, key=PHASE_ORDER.index):
        errs.append("phases out of order")
    for i, s in enumerate(steps, 1):
        if s["step_no"] != i:
            errs.append(f"step_no gap at {i}")
        if s["state"] != OP_STATE.get(s["operation"]):
            errs.append(f"bad state for {s['operation']}")
        if s["operation"] not in PHASE_OPS[s["phase"]]:
            errs.append(f"operation {s['operation']} not allowed in {s['phase']}")
        ev = s["evidence_id"]
        if ev and ev.startswith("evidence_") and manifest_cap.get(ev, "9999") > case["audit_at"]:
            errs.append(f"evidence {ev} captured after audit_at")
    return errs


def _check_complete(steps: list[Row]) -> list[str]:
    errs = []
    if any(s["phase"] != "VERIFICATION" for s in steps):
        errs.append("COMPLETE must contain only VERIFICATION steps")
    if any(not s["evidence_id"] for s in steps):
        errs.append("COMPLETE verification without evidence_id")
    return errs


def _check_incomplete(steps: list[Row]) -> list[str]:
    errs = []
    if not any(s["phase"] == "FINDING" for s in steps):
        errs.append("INCOMPLETE without finding")
    for s in steps:
        if s["phase"] == "FINDING" and not s["evidence_id"]:
            errs.append("finding without evidence_id")
        if s["phase"] != "FINDING" and s["evidence_id"]:
            errs.append(f"{s['phase']} step with evidence_id")
    return errs


def _check_status(status: str, steps: list[Row]) -> list[str]:
    """Invariants tying the steps to the COMPLETE / INCOMPLETE status."""
    if status == "COMPLETE":
        return _check_complete(steps)
    if status == "INCOMPLETE":
        return _check_incomplete(steps)
    return []


def validate(case: Row, result: Result, manifest_cap: dict[str, str]) -> list[str]:
    """Return a list of invariant violations (empty list = valid)."""
    status, steps = result["status"], result["steps"]
    if status == "NOT_APPLICABLE":
        return ["NOT_APPLICABLE must have empty steps"] if steps else []
    return _check_steps(case, steps, manifest_cap) + _check_status(status, steps)


def load_manifest_caps() -> dict[str, str]:
    """file_id -> capture timestamp, from the evidence manifest."""
    return {r["file_id"]: r["captured_at"] for r in read_csv(os.path.join(DS, "evidence_files.csv"))}


def run_requests(requests: list[Row], auditor: Auditor) -> list[Result]:
    """Audit and validate every request in natural case order."""
    caps = load_manifest_caps()
    rows = []
    for case in sorted(requests, key=lambda r: case_key(r["case_id"])):
        res = auditor.audit(case)
        res["errors"] = validate(case, res, caps)
        res["case_id"] = case["case_id"]
        rows.append(res)
    return rows


def write_output(rows: list[Result], path: str) -> None:
    """Write the deliverable CSV (case_id, deletion_status, steps_json)."""
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["case_id", "deletion_status", "steps_json"])
        for r in rows:
            w.writerow([r["case_id"], r["status"], json.dumps(r["steps"], ensure_ascii=False, separators=(",", ":"))])


def _review_tier(flags: list[str], contested: tuple[str, ...]) -> int:
    """Review priority: 1 image/PDF evidence, 2 unseen evidence family, 3 contested or timing-inferred, 4 other."""
    if any(f.startswith("relies_on_transcribed") for f in flags):
        return 1
    if any(f.startswith("evidence_family_not_in_samples") for f in flags):
        return 2
    if contested or any(f.startswith("inferred_by_timing") for f in flags):
        return 3
    return 4


def _review_entries(rows: list[Result]) -> list[tuple[Any, ...]]:
    """(tier, #candidates, #sharing cases, case_id, row, candidates, sharing) for every row with flags, sorted."""
    sharing: dict[tuple[str, ...], int] = {}
    for r in rows:
        if r.get("contested"):
            sharing[r["contested"]] = sharing.get(r["contested"], 0) + 1
    out = []
    for r in rows:
        flags = r["review"] + r["errors"]
        if not flags:
            continue
        contested = r.get("contested") or ()
        shared = sharing.get(contested, 0)
        out.append(
            (_review_tier(flags, contested), len(contested) or 99, shared or 99, r["case_id"], r, contested, shared)
        )
    out.sort(key=lambda x: (x[0], x[1], x[2], case_key(x[3])))
    return out


def write_review(rows: list[Result], path: str) -> int:
    """Review list ordered by what a human should look at first; returns the number of cases listed.

    tier 1  evidence read from an image or PDF (transcription, never parsed)
    tier 2  evidence family no public sample answer cites (parser untested against a gold answer)
    tier 3  contested accounts, easiest decision first: fewest candidate accounts, then fewest cases
            competing for the same candidates (one case with two candidates is a coin flip you can settle
            by looking at the source data)
    tier 4  any other note
    """
    out = _review_entries(rows)
    header = [
        "rank",
        "tier",
        "case_id",
        "status",
        "candidate_accounts",
        "cases_sharing_them",
        "families",
        "notes_and_review_flags",
    ]
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(header)
        for rank, (tier, _k, _g, case_id, r, contested, shared) in enumerate(out, 1):
            families = ";".join(r.get("families", []))
            flags = "; ".join(r["notes"] + r["review"] + r["errors"])
            w.writerow([rank, tier, case_id, r["status"], len(contested) or "", shared or "", families, flags])
    return len(out)
