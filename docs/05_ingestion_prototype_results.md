# 05. Ingestion prototype: measured results

> **Status 2026-10-25.** Analysis-phase note, written before the code. The code and `code/evaluation/evaluation_report.md` are current; where they differ (thresholds, the second-offset resolver, the review ranking, conditions for rules 05/06/12/13) the report wins. Kept for the reasoning and the evidence behind the decisions.

A research agent built and ran a prototype of the unified observation table over `dataset/`. All numbers below are **reported by that agent** and were not independently re-run. The prototype code and database lived in a temporary session folder and are not in the repo; the final ingestion code is in `code/ghost/ingest/`.

## Verdict

- Ingestion works: every parseable evidence file lands in one SQLite table in about 0.15 to 0.5 seconds, with zero unparsed lines.
- Reproducing the expected sample steps from the table plus the activity stream reaches **about 91%** (101 of 111 finding and verification (resource, system) pairs), but about 40% of those depend on weak links that need human review. Without the activity stream and later-exported files it is only **68 to 70%**.
- Numbers are tuple-level (resource, system, operation), not full step-sequence accuracy.
- Heuristics were tuned on the 32 samples; thresholds are not validated elsewhere.

## Table schema (SQLite)

- `observation`: `obs_id, file_id, file_captured_at, observed_at, observed_at_src, resource_id, system_id, category, state, source_ref, kind, extras`. `kind` is record, lookup_404, lookup_not_found, absence_vs_replica or manual.
- `obs_ident`: `(obs_id, id_type, value, role)`; types email (lowercased), user, hash, phone (digits only), name, file, resource.
- `coverage`: `(file_id, system_id, scope_kind, scope_time, level, source_ref)`; levels FULL, EMPTY, SAMPLE, LOOKUPS, COMPLETE, DROPPED_AUX, UNKNOWN, MANUAL.
- `activity`, `activity_edge` (linked, attachment_owner, mention), `parse_stats`, `unparsed`.

Only FULL and EMPTY coverage count as proof of absence. SAMPLE and LOOKUPS do not.

## Parse results

| Format | Files | Items | Parsed |
|---|---|---|---|
| SQL | 24 | 969 INSERTs | 969 |
| JSON | 28 | 890 records | 890 |
| Handover txt | 1 | 41 rows | 41 |
| Logs | 26 | 2,211 lines | 2,211 |
| PNG / PDF | 15 | not parsed | stubs only |

"Parsed" means lexed and mapped to a state; semantics were checked only against the 32 samples. 2,907 observations, 4,179 identifier rows; every observation has a record-level time. 264 observations carry no identifier (50 of them ABSENT).

Observations by category and state: USER_PROFILE PRESENT 418 / ABSENT 258; SEARCH_INDEX_ENTRY PRESENT 486; SECURITY_AUDIT_LOG PRESENT 662; ANALYTICS_PROFILE ANONYMIZED 215 / IDENTIFIABLE 121; SUPPORT_MESSAGE IDENTIFIABLE 217 / REDACTED 62; SUPPORT_ATTACHMENT PRESENT 31; DATA_FLOW ACTIVE 181 / DISABLED 62; BACKUP_ARCHIVE ACTIVE 45 / BLOCKED 62; USER_EXPORT PRESENT 52; LEGAL_HOLD_RECORD PRESENT 12; ACCOUNT_TOMBSTONE IDENTIFIABLE 9 / REDACTED 9.

## How much of the activity log appears in the table

1,250 of 3,948 distinct activity resource ids (31.7%). Backups and data flows 100%, tombstones 91%, legal holds 80%, support 45%, search 42%, analytics 36%, accounts 34%, exports 17.5%; audit records, cache and email delivery 0%. A missing account id usually means the account is absent, so **only the activity stream knows it ever existed**. It is a required input, not just context.

## Reproducing the sample answers (111 expected pairs in 32 samples)

| Variant | Reproduced |
|---|---|
| Strict (time filters, no activity cluster) | 76 / 111 (68.5%) |
| Identity links may use later-exported files if record time <= audit, no cluster | 78 / 111 (70.3%) |
| Strict plus activity cluster | 101 / 111 (91.0%) |
| Same plus later-file links | 101 / 111 (91.0%) |
| Same plus state read from later files (cannot be cited) | 106 / 111 (95.5%) |

- Cited `evidence_id` would match the expected one in 72 of 72 checked pairs.
- 23 of 32 cases have every expected pair.
- The 10 failures: 4 are image or PDF only (`account_004`, `support_001`, `audit_record_6645`, `audit_record_5569`); 5 are audit records found only in files exported after `audit_at` (cases 09, 23, 24, 29, 30; arguably leakage); 1 has no identity link (`analytics_901`, case 04).
- 34 of the expected pairs (30%) were not strongly linked; most are `account_*` ids found through the activity cluster.

## False links

- Exact email / `user_N` / hash links: 77 true, 1 false (1.3%). The false one is case 17's `account_6523`: an exact-email 404 lookup from March, before the request; the expected answer excludes it. Only a "lookup key, older than the request" signal catches it.
- Lookalike decoys: 22 emails in evidence belong to nobody. Exact matching links none, and no resource is claimed by two users. Looser matchers produced **zero true links** on the samples (fuzzy email ratio 0.90: 0 true / 3 false; same alphabetic local part: 0 / 4; same 6-character prefix: 0 / 56).
- Activity-cluster links are the real false-link source: contested clusters had 18 true and 44 false (29% precision); uncontested had 5 true and 1 false.
- Identity resolution is clean: all 850 hashes equal sha256 of the normalized email, no shared email or phone, all request emails resolve.

