"""Observation rows shaped as record_type / result / subject lookups (ledgers, handover notes, log lookups)."""

from __future__ import annotations

from typing import Any

from .table import Source, Table
from .vocab import RECORD_TYPE_CATEGORIES, classify, res_of

# Lookup vocabulary -> observation state; every other result already is a state name.
_RESULT_STATE = {"FOUND": "PRESENT", "NOT_FOUND": "ABSENT"}


def emit_lookup_record(table: Table, src: Source, rec: dict[str, Any], ref: str, subject_key: str) -> None:
    """Add one observation for a lookup row.

    `rec` carries result, resource_id and optionally record_type, system, recorded_at/observed_at; the value stored
    under `subject_key` becomes the subject identifier ("note" when it is free text such as "no direct identifier").
    """
    raw_result = rec["result"]
    state = _RESULT_STATE.get(raw_result, raw_result)
    record_type = rec.get("record_type")
    implied = res_of(rec["resource_id"])
    category = record_type if record_type in RECORD_TYPE_CATEGORIES else (implied[1] if implied else None)
    value = rec.get(subject_key)
    idents = []
    if value is not None:
        found = classify(value)
        idents.append((found[0], found[1], "subject") if found else ("note", str(value), "subject"))
    kind = "lookup_not_found" if state == "ABSENT" else "record"
    table.add(
        src,
        rec.get("recorded_at") or rec.get("observed_at"),
        rec["resource_id"],
        rec.get("system"),
        category,
        state,
        ref,
        idents,
        kind,
        {"raw_result": raw_result, "record_type": record_type},
    )
