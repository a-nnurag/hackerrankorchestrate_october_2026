"""Independent contract validator for an output CSV (separate code from the pipeline's own checks).

    python code/evaluation/validate_output.py [output.csv] [--requests dataset/deletion_requests.csv] [--gold]

Checks everything problem_statement.md and AGENTS.md section 6.3-6.6 state about the file, plus
structural rules observed in every public answer.  The validator is itself tested by running it on
dataset/sample_output.csv (known-good): it must report 0 violations there (`--gold`).

Contract checks
  file       header exactly case_id,deletion_status,steps_json; one row per request; no duplicates;
             rows in the order of the requests file (natural case order); status in the allowed set
  steps      valid JSON array; exactly the 7 keys; step_no 1..n; types; phase/operation/state allowed
             together; steps ordered by (phase, operation order, system_id, resource_id); no duplicates
  evidence   findings and COMPLETE verifications cite a known file_id/activity_id/audit_id; remediation and
             INCOMPLETE verification use ""; no cited file captured (or activity logged) after audit_at
  status     NOT_APPLICABLE -> []; COMPLETE -> only VERIFICATION; INCOMPLETE -> findings present
Structural rules seen in all public answers
  every finding has a remediation and a verification on the same (system, resource), every remediation has
  a verification; retained categories (audit_record, legal_hold, backup, tombstone) are never deleted;
  no DELETE on a backup/audit/legal/tombstone record; at most one account, tombstone, analytics and
  marketing resource per case (a person can have several search/support/export/connector/audit records)

Layout: constants first, then one small function per rule family (file_errors, step_errors, status_errors,
pairing_errors, singleton_errors); validate() only wires them together.  Every rule returns a list of
(case_id, message) pairs, so a rule can be tested on its own and the rule set stays easy to audit.
"""

import argparse
import csv
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CODE = os.path.dirname(HERE)
REPO = os.path.dirname(CODE)
DS = os.path.join(REPO, "dataset")

HEADER = ["case_id", "deletion_status", "steps_json"]
STATUSES = ("COMPLETE", "INCOMPLETE", "NOT_APPLICABLE")
MAX_SHOWN = 40  # violations printed before "... N more"
PHASES = ["FINDING", "REMEDIATION", "VERIFICATION"]
OPS = {
    "FINDING": ["REPORT_REMAINING_RECORD", "REPORT_EXPOSED_PII", "REPORT_ACTIVE_DATA_FLOW", "REPORT_RESTORE_RISK"],
    "REMEDIATION": ["DISABLE_DATA_FLOW", "BLOCK_RESTORE", "DELETE_RECORD", "REDACT_RECORD", "ANONYMIZE_RECORD"],
    "VERIFICATION": [
        "VERIFY_RECORD_ABSENT",
        "VERIFY_RECORD_PRESENT",
        "VERIFY_RECORD_REDACTED",
        "VERIFY_RECORD_ANONYMIZED",
        "VERIFY_DATA_FLOW_DISABLED",
        "VERIFY_RESTORE_BLOCKED",
    ],
}
STATE = {
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
KEYS = {"step_no", "phase", "system_id", "resource_id", "operation", "state", "evidence_id"}
NEVER_DELETE = ("audit_record_", "legal_hold_", "backup_", "tombstone_")
SINGLETON_TYPES = ("account", "tombstone", "analytics", "marketing")
# remediation that goes with each finding, and the verification that goes with each remediation
FINDING_TO_REMEDIATION = {
    "REPORT_REMAINING_RECORD": "DELETE_RECORD",
    "REPORT_ACTIVE_DATA_FLOW": "DISABLE_DATA_FLOW",
    "REPORT_RESTORE_RISK": "BLOCK_RESTORE",
}
REMEDIATION_TO_VERIFY = {
    "DELETE_RECORD": "VERIFY_RECORD_ABSENT",
    "DISABLE_DATA_FLOW": "VERIFY_DATA_FLOW_DISABLED",
    "BLOCK_RESTORE": "VERIFY_RESTORE_BLOCKED",
    "REDACT_RECORD": "VERIFY_RECORD_REDACTED",
    "ANONYMIZE_RECORD": "VERIFY_RECORD_ANONYMIZED",
}
# phase -> (phase of its partner step, operation -> partner operation)
PAIRING = {
    "FINDING": ("REMEDIATION", FINDING_TO_REMEDIATION),
    "REMEDIATION": ("VERIFICATION", REMEDIATION_TO_VERIFY),
}


def ds_path(name):
    return os.path.join(DS, name)


def read(path):
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.reader(f))


