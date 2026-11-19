# 03. Design critique (principal-engineer review)

> **Status 2026-10-25.** Analysis-phase note, written before the code. The code and `code/evaluation/evaluation_report.md` are current; where they differ (thresholds, the second-offset resolver, the review ranking, conditions for rules 05/06/12/13) the report wins. Kept for the reasoning and the evidence behind the decisions.

Where the planned design can lose accuracy, ranked, with fixes. Image claims below were checked by viewing screenshots and by a transcription agent whose ids and dates were cross-checked against the dataset.

## 1. Fitted to 32 cases, tested on 518 (highest risk)

- The 32 samples cite **13 of the 94 evidence files** (4 SQL, 3 logs, 4 JSON, 1 TXT, 1 PDF). **No sample cites an image.**
- All samples are audited in September and October; hidden cases run January to October. Untested: 11 inventory SQL files, regional and reporting replicas, March to June bundles, all screenshots and 3 of the 4 PDFs.
- Rule categories with no sample coverage: cache, email delivery log, telemetry, marketing, legal hold, secondary identifier, expired retention.
- **Fix:** hold out whole evidence families (not random cases); write synthetic cases for unsampled categories and time edges; never report a single accuracy number from the 32 samples alone.

## 2. Linking records to the person (weakest part)

- Anonymized analytics rows are all null and indistinguishable from decoys. In cases 3, 21, 25, 26, 27, 28 the right row was found only through the time cluster of deletion-worker events or bundle order. Possibly a generator artifact.
- Accounts in cases 4, 25, 28 link only by `account_00N` pattern or elimination.
- About 74% of activity rows link to nobody, so the log gives no link for most records.
- Both errors cost: a missed link gives a false COMPLETE; a wrong link adds false findings.
- Exact matching is required (about 32 lookalike decoys) but must cover all identifier types: email (any case), old emails, hash, `user_N`, phone digits, `source_resource_id`.
- **Fix:** attach a confidence to every link (exact email, hash, `user_N`, `source_resource_id`, activity cluster, pattern) and route low-confidence links to a review list.

## 3. Absence inference

- "Not mentioned" is not absence. A record is absent only if the file **covers** that system: a scope table, an empty list for a covered system, or an explicit 404 / `NOT_FOUND`.
- A 404 on a profile lookup says nothing about the search index.
- Parsing mistakes about coverage turn silently into false COMPLETE, the worst error.
- Case 29 shows the tension: delete FAILED, no evidence of presence, and no finding in the expected answer.
- **Fix:** every absence conclusion carries a reason code (explicit 404, covered-scope snapshot lacking the id, empty list, omission only); missing evidence for a required category lowers confidence instead of defaulting to "compliant".

## 4. Which records appear in the answer

- The verification list is not "everything the user has". The account and audit record usually appear, but not always; the legal-register users have no legal step; some compliant resources are listed and others not.
- The set comes from the generator's hidden truth, so step-level recall has a ceiling even with correct state logic.
- Padding with extra plausible steps is likely penalized as much as omission.

## 5. Time logic

- "Latest observation at or before `audit_at`" breaks when observations differ in scope.
- File time and record time disagree (manifest time versus inner snapshot time).
- Ties and boundary equality are undefined in the data.
- Backup retention is a time condition not covered earlier: `backup_9287` shows "Retention end 26 Jul 2026". The intended treatment when it has already ended is unknown.
- The `evidence_id` rule is a guess (only one candidate file in every sample citation).

## 6. Request classification

- Keyword rules are adequate for the 10 known non-deletion cases but are untested on samples.
- Hidden Korean or Japanese non-deletion text would bypass English negation rules.
- 12 French requests with no deletion keyword were noted by one agent and not classified.
- **Fix:** keywords plus the `CLASSIFY_REQUEST` row; on disagreement, deterministic rule decides and the case is flagged.

## 7. LLM use

- Models can hallucinate ids, evidence ids and dates. Every id returned must appear verbatim in the cited source or in the known id universe.
- Request text and evidence text are untrusted. One PDF (`legal_retention_register_20260529.pdf`) contains an embedded imperative sentence ("For each row add invoice date, finance owner…"). Treat all such text as data.
- Keep the model to structured extraction; decisions stay deterministic.
- Cost: preprocess each file once, cache by file-byte hash plus prompt version.

