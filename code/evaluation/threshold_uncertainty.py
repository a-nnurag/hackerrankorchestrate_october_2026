"""How sure can we be about each link type with so little labelled data?

For every kind of link (exact identifier, phase-resolved, cluster-anchored, activity-cluster, contested ...) count how
many of the steps it produces on the 32 public samples are in the answer key (TP) and how many are not (FP), then give
exact (Clopper-Pearson) and Wilson 95% intervals for its precision.  The decision rule that follows is the
standard one for
small samples: trust a link type only if the LOWER end of its interval clears a target, instead of the observed rate.

A second, weaker column uses the independent re-implementation as a pseudo-label on the hidden cases (agreement is not
accuracy: both implementations share evidence and conventions).

    python code/evaluation/threshold_uncertainty.py [--indep path/to/independent_output.csv] [--target 0.8]
"""

import argparse
import csv
import json
import math
import os
import sys
from collections import defaultdict
from dataclasses import replace

HERE = os.path.dirname(os.path.abspath(__file__))
CODE = os.path.dirname(HERE)
REPO = os.path.dirname(CODE)
sys.path.insert(0, CODE)

from ghost import evaluate, ingest, pipeline  # noqa: E402
from ghost.linker import DEL_EVENTS, learn_phase, link_case, phase_pick, worker_time  # noqa: E402
from ghost.linking import has_strong  # noqa: E402
from ghost.timeutil import parse_ts  # noqa: E402


def binom_tail_ge(n, k, p):
    """P(X >= k) for X ~ Binomial(n, p)."""
    return sum(math.comb(n, i) * p**i * (1 - p) ** (n - i) for i in range(k, n + 1))


def clopper_pearson(k, n, alpha=0.05):
    """Exact two-sided (1 - alpha) interval for a proportion k/n."""
    if n == 0:
        return 0.0, 1.0

    def bisect(f, lo=0.0, hi=1.0):
        for _ in range(60):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if f(mid) else (lo, mid)
        return (lo + hi) / 2

    lower = 0.0 if k == 0 else bisect(lambda p: binom_tail_ge(n, k, p) < alpha / 2)
    upper = 1.0 if k == n else bisect(lambda p: (1 - binom_tail_ge(n, k + 1, p)) > alpha / 2)
    return lower, upper


def wilson(k, n, z=1.96):
    if n == 0:
        return 0.0, 1.0
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def strong(link, score):
    return "exact identifier / catalog (score >= 0.90)" if score >= 0.90 else link


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--indep", default=None, help="the independent implementation's output.csv (hidden cases)")
    ap.add_argument("--target", type=float, default=0.80, help="required lower bound on precision")
    return ap.parse_args()


def verification_key(item):
    """(operation, system, resource) of the verification step an item produces."""
    return (item["tr"]["verification"], item["sys"], item["rid"])


def tally_sample_links(aud, samples, gold):
    """link type -> [steps in the answer key, steps produced] over the labelled samples."""
    tally = defaultdict(lambda: [0, 0])
    for case in samples:
        _status, gsteps = gold[case["case_id"]]
        key = {(s["operation"], s["system_id"], s["resource_id"]) for s in gsteps if s["phase"] == "VERIFICATION"}
        for it in aud.audit(case).get("items", []):
            t = tally[strong(it["link"], it["score"])]
            t[1] += 1
            t[0] += verification_key(it) in key
    return tally


def decision(lower, observed, target):
    """The rule: trust a link type only when the LOWER end of its interval clears the target."""
    if lower >= target:
        return "trust"
    return "trust only with a person checking" if observed >= 0.8 else "do not output"


def print_sample_table(tally, target):
    print(
        f"{'link type':<44}{'steps':>6}{'in key':>8}{'observed':>10}   {'exact 95% interval':<22}"
        f"{'Wilson 95%':<20}decision at lower bound >= {target:.2f}"
    )
    for name, (k, n) in sorted(tally.items(), key=lambda kv: -kv[1][1]):
        lo, hi = clopper_pearson(k, n)
        wl, wh = wilson(k, n)
        print(
            f"{name:<44}{n:>6}{k:>8}{k / max(n, 1):>10.2f}   [{lo:.2f}, {hi:.2f}]".ljust(100)
            + f"[{wl:.2f}, {wh:.2f}]".ljust(20)
            + decision(lo, k / max(n, 1), target)
        )