def read_dicts(path):
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def case_key(c):
    head, _, num = c.rpartition("_")
    return (head, int(num)) if num.isdigit() else (c, 0)


class EvidenceTimes:
    """When each citable id was captured (evidence file) or logged (activity row, audit row)."""

    def __init__(self, manifest_path=None, activity_path=None):
        manifest = read_dicts(manifest_path or ds_path("evidence_files.csv"))
        activity = read_dicts(activity_path or ds_path("system_activity.csv"))
        self.files = {r["file_id"]: r["captured_at"] for r in manifest}
        self.activity = {r["activity_id"]: r["event_time"] for r in activity}
        self.audits = {r["audit_id"]: r["event_time"] for r in read_dicts(ds_path("user_audit_log.csv"))}

    def when(self, evidence_id):
        return self.files.get(evidence_id) or self.activity.get(evidence_id) or self.audits.get(evidence_id)


class StepOrder:
    """Running state while walking one case's steps: previous sort key and identities already seen."""

    def __init__(self):
        self.last = None
        self.seen = set()


# ---------------------------------------------------------------- file-level rules


def file_errors(body, reqs, by_req):
    """Rules about the CSV as a whole: columns, duplicates, id set, order and row count."""
    errs = []
    ids = [r[0] for r in body]
    if any(len(r) != 3 for r in body):
        errs.append(("file", "a row does not have exactly 3 columns"))
    if len(set(ids)) != len(ids):
        errs.append(("file", "duplicate case_id rows"))
    if set(ids) != set(by_req):
        missing, extra = sorted(set(by_req) - set(ids))[:3], sorted(set(ids) - set(by_req))[:3]
        errs.append(("file", f"case ids differ from requests: missing {missing}, extra {extra}"))
    if ids != sorted(ids, key=case_key):
        errs.append(("file", "rows are not in natural case order"))
    if len(body) != len(reqs):
        errs.append(("file", f"{len(body)} rows for {len(reqs)} requests"))
    return errs


# ---------------------------------------------------------------- per-step rules


def shape_errors(cid, i, s):
    """Key set, step_no and value types.  Returns (errors, can_continue); a wrong key set stops the step's checks."""
    if not isinstance(s, dict) or set(s) != KEYS:
        return [(cid, f"step {i}: keys {sorted(s) if isinstance(s, dict) else type(s)}")], False
    errs = []
    if s["step_no"] != i or isinstance(s["step_no"], bool):
        errs.append((cid, f"step_no {s['step_no']} at position {i}"))
    # sorted: a bare set difference has no stable order and the report must be reproducible
    errs += [(cid, f"step {i}: {k} is not a string") for k in sorted(KEYS - {"step_no"}) if not isinstance(s[k], str)]
    return errs, True


def order_errors(cid, i, s, track):
    """Steps must be sorted by (phase, operation order, system, resource) and must not repeat."""
    ph, op = s["phase"], s["operation"]
    errs = []
    key = (PHASES.index(ph), OPS[ph].index(op), s["system_id"], s["resource_id"])
    if track.last is not None and key < track.last:
        errs.append((cid, f"step {i}: out of order {key} after {track.last}"))
    track.last = key
    ident = (ph, op, s["system_id"], s["resource_id"])
    if ident in track.seen:
        errs.append((cid, f"step {i}: duplicate {ident}"))
    track.seen.add(ident)
    return errs


def evidence_errors(cid, i, s, status, audit_at, times):
    """Evidence is required for findings and COMPLETE verifications, forbidden elsewhere, and must pre-date audit_at."""
    errs = []
    ph, ev = s["phase"], s["evidence_id"]
    needs = ph == "FINDING" or (ph == "VERIFICATION" and status == "COMPLETE")
    if needs and not ev:
        errs.append((cid, f"step {i}: {ph} in {status} without evidence_id"))
    if not needs and ev:
        errs.append((cid, f"step {i}: {ph} in {status} must have empty evidence_id"))
    if ev:
        when = times.when(ev)
        if when is None:
            errs.append((cid, f"step {i}: unknown evidence id {ev}"))
        elif when > audit_at:
            errs.append((cid, f"step {i}: {ev} dated {when} is after audit_at {audit_at}"))
    return errs


def step_errors(cid, i, s, status, audit_at, times, track):
    errs, proceed = shape_errors(cid, i, s)
    if not proceed:
        return errs
    ph, op = s["phase"], s["operation"]
    if ph not in PHASES or op not in OPS.get(ph, []):
        return errs + [(cid, f"step {i}: operation {op} not allowed in {ph}")]
    if s["state"] != STATE[op]:
        errs.append((cid, f"step {i}: state {s['state']} for {op}"))
    errs += order_errors(cid, i, s, track)
    errs += evidence_errors(cid, i, s, status, audit_at, times)
    if op == "DELETE_RECORD" and s["resource_id"].startswith(NEVER_DELETE):
        errs.append((cid, f"step {i}: {s['resource_id']} must be retained, not deleted"))
    return errs