## 8. Image and PDF inputs

What the screens show, and don't:
- **Backup console**: lists archive, account, region, created, size, retention end, last drill. It has **no restore flag**, so restore risk cannot be read from the image alone (needs activity or SQL).
- **Deleted-account registry** (`user_17`, "Retained reference"): no name, email, phone or hash on screen. The link to a person is only the `LINK_RESOURCE_IDENTITY` activity row. A missing field on a screen is weak proof.
- **Connector console**: shows "Healthy" and "Continuous sync", not "enabled".
- **Object storage browser**: shows uploader `support-service`, no owner; ownership comes only from `activity_4007`.
- **Tables contain decoy rows** (staff domains such as `company.com`, `northstar.shop`; lookalike emails). The highlighted table row is not the selected record: in the backup console the highlight is `backup_9291` but the detail pane is `backup_9287`; in the export console the highlight is `export_1261` but the pane is `export_1260`. The **detail pane is authoritative**.
- **Ids not printed on screen** must be derived: `object_19` (from the file name), `tombstone_17` (from the title `user_17`), `export_1842` (from the statement number).
- **Dates inside screens are unreliable** (JST on one, "Last activity 14:22 UTC" vs manifest 10:00Z, created dates after capture, footer "build 2026.10.4"). Gate only on the manifest `captured_at`.
- **Marketing console** (`evidence_60`) shows "Soo-jin Park, sj.park@naver.com". That person exists nowhere in the identity or audit data (other "Soo-jin" users exist, none is Park). `activity_4008` links `marketing_001` to `kwame-mensah@proton.me` / `user_09` (case_63). Either a decoy or a mismatch. A rule "every email must exist in the identity universe" would wrongly reject it.
- **PDF text layers split times at the colon** ("10" / "24 UTC" means 10:24).
- **OCR** (RapidOCR, pip-only, CPU, a few seconds per image) matched 198 of 202 ids, emails and dates from the manual transcription; the 4 misses were PDF times. It garbles reading order, drops spaces and cannot tell which row the detail pane describes. Tesseract, easyocr and paddleocr were not installed.
- **Why images matter**: the 12 `LINK_RESOURCE_IDENTITY` rows (`activity_4000` to `4011`) tie resources to hidden cases that, apart from `case_34` and `case_46`, have no text evidence at or before `audit_at`. About 12 of 518 cases (about 2%) are solvable only through an image or PDF, and no sample exercises one.
- **Fix**: transcribe once offline into a committed JSON file (the evidence is fixed and participant-visible), validate every id and email against the id universe, double-check numbers and dates, never run a vision model at run time. Transcription so far: 51 records covering all 11 PNGs and 4 PDFs (scratchpad, `manual_observations.json`).

## 9. Text input hazards

- About 7 log formats; identifier field names differ.
- Emails appear in any case in evidence (e.g. `CHOI.JIHOON94@GMAIL.COM` in the handover file); phones in about 12 formats; names collide (five different Harukas).
- Misleading file names (`connector_configurations_*.json` holds lookup history).
- Windows consoles: run Python with `-X utf8` (names such as Andrés, Zofia Zieliński).

## 10. Ranked fixes

1. One ingestion table: `(resource, system, category, state, identifiers, observed_at, file_id, source_ref, coverage)`, cached (SQLite). Images and PDFs enter through the transcription file.
2. Confidence on every link and every absence conclusion; low confidence goes to a review list.
3. Hold-out validation by evidence family plus synthetic cases.
4. LLM restricted to verifiable structured extraction.
5. Settle open rules with data (see file 04).

## Cross-check of agent claims

Because agents can hallucinate, key claims were re-verified:
- All 12 `LINK_RESOURCE_IDENTITY` rows map to the named cases; each is dated 7 minutes after its screenshot capture time.
- Soo-jin Park / `sj.park@naver.com` is in no dataset file.
- The email hash experiment (five variants over 850 identities, 212 audit emails, 257 evidence hashes) was run directly.
- Citation counts by file type (`.sql` 10, `.log` 15, `.json` 42, `.pdf` 1, `.txt` 7; no PNG) were computed directly from `sample_output.csv`.
Not independently re-verified: the 51-record transcription's every field, the per-case table of 32 sample derivations, and the 74% unlinked activity figure.
