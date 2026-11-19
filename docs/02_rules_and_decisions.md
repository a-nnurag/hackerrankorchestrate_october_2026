# 02. Rules, decisions, ordering, time

> **Status 2026-10-25.** Analysis-phase note, written before the code. The code and `code/evaluation/evaluation_report.md` are current; where they differ (thresholds, the second-offset resolver, the review ranking, conditions for rules 05/06/12/13) the report wins. Kept for the reasoning and the evidence behind the decisions.

Everything here was reverse-engineered from the 32 sample answers unless marked "(guess)". The decision table reproduced all 32 samples except where `04_open_questions_and_roadmap.md` lists exceptions.

## Pipeline

1. Classify the request (deletion or not). Not deletion: `NOT_APPLICABLE`, `[]`.
2. Resolve identity: normalize email, find the user, build the full identifier set.
3. Collect observations from evidence captured at or before `audit_at`; filter again per record time.
4. Link observations to the user by exact identifier match.
5. Determine each record's state at `audit_at` and compare with its rule.
6. Check what can recreate data: active flows, restorable backups, syncs after a delete.
7. Build steps in the fixed order.
8. Validate (invariants below).

## Rule table with conditions

A rule is `category + condition -> action`. Each condition is a check on a concrete field.

| Category | Condition | Where the answer is | If true | If false |
|---|---|---|---|---|
| USER_PROFILE | always | profile tables, lookups, handover | DELETE | n/a |
| SEARCH_INDEX_ENTRY | always | `customer_search_documents`, search lookups | DELETE | n/a |
| CACHE_ENTRY | always | cache_service | DELETE | n/a |
| USER_EXPORT | always | `customer_exports`, export jobs | DELETE | n/a |
| MARKETING_PROFILE | always | marketing console / records | DELETE | n/a |
| SECONDARY_IDENTIFIER | always | legacy index lookups | DELETE | n/a |
| SUPPORT_MESSAGE | shared context must be kept | message text with email/name/phone | REDACT | DELETE (guess) |
| SUPPORT_ATTACHMENT | belongs only to the subject | `LINK_RESOURCE_IDENTITY` text, PDF uploader | DELETE | keep or redact (guess) |
| ANALYTICS_PROFILE | still attributable | any of `user_id`, email, phone, hash set | ANONYMIZE | already compliant |
| PRODUCT_TELEMETRY | still attributable | telemetry evidence | ANONYMIZE | already compliant |
| EMAIL_DELIVERY_LOG | contains a user email | delivery log text | REDACT | already compliant |
| SECURITY_AUDIT_LOG | within retention | `retention_until` vs `audit_at` | RETAIN | no retention basis (guess) |
| LEGAL_HOLD_RECORD | hold active at `audit_at` | `legal_hold_*` rows, register | RETAIN | no basis (guess) |
| BACKUP_ARCHIVE | restore can be blocked | `restore_allowed`, restore checks | RETAIN and BLOCK_RESTORE | n/a |
| ACCOUNT_TOMBSTONE | account deleted, `user_id` needed | tombstone fields | REDACT all but `user_id` | n/a |
| Data flow (not a record) | `enabled` | `connector_subscriptions`, heartbeat | DISABLE_DATA_FLOW | already disabled |

Categories with **no** sample coverage: cache, email delivery log, product telemetry, marketing, legal hold, secondary identifier, expired retention. Their mapping is from `deletion_rules.csv` only.

## Decision table (record state to steps)

| State seen at `audit_at` | Finding | Remediation | Verification |
|---|---|---|---|
| Profile, search entry, export or subject-only attachment present | REPORT_REMAINING_RECORD | DELETE_RECORD | VERIFY_RECORD_ABSENT |
| Support message exposes email, name or phone | REPORT_EXPOSED_PII | REDACT_RECORD | VERIFY_RECORD_REDACTED |
| Analytics still attributable | REPORT_EXPOSED_PII | ANONYMIZE_RECORD | VERIFY_RECORD_ANONYMIZED |
| Tombstone has any of name / email / phone / hash | REPORT_EXPOSED_PII | REDACT_RECORD | VERIFY_RECORD_REDACTED |
| Data flow active | REPORT_ACTIVE_DATA_FLOW | DISABLE_DATA_FLOW | VERIFY_DATA_FLOW_DISABLED |
| Backup restorable | REPORT_RESTORE_RISK | BLOCK_RESTORE (never delete the archive) | VERIFY_RESTORE_BLOCKED |
| Security audit record present | none | none | VERIFY_RECORD_PRESENT |
| Already compliant (absent, redacted, all-null, disabled, blocked) | none | none | the matching VERIFY step, with citation |