## Confidence scheme

Link scores: exact current email 0.99; exact historical email 0.97; `user_N` 0.97; hash 0.96; catalog link (`LINK_RESOURCE_IDENTITY`) 0.95; attachment catalog 0.92; `source_resource_id` 0.85; same resource id as a strongly linked record 0.80; cluster anchored by a strongly linked account 0.70; phone 0.60; activity cluster with a unique anchor 0.45; contested cluster 0.30; name only 0.25; id pattern 0.15. A query key is multiplied by 0.90; an email only mentioned in text by 0.95. A record that carries a foreign identity and none of ours is rejected.

Absence scores: explicit 404 / NOT_FOUND 0.95; replica-drift 0.90; covered-scope snapshot lacking the id 0.85; empty list 0.60; activity-only omission 0.30.

Measured on the samples (strict, with clusters):

| Minimum link score | True | False | Precision | Recall |
|---|---|---|---|---|
| >= 0.90 | 77 | 1 | 0.99 | 69% |
| >= 0.45 | 83 | 2 | 0.98 | 75% |
| >= 0.30 | 101 | 46 | 0.69 | 91% |

## Review routing (proposed)

- Auto-accept: every concluded item >= 0.90 and at least one strongly linked record. Only 7 of 32 samples qualify (6 exactly right); about 25 to 29% of the 518 cases.
- Soft accept (single spot check): unique-anchor cluster items at 0.45 to 0.70 (precision about 0.83 on 6 samples).
- Review list: any contested cluster (<= 0.30); any absence below 0.85 whose resource is not otherwise linked; any resource that appears only in an image or PDF; an exact-email link that comes only from a lookup key and predates `requested_at`.
- Expected volume: about 70% of the 518 cases contain at least one item below 0.90. **The review list would be very large**, so thresholds need rethinking before they are used to gate output. Confidence is better used to rank uncertainty and decide when to spend LLM or manual effort than to withhold answers, because every case still needs a row in `output.csv`.

## Parsing recipes (for the real implementation)

- Key=value pairs: `([A-Za-z_]\w*)=("(?:[^"\\]|\\.)*"|\S+)`
- Log headers: bracketed `\[(\w+)\] \[(\w+)\] \[([^\]]+)\] (\w+): ?(.*)`; cloud: take `message="(.*)"\s*$`, unescape `\"`, trace id from `requestId`; pipe: `line.split(' | ', 5)`; syslog `<\d+>1 (\S+) (\S+) (\S+) - - (.*)`; JSON after the timestamp; otherwise logfmt containing `event=`.
- The query key lives on the `*_started` line and the result with `resource_id` on the `*_completed` line with the same trace id. Collect identifiers per trace from `lookup_key`, `match_key`, `subject_key`, `scan_key`, `subject_ref`, `owner_key`, `correlation_key`, `matched_value`.
- State rules from events: `profile_lookup_completed` rows=0 or 404 means ABSENT; `index_query_completed` result=hit means PRESENT; connector events ACTIVE only if `enabled=true` and the scheduler is registered; `restore_policy_read_completed` restore_allowed true means ACTIVE; `restore_candidate_evaluated` ACTIVE only if `eligible=true` and `deletion_block=false`; `restore_authorization_completed` `decision=deny` means BLOCKED; `message_pii_scan` IDENTIFIABLE; `message_read` REDACTED when the text is `[REDACTED]`; `analytics_profile_read` ANONYMIZED when `direct_identifiers=0`.
- Handover: `^- (\S+) \| (\w+) \| (\S+) \| (\w+) \| (\w+) \| (.*)$`. Manifest and ledger JSON use the same `record_type` / `result` vocabulary (FOUND to PRESENT, NOT_FOUND to ABSENT).
- SQL: inventory files have `snapshot_scope` plus eight tables; record-JSON files use `record_json`, `origin_system`, `collection_name`; simple-table files (evidence_54, evidence_57) use plain tables; in drift files diff primary against replica tables.
- JSON bundles: use each snapshot's `captured_at`, not the bundle's `exported_at`.
- Identifier regexes: emails `[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}` lowercased; users `\buser_\d+\b`; hashes `\b[0-9a-f]{64}\b`; phones digits only, 7 or more; skip `integrity_seal`.

## Known limits

- Cluster logic (account anchor, 3.2 hour forward window, unclaimed by others) was built from the samples and not validated elsewhere. Narrowing the anchor window barely changed results.
- Support events with an unknown subtype are labelled `SUPPORT_RECORD`; an export with `available=false` is still reported PRESENT; `object_*` rows are kept as `OBJECT_BLOB` with no rule (treating them as support attachments created a false link in case 07).
- Coverage assumptions (FULL for `snapshot_scope`, table dumps and empty bundle snapshots; SAMPLE for other bundles and record-JSON dumps) are unvalidated.
- The 91% figure uses later-exported files only for identity links. The 95.5% figure also reads state from later files, which cannot be cited.
- Images and PDFs need manual transcription: evidence_04, 09, 14, 18, 19, 23, 27, 28, 32, 37, 42, 46, 55, 58, 60 (schema in `manual_transcriptions\_schema.json`; a transcription of all 15 also exists in the scratchpad `transcribe\manual_observations.json`).
