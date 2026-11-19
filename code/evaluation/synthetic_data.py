"""Dataset builder for synthetic_cases.py: a tiny private participant dataset written to a temp directory.

Nothing here runs the pipeline.  The module only holds the data tables and the code that turns them into the
files the pipeline reads (user_identities.csv, user_audit_log.csv, system_activity.csv, evidence_files.csv,
deletion_requests.csv, evidence/records/*), so the expected answers and the test runner live in synthetic_cases.py.

Sections, in file order:
  1. constants and small helpers
  2. USERS            the people the cases are about (user_901..user_921)
  3. AUDIT_LOG        profile changes (old email, old phone) that identity resolution must follow
  4. EVIDENCE_FILES   plain-text handover files, one entry per case family S2..S16
  5. SQL snapshots    the two database-style evidence files (S10 replica drift, S16-S22 rule conditions)
  6. CASES            the deletion requests (syn_1 .. syn_22)
  7. build(root)      writes everything and returns the request rows

    build(root) -> list[dict]     (the request rows, in case order)
"""

import csv
import hashlib
import json
import os
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
CODE = os.path.dirname(HERE)
REPO = os.path.dirname(CODE)

# ---------------------------------------------------------------- 1. constants and helpers

STAMP = "2026-05-10T09:00:00Z"  # capture time of most evidence files: before every audit_at below
AUDIT_AT = "2026-05-10T12:00:00Z"
REQUESTED_AT = "2026-05-01T09:00:00Z"
REQ = "I would like my account and personal data erased, please confirm when done."
USER_UPDATED_AT = "2026-01-01T00:00:00Z"
HANDOVER_BANNER = "SYNTHETIC HANDOVER\n\n"
# column list shared by the primary and replica tables of the SQL snapshots
TABLE_COLUMNS = (
    "(resource_id TEXT PRIMARY KEY, origin_system TEXT NOT NULL, collection_name TEXT NOT NULL, "
    "record_json TEXT NOT NULL CHECK (json_valid(record_json)), updated_at TEXT NOT NULL)"
)


def sha(e):
    return hashlib.sha256(e.strip().lower().encode()).hexdigest()


