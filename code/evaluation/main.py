"""Evaluation harness: score the 32 public samples, run ablations, run synthetic cases.

    python code/evaluation/main.py            # prints the tables used in evaluation_report.md
    python code/evaluation/main.py --json out.json

Ablations switch one design decision off at a time, so the report can show what each decision is
worth.  Every number is computed from dataset/sample_output.csv, which is the only labelled data.
"""

import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CODE = os.path.dirname(HERE)
sys.path.insert(0, CODE)

from ghost import evaluate, ingest, pipeline  # noqa: E402

CONFIGS = [
    ("default (relaxed, min_link 0.45, cluster, type cap, since-request)", {}),
    ("mode=record (no state from later-exported files)", {"mode": "record"}),
    ("mode=strict (no later-exported files at all)", {"mode": "strict"}),
    ("min_link=0.30 (accept contested cluster links)", {"min_link": 0.30}),
    ("min_link=0.70", {"min_link": 0.70}),
    ("no activity-cluster links", {"cluster": False}),
    ("no one-resource-per-type cap", {"one_per_type": False}),
    ("derive absence from later snapshots", {"derive_absence": True}),
    ("ignore requested_at (use pre-request observations)", {"since_request": False}),
    ("no reported_status filter on anchor accounts", {"status_filter": False}),
    ("no second-offset resolver for contested accounts and analytics", {"phase": False}),
    ("no propagation of assigned accounts to other cases", {"propagate": False}),
]


def llm_config():
    """Add a row for the optional LLM adjudicator when an Ollama server is reachable."""
    from ghost.llm import LLM

    if not LLM.available():
        return []
    return [(f"default + LLM adjudication ({LLM().model})", {"llm": LLM()})]


def run(opts, samples, hidden, expected):
    aud = pipeline.Auditor(samples + hidden, **opts)
    rows = pipeline.run_requests(samples, aud)
    return rows, evaluate.compare(rows, expected)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=None)
    a = ap.parse_args()
    ingest.build()
    samples = pipeline.read_csv(os.path.join(ingest.DS, "sample_deletion_requests.csv"))
    hidden = pipeline.read_csv(os.path.join(ingest.DS, "deletion_requests.csv"))
    expected = evaluate.load_expected()
    caps = pipeline.load_manifest_caps()
    universe = evaluate.id_universe()

    results = []
    print(f"{'configuration':<70} status  prec   rec    F1    exact  LCS")
    for name, opts in CONFIGS + llm_config():
        rows, m = run(opts, samples, hidden, expected)
        n = m["n"]
        prec = m["tp"] / m["pred"] if m["pred"] else 0
        rec = m["tp"] / m["gold"]
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0
        r = dict(
            config=name,
            status=f"{m['status_ok']}/{n}",
            precision=round(prec, 3),
            recall=round(rec, 3),
            f1=round(f1, 3),
            exact=f"{m['exact_seq']}/{n}",
            lcs=round(m["lcs"] / n, 3),
        )
        results.append(r)
        print(
            f"{name:<70} {r['status']:<7} {r['precision']:<6} {r['recall']:<6} {r['f1']:<5} {r['exact']:<6} {r['lcs']}"
        )

    rows, m = run({}, samples, hidden, expected)
    print("\n=== default configuration, detail ===")
    print(evaluate.summarize(m))
    bad = evaluate.hallucination_check(rows, {r["case_id"]: r for r in samples}, caps, universe)
    print(f"hallucination check (samples): {len(bad)} ungrounded references")
    print("per-case (gold status, predicted, gold steps, predicted steps, exact tuples matched):")
    for c in m["per_case"]:
        print("  ", *c)

    print("\n=== synthetic cases ===")
    p = subprocess.run(
        [sys.executable, "-X", "utf8", os.path.join(HERE, "synthetic_cases.py")], capture_output=True, text=True
    )
    print(p.stdout.strip())
    if a.json:
        json.dump({"ablations": results, "per_case": m["per_case"]}, open(a.json, "w"), indent=1)
    return p.returncode


if __name__ == "__main__":
    sys.exit(main())
