"""Synthetic evaluation cases written by us (not from the organisers' data).

A tiny private dataset is generated in a temp directory and the full pipeline is run on it.  Each
case targets a risk found in the design review:

  S1  NOT_APPLICABLE        deletion words appear but the person refuses deletion
  S2  time boundary         evidence captured exactly at audit_at is usable; email is UPPERCASE in evidence
  S3  later reactivation    a snapshot captured after audit_at must not change a COMPLETE answer
  S4  historical identity   request uses the OLD email; a support record carries only the OLD email's hash
  S5  lookalike decoy       a record for a near-identical email must not be linked
  S6  tombstone             tombstone with direct identifiers is exposed PII; retained audit record stays
  S7  ordering              active data flow and restorable backup: DISABLE before BLOCK, findings sorted
  S8  stale observation     a record seen BEFORE the request does not prove the state after it
  S9  rare categories      cache entry, email delivery log, marketing profile (no real-data coverage)
  S10 replication drift    primary row anonymized but the read replica still holds the identifiers
  S11 old phone number     record carries only the user's previous phone
  S12/13 same person       two requests with different audit_at: each answer follows its own time
  S14 id ordering          search_10 sorts before search_9 as text (our documented choice)
  S15 no usable evidence   only evidence captured after audit_at: COMPLETE with [] and a review flag
  S16/17 retention         audit record past its retention end is deleted, within it is verified present
  S18 legal hold ended     a hold record whose end date has passed is deleted
  S19/20 attachment owner  uploaded by staff -> redact (shared); uploaded by the subject -> delete
  S21/22 shared context    message without order/agent context: rules default redact, model verdict -> delete

Layout: synthetic_data.py builds the dataset (users, evidence files, SQL snapshots, requests); this file holds
the expected answers (EXPECTED) and the runner.

Run:  python code/evaluation/synthetic_cases.py        (exit code 0 = all pass)
"""

import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
CODE = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import synthetic_data  # noqa: E402


def S(phase, op, system, rid, ev=""):
    return (phase, op, system, rid, ev)