def write_csv(path, header, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def line(ts, system, rid, rtype, result, subject):
    """One handover-file line: '- time | system | resource | type | result | who it identifies'."""
    return f"- {ts} | {system} | {rid} | {rtype} | {result} | {subject}"


def account_gone(n, subject, ts=STAMP):
    """The account lookup that returns NOT_FOUND: every case needs it so the account is verified absent."""
    return line(ts, "account_service", f"account_{n}", "USER_PROFILE", "NOT_FOUND", subject)


def at_stamp(system, rid, rtype, result, subject):
    return line(STAMP, system, rid, rtype, result, subject)


def req(case, email, requested, audit, text=REQ):
    return {
        "case_id": case,
        "email": email,
        "requested_at": requested,
        "reported_status": "COMPLETE",
        "reported_at": requested[:10] + "T12:00:00Z",
        "audit_at": audit,
        "request_text": text,
    }


# ---------------------------------------------------------------- 2. users

USERS = {  # user_id: (name, email, phone)
    "user_901": ("Alice Tester", "alice.tester@example.com", "+1 555 0101"),
    "user_902": ("Bob Tester", "bob.new@example.com", "+1 555 0102"),
    "user_903": ("Carla Tester", "carla.tester@example.com", "+1 555 0103"),
    "user_904": ("Dmitri Tester", "dmitri.tester@example.com", "+1 555 0104"),
    "user_905": ("Eve Tester", "eve.tester@example.com", "+1 555 0105"),
    "user_906": ("Farid Tester", "farid.tester@example.com", "+1 555 0106"),
    "user_907": ("Gita Tester", "gita.tester@example.com", "+1 555 0107"),
    "user_908": ("Hana Tester", "hana.tester@example.com", "+1 555 0108"),
    "user_909": ("Ivo Tester", "ivo.tester@example.com", "+1 555 0109"),
    "user_910": ("Jun Tester", "jun.tester@example.com", "+1 555 0110"),
    "user_911": ("Kira Tester", "kira.tester@example.com", "+1 555 0111"),
    "user_912": ("Luis Tester", "luis.tester@example.com", "+1 555 0112"),
    "user_913": ("Mina Tester", "mina.tester@example.com", "+1 555 0113"),
    "user_914": ("Noor Tester", "noor.tester@example.com", "+1 555 0114"),
    "user_915": ("Olga Tester", "olga.tester@example.com", "+1 555 0115"),
    "user_916": ("Pia Tester", "pia.tester@example.com", "+1 555 0116"),
    "user_917": ("Quin Tester", "quin.tester@example.com", "+1 555 0117"),
    "user_918": ("Rae Tester", "rae.tester@example.com", "+1 555 0118"),
    "user_919": ("Sol Tester", "sol.tester@example.com", "+1 555 0119"),
    "user_920": ("Tao Tester", "tao.tester@example.com", "+1 555 0120"),
    "user_921": ("Uma Tester", "uma.tester@example.com", "+1 555 0121"),
}

# ---------------------------------------------------------------- 3. audit log
# user_902 changed email (old address bob.old@example.com); user_911 changed phone (old +1 555 0911)

AUDIT_LOG = [
    ["audit_s1", "user_902", "2026-02-01T00:00:00Z", "email", "bob.old@example.com", "bob.new@example.com"],
    [
        "audit_s2",
        "user_902",
        "2026-02-01T00:00:00Z",
        "email_hash",
        sha("bob.old@example.com"),
        sha("bob.new@example.com"),
    ],
    ["audit_s3", "user_911", "2026-02-01T00:00:00Z", "phone", "+1 555 0911", "+1 555 0111"],
]

# ---------------------------------------------------------------- 4. plain-text evidence files
# file_id -> (file name, captured_at, lines).  The dict order is the manifest order.

EVIDENCE_FILES = {
    # S2 (user_901) evidence captured exactly at audit_at, uppercase email
    "evidence_s2": (
        "s2_handover.txt",
        AUDIT_AT,
        [
            account_gone(9001, "ALICE.TESTER@EXAMPLE.COM", AUDIT_AT),
            line(AUDIT_AT, "search_service", "search_9001", "SEARCH_INDEX_ENTRY", "FOUND", "ALICE.TESTER@EXAMPLE.COM"),
        ],
    ),
    # S3 (user_903) clean state at audit, reactivation in a later file
    "evidence_s3a": (
        "s3_before.txt",
        "2026-05-10T10:00:00Z",
        [account_gone(9003, "carla.tester@example.com", "2026-05-10T10:00:00Z")],
    ),
    "evidence_s3b": (
        "s3_after.txt",
        "2026-05-12T10:00:00Z",
        [
            line(
                "2026-05-12T10:00:00Z",
                "account_service",
                "account_9003",
                "USER_PROFILE",
                "FOUND",
                "carla.tester@example.com",
            )
        ],
    ),
    # S4 (user_902) old email request, support record only carries the OLD email hash
    "evidence_s4": (
        "s4_handover.txt",
        STAMP,
        [
            account_gone(9002, "bob.new@example.com"),
            at_stamp("support_platform", "support_9002", "SUPPORT_MESSAGE", "IDENTIFIABLE", sha("bob.old@example.com")),
        ],
    ),
    # S5 (user_904) lookalike decoy records must not be linked
    "evidence_s5": (
        "s5_handover.txt",
        STAMP,
        [
            account_gone(9004, "dmitri.tester@example.com"),
            at_stamp("search_service", "search_9099", "SEARCH_INDEX_ENTRY", "FOUND", "dmitri.tester2@example.com"),
            at_stamp("search_service", "search_9098", "SEARCH_INDEX_ENTRY", "FOUND", "dmitri.tester@example.org"),
        ],
    ),
    # S6 (user_905) tombstone exposed + retained audit record
    "evidence_s6": (
        "s6_handover.txt",
        STAMP,
        [
            account_gone(9005, "eve.tester@example.com"),
            at_stamp("identity_service", "tombstone_9005", "ACCOUNT_TOMBSTONE", "IDENTIFIABLE", "user_905"),
            at_stamp("security_service", "audit_record_9005", "SECURITY_AUDIT_LOG", "FOUND", "user_905"),
        ],
    ),
    # S7 (user_906) active flow + restorable backup + remaining search (ordering)
    "evidence_s7": (
        "s7_handover.txt",
        STAMP,
        [
            account_gone(9006, "farid.tester@example.com"),
            at_stamp("backup_service", "backup_9006", "BACKUP_ARCHIVE", "ACTIVE", "farid.tester@example.com"),
            at_stamp("integration_service", "data_flow_9006", "DATA_FLOW", "ACTIVE", "farid.tester@example.com"),
            at_stamp("search_service", "search_9006", "SEARCH_INDEX_ENTRY", "FOUND", "farid.tester@example.com"),
        ],
    ),
    # S8 (user_907): record seen BEFORE the request (stale) and a clean lookup after it
    "evidence_s8a": (
        "s8_old.txt",
        "2026-03-01T09:00:00Z",
        [
            line(
                "2026-03-01T09:00:00Z",
                "search_service",
                "search_9007",
                "SEARCH_INDEX_ENTRY",
                "FOUND",
                "gita.tester@example.com",
            )
        ],
    ),
    "evidence_s8b": ("s8_new.txt", STAMP, [account_gone(9007, "gita.tester@example.com")]),
    # S9 (user_909) categories with no real-data coverage: cache entry, email delivery log, marketing profile
    "evidence_s9": (
        "s9_handover.txt",
        STAMP,
        [
            account_gone(9009, "ivo.tester@example.com"),
            at_stamp("cache_service", "cache_9009", "CACHE_ENTRY", "FOUND", "ivo.tester@example.com"),
            at_stamp(
                "email_delivery_service",
                "email_delivery_9009",
                "EMAIL_DELIVERY_LOG",
                "IDENTIFIABLE",
                "ivo.tester@example.com",
            ),
            at_stamp("marketing_platform", "marketing_9009", "MARKETING_PROFILE", "FOUND", "ivo.tester@example.com"),
        ],
    ),
    # S10 (user_910): the account lookup; the replica-drift evidence is the SQL snapshot below
    "evidence_s10": ("s10_account.txt", STAMP, [account_gone(9010, "jun.tester@example.com")]),
    # S11 (user_911) record carries only the OLD phone number
    "evidence_s11": (
        "s11_handover.txt",
        STAMP,
        [
            account_gone(9011, "kira.tester@example.com"),
            at_stamp("support_platform", "support_9011", "SUPPORT_MESSAGE", "IDENTIFIABLE", "+1 555 0911"),
        ],
    ),
    # S12/S13 (user_912) one person, two requests with different audit_at: the search entry is gone by the second
    "evidence_s12a": (
        "s12_early.txt",
        "2026-05-05T09:00:00Z",
        [
            account_gone(9012, "luis.tester@example.com", "2026-05-05T09:00:00Z"),
            line(
                "2026-05-05T09:00:00Z",
                "search_service",
                "search_9012",
                "SEARCH_INDEX_ENTRY",
                "FOUND",
                "luis.tester@example.com",
            ),
        ],
    ),
    "evidence_s12b": (
        "s12_late.txt",
        STAMP,
        [
            account_gone(9012, "luis.tester@example.com"),
            at_stamp("search_service", "search_9012", "SEARCH_INDEX_ENTRY", "NOT_FOUND", "luis.tester@example.com"),
        ],
    ),
    # S14 (user_913) two search entries whose ids sort differently as text and as numbers
    "evidence_s14": (
        "s14_handover.txt",
        STAMP,
        [
            account_gone(9013, "mina.tester@example.com"),
            at_stamp("search_service", "search_9", "SEARCH_INDEX_ENTRY", "FOUND", "mina.tester@example.com"),
            at_stamp("search_service", "search_10", "SEARCH_INDEX_ENTRY", "FOUND", "mina.tester@example.com"),
        ],
    ),
    # S15 (user_914) nothing usable: the only evidence is captured after audit_at
    "evidence_s15": (
        "s15_late.txt",
        "2026-06-01T09:00:00Z",
        [account_gone(9014, "noor.tester@example.com", "2026-06-01T09:00:00Z")],
    ),
    # S16-S22 account lookups for users 915..921 (their records are in the SQL snapshot below)
    "evidence_s16": (
        "s16_accounts.txt",
        STAMP,
        [
            account_gone(f"90{n}", f"{name}.tester@example.com")
            for n, name in [(15, "olga"), (16, "pia"), (17, "quin"), (18, "rae"), (19, "sol"), (20, "tao"), (21, "uma")]
        ],
    ),
}

# ---------------------------------------------------------------- 5. SQL snapshots

S10_SQL_NAME = "s10_replica.sql"
S16_SQL_NAME = "s16_conditions.sql"


def insert_row(rid, origin, collection, record_json, table="customer_data_primary"):
    return f"INSERT INTO \"{table}\" VALUES('{rid}','{origin}','{collection}','{record_json}','{STAMP}');"


def snapshot_sql(topology, tables, inserts):
    header = [
        "-- Synthetic snapshot",
        f"-- Captured at: {STAMP}",
        f"-- Database topology: {topology}",
        "BEGIN TRANSACTION;",
    ]
    creates = [f"CREATE TABLE {t} {TABLE_COLUMNS};" for t in tables]
    return "\n".join(header + creates + inserts + ["COMMIT;"]) + "\n"


def s10_sql():
    """S10 (user_910) replication drift: the primary row is anonymized, the read replica still holds the identifiers."""
    metrics = {"sessions_30d": 3}
    anonymized = {"resource_id": "analytics_9010", "user_id": None, "email": None, "phone": None, "email_hash": None}
    leaking = dict(anonymized, user_id="user_910", email="jun.tester@example.com")
    args = ("analytics_9010", "analytics_platform", "customer_analytics_reports")
    compact = {"separators": (",", ":")}  # the original snapshot text has no spaces after , and :
    return snapshot_sql(
        "read_replica",
        ["customer_data_primary", "customer_data_read_replica"],
        [
            insert_row(*args, json.dumps({**anonymized, "metrics": metrics}, **compact)),
            insert_row(
                *args, json.dumps({**leaking, "metrics": metrics}, **compact), table="customer_data_read_replica"
            ),
        ],
    )


# S16-S22 conditions of rules 05, 06, 12, 13: (collection, origin system, record)
S16_RECORDS = [
    (  # S16 retention already ended -> delete
        "security_audit_events",
        "security_service",
        {
            "resource_id": "audit_record_9015",
            "subject_reference": "user_915",
            "event_name": "login",
            "retention_until": "2026-04-01T00:00:00Z",
        },
    ),
    (  # S17 still within retention -> verify present
        "security_audit_events",
        "security_service",
        {
            "resource_id": "audit_record_9016",
            "subject_reference": "user_916",
            "event_name": "login",
            "retention_until": "2030-04-01T00:00:00Z",
        },
    ),
    (  # S18 legal hold ended -> delete
        "retained_order_records",
        "legal_service",
        {
            "resource_id": "legal_hold_9017",
            "subject_reference": "user_917",
            "order_reference": "ORD-9017",
            "retained_until": "2026-01-01T00:00:00Z",
        },
    ),
    (  # S19 attachment uploaded by staff -> redact (shared)
        "ticket_attachments",
        "support_platform",
        {
            "resource_id": "support_9018",
            "subject_reference": "user_918",
            "uploaded_by": "agent.sam@northstar.shop",
            "file_name": "label.pdf",
        },
    ),
    (  # S20 attachment uploaded by the subject -> delete
        "ticket_attachments",
        "support_platform",
        {
            "resource_id": "support_9019",
            "subject_reference": "user_919",
            "uploaded_by": "sol.tester@example.com",
            "file_name": "photo.jpg",
        },
    ),
    (  # S21 message without order/agent context: rules default to redact
        "support_conversations",
        "support_platform",
        {
            "resource_id": "support_9020",
            "subject_reference": "user_920",
            "message_text": "Please note my new phone and write to tao.tester@example.com",
        },
    ),
    (  # S22 same text; the (fake) model verdict decides -> delete
        "support_conversations",
        "support_platform",
        {
            "resource_id": "support_9021",
            "subject_reference": "user_921",
            "message_text": "Please note my new phone and write to uma.tester@example.com",
        },
    ),
]


def s16_sql():
    inserts = [
        insert_row(rec["resource_id"], origin, coll, json.dumps(rec).replace("'", "''"))
        for coll, origin, rec in S16_RECORDS
    ]
    return snapshot_sql("primary", ["customer_data_primary"], inserts)


# extra manifest rows for the SQL files: file_id -> file name
SQL_FILES = {"evidence_s10sql": (S10_SQL_NAME, s10_sql), "evidence_s16sql": (S16_SQL_NAME, s16_sql)}

# ---------------------------------------------------------------- 6. requests
# (case_id, email, audit_at, request text).  Only syn_1 differs from the default text.

NOT_DELETION_TEXT = (
    "Please correct the spelling of my surname. I am not asking for deletion, so do not close the account."
)
CASES = [
    ("syn_1", "alice.tester@example.com", AUDIT_AT, NOT_DELETION_TEXT),
    ("syn_2", "alice.tester@example.com", AUDIT_AT, REQ),
    ("syn_3", "carla.tester@example.com", AUDIT_AT, REQ),
    ("syn_4", "bob.old@example.com", AUDIT_AT, REQ),
    ("syn_5", "dmitri.tester@example.com", AUDIT_AT, REQ),
    ("syn_6", "eve.tester@example.com", AUDIT_AT, REQ),
    ("syn_7", "farid.tester@example.com", AUDIT_AT, REQ),
    ("syn_8", "gita.tester@example.com", AUDIT_AT, REQ),
    ("syn_9", "ivo.tester@example.com", AUDIT_AT, REQ),
    ("syn_10", "jun.tester@example.com", AUDIT_AT, REQ),
    ("syn_11", "kira.tester@example.com", AUDIT_AT, REQ),
    ("syn_12", "luis.tester@example.com", "2026-05-06T12:00:00Z", REQ),  # early audit: the search entry still exists
    ("syn_13", "luis.tester@example.com", AUDIT_AT, REQ),
    ("syn_14", "mina.tester@example.com", AUDIT_AT, REQ),
    ("syn_15", "noor.tester@example.com", AUDIT_AT, REQ),
    ("syn_16", "olga.tester@example.com", AUDIT_AT, REQ),
    ("syn_17", "pia.tester@example.com", AUDIT_AT, REQ),
    ("syn_18", "quin.tester@example.com", AUDIT_AT, REQ),
    ("syn_19", "rae.tester@example.com", AUDIT_AT, REQ),
    ("syn_20", "sol.tester@example.com", AUDIT_AT, REQ),
    ("syn_21", "tao.tester@example.com", AUDIT_AT, REQ),
    ("syn_22", "uma.tester@example.com", AUDIT_AT, REQ),
]

# ---------------------------------------------------------------- 7. writing the dataset


def write_participant_tables(root):
    write_csv(
        os.path.join(root, "user_identities.csv"),
        ["user_id", "name", "email", "phone", "email_hash", "updated_at"],
        [[u, n, e, p, sha(e), USER_UPDATED_AT] for u, (n, e, p) in USERS.items()],
    )
    write_csv(
        os.path.join(root, "user_audit_log.csv"),
        ["audit_id", "user_id", "event_time", "field_name", "old_value", "new_value"],
        AUDIT_LOG,
    )
    write_csv(
        os.path.join(root, "system_activity.csv"),
        [
            "activity_id",
            "event_time",
            "event_type",
            "source_system",
            "target_system",
            "resource_id",
            "reported_result",
            "details",
        ],
        [],
    )
    shutil.copy(os.path.join(REPO, "dataset", "deletion_rules.csv"), os.path.join(root, "deletion_rules.csv"))


def write_evidence(root):
    """Writes the evidence files and evidence_files.csv (text files first, then the SQL snapshots)."""
    records = os.path.join(root, "evidence", "records")
    os.makedirs(records)
    manifest = []
    for fid, (name, cap, lines) in EVIDENCE_FILES.items():
        with open(os.path.join(records, name), "w", encoding="utf-8", newline="") as f:
            f.write(HANDOVER_BANNER + "\n".join(lines) + "\n")
        manifest.append([fid, f"evidence/records/{name}", "synthetic", cap])
    for fid, (name, make_text) in SQL_FILES.items():
        with open(os.path.join(records, name), "w", encoding="utf-8") as f:  # platform newlines, as before
            f.write(make_text())
        manifest.append([fid, f"evidence/records/{name}", "synthetic", STAMP])
    write_csv(os.path.join(root, "evidence_files.csv"), ["file_id", "file_path", "origin", "captured_at"], manifest)


def build(root):
    """Write the whole synthetic dataset under root and return its deletion requests."""
    write_participant_tables(root)
    write_evidence(root)
    cases = [req(cid, email, REQUESTED_AT, audit, text) for cid, email, audit, text in CASES]
    write_csv(os.path.join(root, "deletion_requests.csv"), list(cases[0]), [list(c.values()) for c in cases])
    write_csv(os.path.join(root, "sample_deletion_requests.csv"), list(cases[0]), [])
    return cases
