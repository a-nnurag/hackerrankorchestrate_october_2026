# Research record

Everything that was looked up or measured while building the audit agent, in one place: what was asked, what was found, what it
changed, and how sure we are. Detail lives in the numbered notes (`docs/01` to `09`) and in `code/evaluation/evaluation_report.md`;
this file is the index and the synthesis.

**Evidence levels:** *measured* (we ran it, a script reproduces it), *reported* (an agent or a source said it, not re-run by us),
*guess* (reasoned, no data). Web sources are mostly papers, working papers, vendor documentation and blogs. None addresses this
exact task, several were read only as abstracts or summaries, and vendor numbers can change; they give direction, not constants.

## 1. Questions and answers at a glance

| # | Question | Answer in one line | Level | Where |
|---|---|---|---|---|
| 1 | Is there a ready-made plugin or solution for this challenge? | No. Only a different edition's starter repo and generic GDPR skills; none verifies erasure across systems. A pre-built answer would also be off-limits under `AGENTS.md`. | measured (searches) | 2.1 |
| 2 | Which local LLM fits an RTX 3050 6 GB? | `qwen3.5:4b` (3.3 to 4.0 GB, text and image) beat `qwen3:4b` and `qwen2.5:3b` on our request-wording tests. | measured | 2.2, 4.6 |
| 3 | How should retention ends, legal holds, shared attachments and the log gap be handled? | Dates compared with `audit_at`; shared items redacted; late log entries appended, never edited. LLM only for free text. | reported (sources), measured (tests) | 2.3, `07` |
| 4 | How to handle thresholds tuned on 32 cases? | Interval lower bounds, leave-one-out, bootstrap, labels made from the data itself. | measured | 2.4, `09` |
| 5 | How to link records when candidates look identical? | Status filter, learned second-offset pattern, assignment constraint, abstain otherwise. | measured | 2.5, 4.4 |
| 6 | Can Groq's free tier run an evaluation agent? | Yes within 30 RPM / 8,000 TPM / 200,000 TPD (Developer-plan base figures); the client paces itself to 80%. | reported (limits), measured (simulation) | 2.6 |
| 7 | Do cited files really contain what the steps claim? | All 1,167 cited steps are supported by the raw file text; 17 findings and 12 image/PDF steps need a person. | measured | 4.8 |
| 8 | What is still unknown? | Hidden-set accuracy; the 12 screenshot/PDF cases; unspecified conventions. | measured | 5 |

## 2. Web research

### 2.1 Is there a ready-made plugin or solution? (answer: no)

