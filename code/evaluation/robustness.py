"""How much do the tuned settings overfit the 32 samples?

1. Sensitivity grid: F1 over min_link x anchor window x status filter.  A wide flat region means the
   result does not hinge on one lucky value.
2. Leave-one-case-out: for each sample case, choose the best configuration on the other 31, score the
   held-out case with it, and pool.  This estimates the performance of the *tuning procedure*.
3. Case-level bootstrap: resample the 32 cases (steps inside a case are correlated, so cases are the
   unit) to put a 95% interval on precision, recall and F1.

    python code/evaluation/robustness.py
"""

import itertools
import os
import random
import sys
from math import sqrt

HERE = os.path.dirname(os.path.abspath(__file__))
CODE = os.path.dirname(HERE)
sys.path.insert(0, CODE)

from ghost import evaluate, ingest, pipeline  # noqa: E402

MIN_LINK = [0.30, 0.45, 0.60, 0.70]
WINDOWS = [(-1.3, 0.3), (-1.3, -0.7), (-3.0, 3.0)]
STATUS = [True, False]


def per_case(samples, hidden, expected, min_link, window, status):
    aud = pipeline.Auditor(samples + hidden, min_link=min_link, anchor_window=window, status_filter=status)
    rows = pipeline.run_requests(samples, aud)
    out = {}
    for r in rows:
        gst, gsteps = expected[r["case_id"]]
        gt, pt = {evaluate.TUP(s) for s in gsteps}, {evaluate.TUP(s) for s in r["steps"]}
        out[r["case_id"]] = (len(gt & pt), len(pt), len(gt), r["status"] == gst)
    return out


def prf(tp, pred, gold):
    p = tp / pred if pred else 0.0
    r = tp / gold if gold else 0.0
    return p, r, (2 * p * r / (p + r) if p + r else 0.0)


def total(cases, res):
    tp = sum(res[c][0] for c in cases)
    pred = sum(res[c][1] for c in cases)
    gold = sum(res[c][2] for c in cases)
    return prf(tp, pred, gold)


def print_grid(grid, ids):
    """Section 1: F1 of every configuration on all samples, with the spread over the grid."""
    print("1. sensitivity grid (F1 on all 32 samples)")
    print(f"{'min_link':<9}{'anchor window':<16}{'status filter':<15}{'prec':<7}{'rec':<7}{'F1':<7}{'status ok'}")
    for (ml, w, st), res in grid.items():
        p, r, f = total(ids, res)
        print(f"{ml:<9}{str(w):<16}{str(st):<15}{p:<7.3f}{r:<7.3f}{f:<7.3f}{sum(v[3] for v in res.values())}/32")
    f1s = sorted(total(ids, res)[2] for res in grid.values())
    print(f"   F1 over {len(f1s)} configurations: min {f1s[0]:.3f}, median {f1s[len(f1s) // 2]:.3f}, max {f1s[-1]:.3f}")


def leave_one_out(grid, ids):
    """Section 2: choose the best configuration on 31 cases, score the held-out case, pool the held-out counts."""
    print("\n2. leave-one-case-out (choose best config on 31 cases, score the held-out case)")
    held = [0, 0, 0]
    chosen = {}
    for c in ids:
        rest = [x for x in ids if x != c]
        best = max(grid, key=lambda k: (total(rest, grid[k])[2], k[0]))
        chosen[best] = chosen.get(best, 0) + 1
        for j in range(3):
            held[j] += grid[best][c][j]
    p, r, f = prf(*held)
    print(
        f"   held-out precision {p:.3f}  recall {r:.3f}  F1 {f:.3f}   (in-sample best: "
        f"{max(total(ids, v)[2] for v in grid.values()):.3f})"
    )
    print("   configurations chosen across the 32 folds:", {str(k): v for k, v in chosen.items()})


def wilson_interval(successes, n, z=1.96):
    """Wilson score interval for a proportion."""
    p = successes / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return centre - half, min(1.0, centre + half)


def bootstrap(default, ids, resamples=2000, seed=7):
    """Section 3: case-level bootstrap of precision, recall and F1 for the default configuration."""
    print(f"\n3. bootstrap over cases (default configuration, {resamples} resamples)")
    rnd = random.Random(seed)
    stats = []
    for _ in range(resamples):
        sample = [rnd.choice(ids) for _ in ids]
        stats.append(prf(*(sum(default[c][j] for c in sample) for j in range(3))))
    for i, name in enumerate(["precision", "recall", "F1"]):
        v = sorted(s[i] for s in stats)
        print(f"   {name:<10} 95% interval [{v[int(0.025 * len(v))]:.3f}, {v[int(0.975 * len(v))]:.3f}]")
    ok = sum(v[3] for v in default.values())
    lo, hi = wilson_interval(ok, len(ids))
    print(f"   status accuracy {ok}/{len(ids)}: Wilson 95% interval [{lo:.3f}, {hi:.3f}]")


def main():
    ingest.build()
    samples = pipeline.read_csv(os.path.join(ingest.DS, "sample_deletion_requests.csv"))
    hidden = pipeline.read_csv(os.path.join(ingest.DS, "deletion_requests.csv"))
    expected = evaluate.load_expected()
    ids = sorted(expected)
    grid = {
        (ml, w, st): per_case(samples, hidden, expected, ml, w, st)
        for ml, w, st in itertools.product(MIN_LINK, WINDOWS, STATUS)
    }
    print_grid(grid, ids)
    leave_one_out(grid, ids)
    bootstrap(grid[(0.45, (-1.3, 0.3), True)], ids)


if __name__ == "__main__":
    main()