Standing conventions from the samples:
- The user's **account always gets VERIFY_RECORD_ABSENT**, even when it was never a finding. If the account is itself a finding there is no duplicate.
- Audit records get VERIFY_RECORD_PRESENT only in later evidence families (absent from cases 1 to 8 and 10).
- Audit records are never remediated; backups are never deleted; a compliant tombstone is never deleted; a retained record that is missing makes a case INCOMPLETE.
- COMPLETE contains only verification steps. COMPLETE needs no finding at all.
- Case 12 treats an analytics-looking record (`analytics_9914`, matched through an old email hash with `email_opt_in`) as marketing and **deletes** it rather than anonymizing.

## Status decision

- **COMPLETE**: no finding at `audit_at`: every linked record is absent or compliant, nothing can recreate data, required retained records exist.
- **INCOMPLETE**: any finding.
- **NOT_APPLICABLE**: the request does not authorize deletion.
- Never use `reported_status` as a signal.

## Activity log versus evidence

Treat activity rows as claims and evidence as truth.
- SUCCESS delete but record still present: cases 05, 06, 07, 08, 10, 16, 24.
- FAILED or PARTIAL delete but evidence clean: cases 02, 13, 25, 26, 28 (COMPLETE or no finding for that record).
- A later SYNC / RESTORE / INDEX / CREATE_EXPORT for the same resource after a DELETE means the data may exist again. 56 account to replica sync pairs follow deletes; 31 "connector repopulated downstream" rows; 1 restore job. Order events by `event_time` (the file is not in time order).
- The activity event type usually equals the remediation (`DELETE_RECORD`, `REDACT_RECORD`, `ANONYMIZE_RECORD`); `CHECK_DATA_FLOW` goes with DISABLE_DATA_FLOW and `CHECK_RESTORE_ACCESS` with BLOCK_RESTORE.
- About 74% of activity rows link to no requester; do not assume a row belongs to a case.

## Ordering (zero violations on all 32 samples)

Sort key for every step: `(phase, operation index in the allowed-operations table, system_id, resource_id)`, step numbers 1..n.

- Findings: REMAINING, EXPOSED_PII, ACTIVE_DATA_FLOW, RESTORE_RISK.
- Remediation: DISABLE_DATA_FLOW, BLOCK_RESTORE, DELETE, REDACT, ANONYMIZE. This table order already puts flows and restores first, so no separate dependency graph is needed.
- Verification: ABSENT, PRESENT, REDACTED, ANONYMIZED, DATA_FLOW_DISABLED, RESTORE_BLOCKED.
- Sort of resource ids: no sample has two steps sharing phase, operation and system, so string vs numeric is never tested. In the hidden cases only about 5 to 10 same-prefix groups were found (cases 95, 131, 176, 278, 407, 489, 527), all with equal digit counts, where string and numeric order agree. Use plain string sort (reported, high confidence that it is moot).
- Untested: a case with both a data flow and a restore to remediate; by table order flows come first (guess).

## `evidence_id` choice

- Findings and COMPLETE verifications cite one file whose `captured_at <= audit_at` (file-level time, never timestamps inside the file). Cite `file_id` only; no sample cites an `activity_id` or `audit_id`.
- Reported (open-rules agent, high confidence): in 30 of 32 samples exactly one file at or before `audit_at` witnesses the user or the answer's resources. Across the 518 hidden cases, 1,180 of 1,180 resources found appear in exactly one such file, so ties should not occur. When several qualify, take the latest.
- Falsified hypotheses: "earliest" (cases 15 and 17 ignore an older file) and "latest file overall" (cases 21 to 28 cite evidence_92, captured 11:44:55, not evidence_51 at 12:00:00).
- Later twin files (evidence_02 vs evidence_92 for cases 21 to 30; evidence_06 vs evidence_93 for case 09) must never be cited, but may supply identifiers for steps that carry no citation.
- One anomaly: COMPLETE case_04 cites evidence_54 for `account_004` (appears in no file) although the later, empty evidence_90 would also prove absence. Probably the answer key uses the story-series witness file (guess).
- Per-resource citation: within a case every step cites the same file in 31 of 32 samples (exception: case_04).
- Remediation steps and INCOMPLETE verification steps always have an empty `evidence_id`.
- COMPLETE absence is proved by a snapshot that covers the service but lacks the id (cases 1, 2, 4 cite `evidence_54`), by a 404 lookup, by `NOT_FOUND`, or by an empty collection (case 31 cites `evidence_51`).
- Some records are discovered only in files dated after `audit_at` whose inner snapshot time is earlier (case 09, audit records for cases 23, 24, 29, 30). This is acceptable for discovery and for INCOMPLETE verification (no citation), but a COMPLETE step cannot cite such a file.

