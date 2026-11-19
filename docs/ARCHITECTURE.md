# Architecture

A deterministic pipeline that turns one deletion request into a status and an ordered list of steps. No model is needed at run
time; an optional local LLM is a fallback for request wording the rules cannot classify and for two free-text conditions.

## Data flow

```
dataset/*.csv + evidence/**                       code/ghost/manual/*.json (screenshots, PDFs)
        |                                                    |
        v                                                    v
  ingest/  --------------- one SQLite observation table (resource, system, category, state, identifiers,
        |                   record time, file, coverage) + activity stream + catalog edges
        v
  store.py  (in-memory view)          identity.py  (email -> user -> identifiers valid at audit_at)
        \                                  /
         \                                /
          linking.py  --  exact identifiers (claims.py) -> catalog / attachment / source links
                      --  anchoring.py: activity-cluster links, timing.py: second-offset pattern
          conclusion.py -- state of every linked resource at audit_at and the file that proves it
                |
          conditions.py -- rules 05, 06, 12, 13 (dates, uploader, shared context); LLM only for free text
                |
          rules.py  -- (category, state) -> finding / remediation / verification operations
                |
          pipeline.py -- Auditor.audit(case): select items, build ordered steps, validate, flag for review
                |
          output.csv  +  review list (tiers: image/PDF, unseen family, contested or timing-inferred, other)
```

One request in, one row out. `classify.py` runs first: a request that does not authorise deletion returns `NOT_APPLICABLE`
with no steps before any evidence is touched.

## Module map (`code/`)

| Module | Responsibility |
|---|---|
| `main.py` | command line: ingest, audit all requests, write `output.csv`, optional evaluation and review list |
| `ghost/ingest/` | parse every SQL, JSON, log, text file and the manual transcriptions into the observation database |
| `ghost/store.py` | in-memory view of that database |
| `ghost/identity.py` | email, hash, phone resolution and their history |
| `ghost/settings.py` | `LinkSettings` (every threshold, window and switch, each with the evidence behind it) and the fixed vocabularies |
| `ghost/claims.py` | which user owns which resource by exact identifier |
| `ghost/linking.py`, `anchoring.py`, `timing.py` | the link steps in decreasing strength; timing links are weak and always flagged |
| `ghost/conclusion.py` | state at `audit_at`, absence proved only by a covering source |
| `ghost/rules.py` | the policy table as data |
| `ghost/conditions.py` | conditions of the retention, ownership and shared-context rules |
| `ghost/classify.py` | request classification and instruction stripping |
| `ghost/pipeline.py` | `Auditor`: orchestration, item selection, step ordering, validation, review flags, review list |
| `ghost/evaluate.py` | metrics against labelled answers and the hallucination check |
| `ghost/llm/` | optional LLM clients (Ollama local, Groq cloud with free-tier rate limiting), prompts and guarded adjudicators |
| `evaluation/` | evaluation harness, test suites, tooling (see `evaluation/run_all.py`) |
| `tests/` | `unittest` wrapper that runs the offline suites |

## Rules the design follows

- **Claims are not proof.** Activity results and `reported_status` never decide a state; evidence at or before `audit_at` does.
- **Absence needs a covering source** (a 404, a scope row, an empty collection); silence proves nothing.
- **Links have a strength.** Exact identifiers (0.90 and above) carry findings; timing-only links (0.30 to 0.70) can add
  "already compliant" checks and are flagged; contested links are not output.
- **The model never decides alone.** Every answer must be valid JSON, quote the text verbatim and agree with the schema;
  otherwise the rules decide.
- **Configuration is explicit.** `LinkSettings` is a frozen dataclass handed down from `Auditor`; no module-level switches.
- **Determinism.** No randomness, sorted iteration where order matters; two processes with different hash seeds write the same bytes.

## Extending

- A new evidence format: add a parser module under `ghost/ingest/` that fills a `Table`, register it in `ghost/ingest/__init__.py`.
- A new data category or rule: add it to `ghost/rules.py` (category, state, treatment); add a case to `evaluation/synthetic_cases.py`.
- A new link signal: add a step in `ghost/linking.py` with its own confidence in `settings.LINK`, and judge it with
  `evaluation/threshold_uncertainty.py`.

## Testing and quality gates

`python code/evaluation/run_all.py` (or `python -m unittest discover -s code/tests -t code`) runs the offline suites. The golden
check fingerprints the evidence table, every case result and the `output.csv` bytes, so a refactor cannot change a decision
unnoticed. Static gates (`pyproject.toml`): `ruff check`, `ruff format --check`, `mypy code/ghost`, complexity at most 10 per
function. Figures are in `docs/CODE_QUALITY.md`.
