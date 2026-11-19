"""Parser for SQL snapshot dumps: the file is executed in an in-memory SQLite and every table row is observed."""

from __future__ import annotations

import collections
import json
import re
import sqlite3
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

from .identifiers import has_direct, idents_from_record
from .states import analytics_state, state_for_record
from .table import Source, Table
from .vocab import category_of

_INSERT_RE = re.compile(r"^INSERT INTO \"?(\w+)\"? VALUES\s*\(\s*'([^']*)'")
_TOPOLOGY_RE = re.compile(r"-- Database topology: (\w+)")

# Inventory tables (flat columns, no record_json): table -> (system_id, category).
_INVENTORY_TABLES = {
    "customer_profiles": ("account_service", "USER_PROFILE"),
    "customer_search_documents": ("search_service", "SEARCH_INDEX_ENTRY"),
    "customer_analytics_profiles": ("analytics_platform", "ANALYTICS_PROFILE"),
    "support_records": ("support_platform", "SUPPORT_MESSAGE"),
    "customer_exports": ("export_service", "USER_EXPORT"),
    "connector_subscriptions": ("integration_service", "DATA_FLOW"),
    "backup_restore_entries": ("backup_service", "BACKUP_ARCHIVE"),
    "security_audit_records": ("security_service", "SECURITY_AUDIT_LOG"),
}
# Inventory columns that describe the record itself rather than the data subject.
_INVENTORY_NON_SUBJECT_COLUMNS = frozenset(
    {
        "resource_id",
        "updated_at",
        "object_key",
        "archive_key",
        "index_name",
        "connector_name",
        "message_excerpt",
        "audience_cohort",
        "event_code",
        "retention_until",
        "account_status",
        "last_delivery_status",
        "enabled",
        "restore_allowed",
    }
)
# Plain profile/search copies kept in a primary table and replicas: table -> role.
_COPY_TABLES = {
    "customer_profiles_primary": "primary",
    "customer_profiles_failover_replica": "replica",
    "search_documents_primary": "primary",
}

Placement = tuple[str | None, str | None, str | None]  # (system_id, category, collection)


@dataclass
class _Snapshot:
    """State shared by the row handlers while one SQL dump is read."""

    table: Table
    src: Source
    topology: str | None
    insert_lines: dict[tuple[str, str], int]
    primary: dict[str, Placement] = field(default_factory=dict)
    replicas: dict[str, dict[str, Placement]] = field(default_factory=lambda: collections.defaultdict(dict))

    def remember(self, table_name: str, role: str, rid: str, placement: Placement) -> None:
        """Index the row by resource id so replica rows can later be compared against the primary."""
        (self.primary if role == "primary" else self.replicas[table_name])[rid] = placement


def _scan_inserts(text: str) -> tuple[dict[tuple[str, str], int], int]:
    """Line number of each INSERT (keyed by table and first value) and the total INSERT count."""
    lines: dict[tuple[str, str], int] = {}
    count = 0
    for number, line in enumerate(text.split("\n"), 1):
        match = _INSERT_RE.match(line)
        if match:
            lines[(match.group(1), match.group(2))] = number
            count += 1
        elif line.startswith("INSERT INTO") and "snapshot_scope" in line:
            count += 1
    return lines, count


# ---------------------------------------------------------------- inventory tables
def _flow_state(row: dict, rec: dict, extras: dict) -> str:
    enabled = bool(int(row["enabled"]))
    extras.update(enabled=enabled, delivery=row["last_delivery_status"], connector=row["connector_name"])
    return "ACTIVE" if enabled else "DISABLED"


def _backup_state(row: dict, rec: dict, extras: dict) -> str:
    allowed = bool(int(row["restore_allowed"]))
    extras["restore_allowed"] = allowed
    return "ACTIVE" if allowed else "BLOCKED"


def _analytics_state(row: dict, rec: dict, extras: dict) -> str:
    return analytics_state(rec)


def _support_state(row: dict, rec: dict, extras: dict) -> str:
    return "IDENTIFIABLE" if has_direct(rec) else "REDACTED"


def _profile_state(row: dict, rec: dict, extras: dict) -> str:
    extras["account_status"] = row["account_status"]
    return "PRESENT"


def _audit_state(row: dict, rec: dict, extras: dict) -> str:
    extras.update(event=row["event_code"], retention_until=row["retention_until"])
    return "PRESENT"


_INVENTORY_STATE: dict[str | None, Callable[[dict, dict, dict], str]] = {
    "DATA_FLOW": _flow_state,
    "BACKUP_ARCHIVE": _backup_state,
    "ANALYTICS_PROFILE": _analytics_state,
    "SUPPORT_MESSAGE": _support_state,
    "USER_PROFILE": _profile_state,
    "SECURITY_AUDIT_LOG": _audit_state,
}


def _inventory_row(snap: _Snapshot, table_name: str, row: dict, ref: str) -> None:
    system, category = _INVENTORY_TABLES[table_name]
    rec = {k: v for k, v in row.items() if k not in _INVENTORY_NON_SUBJECT_COLUMNS}
    extras: dict[str, Any] = {"table": table_name}
    state_rule = _INVENTORY_STATE.get(category)
    state = state_rule(row, rec, extras) if state_rule else "PRESENT"
    snap.table.add(
        snap.src,
        row["updated_at"],
        row["resource_id"],
        system,
        category,
        state,
        ref,
        idents_from_record(rec),
        "record",
        extras,
    )


