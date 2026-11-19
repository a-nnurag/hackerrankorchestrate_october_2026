"""Evidence-presence (provenance) check: does each cited file really contain what the step claims?

A deterministic second look that does not use the observation table: it reads the raw cited file and asks

  FINDING       the resource id appears in the file, and the file also contains an identifier of the person
                (email, hash, user id or phone valid at audit_at)
  VERIFICATION  (COMPLETE cases) a PRESENT/REDACTED/ANONYMIZED/DISABLED/BLOCKED claim needs the resource id in the
                file; an ABSENT claim needs the resource id with a not-found style marker, or proof that the file
                covers the system (a snapshot scope row, or other rows of that system)
  images/PDFs   cannot be read as text: reported as 'manual' and listed for a person or a vision model

    python code/evaluation/provenance_check.py [output.csv] [--requests dataset/deletion_requests.csv] [--show N]

The exit code is always 0 by design: the report is a triage list, not a gate.
"""

import argparse
import csv
import json
import os
import re
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
CODE = os.path.dirname(HERE)
REPO = os.path.dirname(CODE)
DS = os.path.join(REPO, "dataset")
sys.path.insert(0, CODE)

from ghost.identity import Identity  # noqa: E402

NOT_FOUND = re.compile(
    r"NOT_FOUND|rows=0|\"rows\":\s*0|404|status_code\W+404|total_hits=0|\"total\":\s*0|\"profile\":\s*null"
    r"|result=miss|\bmiss\b",
    re.I,
)
TEXT_SUFFIXES = (".sql", ".json", ".log", ".txt")
RECORD_WINDOW = 900  # characters either side of the resource id that count as "the same record"
MARKER_BEFORE, MARKER_AFTER = 200, 300  # where a not-found marker may sit around an ABSENT claim
MIN_PHONE_DIGITS = 7  # shorter digit strings match too many unrelated numbers

# Outcome labels.  Upper-case ones and those containing NOT are the "unsupported" classes counted in the summary.
IN_ACTIVITY = "activity/audit id (not a file)"
MANUAL = "manual: image/PDF"
FIND_OK = "resource and identifier in file"
FIND_NO_IDENT = "resource in file, no identifier of the person"
FIND_NO_RES = "RESOURCE NOT IN FILE"
ABSENT_MARKER = "absent: resource with a not-found marker"
ABSENT_NO_MARKER = "absent: resource present in file, no marker"
ABSENT_COVERED = "absent: file covers the system"
ABSENT_UNSUPPORTED = "ABSENT NOT SUPPORTED (resource and system not in file)"
STATE_OK = "state claim: resource in file"
STATE_NO_RES = "STATE CLAIM, RESOURCE NOT IN FILE"


def read(path):
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


class RawFiles:
    """Lazily loaded text of cited evidence files; None for images and PDFs, which cannot be read as text."""

    def __init__(self, files):
        self.files = files
        self.cache = {}

    def get(self, file_id):
        if file_id not in self.cache:
            self.cache[file_id] = self._load(os.path.join(DS, self.files[file_id]["file_path"]))
        return self.cache[file_id]

    @staticmethod
    def _load(path):
        if not path.lower().endswith(TEXT_SUFFIXES):
            return None
        with open(path, encoding="utf-8", errors="ignore") as f:
            return f.read()


def person_identifiers(ident, req):
    """Every identifier (user id, emails, hashes, long phones) the person had at audit_at."""
    users = ident.resolve(req["email"], req["audit_at"])
    state = ident.asof(users[0], req["audit_at"]) if users else None
    if not state:
        return set()
    phones = {p for p in state["phones"] if len(p) >= MIN_PHONE_DIGITS}
    return {state["user"]} | state["emails_cur"] | state["emails_hist"] | state["hashes"] | phones


def record_window(low, resource_id):
    """The text around each occurrence of the resource id (an identifier must sit in the same record)."""
    spans = [
        (m.start() - RECORD_WINDOW, m.end() + RECORD_WINDOW) for m in re.finditer(re.escape(resource_id.lower()), low)
    ]
    return " ".join(low[max(0, a) : b] for a, b in spans)


def has_identifier(window, idents):
    digits = re.sub(r"\D", "", window)
    return any(i.lower() in window for i in idents) or any(i.isdigit() and i in digits for i in idents)


