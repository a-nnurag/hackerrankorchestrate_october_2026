# 07. Retention and hold dates, attachment ownership, shared context, and the log gap

Follow-up to the self-review of 2026-10-25. Web research first, then implementation split into what rules
can decide and what needs a model. The web sources are mostly vendor blogs, glossaries and the GDPR text;
none addresses this dataset, so `dataset/deletion_rules.csv` stays the authority. Not legal advice.

## What the sources say

- Erasure has exceptions for a specific legal obligation and for legal claims (Art. 17(3)); a vague "might be
  needed" does not qualify ([GDPR Art. 17](https://gdpr-info.eu/art-17/),
  [GDPR Local](https://gdprlocal.com/es/right-to-erasure/)).
- A legal hold overrides automatic disposal while active; on release normal retention resumes and records
  already past their period may be purged straight away ([Venio](https://www.veniosystems.com/blog/legal-hold-and-auto-deletion-in-m365-and-google-vault),
  [Folderit](https://www.folderit.com/glossary/retention-hold/)). A hold protects from its effective date,
  not from when the duty began.
- Redaction or anonymisation is a common form of partial erasure; regulators press controllers to finish
  erasing related data ([Irish DPC case studies](https://www.dataprotection.ie/dpc-guidance/case-studies/erasure)).
  Nothing found says whether redacting only the requester in a shared conversation satisfies Art. 17.
- Corrections to an append-only trail are new entries with a reason, never edits
  ([Cratis](https://www.cratis.io/chronicle/events/revision/),
  [audit-log design](https://www.techinterview.org/post/3233465643/system-design-audit-log/)).

## What is rules and what is LLM

| Issue | Decided by rules | LLM (only when rules cannot classify) |
|---|---|---|
| Retention end of an audit record (rule_12) | date comparison with `audit_at` | never |
| Legal hold end (rule_13) | date comparison with `audit_at` | never |
| Attachment owned only by the subject (rule_06) | uploader identity, catalog phrases | free-text catalog notes |
| Shared message context (rule_05) | context words | messages with no context words |
| Log gap | append late entries (no model) | never |

Unspecified by the task, so flagged for review: expired retention is treated as an ordinary record
(report and delete); a shared attachment is redacted (nearest allowed operation to rule_05).

## Where it lives

`code/ghost/conditions.py`, rule-table entries in `code/ghost/rules.py` (`EXPIRED`, `SHARED`,
`NO_SHARED_CONTEXT`), adjudicators in `code/ghost/llm.py`, tests `code/evaluation/synthetic_cases.py`
(syn_16 to syn_22) and `code/evaluation/test_condition_llm.py`. Results are in
`code/evaluation/evaluation_report.md` section 13.

## Log

`log.txt` is append-only. Six turns were missing individual entries; they were added as clearly marked
`LATE ENTRY` records with the write time, earlier entries untouched. The submitted trace should also include
the session files and `/export` transcript required by `agent_trace_instructions.md`.
