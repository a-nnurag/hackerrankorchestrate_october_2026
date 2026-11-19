# 04. Open questions, tests, roadmap

> **Status 2026-10-25.** Analysis-phase note, written before the code. The code and `code/evaluation/evaluation_report.md` are current; where they differ (thresholds, the second-offset resolver, the review ranking, conditions for rules 05/06/12/13) the report wins. Kept for the reasoning and the evidence behind the decisions.

## Status

| Work item | Status |
|---|---|
| Identity and activity analysis | done (agent report, key figures re-verified) |
| Evidence format analysis | done |
| Sample reverse-engineering (32 cases) | done |
| Image and PDF transcription, OCR feasibility | done; evidence-family plan, synthetic cases and LLM schema not written by that agent |
| Open-rule analysis (evidence_id, sort, retention, marketing, link rows) | done; findings folded into files 02 and 04 (legal-hold rows spot-checked, rest reported) |
| Ingestion prototype and confidence measurement | done; see [05](05_ingestion_prototype_results.md). About 91% of sample pairs reproducible with the activity stream, 68 to 70% without |
| Solution code | done: `code/` (pipeline, evaluation harness, tests); see `code/README.md` |

## Open questions (undetermined by the data seen so far)

1. **Which file to cite** when several qualify. Settled as far as the data allows: latest qualifying file, per resource (see file 02). Ties should not occur (1,180 of 1,180 hidden resources appear in one file at or before audit). Residual: case_45's `audit_record_003` is shown by both `evidence_37` (image) and `evidence_55` (PDF); a coin flip, lean `evidence_55` (it proves the retention window).
2. **Resource id sort**: effectively moot; string sort agrees with numeric on every hidden group found.
3. **Both a data flow and a restore in one case**: order should be flow then restore by table order; untested.
4. **Expired retention or ended legal hold** before `audit_at`: expected treatment unknown. In the evidence checked, every SQL and JSON `retention_until` is 2031 or later, the PDF extract retains `audit_record_003` to 2027-08-25, and the backup console shows `backup_9287` retention end 26 Jul 2026 (the hidden `case_55` audit is 2026-04-30, so the retention is still running at the audit date).
5. **Legal register PDF**: listed users overlap sample users whose answers have no legal step; probably a decoy.
6. **Marketing contradiction** (`marketing_001`, `case_63`): screenshot shows Soo-jin Park (not in the data); link row says `user_09` (Kwame Mensah). The screenshot (07:20Z) and link row (07:27:01Z) are both before case_63's audit (09-17T09:20Z), and case_63 has no other evidence. Recommendation (about 60%, reported): treat it as case_63's record: INCOMPLETE, finding `marketing_platform/marketing_001` REPORT_REMAINING_RECORD citing `evidence_60`, DELETE_RECORD (rule_10), VERIFY_RECORD_ABSENT. Falsified if the gold answer for case_63 is `[]` or COMPLETE with no marketing step.
6b. **Legal holds** for hidden cases 261, 390, 460, 473, 505, 511 (add VERIFY_RECORD_PRESENT) and the later-file-only holds 220 and 432 (omit): see file 02. No sample can confirm either way.
6c. **Undeterminable ids**: audit ids for cases 18 and 20 appear in no participant file; account and audit ids for the image-only cases exist only in later files (`evidence_01`, `evidence_02`), usable for uncited steps only.
6d. **Absence file for story-series accounts** (cases 1, 2, 4 cite `evidence_54`; the later empty `evidence_90` would also prove absence).
7. **Which compliant resources appear** in COMPLETE and INCOMPLETE verification lists; depends on hidden truth.
8. **Analytics linkage** in cases 3, 21, 25, 26, 27, 28 and account linkage in cases 4, 25, 28 cannot be decided from content alone.
9. **Case 12**: a record shown by an analytics-looking log is treated as marketing and deleted.
10. **Case 29**: delete FAILED, no evidence of presence, no account finding. When is silence accepted?
11. **Categories with no sample**: cache, email delivery log, telemetry, marketing, secondary identifier.
12. **Boundary equality** for activity and identity changes at exactly `audit_at`.
13. **Twelve French requests** with no deletion keyword: classify before finalizing the `NOT_APPLICABLE` rule.

## Cases that depend on images or PDFs

Twelve `LINK_RESOURCE_IDENTITY` rows connect resources to cases. Verified mapping (case, audit time, resource, evidence):

| Case | `audit_at` | Resource | Evidence file |
|---|---|---|---|
| case_34 | 2026-09-27 | `account_5762` | `evidence_04` account console (also `evidence_01` log) |
| case_35 | 2026-09-02 | `search_428` | `evidence_09` search inspector |
| case_39 | 2026-08-08 | `data_flow_1121` | `evidence_14` connector console |
| case_50 | 2026-07-14 | `analytics_7438` | `evidence_19` analytics view |
| case_52 | 2026-06-19 | `export_1260` | `evidence_23` export console |
| case_33 | 2026-07-19 | `export_1842` | `evidence_18` account history PDF |
| case_53 | 2026-05-25 | `support_1034` | `evidence_28` support ticket console |
| case_55 | 2026-04-30 | `backup_9287` | `evidence_32` backup console |
| case_61 | 2026-02-14 | `object_19` | `evidence_46` object storage |
| case_63 | 2026-09-17 | `marketing_001` | `evidence_60` marketing console |
| case_45 | 2026-09-06 | `audit_record_003` | `evidence_37` security explorer, `evidence_55` retention PDF |
| case_46 | 2026-03-11 | `tombstone_17` | `evidence_42` registry (also `evidence_67` lookup trace) |