Queries: the challenge name with "deletion audit agent plugin"; the October repo name; "Claude Code plugin GDPR data deletion audit right
to erasure verification skill". Found: the June edition's starter repository
([interviewstreet/hackerrank-orchestrate-june26](https://awesome.ecosyste.ms/projects/github.com%2Finterviewstreet%2Fhackerrank-orchestrate-june26)),
a feature request to delete session data ([anthropics/claude-code#24126](https://github.com/anthropics/claude-code/issues/24126)),
generic GDPR skills ([gdpr-data-audit](https://claudskills.com/skills/gdpr-data-audit/), [gdpr-rails](https://claudskills.com/skills/gdpr-rails/)) and
vendor deletion wrappers ([Klaviyo](https://openskillindex.com/skills/jeremylongshore-claude-code-plugins-plus-skills-klaviyo-data-handling)).
Nothing confirms erasure across systems. Decision: build it; do not install unvetted third-party skills.

### 2.2 Local model for a 6 GB GPU

Sources: [best Ollama models for 6 GB](https://localaimaster.com/vram/best-ollama-models-6gb-vram),
[best local LLM 6 GB](https://www.promptquorum.com/ar/prompt-bites/best-local-llm-6gb-vram) (SEO-style, benchmark claims unverified),
and the [Ollama library page for qwen3.5](https://ollama.com/library/qwen3.5): 2b 2.7 to 3.1 GB, 4b 3.3 to 4.0 GB, 9b 6.6 to 7.6 GB (too big),
256K context, text and image input. Context size, not weights, is the trap on 6 GB (we use `num_ctx` 2048). Installed here: `qwen3:4b`,
`qwen2.5:3b-instruct`, `minicpm-v` (5.5 GB, vision, barely fits). We pulled `qwen3.5:4b`. Our own comparison is in 4.6.

### 2.3 Retention, legal hold, shared records, log corrections (details in `docs/07`)

- Erasure has exceptions for a specific legal obligation or legal claims, and a vague need does not qualify
  ([GDPR Art. 17](https://gdpr-info.eu/art-17/), [GDPR Local](https://gdprlocal.com/es/right-to-erasure/)).
- A legal hold overrides disposal while active; on release retention resumes and expired records can be purged at once; a hold protects
  from its effective date only ([Venio](https://www.veniosystems.com/blog/legal-hold-and-auto-deletion-in-m365-and-google-vault),
  [Folderit](https://www.folderit.com/glossary/retention-hold/)).
- Redaction and anonymisation are common partial erasure; regulators press controllers to finish related data
  ([Irish DPC case studies](https://www.dataprotection.ie/dpc-guidance/case-studies/erasure)). Nothing found rules on redacting only one party of a
  shared conversation.
- Corrections to an append-only trail are new entries with a reason ([Cratis](https://www.cratis.io/chronicle/events/revision/),
  [audit-log design](https://www.techinterview.org/post/3233465643/system-design-audit-log/)); backfill is not covered, the inference is a late entry with its own timestamp.

Used for: `ghost/conditions.py` (retention end, hold end, uploader not the subject, shared message context), six `LATE ENTRY` records in `log.txt`.

### 2.4 Small-sample statistics (details in `docs/06` and `docs/09`)

Wilson, Jeffreys and Clopper-Pearson intervals for small test sets ([2309.14621](https://arxiv.org/pdf/2309.14621), [2503.01747](https://arxiv.org/pdf/2503.01747),
[Jeffreys interval](https://metricgate.com/calculator/jeffreys-interval), [beta-binomial](https://arxiv.org/pdf/2008.13619)); selective prediction with
risk control ([Selective Conformal Risk Control](https://arxiv.org/pdf/2512.12844), [2606.08517](https://papers.cool/arxiv/2606.08517)); nested cross-validation
([Raschka](https://arxiv.org/pdf/1811.12808), [small-data study](https://arxiv.org/pdf/2208.10784)); about 100 evaluations are needed for plus or minus 9 points
([calculator](https://aischool.lillytechsystems.com/tools/eval-confidence.html)). No source settles a plateau or one-standard-error rule for tiny sets.

### 2.5 Linking, abstaining, extracting from images (details in `docs/06`)

Fellegi-Sunter three-way decisions (link, non-link, review) and one-to-one assignment with a threshold ([Census](https://www.census.gov/content/dam/Census/library/working-papers/2004/adrm/rrs2004-01.pdf),
[Bayesian bipartite matching](https://arxiv.org/pdf/1601.06630)); unsupervised EM estimates of match probabilities are unreliable as error rates
([Census 2007](https://www.census.gov/content/dam/Census/library/working-papers/2007/adrm/rrs2007-05.pdf),
[Statistics Canada](https://www150.statcan.gc.ca/n1/en/catalogue/11-522-X202200100001)); for image extraction run two independent readings, validate identifiers
against format and reference data, and keep human double entry for conflicts
([Neo4j lesson](https://graphacademy.neo4j.com/courses/entity-communication-networks/1-extraction/9-extracting-with-vision/),
[validation patent](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/11720961)).

### 2.6 Groq for evaluation-time agents

From Groq's own documentation pages when fetched (values can change; check the console):
[models](https://console.groq.com/docs/models) (`openai/gpt-oss-120b` $0.15/$0.60, `openai/gpt-oss-20b` $0.075/$0.30, `qwen/qwen3.8-27b` $0.80/$4.00 per 1M tokens),
[structured outputs](https://console.groq.com/docs/structured-outputs) (strict `json_schema` on gpt-oss and qwen3.8; other models JSON-object mode),
[vision](https://console.groq.com/docs/vision) (`qwen/qwen3.8-27b`, 3 images per request, 2,048 tokens per image),
[rate limits](https://console.groq.com/docs/rate-limits) (Developer-plan base 30 RPM, 1,000 RPD, 8,000 TPM, 200,000 TPD per model, per organisation;
`retry-after` on 429; `x-ratelimit-*` headers; no separate free-tier numbers on the page),
[reasoning](https://console.groq.com/docs/reasoning) (`reasoning_effort` low/medium/high and `include_reasoning` for the gpt-oss models; whether reasoning tokens count
toward limits is not stated, so the client assumes they do). Implemented as `GroqLLM` and `RateLimiter` (`code/ghost/llm.py`). No live run: no key here.

## 3. Prompt-injection and PII checks (no web source needed)

Designed and tested ourselves: instruction-like fragments are stripped before matching and before any model sees text; models must answer in a schema and quote verbatim.
A live test found the raw text could flip `qwen3.5:4b` on 1 of 3 injections, fixed by sanitising inside the adjudicators (`code/evaluation/test_condition_llm.py`).
The 518-request metamorphic test with an appended injection changes no output. PII detection works on field values and an email pattern; phone numbers or names inside free text
and obfuscated emails are not covered (none occur in the 107 message texts).

## 4. Internal research and measurements

### 4.1 Agent studies of the dataset (`docs/01` to `05`)
Identity and activity (all 518 request emails resolve; `email_hash` is sha256 of the lower-cased email; 10 non-deletion requests match 10 `CLASSIFY_REQUEST` rows; about 74% of
activity rows link to no requester); evidence formats (every file parses; 7 log layouts; scope rows prove absence; replica drift is by set difference); reverse-engineering of the 32 sample answers
(decision table, ordering key with zero violations, citation rule); transcription of 11 screenshots and 4 PDFs; open rules (latest qualifying file per resource, sort moot, legal holds, the `marketing_001` mismatch); ingestion prototype (91% of sample pairs reproducible).
Level: reported by the agents, key figures re-verified by us.

### 4.2 Findings that changed the design
`reported_status` mirrors the account delete result (16/16, 10/10, 5/5); observations older than the request are stale; absence is proved only by coverage; a type cap hid a real second leak (restricted to singleton types);
a mixed request ("delete my account, don't delete my invoices") was misclassified (conflict detection plus optional LLM); a later-exported file can only support uncited steps.

### 4.3 Robustness (`code/evaluation/robustness.py`)
24 configurations: F1 0.937 to 0.987; the chosen setting wins all 32 leave-one-case-out folds; bootstrap F1 [0.971, 0.998]; status 32/32, Wilson [0.893, 1.000].

### 4.4 Link evidence (`code/evaluation/threshold_uncertainty.py`, `docs/09`)
Per link type with exact intervals (exact identifiers 83/84, lower bound 0.94; unique-anchor cluster 17/17, 0.80; second-offset resolver 3/3, 0.29; contested 2/20); event-time second offsets are a per-type pattern
(search entries 122 of 138 on 21 or 22 s; anonymized analytics +40/41 s in 129 of 358 pairs); self-supervised hold-out of exact-linked accounts: 74 cases, 50 correct picks, 0 wrong, 24 abstentions, precision interval [0.929, 1.000].

### 4.5 Differential test (`code/evaluation/compare_outputs.py`)
An independently built implementation: 517 of 518 statuses identical; findings identical except case_126; accounts 401 same, 3 different; analytics 160 same, 0 different; it fills 93 accounts and 30 analytics rows we abstain on.

### 4.6 LLM measurements
Request wording, 26 hand-labelled plus 50 real (10 refusals): `qwen3.5:4b` v1 prompt 76 of 76, v0 74 of 76, "unclear" variant unusable (about 40 abstentions); `qwen3:4b` 24 of 26; `qwen2.5:3b` 15 of 26.
Second opinion on all 398 unique real texts: 373 agree, 20 rejected by the quote guard (fixed for elided quotes), 5 disagree with the rules being right. Condition adjudicators 12 of 12 plus 3 of 3 injections.
Vision cross-check (`minicpm-v`): 20 of 24 ids and emails read, no contradictions.

### 4.7 Synthetic and mutation tests
22 synthetic cases (mutation-checked); validator mutations 10 of 10 caught; metamorphic tests M1 to M8 and a byte-identical run across hash seeds.

### 4.8 Evidence presence (`code/evaluation/provenance_check.py`, `presence_agent.py`)
1,167 cited steps checked against raw files: 0 unsupported; 17 findings with the identifier on another log line; 12 image/PDF steps. Swapping 200 citations is caught 91% of the time (misses are "nothing here" absences).
The LLM presence agent (Groq or Ollama) is built and tested offline; its accuracy is not measured.

## 5. Gaps and open questions

Hidden-set accuracy; the 12 screenshot/PDF cases (and `case_63`'s identity); whether the grader expects later-exported records, numeric row order, `COMPLETE []` for no evidence, deletion of expired retention, redaction of shared attachments;
no source on redacting one party of a shared conversation or on a plateau rule for tiny sets; free-tier limits specific to your account (read the console); product telemetry and secondary identifiers have no parser path.

## 6. Reproduce

| Result | Command |
|---|---|
| sample scores, ablations, synthetic cases | `python code/evaluation/main.py` |
| thresholds, bootstrap, leave-one-out | `python code/evaluation/robustness.py` |
| link-type intervals, self-supervised test | `python code/evaluation/threshold_uncertainty.py --indep <other output.csv>` |
| differential test | `python code/evaluation/compare_outputs.py output.csv <other output.csv>` |
| contract, mutation, determinism | `python code/evaluation/validate_output.py`, `metamorphic.py` |
| provenance | `python code/evaluation/provenance_check.py` |
| LLM tests | `test_classifier.py`, `test_condition_llm.py`, `llm_benchmark.py`, `llm_second_opinion.py` |
| Groq client and limits | `test_groq_client.py`, `test_groq_limits.py`, `presence_agent.py --dry-run` |