# ---------------------------------------------------------------- record_json tables
def _record_json_row(snap: _Snapshot, table_name: str, row: dict, ref: str) -> None:
    rid = row["resource_id"]
    rec = json.loads(row["record_json"])
    system = row["origin_system"]
    collection = row["collection_name"]
    category = category_of(collection, rid)
    state, extras = state_for_record(category, rec)
    extras.update({"table": table_name, "topology": snap.topology, "collection": collection})
    snap.table.add(
        snap.src, row["updated_at"], rid, system, category, state, ref, idents_from_record(rec), "record", extras
    )
    role = "primary" if table_name == "customer_data_primary" else "replica"
    snap.remember(table_name, role, rid, (system, category, collection))


# ---------------------------------------------------------------- profile / search copies
def _copy_row(snap: _Snapshot, table_name: str, row: dict, ref: str) -> None:
    rec = {
        "email": row.get("email"),
        "phone": row.get("phone"),
        "full_name": row.get("full_name") or row.get("display_name"),
        "user_id": row.get("user_id"),
        "source_resource_id": row.get("source_resource_id"),
    }
    system, category = _copy_table_home(table_name)
    extras = {"table": table_name, "topology": snap.topology, "account_status": row.get("account_status")}
    snap.table.add(
        snap.src,
        row.get("updated_at") or row.get("indexed_at"),
        row["resource_id"],
        system,
        category,
        "PRESENT",
        ref,
        idents_from_record(rec),
        "record",
        extras,
    )
    snap.remember(table_name, _COPY_TABLES[table_name], row["resource_id"], (system, category, None))


def _copy_table_home(table_name: str) -> tuple[str, str]:
    if table_name.startswith("customer_profiles"):
        return "account_service", "USER_PROFILE"
    return "search_service", "SEARCH_INDEX_ENTRY"


# ---------------------------------------------------------------- whole-dump driver
def _dict_rows(db: sqlite3.Connection, query: str) -> Iterator[dict[str, Any]]:
    cursor = db.execute(query)
    names = [column[0] for column in cursor.description]
    for values in cursor:
        yield dict(zip(names, values, strict=True))


def _read_table(db: sqlite3.Connection, snap: _Snapshot, table_name: str) -> int:
    """Observe every row of one table; returns the number of rows read."""
    count = 0
    for row in _dict_rows(db, f"select * from {table_name}"):
        count += 1
        line = snap.insert_lines.get((table_name, row["resource_id"]), 0)
        ref = f"{snap.src.path}:{line}:{table_name}"
        if "record_json" in row:
            _record_json_row(snap, table_name, row, ref)
        elif table_name in _INVENTORY_TABLES:
            _inventory_row(snap, table_name, row, ref)
        elif table_name in _COPY_TABLES:
            _copy_row(snap, table_name, row, ref)
        else:
            snap.table.note_parse(snap.src, "sql-unknown-table", 0, 0, table_name)
    return count


def _read_scope(db: sqlite3.Connection, snap: _Snapshot) -> int:
    """Turn snapshot_scope rows into FULL coverage facts; returns the number of rows."""
    count = 0
    for row in _dict_rows(db, "select * from snapshot_scope"):
        ref = f"{snap.src.path}:snapshot_scope"
        snap.table.cover(snap.src, row["origin_system"], "snapshot_scope", row["captured_at"], "FULL", ref)
        count += 1
    return count


def _cover_unscoped_dump(snap: _Snapshot) -> None:
    """A dump without snapshot_scope proves little: sample coverage per (system, collection) plus replica drift."""
    src = snap.src
    seen = collections.Counter((system, collection) for system, _category, collection in snap.primary.values())
    for (system, collection), count in seen.items():
        ref = f"{src.path}:{collection}:{count}rows"
        snap.table.cover(src, system, "primary_table_has_collection", src.captured_at, "SAMPLE", ref)
    # A record present in a replica but missing from the primary was deleted there: explicit absence observation.
    for table_name, rows in snap.replicas.items():
        for rid, (system, category, _collection) in rows.items():
            if rid not in snap.primary:
                extras = {"table": "primary", "missing_in_primary_but_in": table_name}
                ref = f"{src.path}:primary-vs-{table_name}"
                snap.table.add(
                    src, src.captured_at, rid, system, category, "ABSENT", ref, [], "absence_vs_replica", extras
                )


def _read_dump(db: sqlite3.Connection, snap: _Snapshot) -> int:
    """Observe all tables of the executed dump; returns the total number of rows read."""
    names = [r[0] for r in db.execute("select name from sqlite_master where type='table'")]
    n_rows = _read_scope(db, snap) if "snapshot_scope" in names else 0
    has_scope = n_rows > 0
    n_rows += sum(_read_table(db, snap, name) for name in names if name != "snapshot_scope")
    if not has_scope:
        _cover_unscoped_dump(snap)
    for name in names:
        if name in _COPY_TABLES:
            system, _category = _copy_table_home(name)
            snap.table.cover(snap.src, system, "table_dump", snap.src.captured_at, "FULL", f"{snap.src.path}:{name}")
    return n_rows


def parse_sql(table: Table, src: Source) -> None:
    """Parse one SQL snapshot dump into observations and coverage; parse stats compare rows with INSERT counts."""
    with open(src.path, encoding="utf8") as handle:
        text = handle.read()
    insert_lines, n_inserts = _scan_inserts(text)
    db = sqlite3.connect(":memory:")
    try:
        db.executescript(text)
    except Exception as exc:  # a dump the engine rejects is reported, not fatal
        table.note_parse(src, "sql", n_inserts, 0, "ERROR " + str(exc))
        db.close()
        return
    topology = _TOPOLOGY_RE.search(text)
    snap = _Snapshot(table, src, topology.group(1) if topology else None, insert_lines)
    n_rows = _read_dump(db, snap)
    db.close()
    note = "ok" if n_rows == n_inserts else f"rows {n_rows} != inserts {n_inserts}"
    table.note_parse(src, "sql", n_inserts, n_rows, note)
