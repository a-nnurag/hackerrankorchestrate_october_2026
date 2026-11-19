"""Consistency checks for the committed image/PDF transcriptions (code/ghost/manual/*.json).

Every id, email and user id we transcribed must be explainable by participant data we did not
transcribe, so a misread character cannot silently create a finding:

  1. resource_id exists in system_activity.csv or sample_output.csv
  2. each user_id exists in user_identities.csv
  3. each email is a current or historical email of a known user (else: flagged, e.g. a decoy)
  4. if a LINK_RESOURCE_IDENTITY activity row names this resource, its email/user_id equal ours
  5. the user in (3)/(4) has a request, and the file was captured at or before that request's audit_at

    python code/evaluation/check_manual.py

The exit code is always 0 by design: flagged entries are a review list, not a gate.
"""

import csv
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CODE = os.path.dirname(HERE)
REPO = os.path.dirname(CODE)
DS = os.path.join(REPO, "dataset")
sys.path.insert(0, CODE)

from ghost.identity import Identity  # noqa: E402

EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
USER_ID = re.compile(r"user_\d+")
LINK_EVENT = "LINK_RESOURCE_IDENTITY"


def rows(name):
    with open(os.path.join(DS, name), encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


class Reference:
    """Participant data the transcriptions are checked against."""

    def __init__(self):
        self.ident = Identity()
        activity = rows("system_activity.csv")
        self.activity_rids = {a["resource_id"] for a in activity}
        with open(os.path.join(DS, "sample_output.csv"), encoding="utf-8") as f:
            self.sample_text = f.read()
        self.links = {a["resource_id"]: a for a in activity if a["event_type"] == LINK_EVENT}
        self.requests = rows("deletion_requests.csv") + rows("sample_deletion_requests.csv")
        self.manifest = {r["file_id"]: r for r in rows("evidence_files.csv")}


def identity_notes(entry, captured, ref):
    """Checks 2 and 3: user ids and emails must belong to known users.  Returns (notes, users found)."""
    notes, users = [], set()
    for u in entry["identifiers"].get("user_ids", []):
        if u not in ref.ident.users:
            notes.append(f"unknown user_id {u}")
        users.add(u)
    for em in entry["identifiers"].get("emails", []):
        found = ref.ident.resolve(em, captured)
        if not found:
            notes.append(f"email {em} matches no identity (decoy or misread)")
        users.update(found)
    return notes, users


def link_notes(entry, link):
    """Check 4: the LINK_RESOURCE_IDENTITY row must name the same email / user id as the transcription."""
    notes = []
    lem = EMAIL.search(link["details"])
    lu = USER_ID.search(link["details"])
    emails = entry["identifiers"].get("emails", [])  # some screens print no email at all (link row only)
    user_ids = entry["identifiers"].get("user_ids")
    if lem and emails and lem.group(0).lower() not in [x.lower() for x in emails]:
        notes.append(f"LINK row names {lem.group(0)}, transcription has {emails}")
    if lu and user_ids and lu.group(0) not in user_ids:
        notes.append(f"LINK row names {lu.group(0)}, transcription has {user_ids}")
    return notes, (lu.group(0) if lu else None)


def request_notes(users, captured, ref):
    """Check 5: a request must belong to one of the users and pre-date the capture.  Returns (notes, cases)."""
    cases = []
    for r in ref.requests:
        resolved = ref.ident.resolve(r["email"], captured)
        if resolved and set(resolved) & users:
            cases.append(r)
    if not cases:
        return ["no request belongs to this user"], cases
    if all(captured > r["audit_at"] for r in cases):
        return [f"captured {captured} is after every related audit_at"], cases
    return [], cases


def entry_notes(entry, captured, ref):
    """All problems found for one transcribed entry, plus the cases it belongs to."""
    rid = entry["resource_id"]
    notes = []
    if rid not in ref.activity_rids and rid not in ref.sample_text:
        notes.append("resource_id not in activity or sample answers")
    id_notes, users = identity_notes(entry, captured, ref)
    notes += id_notes
    link = ref.links.get(rid)
    if link:
        l_notes, linked_user = link_notes(entry, link)
        notes += l_notes
        if linked_user:
            users.add(linked_user)
    req_notes, cases = request_notes(users, captured, ref)
    return notes + req_notes, cases


def format_line(fid, rid, cases, notes):
    head = f"{'OK  ' if not notes else 'FLAG'} {fid} {rid:<16} cases={[r['case_id'] for r in cases]}"
    return head + ("" if not notes else "\n       - " + "\n       - ".join(notes))


def main():
    ref = Reference()
    problems = checked = 0
    for path in sorted(glob.glob(os.path.join(CODE, "ghost", "manual", "evidence_*.json"))):
        with open(path, encoding="utf-8") as f:
            j = json.load(f)
        fid = j["file_id"]
        captured = ref.manifest[fid]["captured_at"]
        for e in j["entries"]:
            notes, cases = entry_notes(e, captured, ref)
            checked += 1
            problems += bool(notes)
            print(format_line(fid, e["resource_id"], cases, notes))
    print(f"\n{checked - problems}/{checked} transcribed entries fully consistent with participant data")
    return 0


if __name__ == "__main__":
    sys.exit(main())
