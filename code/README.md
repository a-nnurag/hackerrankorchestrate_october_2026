# Ghost Data Still Exists: deletion-audit agent

A deterministic pipeline that audits each deletion request: it decides whether deletion was
requested, reconstructs what still exposes the person at `audit_at`, and writes the ordered
findings, remediation and verification steps. No language model is called at run time.

## Setup and run

Requires Python 3.10 or newer (tested on 3.14) and no third-party packages.

```bash
# from the repository root, with the dataset in dataset/
python code/main.py                 # audits dataset/deletion_requests.csv, writes output.csv
python code/main.py --eval          # also scores the 32 public samples (dataset/sample_output.csv)
python code/evaluation/main.py      # ablations + synthetic cases (the tables in the evaluation report)
python code/evaluation/synthetic_cases.py   # only the 22 synthetic cases
python code/evaluation/presence_agent.py --dry-run   # LLM evidence-presence agent (Groq or Ollama); --selftest runs offline
python code/evaluation/test_groq_client.py  # offline tests of the Groq client
python code/evaluation/test_groq_limits.py  # offline simulation of the free-tier rate limits (fake clock)
python code/evaluation/test_condition_llm.py # live check of the ownership and shared-context adjudicators
python code/evaluation/test_classifier.py   # request-classifier tests (rules, guards, live LLM if Ollama is up)
python code/evaluation/llm_benchmark.py     # compare installed Ollama models on 26 labelled requests
python code/evaluation/vision_crosscheck.py # independent vision-model check of the image transcriptions
python code/evaluation/validate_output.py   # independent contract check of output.csv (add --gold to validate the sample answers)
python code/evaluation/metamorphic.py       # metamorphic, determinism and validator-mutation tests
python code/evaluation/compare_outputs.py output.csv other.csv --out diff.csv   # differential test against an independent implementation
python code/evaluation/threshold_uncertainty.py [--indep other.csv]   # per-link-type intervals and the self-supervised hold-out
python code/evaluation/robustness.py        # threshold sensitivity, leave-one-case-out, bootstrap intervals
python code/evaluation/check_manual.py      # consistency of the image/PDF transcriptions with identity and activity data
python code/evaluation/diff_cases.py --only-bad   # missing/extra steps per public sample
```

On Windows consoles use `python -X utf8 code/main.py` if names print incorrectly.

Optional local LLM (Ollama, off by default): `python code/main.py --llm [--llm-model qwen3.5:4b]`.
It is consulted only for request text the rules flag as conflicting or unknown, its answer must
quote the request verbatim, and the rules decide whenever it is unavailable or invalid. On the 518
real requests it is never called, so output.csv is identical with and without it.

Groq as an alternative provider (cloud, OpenAI-compatible API): set `GROQ_API_KEY` in your environment (never in a file, never
in chat) and use `--llm-provider groq [--llm-model openai/gpt-oss-120b]`. Text sent to Groq leaves the machine; use it only for
the fictional challenge data. If the final run uses it, record the provider, model, calls and tokens in
`evaluation/usage_report.md` (the client keeps `usage` and an estimated cost). The client paces itself to the free-tier limits (30 RPM, 1,000 RPD, 8,000 TPM, 200,000 TPD
assumed; read yours at console.groq.com/settings/limits and set `GHOST_GROQ_LIMITS="rpm=..,rpd=..,tpm=..,tpd=.."`), keeps a daily budget in
`code/.cache/groq_budget.json`, honours `retry-after` and the `x-ratelimit-*` headers, and caches every answer. The evidence-presence agent
(`python code/evaluation/presence_agent.py --provider groq`) is an evaluation-time check and is not part of `main.py`.

Useful options of `code/main.py`: `--out PATH`, `--mode strict|record|relaxed`, `--min-link X`,
`--no-cluster`, `--review PATH` (a ranked review list: tier 1 image/PDF evidence, tier 2 evidence family no sample cites, tier 3 contested accounts easiest first, tier 4 other; the last run is in `code/evaluation/artifacts/review_list.csv`). `GHOST_DATASET=<dir>`
points the code at another dataset directory (used by the synthetic tests).

Output: `output.csv` at the repository root, 518 rows in the order of `deletion_requests.csv`
(natural order: case_33, case_34, ...), columns `case_id,deletion_status,steps_json`.
A full run takes a few seconds.

## How it works

| Module | Role |
|---|---|
| `ghost/classify.py` | decides whether the request authorises deletion (explicit non-deletion phrases; everything else is a deletion or audit request) |
| `ghost/conditions.py` | conditions of rules 05, 06, 12, 13 (retention/hold end dates, attachment ownership, shared message context): rules first, LLM only for free text |
| `ghost/llm/` | optional LLM clients (Ollama, Groq with free-tier rate limiter), prompts, on-disk cache, guarded adjudicators |
| `ghost/ingest/` | parses every SQL, JSON, log and text evidence file and the manual image/PDF transcriptions (`ghost/manual/`) into one SQLite observation table |
| `ghost/identity.py` | resolves the request email (current or historical, any case) to a user and builds the identifier set valid at `audit_at` |
| `ghost/claims.py`, `linking.py`, `anchoring.py`, `timing.py`, `linker.py` | link observations and activity to the user with a confidence score (exact email 0.99 down to activity-cluster 0.30); `linker.py` is the facade |
| `ghost/conclusion.py` | concludes each resource's state at `audit_at`; absence only from covering evidence |
| `ghost/rules.py` | policy as data: (category, state) to finding, remediation and verification operations |
| `ghost/settings.py` | `LinkSettings` (all thresholds with their evidence) and fixed vocabularies |
| `ghost/pipeline.py` | `Auditor`: per-case orchestration, item selection, step ordering, validation, review list |
| `ghost/evaluate.py` | metrics against labelled answers and a hallucination check |

See `docs/ARCHITECTURE.md` for the data flow and `docs/CODE_QUALITY.md` for the quality gates.

Key decisions (documented with evidence in `docs/`):

- Reported statuses and activity results are claims; state comes from evidence.
- Evidence is used only if its manifest `captured_at` is at or before `audit_at` (equality allowed).
  A record must also be observed at or after `requested_at` to show the post-request state.
- Records exported after `audit_at` but timestamped before it may support uncited verification
  steps, never a citation. A finding whose only state file is later cites the deletion-worker
  activity row.
- Steps are sorted by (phase, operation order, system_id, resource_id), numbered from 1.
- Links below confidence 0.45 are dropped (they would guess between cases) and listed in the review
  file.

## Layout

```
code/
  main.py                  entry point
  ghost/                   pipeline package (ingest/, llm/, linking, rules, ...; manual/ transcriptions)
  evaluation/              evaluation_report.md, usage_report.md, harness, synthetic cases, tooling
  tests/                   unittest wrapper over the offline suites
```

Tests and quality gates:

```bash
python code/evaluation/run_all.py                    # all offline suites
python -m unittest discover -s code/tests -t code    # same, unittest runner
python code/evaluation/golden_check.py               # decisions and output.csv unchanged
python -m ruff check code && python -m ruff format --check code && python -m mypy code/ghost
python code/evaluation/check_log.py                  # log.txt format check
```

Do not include `dataset/`, `code/.cache/` or `output.csv` in `code.zip`.
