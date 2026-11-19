"""Show, per public sample, which gold steps are missing and which predicted steps are extra.

python code/evaluation/diff_cases.py [--min-link 0.3] [--mode record] [--no-cluster] [case_id ...]
"""

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from ghost import evaluate, ingest, pipeline  # noqa: E402


def short(s):
    return f"{s['phase'][0]}:{s['operation']}:{s['system_id']}/{s['resource_id']}@{s['evidence_id'] or '-'}"


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("cases", nargs="*")
    ap.add_argument("--mode", default="relaxed")
    ap.add_argument("--min-link", type=float, default=0.45)
    ap.add_argument("--no-cluster", action="store_true")
    ap.add_argument("--only-bad", action="store_true")
    ap.add_argument("--derive-absence", action="store_true")
    ap.add_argument("--no-type-cap", action="store_true")
    return ap.parse_args()


def build_auditor(a):
    """Auditor over the samples and the hidden requests with the options given on the command line."""
    samples = pipeline.read_csv(os.path.join(ingest.DS, "sample_deletion_requests.csv"))
    hidden = pipeline.read_csv(os.path.join(ingest.DS, "deletion_requests.csv"))
    aud = pipeline.Auditor(
        samples + hidden,
        mode=a.mode,
        min_link=a.min_link,
        cluster=not a.no_cluster,
        derive_absence=a.derive_absence,
        one_per_type=not a.no_type_cap,
    )
    return aud, samples


def step_differences(row, gsteps):
    """-> (gold steps the pipeline missed, steps it produced that the gold answer does not have), as short strings."""
    gold = {evaluate.TUP(s): s for s in gsteps}
    pred = {evaluate.TUP(s): s for s in row["steps"]}
    return [short(gold[k]) for k in gold if k not in pred], [short(pred[k]) for k in pred if k not in gold]


def print_diff(row, expected, only_bad):
    """Print the missing and extra steps of one case against its gold answer."""
    gst, gsteps = expected[row["case_id"]]
    miss, extra = step_differences(row, gsteps)
    if only_bad and not (miss or extra or gst != row["status"]):
        return
    print(f"{row['case_id']} gold={gst} pred={row['status']} steps gold={len(gsteps)} pred={len(row['steps'])}")
    for x in miss:
        print("   MISSING", x)
    for x in extra:
        print("   EXTRA  ", x)


def main():
    a = parse_args()
    ingest.build()
    aud, samples = build_auditor(a)
    expected = evaluate.load_expected()
    for row in pipeline.run_requests(samples, aud):
        if not a.cases or row["case_id"] in a.cases:
            print_diff(row, expected, a.only_bad)


if __name__ == "__main__":
    main()