The 12 rows were re-verified against `system_activity.csv` and the request emails (including historical emails). The evidence-file column comes from the transcription agent's mapping and is not independently re-verified. `case_33` and `case_52` are the same person with different cutoffs; `export_1260` is live at the 06-19 audit but expired 25 Jun by the 07-19 audit. Likely treatments (all guesses from sample analogues, reported by the open-rules agent): `case_34` account present in the newer image so REPORT_REMAINING_RECORD (the older `evidence_01` shows a 404, the newer file wins); `case_35` delete `search_428` (`search_1874` is a decoy); `case_39` disable `data_flow_1121` (`data_flow_9846` is another person); `case_50` anonymize `analytics_7438`; `case_52` delete `export_1260`; `case_33` likely only `export_1842` (low confidence, `export_1260` expired 25 Jun); `case_53` redact `support_1034`; `case_55` block restore on `backup_9287`; `case_61` delete `object_19`; `case_45` verify `audit_record_003` present, probably COMPLETE; `case_46` COMPLETE with `account_6523` absent (citing `evidence_67`) and `tombstone_17` redacted (citing `evidence_42`). Expected outputs for these cases are unknown; the only sample analogue is `case_07`'s PDF citation (`evidence_58`).

## Test plan

**Hold-out by family.** Evidence families (by file name, about 24): handover TXT; failover-replica SQL (two kinds); inventory SQL (11); read-replica SQL (5); regional-replica SQL (3); reporting-replica SQL (2); search-primary SQL; snapshot bundles (12); service resource exports (11); connector / export-manifest / security-ledger JSON; analytics report JSON; export jobs JSON; resource lookup traces (11); seven other log formats; PDFs; images. The samples exercise only the 13 cited files. Plan: leave-one-family-out over the samples where a family has sample coverage; report image/PDF-only and unsampled-family cases separately; report step-level, field-level and sequence accuracy.

**Synthetic cases** (each with input row, small evidence snippet and expected `steps_json` that follows the sample conventions). Not yet written. Required scenarios:
1. NOT_APPLICABLE with a negation trap, in a non-English language.
2. Evidence captured exactly at `audit_at`.
3. Later snapshot after `audit_at` showing reactivation that must be ignored.
4. Historical email with a hash-only record.
5. Uppercase email in request and in evidence.
6. Lookalike decoy email.
7. Tombstone with partial identifiers.
8. Backup restore risk and active data flow together (ordering).
9. Security audit record within retention and past retention.
10. Replica-only drift.

The evaluation report needs at least three of these.

**Hallucination check.** Every id, email, date and evidence id in the output (and in the transcription file) must exist verbatim in a source file or in the id universe built from `system_activity.csv`, `user_identities.csv`, `user_audit_log.csv` and `sample_output.csv` (`support_001` appears only in the sample output and one PDF). Ids derived from file names or titles (`object_19`, `tombstone_17`, `export_1842`) must be allowed through the `LINK_RESOURCE_IDENTITY` rows.

**LLM design.** Structured output only: a record with `evidence_id`, `resource_id`, `state` (enum), `identifiers`, `observed_at`, `confidence`. Validators: id exists in source or universe; dates parse and `captured_at <= audit_at`; state in enum; normalized email matches an identity or a link row; embedded instructions ignored. Cache by SHA-256 of file bytes plus prompt version. Use the model for classification fallback and ambiguity only; token and cost estimates are still to be done.

## Build order

1. **Ingestion**: parse every evidence file into one observation table (SQLite cache); load the manual image/PDF transcription through the same schema. Measure parse success and coverage.
2. **Identity**: normalize, resolve current and historical identifiers, per-case time filter.
3. **Linking with confidence**: exact email / hash / `user_N` / phone / `source_resource_id`; reject near matches; record the reason for every link.
4. **State and rule engine**: rules as data (category, condition id, action, step operations); one small function per condition.
5. **Step builder and validators**: ordering key, invariants, absence reasons.
6. **Evaluation**: leave-one-family-out, synthetic cases, hallucination check, `evaluation/evaluation_report.md`, `evaluation/usage_report.md`.
7. **Packaging**: `code/main.py` entry point, README with setup and run steps, `output.csv` at repo root, `code.zip` without `dataset/`.

## Housekeeping

- Log every turn to `log.txt` (AGENTS.md section 5). It becomes the `chat_transcript`.
- Never include secrets or `dataset/` in `code.zip`.
- Do not use organizer-only files or hardcode golden labels; the 32 sample answers are allowed for development and validation.
