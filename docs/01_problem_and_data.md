# 01. Problem and data

> **Status 2026-10-25.** Analysis-phase note, written before the code. The code and `code/evaluation/evaluation_report.md` are current; where they differ (thresholds, the second-offset resolver, the review ranking, conditions for rules 05/06/12/13) the report wins. Kept for the reasoning and the evidence behind the decisions.

## The task

Northstar Shop (fictional) lost $2.4M because a "deleted" customer reappeared. The deletion workflow said "Complete" while personal data remained in secondary databases, search indexes, support attachments, analytics, exports, logs, archives, backups, and a sync job recreated data the account service had deleted.

For each request in `dataset/deletion_requests.csv` (518 cases, `case_33` to `case_550`) the agent must:

1. Decide whether the person actually asked for deletion. If not: `NOT_APPLICABLE` and `[]`.
2. Resolve current and historical identifiers.
3. Reconstruct the state of every relevant record **at `audit_at`**.
4. Apply `dataset/deletion_rules.csv`.
5. Output `COMPLETE` (verification steps only) or `INCOMPLETE` (findings, then remediation, then verification).

A deletion is complete only when every relevant copy has the required treatment, no sync/import/restore path can recreate the data, retained records hold only permitted identifiers, and records that must be kept still exist.

`reported_status` (COMPLETE / PARTIALLY_COMPLETE / NOT_STARTED) is a claim, not proof. It does not predict the answer: in the samples, NOT_STARTED cases 25, 26 and 28 are COMPLETE and COMPLETE cases 05, 07, 10, 11 and others are INCOMPLETE.

## Output contract

`output.csv`: `case_id,deletion_status,steps_json`, exactly 518 rows, sorted by `case_id`.

Each step: `step_no, phase, system_id, resource_id, operation, state, evidence_id`.

| Phase | Operation | State |
|---|---|---|
| FINDING | REPORT_REMAINING_RECORD | PRESENT |
| FINDING | REPORT_EXPOSED_PII | PRESENT |
| FINDING | REPORT_ACTIVE_DATA_FLOW | ACTIVE |
| FINDING | REPORT_RESTORE_RISK | ACTIVE |
| REMEDIATION | DISABLE_DATA_FLOW | DISABLED |
| REMEDIATION | BLOCK_RESTORE | BLOCKED |
| REMEDIATION | DELETE_RECORD | ABSENT |
| REMEDIATION | REDACT_RECORD | REDACTED |
| REMEDIATION | ANONYMIZE_RECORD | ANONYMIZED |
| VERIFICATION | VERIFY_RECORD_ABSENT | ABSENT |
| VERIFICATION | VERIFY_RECORD_PRESENT | PRESENT |
| VERIFICATION | VERIFY_RECORD_REDACTED | REDACTED |
| VERIFICATION | VERIFY_RECORD_ANONYMIZED | ANONYMIZED |
| VERIFICATION | VERIFY_DATA_FLOW_DISABLED | DISABLED |
| VERIFICATION | VERIFY_RESTORE_BLOCKED | BLOCKED |

Rules for `evidence_id`: findings and COMPLETE verifications cite a `file_id`, `activity_id` or `audit_id`; remediation steps and INCOMPLETE verification steps use an empty string. Evidence captured after `audit_at` must not be used.

Deliverables also include `code.zip` (code, prompts, config, README, `evaluation/evaluation_report.md`, `evaluation/usage_report.md`), `output.csv`, the chat transcript (`log.txt`), and an AI interview.

## Dataset files (all under `dataset/`)

| File | Rows | Notes |
|---|---|---|
| `deletion_requests.csv` | 518 | Cases to answer |
| `sample_deletion_requests.csv` / `sample_output.csv` | 32 | Correct answers; sample ids are `case_01` to `case_32` |
| `user_identities.csv` | 850 | Current identity: `user_id`, name, email, phone, `email_hash`, updated time |
| `user_audit_log.csv` | 306 | History: 107 email, 107 email_hash, 92 phone changes; no name changes |
| `system_activity.csv` | 4,011 | Global operational log; mostly unrelated people (about 74% of rows link to no requester) |
| `deletion_rules.csv` | 15 | The policy |
| `evidence_files.csv` | 94 | Manifest: `file_id`, `file_path`, `origin`, `captured_at` |
| `evidence/` | 94 files | 28 JSON, 26 log, 24 SQL, 11 PNG, 4 PDF, 1 TXT |

### `deletion_rules.csv`

