# 06. Handling the four stated limitations

> Status 2026-10-25: updated after the differential test; the contested-links section reflects the second-offset resolver.

Research (web search plus analysis of our own code and data) on how to handle the limitations listed in
`code/evaluation/evaluation_report.md` section 8. What changed in the code is listed per item. The web
sources are mostly papers, working papers and vendor material, and none addressed this exact task;
they are cited for the general method only.

## 1. Thresholds tuned on the samples

**What the literature says**
- With a validation set of 100 or fewer examples, Wilson-type intervals have better coverage than Wald
  or normal-approximation intervals ([arXiv 2309.14621](https://arxiv.org/pdf/2309.14621),
  [arXiv 2503.01747](https://arxiv.org/pdf/2503.01747)).
- Comparisons between settings on very small sets overlap almost entirely; roughly 100 evaluations are
  needed for about ±9 points ([calculator source](https://aischool.lillytechsystems.com/tools/eval-confidence.html)).
- Stratified and repeated cross-validation lower the variance of estimates
  ([Witten et al. slides](https://www.csd.uwo.ca/~xling/cs412/slides/Chapter5.pdf)). No source settled how to
  choose a decision threshold on a set this small.

**What we did** (`code/evaluation/robustness.py`)
- Sensitivity grid over min_link x anchor window x status filter (24 configurations): F1 between 0.917 and
  0.962, with every status 32/32. The worst cases simply fall back to using only exact identity links.
- Leave-one-case-out tuning: the same configuration wins in all 32 folds, held-out F1 0.962.
- Bootstrap over cases (steps inside a case are correlated, so the case is the unit): recall 95% interval
  [0.884, 0.962], F1 [0.938, 0.980]; status accuracy 32/32 with a Wilson 95% interval of [0.893, 1.000].

**What this does not show.** The 32 cases come from the same generator as the hidden 518, but the
interval for status accuracy still includes values near 90%. Hidden-set behaviour for categories and
evidence families the samples never touch cannot be estimated from them.

## 2. Contested links

**What the literature says**
- Fellegi-Sunter linkage uses two thresholds: link, non-link, and a middle band sent to clerical review.
- Linear-sum-assignment (Jaro) enforces one-to-one matching and drops assigned pairs whose weight is
  below the threshold. Used by the US Census Bureau's record linkage program (see
  [Census working paper](https://www.census.gov/content/dam/Census/library/working-papers/2004/adrm/rrs2004-01.pdf),
  [Bayesian bipartite matching](https://arxiv.org/pdf/1601.06630)).
- Our design already matches this shape: accept at 0.90 and above, drop below 0.45, review in between,
  and one resource per type per subject.

**What we found in our own data**
- The workflow's `reported_status` is a summary of the case's account delete result: COMPLETE = SUCCESS
  (16 of 16 sample cases), NOT_STARTED = FAILED (10 of 10), PARTIALLY_COMPLETE = PARTIAL or SUCCESS (5 of 5).
  It is a claim about the system's own outcome, so it is a legitimate key for choosing among candidate
  accounts even though it is not proof of the state.
- Implemented as `STATUS_FILTER` in `ghost/linker.py`: recall 0.891 to 0.927, F1 0.942 to 0.962 on the
  samples; 61 hidden cases gain one step; no status changes.
- That left 10 sample steps (accounts and anonymized analytics rows of cases sharing a `reported_at` and a result).
  Triage of an independent re-implementation (see `code/evaluation/evaluation_report.md` section 15) showed a
  further signal: within one case the event times of its records differ by fixed second offsets per record
  type (search entries: 122 of 138 exact-identifier pairs on 21 or 22 seconds modulo 60; anonymized analytics
  follow their account's delete at +40 or +41 seconds in 129 of 358 pairs, about 20 times chance). The offset
  tables are learned from the data with no answer key and used only to choose between candidate accounts
  (log-likelihood ratio with a margin) and to attach anonymized analytics rows to a resolved account; an account
  chosen for one case is removed from the others' candidates. Result on the samples: recall 0.927 to 0.974,
  precision still 1.000, 1 contested step left.
- This signal comes from how the log was produced, not from a real-world link. It is flagged
  (`inferred_by_timing`) on 287 hidden steps (9%), all "already compliant" verification steps, so no status
  depends on it. Where candidates stay inseparable the pipeline abstains: a forced guess among k is right
  with probability 1/k, no gain.

## 3. Image-dependent cases

**What the literature says** (patents and vendor material, treat as general practice)
- Run two independent extractions and flag disagreements; validate identifiers against format rules and
  reference data; reserve human double-entry for fields that still conflict
  ([Neo4j lesson on multi-engine extraction](https://graphacademy.neo4j.com/courses/entity-communication-networks/1-extraction/9-extracting-with-vision/),
  [validation patent](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/11720961)).

**What we did**
- Independent second reading: `vision_crosscheck.py` (minicpm-v) read 20 of 24 transcribed ids and emails.
  No contradictions; two of the four misses are ids that are not printed on screen (`tombstone_17` comes from
  the title `user_17`, `object_19` from the file name), two are emails in small text.
- Consistency with data we did not transcribe: `check_manual.py` found 13 of 14 entries consistent with
  identity, activity and link rows. The 14th is `marketing_001` (screen shows an unknown person; link row says
  `user_09`, case_63), kept as a known open question.
- Review flag `relies_on_transcribed_image_or_pdf:<files>` on exactly the 12 hidden cases that cite a
  transcribed file (case_33, 34, 35, 39, 45, 46, 50, 52, 53, 55, 61, 63).
- Partial verification of the route: public sample case_07 cites a PDF and is reproduced exactly.

**Still unverified.** No sample cites a screenshot. A human second look at those 12 cases against the
screenshots is the remaining check, and the review flag makes that list explicit.

## 4. Categories with no sample coverage

**Finding.** The data barely contains them, so the limitation is mostly moot:
- cache and email-delivery ids appear only in `system_activity.csv` (284 `REFRESH_CACHE` and 368 `SEND_EMAIL`
  rows); no evidence file mentions either;
- no evidence names a secondary identifier or product telemetry (the only "telemetry" hits are a
  `telemetry_flushed` log line from an unrelated extension);
- marketing occurs once (`marketing_001`, case_63).

**Handling.** The rule table in `ghost/rules.py` covers all of them from `deletion_rules.csv`; synthetic case
`syn_9` checks cache (delete), email delivery log (redact) and marketing profile (delete) end to end.
Product telemetry and secondary identifiers are in the rule table but have no parser path or test, because
there is nothing in the data to parse.

## Other results of this round

- Fixed: instruction-like fragments in a request are stripped before matching; mixed requests ("delete my
  account, don't delete my invoices") are handled by conflict detection plus an optional local LLM
  (`qwen3.5:4b`), see `docs/05` and `evaluation_report.md` section 9.