# ---------------------------------------------------------------- per-case rules


def status_errors(cid, status, steps):
    """What each overall status allows: COMPLETE only verifications, INCOMPLETE needs a finding."""
    phases = {s["phase"] for s in steps if isinstance(s, dict) and "phase" in s}
    errs = []
    if status == "COMPLETE" and phases - {"VERIFICATION"}:
        errs.append((cid, "COMPLETE contains non-verification steps"))
    if status == "INCOMPLETE" and "FINDING" not in phases:
        errs.append((cid, "INCOMPLETE without a finding"))
    if status == "COMPLETE" and not steps:
        errs.append((cid, "COMPLETE with no verification steps"))
    return errs


def pairing_errors(cid, steps):
    """Every finding has its remediation and every remediation its verification on the same resource."""
    have = {
        (s["phase"], s["operation"], s["system_id"], s["resource_id"])
        for s in steps
        if isinstance(s, dict) and set(s) >= KEYS
    }
    errs = []
    for ph, op, sy, rid in sorted(have, key=repr):  # sorted: set order would make the report vary between runs
        next_phase, table = PAIRING.get(ph, (None, {}))
        partner = table.get(op)
        if partner and (next_phase, partner, sy, rid) not in have:
            errs.append((cid, f"{op} on {rid} has no {partner}"))
    return errs


def singleton_errors(cid, steps):
    """At most one account, tombstone, analytics and marketing resource per case."""
    types = {}
    for s in steps:
        if isinstance(s, dict) and "resource_id" in s:
            types.setdefault(s["resource_id"].rsplit("_", 1)[0], set()).add(s["resource_id"])
    return [
        (cid, f"{len(rs)} resources of singleton type {t}: {sorted(rs)}")
        for t, rs in types.items()
        if len(rs) > 1 and t in SINGLETON_TYPES
    ]


def parse_steps(cid, status, raw):
    """Decode steps_json.  Returns (steps, errors); steps is None when the case cannot be checked further."""
    if status not in STATUSES:
        return None, [(cid, f"bad status {status!r}")]
    try:
        steps = json.loads(raw)
    except ValueError:
        return None, [(cid, "steps_json is not valid JSON")]
    if not isinstance(steps, list):
        return None, [(cid, "steps_json is not an array")]
    return steps, []


def case_errors(row, req, times):
    cid, status, raw = row
    steps, errs = parse_steps(cid, status, raw)
    if steps is None:
        return errs
    if status == "NOT_APPLICABLE":
        return [(cid, "NOT_APPLICABLE must be []")] if steps else []
    audit_at = req["audit_at"] if req else "9999"  # unknown case: no time limit (file_errors reports the id)
    track = StepOrder()
    for i, s in enumerate(steps, 1):
        errs += step_errors(cid, i, s, status, audit_at, times, track)
    return errs + status_errors(cid, status, steps) + pairing_errors(cid, steps) + singleton_errors(cid, steps)


def validate(out_path, req_path, activity_path=None, manifest_path=None):
    times = EvidenceTimes(manifest_path, activity_path)
    reqs = read_dicts(req_path)
    by_req = {r["case_id"]: r for r in reqs}
    rows = read(out_path)
    if not rows or rows[0] != HEADER:
        return [("file", f"header is {rows[0] if rows else None}")]
    body = rows[1:]
    errs = file_errors(body, reqs, by_req)
    for r in body:
        if len(r) == 3:
            errs += case_errors(r, by_req.get(r[0]), times)
    return errs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("output", nargs="?", default=os.path.join(REPO, "output.csv"))
    ap.add_argument("--requests", default=ds_path("deletion_requests.csv"))
    ap.add_argument(
        "--gold", action="store_true", help="validate dataset/sample_output.csv against the sample requests"
    )
    a = ap.parse_args()
    if a.gold:
        out, req = ds_path("sample_output.csv"), ds_path("sample_deletion_requests.csv")
    else:
        out, req = a.output, a.requests
    errs = validate(out, req)
    print(f"{out}: {len(errs)} violations")
    for cid, msg in errs[:MAX_SHOWN]:
        print(f"  {cid}: {msg}")
    if len(errs) > MAX_SHOWN:
        print(f"  ... {len(errs) - MAX_SHOWN} more")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