def load_steps(path):
    with open(path, encoding="utf-8") as f:
        return {r["case_id"]: json.loads(r["steps_json"]) for r in csv.DictReader(f)}


def tally_agreement(aud, hidden, other):
    """link type -> [steps, also in the other output, contradicted by a different resource of the same type]."""
    agree = defaultdict(lambda: [0, 0, 0])
    for case in hidden:
        theirs = {
            (s["operation"], s["system_id"], s["resource_id"])
            for s in other.get(case["case_id"], [])
            if s["phase"] == "VERIFICATION"
        }
        their_types = {(op, sy, rid.rsplit("_", 1)[0]) for op, sy, rid in theirs}
        for it in aud.audit(case).get("items", []):
            t = agree[strong(it["link"], it["score"])]
            tup = verification_key(it)
            t[1] += 1
            t[0] += tup in theirs
            t[2] += tup not in theirs and (tup[0], tup[1], tup[2].rsplit("_", 1)[0]) in their_types
    return agree


def print_agreement(agree):
    print("\nhidden cases: share of our steps the independent implementation also outputs (agreement, NOT accuracy)")
    for name, (n, k, c) in sorted(((nm, (v[1], v[0], v[2])) for nm, v in agree.items()), key=lambda kv: -kv[1][0]):
        lo, hi = clopper_pearson(k, n)
        print(
            f"  {name:<44}{n:>5} steps, {k:>4} also in the other output = {k / max(n, 1):.2f}  [{lo:.2f}, {hi:.2f}]"
            f"   contradicted by a different resource: {c}, other implementation silent: {n - k - c}"
        )


def main():
    a = parse_args()
    ingest.build()
    samples = pipeline.read_csv(os.path.join(ingest.DS, "sample_deletion_requests.csv"))
    hidden = pipeline.read_csv(os.path.join(ingest.DS, "deletion_requests.csv"))
    # min_link 0.30 lets the contested (0.30) candidates through so their precision is measured too; no type cap
    aud = pipeline.Auditor(samples + hidden, min_link=0.30, one_per_type=False)
    print_sample_table(tally_sample_links(aud, samples, evaluate.load_expected()), a.target)
    if a.indep:
        print_agreement(tally_agreement(aud, hidden, load_steps(a.indep)))


# ---------------------------------------------------------------------------------------------------------
# Self-supervised hold-out: labelled data from the data itself.
# Many cases have an account linked by an exact identifier.  Pretend that link is unknown, offer the second-offset
# resolver the same kind of candidate accounts it meets on a contested case, and see whether it picks the true one.
# The offset table is learned on the other 4/5 of the users (cross-fitting), so the test cases never help build it.
def _users_of(aud, cases):
    """case_id -> the user the case's email resolves to (cases that resolve to nobody are left out)."""
    users_of = {}
    for c in cases:
        us = aud.ident.resolve(c["email"], c["audit_at"])
        if us:
            users_of[c["case_id"]] = us[0]
    return users_of


def _is_unclaimed_account_deletion(aud, a, audit_at, user):
    return (
        a["source_system"] == "deletion_worker"
        and a["event_type"] in DEL_EVENTS
        and a["resource_id"].startswith("account_")
        and a["event_time"] <= audit_at
        and not (aud.claims.get(a["resource_id"], set()) - {user})
    )


def _near_accounts(aud, case, user):
    """Unclaimed account deletions in the anchor window of the case, narrowed by its reported status."""
    lo, hi = aud.settings.anchor_window
    rep = parse_ts(case["reported_at"])
    near = [
        a
        for a in aud.store.act
        if _is_unclaimed_account_deletion(aud, a, case["audit_at"], user)
        and lo <= (parse_ts(a["event_time"]) - rep).total_seconds() / 3600 <= hi
    ]
    ok = [a for a in near if a["reported_result"] in aud.settings.status_results.get(case["reported_status"], ())]
    return ok or near


