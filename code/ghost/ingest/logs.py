"""Parser for service log files: per-line parsing, trace-level identifiers, event observations and stream coverage."""

from __future__ import annotations

import collections
from dataclasses import dataclass, field

from .log_events import HANDLERS, new_draft, own_line_identifiers
from .log_lines import LogFields, parse_log_line
from .lookup import emit_lookup_record
from .table import Source, Table
from .vocab import classify, res_of

# Fields whose value names the subject; they identify every line of the same trace, not only their own.
_TRACE_KEY_FIELDS = (
    "lookup_key",
    "match_key",
    "subject_key",
    "scan_key",
    "subject_ref",
    "owner_key",
    "correlation_key",
    "matched_value",
)
# Export bookkeeping events carry the totals the log claims; (log field, total it fills). Later entries win.
_TOTAL_EVENTS = ("export_started", "export_completed")
_TOTAL_FIELDS = (
    ("expected_source_events", "expected_source_events"),
    ("target_count", "target_count"),
    ("dropped_auxiliary", "dropped"),
    ("dropped", "dropped"),
)


@dataclass
class _Scan:
    """Result of the first pass over a log file."""

    parsed: list[tuple[int, str, LogFields]] = field(default_factory=list)  # (line number, timestamp, fields)
    n_lines: int = 0
    formats: collections.Counter = field(default_factory=collections.Counter)
    trace_idents: dict[str, list] = field(default_factory=lambda: collections.defaultdict(list))
    totals: dict[str, int | None] = field(
        default_factory=lambda: {"expected_source_events": None, "target_count": None, "dropped": None}
    )

    @property
    def n_ok(self) -> int:
        return len(self.parsed)


def _read_totals(totals: dict[str, int | None], fields: LogFields) -> None:
    if fields.get("event") not in _TOTAL_EVENTS:
        return
    for log_field, total in _TOTAL_FIELDS:
        value = fields.get(log_field)
        if value is not None:
            totals[total] = int(value)


def _remember_trace_identifiers(scan: _Scan, fields: LogFields) -> None:
    trace = fields.get("trace_id")
    if not trace:
        return
    for key in _TRACE_KEY_FIELDS:
        found = classify(fields.get(key))
        if found and found[0] != "resource":
            scan.trace_idents[trace].append((found[0], found[1], "trace:" + key))


def _scan_file(table: Table, src: Source) -> _Scan:
    scan = _Scan()
    with open(src.path, encoding="utf8") as handle:
        lines = handle.read().split("\n")
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        scan.n_lines += 1
        try:
            result = parse_log_line(line)
        except Exception:  # a line that breaks its own layout (bad JSON, ...) counts as unparsed
            result = None
        if result is None:
            table.skip(src, f"{src.path}:{number}", line[:200])
            continue
        fmt, timestamp, fields = result
        scan.formats[fmt] += 1
        scan.parsed.append((number, timestamp, fields))
        _remember_trace_identifiers(scan, fields)
        _read_totals(scan.totals, fields)
    return scan


def _is_start_marker(event: str) -> bool:
    """Start-of-operation events carry no state."""
    return event.endswith("_started") or event.endswith("_scan_started")


def _emit_events(table: Table, src: Source, scan: _Scan) -> tuple[int, int]:
    """Add one observation per resource event; returns (observations added, unmodelled events)."""
    n_obs = n_unmodelled = 0
    for number, timestamp, fields in scan.parsed:
        event = fields.get("event")
        rid = fields.get("resource_id")
        if not rid or event is None or _is_start_marker(event):
            continue
        ref = f"{src.path}:{number}"
        if event == "record_lookup":
            rec = {
                "recorded_at": timestamp,
                "system": fields.get("system"),
                "resource_id": rid,
                "record_type": fields.get("record_type"),
                "result": fields.get("result"),
                "subject_reference": fields.get("subject_reference"),
            }
            emit_lookup_record(table, src, rec, ref, "subject_reference")
        elif event in HANDLERS:
            trace = fields.get("trace_id")
            idents = list(scan.trace_idents.get(trace, [])) if trace else []
            idents += own_line_identifiers(fields)
            draft = new_draft(rid, event, fields)
            table.add(src, timestamp, rid, None, draft.category, draft.state, ref, idents, draft.kind, draft.extras)
        else:
            n_unmodelled += 1
            table.skip(src, ref, f"unmodelled event with resource_id: {event}")
            continue
        n_obs += 1
    return n_obs, n_unmodelled


def _stream_level(dropped: int | None, expected: int | None) -> str:
    """How complete the log stream is: nothing dropped and a known expected size means COMPLETE."""
    if dropped in (0, None) and expected is not None:
        return "COMPLETE"
    return "DROPPED_AUX" if dropped else "UNKNOWN"


def _emit_coverage(table: Table, src: Source, scan: _Scan) -> None:
    totals = scan.totals
    expected = totals["expected_source_events"] or totals["target_count"]
    table.cover(
        src,
        "ALL_LOGGED_SERVICES",
        "log_stream",
        src.captured_at,
        _stream_level(totals["dropped"], expected),
        f"{src.path}:expected={expected}:dropped={totals['dropped']}:lines={scan.n_lines}",
    )
    mentions: collections.Counter = collections.Counter()
    for _number, _timestamp, fields in scan.parsed:
        implied = res_of(fields.get("resource_id"))
        if implied:
            mentions[implied[0]] += 1
    for system, count in mentions.items():
        table.cover(src, system, "log_mentions", src.captured_at, "LOOKUPS", f"{src.path}:{count} events")


def parse_log(table: Table, src: Source) -> None:
    """Parse one log file into event observations, a stream-completeness fact and per-service mention counts."""
    scan = _scan_file(table, src)
    n_obs, n_unmodelled = _emit_events(table, src, scan)
    _emit_coverage(table, src, scan)
    if scan.n_lines == scan.n_ok:
        note = "ok"
    else:
        note = (
            f"{scan.n_lines - scan.n_ok} unparsed; formats={dict(scan.formats)}; obs={n_obs}; unmodelled={n_unmodelled}"
        )
    table.note_parse(src, "log:" + "/".join(scan.formats), scan.n_lines, scan.n_ok, note)