| Rule | Category | Condition | Action |
|---|---|---|---|
| 01 | USER_PROFILE | Always | DELETE |
| 02 | SECONDARY_IDENTIFIER | Always | DELETE |
| 03 | SEARCH_INDEX_ENTRY | Always | DELETE |
| 04 | CACHE_ENTRY | Always | DELETE |
| 05 | SUPPORT_MESSAGE | Shared customer/agent/order context must be retained | REDACT |
| 06 | SUPPORT_ATTACHMENT | Belongs only to the deletion subject | DELETE |
| 07 | ANALYTICS_PROFILE | Still attributable to a user | ANONYMIZE |
| 08 | PRODUCT_TELEMETRY | Still attributable to a user | ANONYMIZE |
| 09 | USER_EXPORT | Always | DELETE |
| 10 | MARKETING_PROFILE | Always | DELETE |
| 11 | EMAIL_DELIVERY_LOG | Contains a user email | REDACT |
| 12 | SECURITY_AUDIT_LOG | Within the supplied retention period | RETAIN |
| 13 | LEGAL_HOLD_RECORD | A supplied legal hold is active | RETAIN |
| 14 | BACKUP_ARCHIVE | Restore access can be blocked | RETAIN |
| 15 | ACCOUNT_TOMBSTONE | Account deleted, only stable `user_id` needed | REDACT |

The four actions are DELETE, REDACT, ANONYMIZE and RETAIN.

- **Delete**: remove the whole record.
- **Redact**: keep the record, blank the named identifying fields (name, email, phone, email hash).
- **Anonymize**: keep the record but irreversibly remove any link to the person. Hashing the email is not anonymization, because anyone with the email can recompute it.
- **Retain**: leave the record; verify it is still present.

### Resource prefixes and systems (from `system_activity.csv`)

`account_` (account_service), `search_` (search_service), `cache_` (cache_service), `export_` (export_service / object_store), `marketing_` (marketing_platform), `support_` (support_platform), `email_delivery_` (email_delivery_service), `analytics_` (analytics_platform), `tombstone_` (identity_service), `audit_record_` (security_service / archive_service), `legal_hold_` (legal_service), `backup_` (backup_service), `data_flow_` (integration_service). Replica systems: `account_replication_cluster`, `account_failover_replica`.

### Activity event types

`DELETE_RECORD` 890, `UPDATE_RECORD` 672, `SYNC_RECORD` 447, `INDEX_RECORD` 400, `SEND_EMAIL` 368, `REFRESH_CACHE` 284, `RETAIN_RECORD` 206, `ANONYMIZE_RECORD` 204, `REDACT_RECORD` 173, `CREATE_EXPORT` 155, `CHECK_DATA_FLOW` 89, `DISABLE_DATA_FLOW` 36, `BLOCK_RESTORE` 36, `CHECK_RESTORE_ACCESS` 28, `LINK_RESOURCE_IDENTITY` 12, `CLASSIFY_REQUEST` 10, `RESTORE_BACKUP` 1. Results: SUCCESS 2,914, FAILED 721, PARTIAL 376. All are claims. In the samples SUCCESS deletes sometimes left data behind (cases 05, 06, 07, 08, 10) and FAILED deletes sometimes had nothing to remove (cases 25, 26, 28).

## Evidence formats

All 94 files were parsed or read; none failed.

**SQL (24 files, SQLite-compatible, load with `executescript`).** Header comment carries `Captured at` and topology. Families:
- Replica families (read / regional / reporting / failover): tables `customer_data_primary` plus one replica table, each `(resource_id, origin_system, collection_name, record_json, updated_at)`. Replica rows equal primary rows, except rows present **only** in a replica. Drift is found by set difference of `resource_id`, not by comparing values.
- `customer_accounts_failover_replica_20260902.sql`: `customer_profiles_primary` and `customer_profiles_failover_replica` (`account_005` is replica-only; this is case_05).
- `customer_search_primary_20260910.sql`: `search_documents_primary` with decoys.
- `customer_data_inventory_*.sql` (11): typed tables plus `snapshot_scope(origin_system, captured_at)`. A scoped system with zero rows proves absence; an out-of-scope system is unknown. Profile status `DELETION_PENDING` still counts as a remaining record.

