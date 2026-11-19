"""SQLite writer: schema, observation/coverage inserts, activity stream with its identifier edges, indexes."""

from __future__ import annotations

import os
import re
import sqlite3
from collections.abc import Iterator

from .identifiers import idents_from_text
from .table import Table
from .vocab import RID_FIND

_SCHEMA = """
create table observation(obs_id integer primary key, file_id text, file_captured_at text, observed_at text,
   observed_at_src text, resource_id text, system_id text, category text, state text, source_ref text, kind text,
   extras text);
create table obs_ident(obs_id int, id_type text, value text, role text);
create table coverage(file_id text, system_id text, scope_kind text, scope_time text, level text, source_ref text);
create table parse_stats(file_id text, path text, fmt text, items int, parsed int, note text);
create table unparsed(file_id text, source_ref text, text text);
create table activity(activity_id text primary key, event_time text, event_type text, source_system text,
   target_system text, resource_id text, reported_result text, details text);
create table activity_edge(activity_id text, event_time text, resource_id text, id_type text, value text,
   edge_kind text);
"""
_INDEXES = (
    "create index i_obs_rid on observation(resource_id)",
    "create index i_obs_file on observation(file_id)",
    "create index i_id_v on obs_ident(value)",
    "create index i_id_o on obs_ident(obs_id)",
)
_ATTACHMENT_OWNER_RE = re.compile(r"\(([\w.\-]+\.\w{2,4})\) belongs only to")


def activity_edges(row: dict[str, str]) -> Iterator[tuple[str, str, str, str, str, str]]:
    """Identifier edges mentioned in the free-text details of one activity row.

    Each edge is (activity_id, event_time, resource_id, id_type, value, edge_kind); a LINK_RESOURCE_IDENTITY event
    links identifiers to the resource, any other event merely mentions them.
    """
    details = row["details"]
    head = (row["activity_id"], row["event_time"], row["resource_id"])
    kind = "linked" if row["event_type"] == "LINK_RESOURCE_IDENTITY" else "mention"
    for id_type, value, _role in idents_from_text(details, "details"):
        yield (*head, id_type, value, kind)
    owner = _ATTACHMENT_OWNER_RE.search(details)
    if owner:
        yield (*head, "file", owner.group(1).lower(), "attachment_owner")
    for other in RID_FIND.findall(details):
        if other != row["resource_id"]:
            yield (*head, "resource", other, "mention")


def write_db(db_path: str, table: Table, activity_rows: list[dict[str, str]]) -> None:
    """Create a fresh SQLite database at `db_path` holding the table and the activity stream."""
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    if os.path.exists(db_path):
        os.remove(db_path)
    db = sqlite3.connect(db_path)
    db.executescript(_SCHEMA)
    db.executemany("insert into observation values (?,?,?,?,?,?,?,?,?,?,?,?)", table.obs)
    db.executemany("insert into obs_ident values (?,?,?,?)", table.ids)
    db.executemany("insert into coverage values (?,?,?,?,?,?)", table.cov)
    db.executemany("insert into parse_stats values (?,?,?,?,?,?)", table.parse)
    db.executemany("insert into unparsed values (?,?,?)", table.unparsed)
    columns = ("activity_id", "event_time", "event_type", "source_system", "target_system", "resource_id")
    for row in activity_rows:
        values = [row[c] for c in columns] + [row["reported_result"], row["details"]]
        db.execute("insert into activity values (?,?,?,?,?,?,?,?)", values)
        db.executemany("insert into activity_edge values (?,?,?,?,?,?)", activity_edges(row))
    for statement in _INDEXES:
        db.execute(statement)
    db.commit()
    db.close()