EXPECTED = {
    "syn_1": ("NOT_APPLICABLE", []),
    "syn_2": (
        "INCOMPLETE",
        [
            S("FINDING", "REPORT_REMAINING_RECORD", "search_service", "search_9001", "evidence_s2"),
            S("REMEDIATION", "DELETE_RECORD", "search_service", "search_9001"),
            S("VERIFICATION", "VERIFY_RECORD_ABSENT", "account_service", "account_9001"),
            S("VERIFICATION", "VERIFY_RECORD_ABSENT", "search_service", "search_9001"),
        ],
    ),
    "syn_3": (
        "COMPLETE",
        [
            S("VERIFICATION", "VERIFY_RECORD_ABSENT", "account_service", "account_9003", "evidence_s3a"),
        ],
    ),
    "syn_4": (
        "INCOMPLETE",
        [
            S("FINDING", "REPORT_EXPOSED_PII", "support_platform", "support_9002", "evidence_s4"),
            S("REMEDIATION", "REDACT_RECORD", "support_platform", "support_9002"),
            S("VERIFICATION", "VERIFY_RECORD_ABSENT", "account_service", "account_9002"),
            S("VERIFICATION", "VERIFY_RECORD_REDACTED", "support_platform", "support_9002"),
        ],
    ),
    "syn_5": (
        "COMPLETE",
        [
            S("VERIFICATION", "VERIFY_RECORD_ABSENT", "account_service", "account_9004", "evidence_s5"),
        ],
    ),
    "syn_6": (
        "INCOMPLETE",
        [
            S("FINDING", "REPORT_EXPOSED_PII", "identity_service", "tombstone_9005", "evidence_s6"),
            S("REMEDIATION", "REDACT_RECORD", "identity_service", "tombstone_9005"),
            S("VERIFICATION", "VERIFY_RECORD_ABSENT", "account_service", "account_9005"),
            S("VERIFICATION", "VERIFY_RECORD_PRESENT", "security_service", "audit_record_9005"),
            S("VERIFICATION", "VERIFY_RECORD_REDACTED", "identity_service", "tombstone_9005"),
        ],
    ),
    "syn_7": (
        "INCOMPLETE",
        [
            S("FINDING", "REPORT_REMAINING_RECORD", "search_service", "search_9006", "evidence_s7"),
            S("FINDING", "REPORT_ACTIVE_DATA_FLOW", "integration_service", "data_flow_9006", "evidence_s7"),
            S("FINDING", "REPORT_RESTORE_RISK", "backup_service", "backup_9006", "evidence_s7"),
            S("REMEDIATION", "DISABLE_DATA_FLOW", "integration_service", "data_flow_9006"),
            S("REMEDIATION", "BLOCK_RESTORE", "backup_service", "backup_9006"),
            S("REMEDIATION", "DELETE_RECORD", "search_service", "search_9006"),
            S("VERIFICATION", "VERIFY_RECORD_ABSENT", "account_service", "account_9006"),
            S("VERIFICATION", "VERIFY_RECORD_ABSENT", "search_service", "search_9006"),
            S("VERIFICATION", "VERIFY_DATA_FLOW_DISABLED", "integration_service", "data_flow_9006"),
            S("VERIFICATION", "VERIFY_RESTORE_BLOCKED", "backup_service", "backup_9006"),
        ],
    ),
    "syn_8": (
        "COMPLETE",
        [
            S("VERIFICATION", "VERIFY_RECORD_ABSENT", "account_service", "account_9007", "evidence_s8b"),
        ],
    ),
    "syn_9": (
        "INCOMPLETE",
        [
            S("FINDING", "REPORT_REMAINING_RECORD", "cache_service", "cache_9009", "evidence_s9"),
            S("FINDING", "REPORT_REMAINING_RECORD", "marketing_platform", "marketing_9009", "evidence_s9"),
            S("FINDING", "REPORT_EXPOSED_PII", "email_delivery_service", "email_delivery_9009", "evidence_s9"),
            S("REMEDIATION", "DELETE_RECORD", "cache_service", "cache_9009"),
            S("REMEDIATION", "DELETE_RECORD", "marketing_platform", "marketing_9009"),
            S("REMEDIATION", "REDACT_RECORD", "email_delivery_service", "email_delivery_9009"),
            S("VERIFICATION", "VERIFY_RECORD_ABSENT", "account_service", "account_9009"),
            S("VERIFICATION", "VERIFY_RECORD_ABSENT", "cache_service", "cache_9009"),
            S("VERIFICATION", "VERIFY_RECORD_ABSENT", "marketing_platform", "marketing_9009"),
            S("VERIFICATION", "VERIFY_RECORD_REDACTED", "email_delivery_service", "email_delivery_9009"),
        ],
    ),
    "syn_10": (
        "INCOMPLETE",
        [
            S("FINDING", "REPORT_EXPOSED_PII", "analytics_platform", "analytics_9010", "evidence_s10sql"),
            S("REMEDIATION", "ANONYMIZE_RECORD", "analytics_platform", "analytics_9010"),
            S("VERIFICATION", "VERIFY_RECORD_ABSENT", "account_service", "account_9010"),
            S("VERIFICATION", "VERIFY_RECORD_ANONYMIZED", "analytics_platform", "analytics_9010"),
        ],
    ),
    "syn_11": (
        "INCOMPLETE",
        [
            S("FINDING", "REPORT_EXPOSED_PII", "support_platform", "support_9011", "evidence_s11"),
            S("REMEDIATION", "REDACT_RECORD", "support_platform", "support_9011"),
            S("VERIFICATION", "VERIFY_RECORD_ABSENT", "account_service", "account_9011"),
            S("VERIFICATION", "VERIFY_RECORD_REDACTED", "support_platform", "support_9011"),
        ],
    ),
    "syn_12": (
        "INCOMPLETE",
        [
            S("FINDING", "REPORT_REMAINING_RECORD", "search_service", "search_9012", "evidence_s12a"),
            S("REMEDIATION", "DELETE_RECORD", "search_service", "search_9012"),
            S("VERIFICATION", "VERIFY_RECORD_ABSENT", "account_service", "account_9012"),
            S("VERIFICATION", "VERIFY_RECORD_ABSENT", "search_service", "search_9012"),
        ],
    ),
    "syn_13": (
        "COMPLETE",
        [
            S("VERIFICATION", "VERIFY_RECORD_ABSENT", "account_service", "account_9012", "evidence_s12b"),
            S("VERIFICATION", "VERIFY_RECORD_ABSENT", "search_service", "search_9012", "evidence_s12b"),
        ],
    ),
    "syn_14": (
        "INCOMPLETE",
        [
            S("FINDING", "REPORT_REMAINING_RECORD", "search_service", "search_10", "evidence_s14"),
            S("FINDING", "REPORT_REMAINING_RECORD", "search_service", "search_9", "evidence_s14"),
            S("REMEDIATION", "DELETE_RECORD", "search_service", "search_10"),
            S("REMEDIATION", "DELETE_RECORD", "search_service", "search_9"),
            S("VERIFICATION", "VERIFY_RECORD_ABSENT", "account_service", "account_9013"),
            S("VERIFICATION", "VERIFY_RECORD_ABSENT", "search_service", "search_10"),
            S("VERIFICATION", "VERIFY_RECORD_ABSENT", "search_service", "search_9"),
        ],
    ),
    "syn_15": ("COMPLETE", []),
    "syn_16": (
        "INCOMPLETE",
        [
            S("FINDING", "REPORT_REMAINING_RECORD", "security_service", "audit_record_9015", "evidence_s16sql"),
            S("REMEDIATION", "DELETE_RECORD", "security_service", "audit_record_9015"),
            S("VERIFICATION", "VERIFY_RECORD_ABSENT", "account_service", "account_9015"),
            S("VERIFICATION", "VERIFY_RECORD_ABSENT", "security_service", "audit_record_9015"),
        ],
    ),
    "syn_17": (
        "COMPLETE",
        [
            S("VERIFICATION", "VERIFY_RECORD_ABSENT", "account_service", "account_9016", "evidence_s16"),
            S("VERIFICATION", "VERIFY_RECORD_PRESENT", "security_service", "audit_record_9016", "evidence_s16sql"),
        ],
    ),
    "syn_18": (
        "INCOMPLETE",
        [
            S("FINDING", "REPORT_REMAINING_RECORD", "legal_service", "legal_hold_9017", "evidence_s16sql"),
            S("REMEDIATION", "DELETE_RECORD", "legal_service", "legal_hold_9017"),
            S("VERIFICATION", "VERIFY_RECORD_ABSENT", "account_service", "account_9017"),
            S("VERIFICATION", "VERIFY_RECORD_ABSENT", "legal_service", "legal_hold_9017"),
        ],
    ),
    "syn_19": (
        "INCOMPLETE",
        [
            S("FINDING", "REPORT_EXPOSED_PII", "support_platform", "support_9018", "evidence_s16sql"),
            S("REMEDIATION", "REDACT_RECORD", "support_platform", "support_9018"),
            S("VERIFICATION", "VERIFY_RECORD_ABSENT", "account_service", "account_9018"),
            S("VERIFICATION", "VERIFY_RECORD_REDACTED", "support_platform", "support_9018"),
        ],
    ),
    "syn_20": (
        "INCOMPLETE",
        [
            S("FINDING", "REPORT_REMAINING_RECORD", "support_platform", "support_9019", "evidence_s16sql"),
            S("REMEDIATION", "DELETE_RECORD", "support_platform", "support_9019"),
            S("VERIFICATION", "VERIFY_RECORD_ABSENT", "account_service", "account_9019"),
            S("VERIFICATION", "VERIFY_RECORD_ABSENT", "support_platform", "support_9019"),
        ],
    ),
    "syn_21": (
        "INCOMPLETE",
        [
            S("FINDING", "REPORT_EXPOSED_PII", "support_platform", "support_9020", "evidence_s16sql"),
            S("REMEDIATION", "REDACT_RECORD", "support_platform", "support_9020"),
            S("VERIFICATION", "VERIFY_RECORD_ABSENT", "account_service", "account_9020"),
            S("VERIFICATION", "VERIFY_RECORD_REDACTED", "support_platform", "support_9020"),
        ],
    ),
    "syn_22": (
        "INCOMPLETE",
        [
            S("FINDING", "REPORT_REMAINING_RECORD", "support_platform", "support_9021", "evidence_s16sql"),
            S("REMEDIATION", "DELETE_RECORD", "support_platform", "support_9021"),
            S("VERIFICATION", "VERIFY_RECORD_ABSENT", "account_service", "account_9021"),
            S("VERIFICATION", "VERIFY_RECORD_ABSENT", "support_platform", "support_9021"),
        ],
    ),
}