def finding_outcome(has_res, has_ident):
    if has_res and has_ident:
        return FIND_OK
    return FIND_NO_IDENT if has_res else FIND_NO_RES


def absent_outcome(step, text, low, has_res):
    """An ABSENT claim needs a not-found marker next to the resource, or proof the file covers the system."""
    rid = step["resource_id"].lower()
    if has_res:
        near = [m.start() for m in re.finditer(re.escape(rid), low)]
        marked = any(NOT_FOUND.search(text[max(0, i - MARKER_BEFORE) : i + MARKER_AFTER]) for i in near)
        return ABSENT_MARKER if marked else ABSENT_NO_MARKER
    if ("snapshot_scope" in low and step["system_id"] in low) or step["system_id"] in low:
        return ABSENT_COVERED
    return ABSENT_UNSUPPORTED


def classify(step, text, idents):
    """Outcome label for one cited step against the raw text of its evidence file."""
    low = text.lower()
    has_res = step["resource_id"].lower() in low
    if step["phase"] == "FINDING":
        has_ident = has_identifier(record_window(low, step["resource_id"]), idents)
        return finding_outcome(has_res, has_ident)
    if step["operation"] == "VERIFY_RECORD_ABSENT":
        return absent_outcome(step, text, low, has_res)
    return STATE_OK if has_res else STATE_NO_RES


def is_unsupported(outcome):
    """Summary-line rule: outcome classes where the raw file does not back the claim."""
    return outcome.upper() == outcome or ("NOT" in outcome and "marker" not in outcome)


def is_listed_bad(outcome):
    """Rows printed in the detail list: the unsupported classes plus weak findings."""
    return outcome.isupper() or ("NOT" in outcome and "marker" not in outcome) or "no identifier" in outcome


def check_step(step, raw_files, idents):
    """Returns the outcome label for a step that cites evidence."""
    ev = step["evidence_id"]
    if ev.startswith(("activity_", "audit_")):
        return IN_ACTIVITY
    text = raw_files.get(ev)
    return MANUAL if text is None else classify(step, text, idents)


def check_rows(rows, reqs, ident, raw_files):
    """Walk the output rows; returns (tally[(phase, op)][outcome] -> count, list of flagged steps)."""
    tally = defaultdict(Counter)
    bad = []
    for row in rows:
        cid = row["case_id"]
        idents = person_identifiers(ident, reqs[cid])
        for s in json.loads(row["steps_json"]):
            if not s["evidence_id"]:
                continue
            outcome = check_step(s, raw_files, idents)
            tally[(s["phase"], s["operation"])][outcome] += 1
            if outcome not in (IN_ACTIVITY, MANUAL) and is_listed_bad(outcome):
                bad.append((cid, s["phase"][0] + ":" + s["operation"], s["resource_id"], s["evidence_id"], outcome))
    return tally, bad


def print_report(output, tally, bad, show):
    print(f"{output}\n")
    grand = Counter()
    for (ph, op), c in sorted(tally.items()):
        print(f"{ph:<13}{op}")
        for k, v in c.most_common():
            print(f"    {v:5}  {k}")
            grand[k] += v
    total = sum(grand.values())
    flagged = sum(v for k, v in grand.items() if is_unsupported(k))
    weak = grand[FIND_NO_IDENT]
    print(
        f"\n{total} cited steps checked; {flagged} not supported by the raw file text, {weak} findings whose "
        f"person-identifier is not in the same record (linked by another route); "
        f"{grand[MANUAL]} cite an image/PDF (needs a person or a vision model)"
    )
    for b in bad[:show]:
        print("   ", *b)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("output", nargs="?", default=os.path.join(REPO, "output.csv"))
    ap.add_argument("--requests", default=os.path.join(DS, "deletion_requests.csv"))
    ap.add_argument("--show", type=int, default=12)
    a = ap.parse_args()
    reqs = {r["case_id"]: r for r in read(a.requests)}
    files = {r["file_id"]: r for r in read(os.path.join(DS, "evidence_files.csv"))}
    tally, bad = check_rows(read(a.output), reqs, Identity(), RawFiles(files))
    print_report(a.output, tally, bad, a.show)
    return 0


if __name__ == "__main__":
    sys.exit(main())
