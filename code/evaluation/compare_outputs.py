"""Differential test: compare two output CSVs produced by independent implementations.

    python code/evaluation/compare_outputs.py output.csv other_output.csv [--out diff.csv]
        [--requests dataset/deletion_requests.csv] [--names ours,other]

Every disagreement is a likely bug in one of the two implementations (or a genuinely ambiguous rule).
Cases are ranked for triage:
    1  status differs            (a different verdict)
    2  findings differ           (a different leak or recreation risk reported)
    3  only verification differs (extra or missing 'already compliant' checks)
    4  only evidence_id differs  (same steps, different citation)
The agreement figures are NOT accuracy: two implementations can agree and both be wrong.  They show
where to look, and a high agreement on a family is weak evidence that its parser is right.
"""

import argparse
import csv
import json
import os
import sys
from collections import namedtuple

HERE = os.path.dirname(os.path.abspath(__file__))
CODE = os.path.dirname(HERE)
REPO = os.path.dirname(CODE)
sys.path.insert(0, CODE)

from ghost import pipeline  # noqa: E402

TIERS = (1, 2, 3, 4)
REQUEST_TEXT_CHARS = 120  # how much of the request text goes into the triage csv

# One compared case.  only_a / only_b are sorted step keys, ev_diff the keys cited differently.
CaseDiff = namedtuple("CaseDiff", "cid status_a status_b ka kb only_a only_b ev_diff")
# One differing case, ready for the triage csv.
Row = namedtuple("Row", "tier cid status_a status_b only_a only_b ev_diff fams")


def load(path):
    with open(path, encoding="utf-8", newline="") as f:
        return {r["case_id"]: (r["deletion_status"], json.loads(r["steps_json"])) for r in csv.DictReader(f)}


def key(s):
    return (s["phase"], s["operation"], s["system_id"], s["resource_id"])


def short(s):
    return f"{s['phase'][0]}:{s['operation'].replace('VERIFY_RECORD_', 'V_').replace('REPORT_', '')}:{s['resource_id']}"


def diff_case(cid, a, b):
    (sa, xa), (sb, xb) = a, b
    ka, kb = {key(s): s for s in xa}, {key(s): s for s in xb}
    only_a, only_b = sorted(set(ka) - set(kb)), sorted(set(kb) - set(ka))
    ev_diff = [k for k in set(ka) & set(kb) if ka[k]["evidence_id"] != kb[k]["evidence_id"]]
    return CaseDiff(cid, sa, sb, ka, kb, only_a, only_b, ev_diff)


def is_identical(d):
    return d.status_a == d.status_b and not d.only_a and not d.only_b and not d.ev_diff


def tier_of(d):
    """Triage rank, 1 (different verdict) to 4 (only a different citation)."""
    if d.status_a != d.status_b:
        return 1
    if any(k[0] == "FINDING" for k in d.only_a + d.only_b):
        return 2
    return 3 if (d.only_a or d.only_b) else 4


def families_of(a_steps, b_steps, manifest):
    return sorted({manifest.get(s["evidence_id"], "") for s in a_steps + b_steps if s["evidence_id"] in manifest})


def to_row(d, tier, manifest, a_steps, b_steps):
    return Row(
        tier,
        d.cid,
        d.status_a,
        d.status_b,
        [short(d.ka[k]) for k in d.only_a],
        [short(d.kb[k]) for k in d.only_b],
        [f"{k[3]}:{d.ka[k]['evidence_id']}|{d.kb[k]['evidence_id']}" for k in d.ev_diff],
        families_of(a_steps, b_steps, manifest),
    )


def compare_all(ids, A, B, manifest):
    """Returns (differing rows, tier counts, identical-case count, step totals (both, a, b))."""
    rows, tier_count = [], dict.fromkeys(TIERS, 0)
    same = tp = pa = pb = 0
    for cid in ids:
        d = diff_case(cid, A[cid], B[cid])
        tp += len(set(d.ka) & set(d.kb))
        pa += len(d.ka)
        pb += len(d.kb)
        if is_identical(d):
            same += 1
            continue
        tier = tier_of(d)
        tier_count[tier] += 1
        rows.append(to_row(d, tier, manifest, A[cid][1], B[cid][1]))
    rows.sort(key=lambda r: (r.tier, pipeline.case_key(r.cid)))
    return rows, tier_count, same, (tp, pa, pb)


def write_triage_csv(path, rows, names, reqs):
    na, nb = names
    header = ["tier", "case_id", f"status_{na}", f"status_{nb}", f"only_{na}", f"only_{nb}"]
    header += ["evidence_differs", "families", "request_text"]
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(header)
        for r in rows:
            text = reqs.get(r.cid, {}).get("request_text", "")[:REQUEST_TEXT_CHARS]
            w.writerow(
                [r.tier, r.cid, r.status_a, r.status_b, " | ".join(r.only_a), " | ".join(r.only_b)]
                + [" | ".join(r.ev_diff), ";".join(r.fams), text]
            )


def family_agreement(ids, A, B, rows, manifest):
    """Per evidence family: (cases citing it in either output, cases among them that agree)."""
    total, same = {}, {}
    differing = {r.cid for r in rows}
    for cid in ids:
        for fam in {manifest.get(s["evidence_id"], "") for s in A[cid][1] + B[cid][1] if s["evidence_id"] in manifest}:
            total[fam] = total.get(fam, 0) + 1
            same[fam] = same.get(fam, 0) + (cid not in differing)
    return total, same


def print_summary(args, names, ids, A, B, result):
    rows, tier_count, same, (tp, pa, pb) = result
    na, nb = names
    n = len(ids)
    print(f"{n} cases compared ({na} = {args.a}, {nb} = {args.b})")
    print(f"identical status and steps and citations : {same}/{n} ({same / n:.1%})")
    print(f"status agrees                            : {sum(A[c][0] == B[c][0] for c in ids)}/{n}")
    print(f"step agreement (tuple on phase/op/system/resource): both {tp}, only {na} {pa - tp}, only {nb} {pb - tp}")
    print("disagreement tiers: " + ", ".join(f"tier {t}: {c}" for t, c in tier_count.items()))


def print_family_table(total, same):
    print("\nagreement by evidence family:")
    for fam, t in sorted(total.items(), key=lambda kv: -kv[1]):
        print(f"  {fam:<42} {same[fam]:>3}/{t:<3} identical")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--out", default=None)
    ap.add_argument("--requests", default=os.path.join(REPO, "dataset", "deletion_requests.csv"))
    ap.add_argument("--names", default="ours,other")
    args = ap.parse_args()
    names = tuple(args.names.split(","))
    A, B = load(args.a), load(args.b)
    reqs = {r["case_id"]: r for r in pipeline.read_csv(args.requests)}
    ids = sorted(set(A) & set(B), key=pipeline.case_key)
    if not ids:
        print("no case ids in common between the two files")
        return 1
    evidence = pipeline.read_csv(os.path.join(REPO, "dataset", "evidence_files.csv"))
    manifest = {r["file_id"]: pipeline.family_of(r["file_path"]) for r in evidence}
    result = compare_all(ids, A, B, manifest)
    print_summary(args, names, ids, A, B, result)
    rows = result[0]
    if args.out:
        write_triage_csv(args.out, rows, names, reqs)
        print(f"wrote {len(rows)} differing cases to {args.out}")
    # per family agreement (cases whose steps cite that family in either output)
    print_family_table(*family_agreement(ids, A, B, rows, manifest))
    return 0


if __name__ == "__main__":
    sys.exit(main())