**Logs (25 files).** About seven line formats, all starting with an ISO timestamp. One key=value regex `(\w+)=(?:"((?:[^"\\]|\\.)*)"|(\S+))` plus a JSON-line parser covers them; `cloud_runtime_export_*` needs `\"` unescaped first. Key events: `profile_lookup_completed` (`rows=0`, 404 means absent), `analytics_identity_scan` / `analytics_profile_read`, `message_pii_scan` / `message_read`, `connector_config_loaded` / `connector_heartbeat`, `restore_candidate_evaluated` / `restore_authorization_completed`, `record_lookup` with `result`. Many lines are noise (cache, DNS, kernel, thread pool). Identifier field names vary (`correlation_key`, `lookup_key`, `subject_key`, `subject_ref`, `match_key`, `scan_key`, `owner_key`).

**JSON (28 files).**
- Snapshot bundles (12): `{exported_at, source, snapshots:[{captured_at, data_store, collection, records}]}`. Snapshot times vary inside one bundle. An empty `records` array in a stored system means absent.
- Service resource exports (11): `{service_exports:{service:{list_key:[...]}}}` with per-row `observed_at`.
- Record-history lists: `connector_configurations_*.json`, `customer_export_manifest_*.json`, `security_audit_ledger_*.json` (names are misleading; each is a list of `{recorded_at, system, resource_id, record_type, result, subject_reference}`).
- `customer_analytics_report_*.json`, `customer_export_jobs_*.json`.

**Text.** `customer_account_handover_20261001.txt` (evidence_03): lines `- ts | system | resource_id | RECORD_TYPE | RESULT | subject`, regex `^- (\S+) \| (\w+) \| (\S+) \| (\w+) \| (\w+) \| (.*)$`. Covers about 10 users including decoys.

**PDFs (4) and images (11).** Business artifacts with a text layer for PDFs; screenshots have no machine-readable text. See `03_design_critique.md` and `04_open_questions_and_roadmap.md`.

### State vocabulary across formats

| Category | Problem state | Compliant state |
|---|---|---|
| Profile / search / export / attachment | FOUND, present, 200, `DELETION_PENDING`, `download_available=true` | NOT_FOUND, 404, `rows=0`, absent |
| Analytics | IDENTIFIABLE, any of email / phone / hash / `user_id` set | ANONYMIZED, all null |
| Support message | IDENTIFIABLE, email in text | `[REDACTED]` |
| Tombstone | any of name, email, phone, hash set | all four null |
| Data flow | ACTIVE, `enabled=1` / true | DISABLED, `enabled=0` |
| Backup | ACTIVE, `restore_allowed=1`, `eligible=true` and `deletion_block=false` | BLOCKED, `restore_allowed=0`, `decision=deny` |
| Security audit / legal hold | FOUND (to be retained) | n/a |

## Identity facts (verified on the full data)

- `email_hash = sha256(email.strip().lower())`. All 850 current hashes and all 107 historical hash changes match. Stored emails are already lowercase and trimmed, so raw and normalized hashes coincide; the data cannot show whether the generator lowercased. No evidence file hashes an uppercase variant.
- All 518 request emails resolve to a user: about 417 current, about 100 historical (the email changed 91 to 215 days before `requested_at`). 20 request emails are uppercase, e.g. `case_38`. The only variation is letter case; no whitespace or unicode variants.
- No email is the current email of one user and the old email of another. Lookalike decoys exist in evidence (about 32 near-match emails such as `g.silva76.jr@gmail.com`); matching must be exact after `strip().lower()`.
- Identifier set per user: `user_id`, name, every current and old email (lowercased), every current and old hash, every phone (digits only), and resources linked by `LINK_RESOURCE_IDENTITY`. Phones appear in about 12 formats.
- 417 hex64 strings appear in text evidence: 58 current hashes, 1 historical, about 358 opaque (decoys, they match no email).
- `user_18` has two requests with different `audit_at` (`case_33`, `case_52`); `user_07` appears in sample `case_07` and `case_61`; `user_17` in `case_17` and `case_46`. Evaluate every case independently.

## Request classification

- Exactly 10 non-deletion requests among the 518: `case_533` to `case_542` (phone update, stop promo emails, data download, login reset, surname correction, marketing lists only, "what do you hold", invoice copy, change email, copy of information). All are English, `NOT_STARTED`. Each has a matching `CLASSIFY_REQUEST` activity row ("non-deletion; no destructive action was authorized"), a second signal.
- The 32 samples contain no `NOT_APPLICABLE` case, so this rule cannot be checked against known answers.
- Negation traps: "not asking for deletion", "do not close", "don't delete". Audit-style requests ("verify it was deleted") are still deletion cases.
- 375 unique request texts for 518 rows; mostly templated English, plus Spanish, Portuguese, French, Korean, Japanese templates (all deletion). One agent counted 12 French requests with no deletion keyword that it did not classify.
