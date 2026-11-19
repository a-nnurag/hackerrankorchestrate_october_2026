# Code quality

How the code is checked, what was wrong when it was measured, and what it looks like now. Tools are development-time only
(`python -m pip install ruff radon vulture mypy`); the solution itself uses only the Python standard library.

## Gates (configured in `pyproject.toml`)

| Gate | Command | Rule |
|---|---|---|
| lint | `python -m ruff check code` | pycodestyle, pyflakes, bugbear, naming, pyupgrade, simplify, import order, docstrings (`D1`), complexity at most 10 |
| format | `python -m ruff format --check code` | one style, 120 columns |
| types | `python -m mypy code/ghost` | public signatures annotated; checked on the whole core package |
| complexity | `python -m radon cc code -s -n C` | prints nothing: no function above rank B |
| dead code | `python -m vulture code --min-confidence 80` | only the unused `cls` of a `unittest` hook is reported |
| behaviour | `python code/evaluation/golden_check.py` | evidence table, per-case results and the `output.csv` bytes are unchanged |
| everything | `python code/evaluation/run_all.py` | 12 offline suites |

## Before and after (measured 2026-10-25)

The first review of the code found it did not meet this bar: the two oldest modules were carried over from a prototype.

| Measure | Before | After |
|---|---|---|
| `ruff check` findings (same configuration) | 392 | 0 |
| files not formatted | 29 of 34 | 0 of 73 |
| functions at complexity rank C or worse | 44 | 0 |
| worst functions | `link_case` 112, `parse_log` 92, `parse_sql` 51, `conclude` 51, `Auditor.audit` 34, `validate` 76, `presence_agent.main` 76 | 10 or below everywhere |
| maintainability index | `ingest.py` 0.0 (rank C), `linker.py` 2.2 (rank C) | every module rank A (lowest 22.9) |
| average complexity | not measured | A (3.6) over 597 blocks |
| `mypy` on `code/ghost` | not run | no issues in 43 files |
| public functions and classes with a docstring (`ghost`, `main`) | not measured | 131 of 132 |
| module-level switches mutated from outside | 6 (`STATUS_FILTER`, `SINCE_REQUEST`, `ANCHOR_WIN`, `PHASE`, ...) | none; one frozen `LinkSettings` |
| dead code | `OPMAP`, `ABS_CONF`, `expected_from_output`, `STUB_SCHEMA`, `utc`, `make_stubs` and a dozen unused names | removed |
| structure | `ingest.py` 912 lines, `linker.py` 408 lines, `llm.py` 565 lines | `ingest/` 16 modules, linking stage 9 modules, `llm/` 10 modules |

## How the refactor was kept safe

Before touching the code a golden check was recorded (`code/evaluation/golden/golden.json`): SHA-256 of the observation table
content, the coverage rows, the activity edges, the result of all 550 cases (status, steps, review flags, notes) and of the
`output.csv` bytes. Four independent copies of the code were refactored in parallel, each verified against that fingerprint
and against the printed output of the affected scripts; the results were then merged and re-verified together. After the merge
the golden check matches, `output.csv` is byte-identical to the version submitted earlier, and `run_all.py` passes.

## Conventions

- Every module starts with a docstring that says what it is for; every public class and function has one that says what it
  takes and returns when that is not obvious.
- Comments explain why (the evidence behind a threshold, the data finding behind a rule), not what the line does.
- Names are words; no single-letter names outside tiny scopes; no assigned lambdas; constants are named and documented.
- A function does one thing and stays under complexity 10; long tables of data (prompts, rule tables, vocabularies) live in
  their own modules.
- Behaviour that depends on a setting reads it from `LinkSettings`; nothing reads or writes module globals.

## What this does not cover

Static metrics do not show that the decisions are right: that is the job of the evaluation (`evaluation/evaluation_report.md`),
and its limits are listed there. The evaluation scripts keep a looser docstring rule (module docstrings required, function
docstrings optional) because they are tools, not the product.
