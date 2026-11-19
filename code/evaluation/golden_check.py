"""Golden regression check: refactoring must not change a single decision.

Fingerprints three things for the real dataset (public samples plus the 518 requests, default settings):

  observations   the evidence table built by the ingestion step (content only, row order ignored)
  results        for every case: status, steps, review flags, notes
  output         the bytes of the CSV that main.py writes

    python code/evaluation/golden_check.py             # compare with code/evaluation/golden/golden.json
    python code/evaluation/golden_check.py --update    # accept the current behaviour as the new golden
    python code/evaluation/golden_check.py --dump DIR  # also write the normalised dumps for diffing

A mismatch prints the first differing case or observation so the change can be traced.
"""

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
CODE = os.path.dirname(HERE)
sys.path.insert(0, CODE)

GOLDEN = os.path.join(HERE, "golden", "golden.json")


def _digest(lines):
    h = hashlib.sha256()
    for line in lines:
        h.update(line.encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


def observation_lines(db_path, dataset_root):
    """Canonical text of every observation with its identifiers, independent of insertion order and machine paths."""
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    idents = {}
    for r in db.execute("select obs_id, id_type, value, role from obs_ident"):
        idents.setdefault(r["obs_id"], []).append((r["id_type"], r["value"], r["role"]))
    norm = re.escape(dataset_root.replace("\\", "/"))
    lines = []
    for r in db.execute("select * from observation"):
        row = {k: r[k] for k in r.keys() if k != "obs_id"}  # noqa: SIM118 (iterating a Row yields values)
        row["source_ref"] = re.sub(norm, "<dataset>", row["source_ref"].replace("\\", "/"))
        row["idents"] = sorted(idents.get(r["obs_id"], []))
        lines.append(json.dumps(row, sort_keys=True, ensure_ascii=False))
    cov = [
        json.dumps(list(r), ensure_ascii=False)
        for r in db.execute("select file_id, system_id, scope_kind, scope_time, level from coverage")
    ]
    edges = [
        json.dumps(list(r), ensure_ascii=False)
        for r in db.execute("select activity_id, resource_id, id_type, value, edge_kind from activity_edge")
    ]
    db.close()
    return sorted(lines), sorted(cov), sorted(edges)


def result_lines(rows):
    out = []
    for r in rows:
        out.append(
            json.dumps(
                {
                    "case": r["case_id"],
                    "status": r["status"],
                    "steps": r["steps"],
                    "review": r["review"],
                    "notes": r["notes"],
                    "errors": r["errors"],
                },
                sort_keys=True,
                ensure_ascii=False,
            )
        )
    return out


def compute(dump_dir=None):
    cache = tempfile.mkdtemp(prefix="ghost_golden_")
    os.environ["GHOST_CACHE_DIR"] = cache
    from ghost import ingest, pipeline

    stats = ingest.build()
    samples = pipeline.read_csv(os.path.join(ingest.DS, "sample_deletion_requests.csv"))
    hidden = pipeline.read_csv(os.path.join(ingest.DS, "deletion_requests.csv"))
    aud = pipeline.Auditor(samples + hidden)
    rows = pipeline.run_requests(samples, aud) + pipeline.run_requests(hidden, aud)
    obs, cov, edges = observation_lines(stats["db"], ingest.DS)
    res = result_lines(rows)
    out_path = os.path.join(cache, "output.csv")
    pipeline.write_output(pipeline.run_requests(hidden, aud), out_path)
    with open(out_path, "rb") as f:
        out_sha = hashlib.sha256(f.read()).hexdigest()
    if dump_dir:
        os.makedirs(dump_dir, exist_ok=True)
        for name, lines in (("observations", obs), ("coverage", cov), ("edges", edges), ("results", res)):
            with open(os.path.join(dump_dir, name + ".jsonl"), "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
    return {
        "observations": {"n": len(obs), "sha256": _digest(obs)},
        "coverage": {"n": len(cov), "sha256": _digest(cov)},
        "activity_edges": {"n": len(edges), "sha256": _digest(edges)},
        "results": {"n": len(res), "sha256": _digest(res)},
        "output_csv_sha256": out_sha,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--update", action="store_true")
    ap.add_argument("--dump", default=None)
    a = ap.parse_args()
    now = compute(a.dump)
    if a.update:
        os.makedirs(os.path.dirname(GOLDEN), exist_ok=True)
        with open(GOLDEN, "w", encoding="utf-8") as f:
            json.dump(now, f, indent=1, sort_keys=True)
        print("golden updated:", json.dumps(now, sort_keys=True))
        return 0
    with open(GOLDEN, encoding="utf-8") as f:
        want = json.load(f)
    bad = [k for k in want if want[k] != now.get(k)]
    for k in want:
        print(
            f"{'OK  ' if k not in bad else 'DIFF'} {k}: {now.get(k)}"
            if k not in bad
            else f"DIFF {k}: golden {want[k]} now {now.get(k)}"
        )
    print(
        "\nGOLDEN MATCH"
        if not bad
        else "\nGOLDEN MISMATCH (rerun with --dump DIR on both versions and diff the .jsonl files)"
    )
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
