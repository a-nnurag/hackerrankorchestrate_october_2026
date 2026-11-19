"""Unified evidence ingestion: every participant-facing file in the dataset becomes rows of one SQLite table.

Only dataset/ files are read, plus the committed transcriptions of the images/PDFs (code/ghost/manual/). Entry point:
`build()`. Environment: GHOST_DATASET (dataset directory) and GHOST_CACHE_DIR (where observations.db is written).
"""

from __future__ import annotations

import csv
import os
import time
from collections.abc import Callable
from typing import Any

from .handover import parse_handover
from .json_exports import parse_json
from .logs import parse_log
from .manual import load_manual
from .paths import DB, DS, MANUAL_DIR, REPO
from .sql_snapshot import parse_sql
from .store import write_db
from .table import Source, Table
from .vocab import digits, norm_email, res_of, sha

__all__ = ["DB", "DS", "MANUAL_DIR", "REPO", "build", "digits", "norm_email", "res_of", "sha"]

_PARSERS: dict[str, Callable[[Table, Source], None]] = {
    "sql": parse_sql,
    "json": parse_json,
    "log": parse_log,
    "txt": parse_handover,
}


def _read_csv(name: str) -> list[dict[str, str]]:
    with open(os.path.join(DS, name), encoding="utf8") as handle:
        return list(csv.DictReader(handle))


def _parse_files(table: Table, manifest: dict[str, dict[str, str]]) -> None:
    """Run the parser matching each evidence file's extension, in file-id order."""
    for path, row in sorted(manifest.items(), key=lambda item: item[1]["file_id"]):
        full_path = os.path.join(DS, path)
        src = Source(row["file_id"], full_path, row["captured_at"])
        extension = path.rsplit(".", 1)[-1].lower()
        parser = _PARSERS.get(extension)
        if parser:
            parser(table, src)
        else:  # images and PDFs: covered by load_manual()
            table.note_parse(src, extension, 0, 0, "NEEDS_MANUAL_TRANSCRIPTION")


def build(db_path: str | None = None) -> dict[str, Any]:
    """Ingest the whole dataset into a fresh SQLite database.

    Args:
        db_path: where to write the database (default: DB).

    Returns:
        Statistics: runtime_s, n_obs, n_ident, n_cov, unparsed (count), manual_loaded (count) and db (path).
    """
    target = db_path or DB
    started = time.time()
    manifest = {row["file_path"]: row for row in _read_csv("evidence_files.csv")}
    table = Table()
    _parse_files(table, manifest)
    n_manual = load_manual(table, manifest)
    write_db(target, table, _read_csv("system_activity.csv"))
    return {
        "runtime_s": time.time() - started,
        "n_obs": len(table.obs),
        "n_ident": len(table.ids),
        "n_cov": len(table.cov),
        "unparsed": len(table.unparsed),
        "manual_loaded": n_manual,
        "db": target,
    }
