"""Loader for the hand-made transcriptions of image/PDF evidence (code/ghost/manual/*.json)."""

from __future__ import annotations

import glob
import json
import os
from collections.abc import Callable

from .paths import MANUAL_DIR
from .table import Source, Table
from .vocab import digits, norm_email

_TEMPLATE_FILE_ID = "evidence_NN"  # the unfilled template: skipped

# transcription field -> (identifier type, normaliser)
_IDENTIFIER_FIELDS: tuple[tuple[str, str, Callable[[str], str]], ...] = (
    ("emails", "email", norm_email),
    ("user_ids", "user", lambda v: v),
    ("hashes", "hash", lambda v: v),
    ("phones", "phone", digits),
    ("names", "name", lambda v: v),
)


def _entry_identifiers(entry: dict) -> list[tuple[str, str, str]]:
    found = entry.get("identifiers", {})
    return [
        (id_type, normalise(value), "manual")
        for field_name, id_type, normalise in _IDENTIFIER_FIELDS
        for value in found.get(field_name, [])
    ]


def _load_entry(table: Table, src: Source, path: str, index: int, entry: dict) -> None:
    ref = f"{os.path.basename(path)}#{index}:{entry.get('locator', '')}"
    extras = {
        "confidence": entry.get("confidence"),
        "retention_until": entry.get("retention_until"),
        "retained_until": entry.get("retained_until"),
    }
    table.add(
        src,
        entry.get("observed_at"),
        entry["resource_id"],
        entry.get("system_id"),
        entry.get("category"),
        entry["state"],
        ref,
        _entry_identifiers(entry),
        "manual",
        extras,
    )
    # a screenshot of an empty result list proves absence for the systems it names
    for system in entry.get("absence_scope", []) or []:
        table.cover(src, system, "manual_absence_scope", src.captured_at, "MANUAL", f"{path}#{index}")


def load_manual(table: Table, manifest: dict[str, dict[str, str]]) -> int:
    """Add the observations of every transcription whose evidence file is in the manifest; returns their count."""
    count = 0
    for path in sorted(glob.glob(os.path.join(MANUAL_DIR, "*.json"))):
        with open(path, encoding="utf8") as handle:
            doc = json.load(handle)
        if not doc.get("entries") or doc.get("file_id", _TEMPLATE_FILE_ID) == _TEMPLATE_FILE_ID:
            continue
        captured_at = next((r["captured_at"] for r in manifest.values() if r["file_id"] == doc["file_id"]), None)
        if captured_at is None:  # the transcription belongs to an evidence file that is not in this manifest
            continue
        src = Source(doc["file_id"], path, captured_at)
        for index, entry in enumerate(doc["entries"]):
            _load_entry(table, src, path, index, entry)
            count += 1
    return count