class FakeLLM:
    """Stands in for the local model: says the message holds no shared context (quote is verbatim)."""

    model = "fake"

    def chat_json(self, system, user, schema, num_ctx=2048):
        return {"quote": "Please note my new phone", "answer": False}


LLM_CASES = {"syn_22"}  # cases whose answer depends on the model's verdict


def run_cases(root, cases):
    """Run the pipeline on the synthetic dataset; the model-dependent cases get the fake model."""
    from ghost import ingest, pipeline

    db = os.path.join(root, "obs.db")
    ingest.build(db)
    plain = [c for c in cases if c["case_id"] not in LLM_CASES]
    modelled = [c for c in cases if c["case_id"] in LLM_CASES]
    rows = {r["case_id"]: r for r in pipeline.run_requests(plain, pipeline.Auditor(cases, db_path=db))}
    with_llm = pipeline.Auditor(cases, db_path=db, llm=FakeLLM())
    rows.update({r["case_id"]: r for r in pipeline.run_requests(modelled, with_llm)})
    return rows


def check_case(cid, want, row):
    """Compare one pipeline result with its expectation, print the verdict line, return True when it passes."""
    status, steps = want
    got = [(s["phase"], s["operation"], s["system_id"], s["resource_id"], s["evidence_id"]) for s in row["steps"]]
    ok = row["status"] == status and got == steps and not row["errors"]
    print(f"{'PASS' if ok else 'FAIL'} {cid}: status {row['status']} (want {status}), {len(got)} steps")
    if not ok:
        print("   want:", steps)
        print("   got :", got, row["errors"], row["review"])
    return ok


def main():
    root = tempfile.mkdtemp(prefix="ghost_syn_")
    os.environ["GHOST_DATASET"] = root  # the pipeline reads the dataset location from the environment
    sys.path.insert(0, CODE)
    try:
        rows = run_cases(root, synthetic_data.build(root))
        failed = sum(not check_case(cid, want, rows[cid]) for cid, want in EXPECTED.items())
        print(f"\n{len(EXPECTED) - failed}/{len(EXPECTED)} synthetic cases pass")
        return 1 if failed else 0
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
