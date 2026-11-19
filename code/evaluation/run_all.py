"""Run every OFFLINE evaluation suite and print one PASS/FAIL table.

    python code/evaluation/run_all.py                 # everything, including the ~1 minute metamorphic suite
    python code/evaluation/run_all.py --quick         # skip metamorphic.py
    python code/evaluation/run_all.py --only validate_gold --only synthetic_cases
    python code/evaluation/run_all.py --list          # suite names

Each suite runs as its own subprocess (`sys.executable -X utf8`) from the repository root, exactly as a person
would type it, so a crash in one suite cannot hide the others.  The pipeline itself (`code/main.py`) runs
first because the validator, provenance and metamorphic suites read the output.csv it writes.  Nothing here
needs the network or a local model: the live-LLM tests are started with --no-live.

Exit code: 0 when every selected suite passes, 1 otherwise.  provenance_check.py exits 0 by design (its report is
a triage list), so it passes whenever it runs to completion.  code/tests/test_suite.py reuses SUITES.
"""

import argparse
import os
import subprocess
import sys
import time
from typing import NamedTuple

HERE = os.path.dirname(os.path.abspath(__file__))
CODE = os.path.dirname(HERE)
REPO = os.path.dirname(CODE)
TAIL_LINES = 15  # lines of a failing suite's output shown under the table
NAME_WIDTH = 22
# suites that do not read output.csv, so --only can skip the pipeline run for them
INDEPENDENT_OF_OUTPUT = ("pipeline", "golden_check", "synthetic_cases")


class Suite(NamedTuple):
    name: str
    script: str  # path relative to code/
    args: tuple[str, ...] = ()
    slow: bool = False  # skipped by --quick


Result = tuple[Suite, int, float, str]  # suite, return code, seconds, combined output

# The pipeline first (it writes output.csv), then the suites in the order of cost.
PIPELINE = Suite("pipeline", "main.py")
SUITES: tuple[Suite, ...] = (
    PIPELINE,
    Suite("golden_check", "evaluation/golden_check.py"),
    Suite("validate_output", "evaluation/validate_output.py", ("output.csv",)),
    Suite("validate_gold", "evaluation/validate_output.py", ("--gold",)),
    Suite("synthetic_cases", "evaluation/synthetic_cases.py"),
    Suite("metamorphic", "evaluation/metamorphic.py", slow=True),
    Suite("test_classifier", "evaluation/test_classifier.py", ("--no-live",)),
    Suite("test_condition_llm", "evaluation/test_condition_llm.py", ("--no-live",)),
    Suite("test_groq_client", "evaluation/test_groq_client.py"),
    Suite("test_groq_limits", "evaluation/test_groq_limits.py"),
    Suite("provenance_check", "evaluation/provenance_check.py"),
    Suite("main_eval", "main.py", ("--eval",)),
)
BY_NAME = {s.name: s for s in SUITES}


def command(suite: Suite) -> list[str]:
    """The exact argv a suite runs with."""
    return [sys.executable, "-X", "utf8", os.path.join(CODE, suite.script), *suite.args]


def run_suite(suite: Suite) -> tuple[int, float, str]:
    """Run one suite from the repo root.  Returns (return code, seconds, combined stdout+stderr)."""
    start = time.perf_counter()
    proc = subprocess.run(
        command(suite),
        cwd=REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=dict(os.environ, PYTHONIOENCODING="utf-8"),
    )
    return proc.returncode, time.perf_counter() - start, proc.stdout + proc.stderr


def select(quick: bool, only: list[str] | None) -> list[Suite]:
    """The suites to run, in table order.  With --only, the pipeline is added when a chosen suite reads output.csv."""
    if not only:
        return [s for s in SUITES if not (quick and s.slow)]
    chosen = {BY_NAME[n] for n in only}
    if any(s.name not in INDEPENDENT_OF_OUTPUT for s in chosen):
        chosen.add(PIPELINE)
    return sorted(chosen, key=SUITES.index)


def print_table(results: list[Result]) -> None:
    print(f"{'suite':<{NAME_WIDTH}} {'result':<7} {'seconds':>8}")
    for suite, rc, secs, _ in results:
        print(f"{suite.name:<{NAME_WIDTH}} {'PASS' if rc == 0 else 'FAIL':<7} {secs:>8.1f}")
    failed = [s.name for s, rc, _, _ in results if rc != 0]
    total = sum(secs for _, _, secs, _ in results)
    verdict = "ALL PASS" if not failed else f"{len(failed)} FAILED ({', '.join(failed)})"
    print(f"\n{len(results) - len(failed)}/{len(results)} suites passed in {total:.1f}s: {verdict}")


def print_failures(results: list[Result]) -> None:
    """Tail of the output of each failing suite, so the cause is visible without re-running it."""
    for suite, rc, _, out in results:
        if rc != 0:
            print(f"\n--- {suite.name} (exit {rc}), last {TAIL_LINES} lines ---")
            print("\n".join(out.strip().splitlines()[-TAIL_LINES:]))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Run every offline evaluation suite and print a PASS/FAIL table.")
    ap.add_argument("--quick", action="store_true", help="skip the slow metamorphic suite")
    ap.add_argument("--only", action="append", choices=sorted(BY_NAME), metavar="NAME", help="run only this suite")
    ap.add_argument("--list", action="store_true", help="print the suite names and exit")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.list:
        print("\n".join(s.name for s in SUITES))
        return 0
    results: list[Result] = []
    for suite in select(args.quick, args.only):
        print(f"running {suite.name} ...", flush=True)
        results.append((suite, *run_suite(suite)))
    print()
    print_table(results)
    print_failures(results)
    return 1 if any(rc != 0 for _, rc, _, _ in results) else 0


if __name__ == "__main__":
    sys.exit(main())
