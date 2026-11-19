"""Ghost Data Still Exists: deletion-audit agent (deterministic pipeline, no model calls).

Usage (from the repository root):
    python code/main.py                      # audit dataset/deletion_requests.csv -> output.csv
    python code/main.py --eval               # also score the 32 public samples (needs sample_output.csv)
    python code/main.py --sample-only        # audit only the samples and print metrics (no output.csv)

Options:
    --out PATH        output file (default: <repo>/output.csv)
    --mode MODE       strict | record | relaxed (default relaxed, see docs/05)
    --min-link X      drop items whose link confidence is below X (default 0.45)
    --llm             adjudicate conflicting request text with an LLM (off by default); --llm-provider ollama|groq
    --no-cluster      disable the low-confidence deletion-worker activity-cluster links
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from ghost import evaluate, ingest, pipeline  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    """Command-line options (documented in the module docstring)."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--requests", default=os.path.join(ingest.DS, "deletion_requests.csv"))
    ap.add_argument("--out", default=os.path.join(ingest.REPO, "output.csv"))
    ap.add_argument("--eval", action="store_true", help="score the public samples as well")
    ap.add_argument("--sample-only", action="store_true", help="only audit the public samples")
    ap.add_argument("--mode", default="relaxed", choices=["strict", "record", "relaxed"])
    ap.add_argument("--min-link", type=float, default=0.45)
    ap.add_argument("--no-cluster", action="store_true")
    ap.add_argument("--derive-absence", action="store_true")
    ap.add_argument("--no-type-cap", action="store_true")
    ap.add_argument(
        "--llm", action="store_true", help="use a local Ollama model to adjudicate conflicting request text"
    )
    ap.add_argument(
        "--llm-model", default=None, help="model tag (Ollama default qwen3.5:4b; Groq default openai/gpt-oss-120b)"
    )
    ap.add_argument(
        "--llm-provider",
        default="ollama",
        choices=["ollama", "groq"],
        help="groq sends request text to Groq (needs GROQ_API_KEY in the environment); ollama stays local",
    )
    ap.add_argument("--review", default=None, help="write per-case review notes (CSV) to this path")
    return ap


def make_llm(args: argparse.Namespace) -> Any:
    """The optional LLM adjudicator, or None when not requested or not reachable."""
    if not args.llm:
        return None
    from ghost import llm as llm_module

    ready = llm_module.GroqLLM.available() if args.llm_provider == "groq" else llm_module.LLM.available()
    if not ready:
        print(
            f"LLM requested but {args.llm_provider} is not available "
            "(server down or GROQ_API_KEY not set); using rules only"
        )
        return None
    llm = llm_module.make_llm(args.llm_provider, args.llm_model)
    print(f"LLM adjudication on: {args.llm_provider} {llm.model}")
    return llm


def report_samples(samples: list[dict[str, str]], auditor: pipeline.Auditor, caps: dict[str, str], universe: set[str]):
    """Score the public samples and print the metrics."""
    rows = pipeline.run_requests(samples, auditor)
    m = evaluate.compare(rows, evaluate.load_expected())
    print("\n=== public samples (32) ===")
    print(evaluate.summarize(m))
    bad = evaluate.hallucination_check(rows, {r["case_id"]: r for r in samples}, caps, universe)
    print(f"hallucination check      : {len(bad)} ungrounded references")
    print(f"validator errors         : {sum(1 for r in rows if r['errors'])} cases")


def main(argv: list[str] | None = None) -> int:
    """Audit the requests and write the output file; returns the process exit code."""
    a = build_parser().parse_args(argv)

    stats = ingest.build()
    print(
        f"ingested {stats['n_obs']} observations ({stats['unparsed']} unparsed, "
        f"{stats['manual_loaded']} manual) in {stats['runtime_s']:.2f}s"
    )
    llm = make_llm(a)

    samples = pipeline.read_csv(os.path.join(ingest.DS, "sample_deletion_requests.csv"))
    hidden = pipeline.read_csv(a.requests)
    auditor = pipeline.Auditor(
        samples + hidden,
        llm=llm,
        mode=a.mode,
        min_link=a.min_link,
        cluster=not a.no_cluster,
        derive_absence=a.derive_absence,
        one_per_type=not a.no_type_cap,
    )
    caps = pipeline.load_manifest_caps()
    universe = evaluate.id_universe()

    if a.eval or a.sample_only:
        report_samples(samples, auditor, caps, universe)
        if a.sample_only:
            return 0

    rows = pipeline.run_requests(hidden, auditor)
    pipeline.write_output(rows, a.out)
    by: dict[str, int] = {}
    for r in rows:
        by[r["status"]] = by.get(r["status"], 0) + 1
    print(f"\nwrote {len(rows)} rows to {a.out}: {by}")
    errs = [(r["case_id"], r["errors"]) for r in rows if r["errors"]]
    bad = evaluate.hallucination_check(rows, {r["case_id"]: r for r in hidden}, caps, universe)
    print(f"validator errors: {len(errs)} cases; ungrounded references: {len(bad)}")
    if llm is not None:
        print(f"LLM usage: {llm.usage}")
    if a.review:
        n = pipeline.write_review(rows, a.review)
        print(
            f"review list: {n} cases written to {a.review} (tiers: 1 image/PDF, 2 unseen family, 3 contested, 4 other)"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
