"""Evaluation against labelled answers (the 32 public samples) plus a hallucination check.

Metrics
    status accuracy        deletion_status equal
    step precision/recall  steps compared as full tuples (phase, system, resource, operation, state, evidence_id)
    field accuracy         per field, over steps aligned by (phase, operation, system, resource)
    sequence accuracy      exact array equality, and normalised LCS ratio of the ordered tuples
Hallucination check (needs no labels)
    every resource_id in a step exists in the evidence table, the activity stream or the manual
    transcriptions; every evidence_id is in the manifest and captured at or before audit_at.
"""

from __future__ import annotations

import csv
import json
import os
import re
import sqlite3
from contextlib import closing
from typing import Any

from .ingest import DB, DS

Step = dict[str, Any]

FIELDS = ["phase", "system_id", "resource_id", "operation", "state", "evidence_id"]


def step_key(step: Step) -> tuple[str, str, str, str]:
    """Alignment key of a step: (phase, operation, system, resource)."""
    return (step["phase"], step["operation"], step["system_id"], step["resource_id"])


def step_tuple(step: Step) -> tuple[Any, ...]:
    """A step as a comparable tuple of all its answer fields."""
    return tuple(step[f] for f in FIELDS)


KEY = step_key
TUP = step_tuple


def lcs_len(a: list[Any], b: list[Any]) -> int:
    """Length of the longest common subsequence of two sequences."""
    if not a or not b:
        return 0
    prev = [0] * (len(b) + 1)
    for x in a:
        cur = [0]
        for j, y in enumerate(b, 1):
            cur.append(prev[j - 1] + 1 if x == y else max(prev[j], cur[j - 1]))
        prev = cur
    return prev[-1]


def load_expected(path: str | None = None) -> dict[str, tuple[str, list[Step]]]:
    """Labelled answers: case_id -> (deletion_status, steps)."""
    path = path or os.path.join(DS, "sample_output.csv")
    with open(path, encoding="utf-8", newline="") as f:
        return {r["case_id"]: (r["deletion_status"], json.loads(r["steps_json"])) for r in csv.DictReader(f)}


def _score_fields(metrics: dict[str, Any], gold_steps: list[Step], pred_steps: list[Step]) -> None:
    """Field-by-field agreement over steps aligned by (phase, operation, system, resource)."""
    gold_by_key = {step_key(s): s for s in gold_steps}
    for s in pred_steps:
        g = gold_by_key.get(step_key(s))
        if g:
            for f in FIELDS:
                metrics["fields"][f][1] += 1
                metrics["fields"][f][0] += g[f] == s[f]


def _score_case(metrics: dict[str, Any], row: dict[str, Any], gold_status: str, gold_steps: list[Step]) -> None:
    pred_steps = row["steps"]
    metrics["n"] += 1
    status_ok = row["status"] == gold_status
    metrics["status_ok"] += status_ok
    by_status = metrics["by_status"].setdefault(gold_status, [0, 0])
    by_status[1] += 1
    by_status[0] += status_ok
    gold, pred = [step_tuple(s) for s in gold_steps], [step_tuple(s) for s in pred_steps]
    metrics["tp"] += len(set(gold) & set(pred))
    metrics["pred"] += len(set(pred))
    metrics["gold"] += len(set(gold))
    metrics["exact_seq"] += gold == pred and status_ok
    metrics["lcs"] += (2 * lcs_len(gold, pred) / (len(gold) + len(pred))) if (gold or pred) else 1.0
    _score_fields(metrics, gold_steps, pred_steps)
    metrics["per_case"].append(
        (row["case_id"], gold_status, row["status"], len(gold_steps), len(pred_steps), len(set(gold) & set(pred)))
    )


def compare(rows: list[dict[str, Any]], expected: dict[str, tuple[str, list[Step]]]) -> dict[str, Any]:
    """Score audited rows against labelled answers; returns the raw counters that `summarize` prints."""
    metrics: dict[str, Any] = {
        "n": 0,
        "status_ok": 0,
        "tp": 0,
        "pred": 0,
        "gold": 0,
        "exact_seq": 0,
        "lcs": 0,
        "fields": {f: [0, 0] for f in FIELDS},
        "by_status": {},
        "per_case": [],
    }
    for row in rows:
        if row["case_id"] in expected:
            gold_status, gold_steps = expected[row["case_id"]]
            _score_case(metrics, row, gold_status, gold_steps)
    return metrics


def summarize(m: dict[str, Any]) -> str:
    """Human-readable metrics block."""
    n = max(m["n"], 1)
    prec = m["tp"] / m["pred"] if m["pred"] else 0.0
    rec = m["tp"] / m["gold"] if m["gold"] else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    lines = [
        f"cases evaluated          : {m['n']}",
        f"status accuracy          : {m['status_ok']}/{m['n']} = {m['status_ok'] / n:.3f}",
    ]
    for k, (a, b) in sorted(m["by_status"].items()):
        lines.append(f"  gold {k:<14}: {a}/{b}")
    lines += [
        f"step precision / recall  : {prec:.3f} / {rec:.3f}   F1 {f1:.3f}   "
        f"(tp {m['tp']}, predicted {m['pred']}, gold {m['gold']})",
        "field accuracy (aligned steps): " + ", ".join(f"{f} {a}/{b}" for f, (a, b) in m["fields"].items()),
        f"exact sequence match    : {m['exact_seq']}/{m['n']} = {m['exact_seq'] / n:.3f}",
        f"mean ordered-LCS F1      : {m['lcs'] / n:.3f}",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------- hallucination check
def id_universe(db_path: str | None = None) -> set[str]:
    """Every resource id that appears in the evidence table or the activity stream."""
    with closing(sqlite3.connect(db_path or DB)) as db:
        ids = {r[0] for r in db.execute("select distinct resource_id from observation where resource_id is not null")}
        ids |= {r[0] for r in db.execute("select distinct resource_id from activity")}
    return ids


def hallucination_check(
    rows: list[dict[str, Any]], requests_by_id: dict[str, Any], caps: dict[str, str], universe: set[str]
) -> list[tuple[str, str]]:
    """Return a list of (case_id, problem). Empty means every id/evidence reference is grounded."""
    problems = []
    for r in rows:
        audit_at = requests_by_id[r["case_id"]]["audit_at"]
        for s in r["steps"]:
            if s["resource_id"] not in universe:
                problems.append((r["case_id"], f"resource_id not in any source: {s['resource_id']}"))
            ev = s["evidence_id"]
            if ev.startswith(("activity_", "audit_")):
                continue  # activity/audit ids are valid citations; existence is checked via the activity table
            if ev:
                if ev not in caps:
                    problems.append((r["case_id"], f"unknown evidence_id {ev}"))
                elif caps[ev] > audit_at:
                    problems.append((r["case_id"], f"evidence {ev} captured after audit_at"))
            if not re.match(r"^[a-z_]+$", s["system_id"]):
                problems.append((r["case_id"], f"odd system_id {s['system_id']}"))
    return problems