## Time rules

| Condition | Rule | Evidence |
|---|---|---|
| Evidence cutoff | use files with `captured_at <= audit_at` (inclusive) | 15 of 75 sample citations are captured exactly at `audit_at` (cases 11, 13, 14, 16, 22, 31, 32) |
| Per-record time | latest observation of each record at or before `audit_at` | bundles mix snapshots from several dates |
| Stale snapshot | older observation is overridden by a later one before `audit_at` | case 26: 09-09 shows `account_5684` present, 09-15 lookup is 404, so absent |
| Later reactivation | observation after `audit_at` ignored | case 27: `account_3866` ACTIVE at 09-17, audit is 09-15 |
| Recreate after delete | a sync/restore/index after a delete and before `audit_at` means data may exist | case 05 delete 09:11:01, sync 09:11:09; case 24 delete 10:59, sync 12:45 |
| Activity events | ignore after `audit_at`; do not use `requested_at` as a lower bound | some real deletes precede the request (case 34) |
| Identity changes | an old email or hash is valid until its change time | explains old identifiers in old snapshots |
| Retention | retain while `retention_until >= audit_at` | all SQL/JSON values are 2031+; PDF extract retains `audit_record_003` to 2027-08-25; backup console shows `backup_9287` retention end 26 Jul 2026; no hidden audit date is past a data retention date in the evidence we checked |
| Legal hold | active if start <= `audit_at` <= end; a hold whose `RETAIN_RECORD` is logged between `requested_at` and `audit_at` is normal, not disqualifying | register PDF lists users 08, 12, 17, 21, 24, 29 but sample answers have no legal-hold step; ignore the register (its `ORD-` ids are not resources). The real signal is `legal_hold_*` rows (see below) |

### Legal holds in hidden cases (reported; first row verified)

There are 10 `RETAIN_RECORD` rows to `legal_service`, 8 link to a user, all `retained_until 2033-12-31`. No retention or hold date in any evidence falls before an `audit_at`, so nothing contradicts RETAIN. No sample user has a legal hold, so the treatment cannot be checked against a known answer.

| Case | Hold | Evidence | Treatment |
|---|---|---|---|
| 261, 390, 460, 473, 505, 511 | `legal_hold_8017`, `8049`, `5622`, `4743`, `2227`, `4887` | the file captured at or before audit | add `legal_service` VERIFY_RECORD_PRESENT (rule_13); sorts before `security_service` in the PRESENT group; medium confidence |
| 220, 432 | `legal_hold_4961`, `438` | file captured after audit (evidence_21 and evidence_40) | link exists only in a later file: omit, low-medium confidence |

Case 261's hold row (`legal_hold_8017`, `user_259`, `ORD-20268017`) was checked in `customer_data_read_replica_20260613.sql`.

Boundary semantics not seen in any sample (guesses): activity event exactly at `audit_at`; identity change exactly at `audit_at`; two observations at the same instant that disagree.

Use the **manifest** `captured_at` as the state time for screenshots and PDFs. Times printed inside screens are unreliable (one is JST, one "Last activity 14:22 UTC" vs manifest 10:00Z, footers say "build 2026.10.4").

## Validation invariants (run on every case)

1. Steps numbered 1..n, no duplicate `(phase, op, system, resource)`, sorted by the key above.
2. COMPLETE has only VERIFICATION steps, each citing a file captured at or before `audit_at`.
3. INCOMPLETE has at least one finding; every finding has a matching remediation and verification.
4. Findings have evidence; remediation and INCOMPLETE verification have `evidence_id=""`; NOT_APPLICABLE is `[]`.
5. Operation / state pairs match the allowed table exactly.
6. Audit records never remediated; backups never deleted; compliant tombstones never deleted.
7. The account always has VERIFY_RECORD_ABSENT.
8. No cited evidence is captured after `audit_at`.
9. Every id in output exists verbatim in the cited source or in the known id universe.

## Cross-checks

- Evidence against activity: SUCCESS plus presence in evidence is drift; FAILED plus clean evidence is complete; the activity type should match the derived remediation; flag any sync after a delete for the same resource.
- Identity: resolve through current rows and the audit log (for example a chain of three emails for one user); match evidence by exact normalized email, hash, `user_N` or phone.
- Reject all near matches (substring, prefix, same-name different email).
