"""In-memory view of the observations database (evidence table, activity stream, catalog edges, coverage)."""

from __future__ import annotations

import collections
import sqlite3
from contextlib import closing
from typing import Any

from .ingest import DB

Row = dict[str, Any]


class Store:
    """All tables of observations.db, loaded once and indexed for the linking and conclusion stages."""

    def __init__(self, db_path: str | None = None) -> None:
        with closing(sqlite3.connect(db_path or DB)) as db:
            db.row_factory = sqlite3.Row
            self._load_observations(db)
            self._load_activity(db)
            self.cov: list[Row] = [
                dict(r) for r in db.execute("select * from coverage where level in ('FULL','EMPTY')")
            ]
            self.fcap: dict[str, str] = {
                r["file_id"]: r["file_captured_at"]
                for r in db.execute("select distinct file_id,file_captured_at from observation")
            }

    def captured_at(self, file_id: str, default: str) -> str:
        """Capture time of an evidence file, or `default` when no observation came from it."""
        return self.fcap.get(file_id, default)

    def _load_observations(self, db: sqlite3.Connection) -> None:
        self.obs: dict[Any, Row] = {}
        for r in db.execute("select * from observation"):
            self.obs[r["obs_id"]] = dict(r, ids=[])
        for r in db.execute("select * from obs_ident"):
            self.obs[r["obs_id"]]["ids"].append((r["id_type"], r["value"], r["role"]))
        self.by_rid: dict[Any, list[Row]] = collections.defaultdict(list)
        for o in self.obs.values():
            self.by_rid[o["resource_id"]].append(o)

    def _load_activity(self, db: sqlite3.Connection) -> None:
        self.act: list[Row] = [dict(r) for r in db.execute("select * from activity order by event_time")]
        self.act_by_rid: dict[Any, list[Row]] = collections.defaultdict(list)
        for a in self.act:
            self.act_by_rid[a["resource_id"]].append(a)
        self.edges: list[Row] = [dict(r) for r in db.execute("select * from activity_edge")]
        self.edges_by_act: dict[Any, list[Row]] = collections.defaultdict(list)
        for e in self.edges:
            self.edges_by_act[e["activity_id"]].append(e)
