"""Parser for JSON evidence files; each distinct file layout has its own small function."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from .identifiers import has_direct, ident_from_value, idents_from_record
from .lookup import emit_lookup_record
from .states import analytics_state, state_for_record
from .table import Source, Table
from .vocab import category_of


# ---------------------------------------------------------------- layout 1: snapshot bundle
def _snapshot_bundle(table: Table, src: Source, doc: dict) -> int:
    """{"snapshots": [{data_store, collection, captured_at, records}]}: one coverage fact per snapshot."""
    count = 0
    for index, snapshot in enumerate(doc["snapshots"]):
        system = snapshot["data_store"]
        collection = snapshot["collection"]
        captured_at = snapshot["captured_at"]
        records = snapshot["records"]
        table.cover(
            src,
            system,
            "bundle_snapshot",
            captured_at,
            "EMPTY" if not records else "SAMPLE",
            f"{src.path}:snapshots[{index}]:{collection}:{len(records)}rec",
        )
        for rec_index, rec in enumerate(records):
            count += 1
            ref = f"{src.path}:snapshots[{index}].records[{rec_index}]"
            if collection == "operational_record_history":
                emit_lookup_record(table, src, rec, ref, "lookup_value")
                continue
            rid = rec.get("resource_id")
            category = category_of(collection, rid)
            state, extras = state_for_record(category, rec)
            extras.update({"collection": collection, "bundle_exported_at": doc["exported_at"], "store": system})
            table.add(src, captured_at, rid, system, category, state, ref, idents_from_record(rec), "record", extras)
    return count


# ---------------------------------------------------------------- layout 2: per-service lookup exports
def _add_service_row(
    table: Table,
    src: Source,
    row: dict,
    ref: str,
    system: str,
    category: str,
    state: str,
    idents: list,
    extras: dict[str, Any],
    kind: str = "record",
) -> None:
    table.add(src, row.get("observed_at"), row["resource_id"], system, category, state, ref, idents, kind, extras)


def _profile_lookups(table: Table, src: Source, system: str, rec: dict, ref: str) -> None:
    if rec.get("status_code") == 404 or not rec.get("profile"):
        extras = {"status": rec.get("status_code")}
        _add_service_row(table, src, rec, ref, system, "USER_PROFILE", "ABSENT", [], extras, "lookup_404")
    else:
        idents = idents_from_record(rec["profile"])
        _add_service_row(table, src, rec, ref, system, "USER_PROFILE", "PRESENT", idents, {"status": 200})


def _index_queries(table: Table, src: Source, system: str, rec: dict, ref: str) -> None:
    hits = rec["hits"]
    docs = hits.get("documents", [])
    query_idents = ident_from_value(rec.get("query"), "lookup")
    if hits.get("total", 0) == 0 or not docs:
        _add_service_row(
            table, src, rec, ref, system, "SEARCH_INDEX_ENTRY", "ABSENT", query_idents, {}, "lookup_zero_hits"
        )
    for doc in docs:
        # a hit may carry its own resource id; otherwise it is attributed to the query row
        rid = doc.get("resource_id", rec["resource_id"])
        idents = idents_from_record(doc) + query_idents
        extras = {"total": hits["total"]}
        table.add(
            src, rec.get("observed_at"), rid, system, "SEARCH_INDEX_ENTRY", "PRESENT", ref, idents, "record", extras
        )


def _analytics_profiles(table: Table, src: Source, system: str, rec: dict, ref: str) -> None:
    state = analytics_state(rec)
    _add_service_row(table, src, rec, ref, system, "ANALYTICS_PROFILE", state, idents_from_record(rec), {})


def _restore_entries(table: Table, src: Source, system: str, rec: dict, ref: str) -> None:
    allowed = bool(rec["restore_allowed"])
    state = "ACTIVE" if allowed else "BLOCKED"
    extras = {"restore_allowed": allowed}
    _add_service_row(table, src, rec, ref, system, "BACKUP_ARCHIVE", state, idents_from_record(rec), extras)


def _connectors(table: Table, src: Source, system: str, rec: dict, ref: str) -> None:
    enabled = bool(rec["enabled"])
    state = "ACTIVE" if enabled else "DISABLED"
    extras = {
        "enabled": enabled,
        "delivery": rec.get("last_delivery_status"),
        "connector": rec.get("connector_name"),
    }
    _add_service_row(table, src, rec, ref, system, "DATA_FLOW", state, idents_from_record(rec), extras)


def _exports(table: Table, src: Source, system: str, rec: dict, ref: str) -> None:
    _add_service_row(table, src, rec, ref, system, "USER_EXPORT", "PRESENT", idents_from_record(rec), {})


def _audit_records(table: Table, src: Source, system: str, rec: dict, ref: str) -> None:
    extras = {"event": rec.get("event_code"), "retention_until": rec.get("retention_until")}
    _add_service_row(table, src, rec, ref, system, "SECURITY_AUDIT_LOG", "PRESENT", idents_from_record(rec), extras)


def _tickets(table: Table, src: Source, system: str, rec: dict, ref: str) -> None:
    state = "IDENTIFIABLE" if has_direct(rec) else "REDACTED"
    _add_service_row(table, src, rec, ref, system, "SUPPORT_MESSAGE", state, idents_from_record(rec), {})


_SERVICE_SECTIONS: dict[str, Callable[[Table, Source, str, dict, str], None]] = {
    "profile_lookups": _profile_lookups,
    "index_queries": _index_queries,
    "profiles": _analytics_profiles,
    "restore_entries": _restore_entries,
    "connectors": _connectors,
    "exports": _exports,
    "audit_records": _audit_records,
    "tickets": _tickets,
}


def _service_exports(table: Table, src: Source, doc: dict) -> int:
    """{"service_exports": {system: {section: [records]}}}: lookups made against each service."""
    count = 0
    for system, sections in doc["service_exports"].items():
        for section, rows in sections.items():
            table.cover(
                src,
                system,
                "service_export_section",
                doc["exported_at"],
                "LOOKUPS",
                f"{src.path}:{system}.{section}:{len(rows)}",
            )
            for index, rec in enumerate(rows):
                count += 1
                ref = f"{src.path}:{system}.{section}[{index}]"
                handler = _SERVICE_SECTIONS.get(section)
                if handler:
                    handler(table, src, system, rec, ref)
                else:
                    table.skip(src, ref, "unknown section " + section)
    return count


# ---------------------------------------------------------------- layout 3: record-history lists
def _record_history(table: Table, src: Source, doc: dict) -> int:
    """{"records": [...], "record_count": n}: manifests, ledgers and connector configs of lookup rows."""
    for index, rec in enumerate(doc["records"]):
        emit_lookup_record(table, src, rec, f"{src.path}:records[{index}]", "subject_reference")
    return len(doc["records"])


# ---------------------------------------------------------------- layout 4: collection dumps
def _collection_dump(table: Table, src: Source, doc: dict) -> int:
    """{"collection": name, "records": [...], "captured_at": t}: analytics reports and export jobs."""
    collection = doc.get("collection")
    records = doc["records"]
    for index, rec in enumerate(records):
        rid = rec["resource_id"]
        category = category_of(collection, rid)
        state, extras = state_for_record(category, rec)
        extras["collection"] = collection
        ref = f"{src.path}:records[{index}]"
        table.add(src, doc["captured_at"], rid, None, category, state, ref, idents_from_record(rec), "record", extras)
    system = "analytics_platform" if collection == "customer_analytics_reports" else "export_service"
    table.cover(
        src,
        system,
        "collection_dump",
        doc["captured_at"],
        "SAMPLE" if records else "EMPTY",
        f"{src.path}:{collection}:{len(records)}",
    )
    return len(records)


def parse_json(table: Table, src: Source) -> None:
    """Parse one JSON evidence file, choosing the layout from its top-level keys."""
    with open(src.path, encoding="utf8") as handle:
        doc = json.load(handle)
    count = 0
    if "snapshots" in doc:
        count = _snapshot_bundle(table, src, doc)
    elif "service_exports" in doc:
        count = _service_exports(table, src, doc)
    elif doc.get("records") is not None and "record_count" in doc:
        count = _record_history(table, src, doc)
    elif doc.get("records") is not None:
        count = _collection_dump(table, src, doc)
    else:
        table.skip(src, src.path, "unknown json layout")
    table.note_parse(src, "json", count, count, "ok")