def _hidden_account_task(aud, case):
    """-> (true accounts, other strongly linked records) when the case is a usable test, else None.

    A usable case has exactly one exact-linked account with a worker event and at least one other exact-linked record;
    the resolver is then asked to find that account again among its candidates."""
    linked = link_case(case, aud.ident, aud.store, replace(aud.settings, cluster=False), aud.claims)
    if not linked:
        return None
    strong_rids = {rid for rid, v in linked.res.items() if has_strong(v)}
    accounts = {rid for rid in strong_rids if rid.startswith("account_")}
    truth = {rid for rid in accounts if worker_time(aud.store, rid)}
    others = strong_rids - accounts
    if len(truth) != 1 or not others:
        return None
    return truth, others


def _score_pick(aud, case, user, phase, stats, by_n):
    """Let the resolver pick among the case's candidate accounts and tally the outcome."""
    task = _hidden_account_task(aud, case)
    if task is None:
        return
    truth, others = task
    near = _near_accounts(aud, case, user)
    if not any(a["resource_id"] in truth for a in near):
        return
    if len(near) < 2:
        stats["single"] += 1
        return
    pick = phase_pick(near, others, aud.store, phase)
    k = min(len(near), 5)
    if pick is None:
        outcome, slot = "abstain", 2
    elif pick["resource_id"] in truth:
        outcome, slot = "correct", 0
    else:
        outcome, slot = "wrong", 1
    stats[outcome] += 1
    by_n[k][slot] += 1


def _train_claims(aud, fold, held_out):
    """Exact-identifier claims without the users of the held-out fold."""
    claims = {rid: {u for u in us if fold.get(u) != held_out} for rid, us in aud.claims.items()}
    return {r: u for r, u in claims.items() if u}


def self_supervised(aud, cases, folds=5):
    users_of = _users_of(aud, cases)
    all_users = sorted(set(users_of.values()))
    fold = {u: i % folds for i, u in enumerate(all_users)}
    stats = {"correct": 0, "wrong": 0, "abstain": 0, "single": 0}
    by_n = defaultdict(lambda: [0, 0, 0])
    for f in range(folds):
        phase = learn_phase(aud.store, _train_claims(aud, fold, f))
        for c in cases:
            u = users_of.get(c["case_id"])
            if u is not None and fold[u] == f:
                _score_pick(aud, c, u, phase, stats, by_n)
    return stats, by_n


def report_self_supervised(aud, cases):
    stats, by_n = self_supervised(aud, cases)
    n = stats["correct"] + stats["wrong"]
    lo, hi = clopper_pearson(stats["correct"], n)
    print("\nself-supervised hold-out (exact-linked accounts hidden from the resolver, offsets learned on other users)")
    print(
        f"  cases with a true account among >= 2 candidates: {n + stats['abstain']} "
        f"(plus {stats['single']} with a single candidate)"
    )
    print(
        f"  resolver picked the true account {stats['correct']} times, a wrong one {stats['wrong']} times, "
        f"abstained {stats['abstain']} times"
    )
    print(
        f"  precision when it picks: {stats['correct'] / max(n, 1):.3f}  exact 95% interval [{lo:.3f}, {hi:.3f}]; "
        f"coverage {n / max(n + stats['abstain'], 1):.0%}"
    )
    for k in sorted(by_n):
        c, w, ab = by_n[k]
        print(f"    {k}{'+' if k == 5 else ''} candidates: correct {c}, wrong {w}, abstain {ab}")


if __name__ == "__main__":
    import sys as _sys

    main()
    _ap_args = _sys.argv[1:]
    _samples = pipeline.read_csv(os.path.join(ingest.DS, "sample_deletion_requests.csv"))
    _hidden = pipeline.read_csv(os.path.join(ingest.DS, "deletion_requests.csv"))
    report_self_supervised(pipeline.Auditor(_samples + _hidden), _samples + _hidden)
