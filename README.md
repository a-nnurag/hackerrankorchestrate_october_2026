# Ghost Data Still Exists: a deletion-audit agent

My solution to **HackerRank Orchestrate (October 2026)**. Final score **73.2 / 100**, rank **#184**.

A deletion workflow can report **Complete** while a person's data still sits in database replicas, logs, support
attachments, exports, search indexes, archives or backups. Sync and restore jobs can also bring deleted data back.

This agent checks whether the data is really gone. For each deletion request it:

1. Decides whether a deletion was actually requested
2. Searches the evidence (SQL snapshots, logs, JSON, text, PDFs and images) for data still linked to the person
3. Returns a verdict: `COMPLETE`, `INCOMPLETE` or `NOT_APPLICABLE`
4. Lists the findings, then the remediation and verification steps, in the order needed to finish the deletion safely

## Results

| Part | Score |
|---|---|
| Output CSV (accuracy) | 27.0 / 30 |
| AI judge interview | 22.5 / 30 |
| Chat transcript | 7.2 / 10 |
| Code | 16.5 / 30 |
| **Final** | **73.2 / 100** |

## Approach: AI where it adds value

The dataset had a limited, well-defined set of case patterns: identity changes, replica drift, retention and legal
holds, backups and restore risks. AI is most useful when there are too many cases to handle one by one. Here each
pattern could be handled with explicit rules, which are more accurate, traceable and testable.

So the core is a **deterministic, rules-based pipeline**:

- Reported statuses are treated as claims. The state of each resource comes from evidence captured before `audit_at`.
- Every finding cites the evidence file that proves it.
- The deletion policy is data (`code/ghost/rules.py`): (category, state) maps to finding, remediation and verification steps.
- An LLM (local Ollama or Groq) is optional and used only for request wording the rules cannot classify. Its answer must
  quote the request word for word, and the rules decide whenever the model is unavailable or invalid. On the 518 real
  requests it is never called, so the output is the same with or without it.

```
dataset/ ──> ingest/ ──> one observation table ──> identity ──> linking ──> conclusion
                                                                              │
                         output.csv  <──  pipeline (ordered steps)  <──  rules + conditions
```

## Quick start

Requires **Python 3.10+**. No third-party packages are needed to run.

The challenge dataset is not included in this repo. Copy the `dataset/` folder from the
[official challenge repository](https://github.com/interviewstreet/hackerrank-orchestrate-october26) into the repo root, then:

```bash
python code/main.py           # audits dataset/deletion_requests.csv and writes output.csv
python code/main.py --eval    # also scores the 32 public sample answers
```

On Windows, use `python -X utf8 code/main.py` if names print incorrectly. A full run takes a few seconds.

Optional LLM fallback:

```bash
python code/main.py --llm                                   # local Ollama
python code/main.py --llm --llm-provider groq               # Groq; set GROQ_API_KEY in your environment
```

## Testing and evaluation

```bash
python code/evaluation/run_all.py                   # all offline test suites
python code/evaluation/main.py                      # ablations and synthetic cases
python code/evaluation/validate_output.py           # contract check of output.csv
python code/evaluation/golden_check.py              # decisions and output.csv unchanged
```

The evaluation also includes metamorphic and determinism tests, 22 synthetic edge cases, threshold-sensitivity and
bootstrap analysis, and a differential check against an independent implementation. The full write-up is in
[code/evaluation/evaluation_report.md](code/evaluation/evaluation_report.md).

## Repository layout

```
code/
  main.py              entry point
  ghost/               pipeline package: ingest, identity, linking, conclusion, rules, pipeline, optional llm
  evaluation/          evaluation report, test harness, synthetic cases, analysis tools
  tests/               unittest wrapper over the offline suites
docs/                  design notes, decisions, research and architecture
output.csv             final predictions for the 518 requests
problem_statement.md   the challenge contract
```

## Documentation

| Document | Contents |
|---|---|
| [code/README.md](code/README.md) | Detailed run options, module map and key decisions |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Data flow, module map, design rules, how to extend |
| [docs/02_rules_and_decisions.md](docs/02_rules_and_decisions.md) | Rule table, decision table, step ordering, time rules |
| [docs/03_design_critique.md](docs/03_design_critique.md) | Where accuracy can be lost and how it was addressed |
| [docs/RESEARCH.md](docs/RESEARCH.md) | Questions asked, sources and measurements |
| [docs/README.md](docs/README.md) | Index of all design notes |
| [code/evaluation/evaluation_report.md](code/evaluation/evaluation_report.md) | Metrics, ablations and robustness results |

## Acknowledgements

The problem statement and dataset belong to [HackerRank](https://www.hackerrank.com/). Built with help from Claude Code.
