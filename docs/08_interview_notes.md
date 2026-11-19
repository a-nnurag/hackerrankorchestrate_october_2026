# 08. Notes for the AI interview

Short, honest talking points. Numbers come from `code/evaluation/evaluation_report.md`.

## The system in one minute

A deterministic Python pipeline (no model needed at run time). Per request:
1. **Classify** the request text: explicit non-deletion phrases (after stripping instruction-like fragments)
   give `NOT_APPLICABLE` with `[]`; everything else is a deletion or audit request.
2. **Resolve identity**: email (any case, current or historical) to a user; identifier set valid at `audit_at`
   (emails, hashes, phones).
3. **Ingest evidence once** into one table (SQL, logs in 8 formats, JSON, handover text; screenshots and PDFs
   through a one-off transcription), with record-level time and coverage (what a snapshot proves absent).
4. **Link** records to the person with a confidence: exact identifier 0.90 and above, timing-only 0.30 to 0.70.
5. **Decide state at `audit_at`** from the latest observation at or before it; claims (activity results,
   `reported_status`) are never proof.
6. **Apply the policy table** (`rules.py`) plus the conditions of rules 05, 06, 12, 13 (`conditions.py`).
7. **Build ordered steps**: findings, remediation (flows and restores first), verification; validate; flag for review.

## Investigation approach (how it was built)

Reverse-engineered the answer conventions from the 32 public answers; five research agents mapped identity,
evidence formats, sample logic, images/PDFs and open rules; a ranked critique before coding; an independent
agent re-implemented the task from the statement alone for a differential test.

## Remediation planning

Order is fixed by the operation table: DISABLE_DATA_FLOW and BLOCK_RESTORE before DELETE, REDACT, ANONYMIZE, so
nothing can recreate what was just removed. Retained records (audit, legal hold, backup, tombstone) are verified
present, never deleted. Every remediated record gets its verification.

## Evaluation

- 32 public samples: status 32/32; step precision 1.000, recall 0.974, F1 0.987; 28/32 exact. **In-sample**: the
  rules were chosen while looking at these answers. Leave-one-case-out and bootstrap: F1 interval 0.971 to 0.998;
  status Wilson interval 0.893 to 1.000.
- 22 synthetic cases of our own (time edges, historical email/hash/phone, lookalikes, replica drift, tombstone,
  rare categories, retention, ownership), mutation-checked.
- Independent implementation: 517/518 statuses identical, findings identical except one case, accounts agree
  401/404 and analytics 160/160 where both give one.
- Metamorphic and determinism tests (case, order, padding, injected instructions, hash seeds), an independent
  contract validator that passes the sample answers, and a raw-file provenance check of all 1,167 citations.

## Decisions worth explaining

- Evidence only counts if captured at or before `audit_at` (equality allowed) and observed at or after the request.
- Absence is proved only by a covering source (a 404, a scope row, an empty collection), never by silence.
- Where candidates cannot be told apart the pipeline leaves the step out and lists the case, rather than guess.
- A second-offset pattern in the event times resolves many ties; it is learned from the data without answers,
  flagged on 287 steps (9%), and no case status depends on it.
- The local LLM (Ollama `qwen3.5:4b`) is optional and a fallback: request wording the rules cannot classify and two
  free-text conditions. Output must be JSON with a verbatim quote; rules win otherwise. It makes 0 calls on the
  real 518 requests.

## Weak points to admit

Hidden accuracy is unknown; 9% of steps rest on timing; the 12 screenshot/PDF cases are unverified by a person
(and `case_63` has an identity mismatch); later-exported records decide one status (`case_126`); the row order,
the treatment of expired retention and shared attachments, and what to output when no evidence exists are choices
the task does not specify; telemetry and secondary identifiers have no parser path.

## Cost

No model calls in the submitted run: 0 tokens, USD 0. Runtime about 7 seconds for all 518 cases.

## Code structure and quality (see ARCHITECTURE.md, CODE_QUALITY.md)

`code/ghost/` is a package per concern: `ingest/` (16 parsers), linking stages, `conclusion`, `rules` (policy as data),
`conditions`, `pipeline.Auditor`, optional `llm/`. One frozen `LinkSettings` holds every threshold with its evidence.
Gates: ruff clean, mypy clean, no function above complexity 10, 12 offline suites, and a golden check that proved the
refactor changed no decision (`output.csv` byte-identical).

## Likely questions and short answers

- **Why no LLM?** The task is mostly exact matching on identifiers, times and tables; rules are reproducible and cost
  nothing. An LLM is used only where wording is free text, and never decides alone.
- **How do you know it works on the hidden 518?** We do not. 32/32 statuses on samples are in-sample; the independent
  re-implementation, synthetic cases, metamorphic tests and the review list are how we bounded the risk.
- **Where could it be wrong?** Timing-inferred links (9% of steps), the 12 image/PDF cases, unspecified conventions.
- **How do you stop prompt injection?** Instruction-like text is stripped before classification; the LLM output must be
  schema-valid with a verbatim quote; rules win otherwise; metamorphic tests inject instructions.
- **Why can a COMPLETE case have steps?** Verification steps cite the evidence proving the compliant state at `audit_at`.
- **What would you do with more time?** Have a person check the review list, add parsers for telemetry and secondary
  identifiers, and measure the LLM presence-check agent live.
- **How was AI used?** Claude Code wrote and refactored the code and docs under the logging rules in `AGENTS.md`;
  research agents analysed the data; decisions and checks are in `log.txt`. Be ready to say what you verified yourself.
- **How was the log corrected?** Early timestamps were invented; a LOG CORRECTION entry states this openly.
