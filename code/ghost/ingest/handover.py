"""Parser for the plain-text handover notes: one `- time | system | resource | type | result | subject` line each."""

from __future__ import annotations

import re

from .lookup import emit_lookup_record
from .table import Source, Table

_HANDOVER_RE = re.compile(r"^- (\S+) \| (\w+) \| (\S+) \| (\w+) \| (\w+) \| (.*)$")


def parse_handover(table: Table, src: Source) -> None:
    """Parse a handover note; lines not starting with "- " are prose and ignored, malformed entries are kept."""
    items = parsed = 0
    with open(src.path, encoding="utf8") as handle:
        for number, line in enumerate(handle, 1):
            line = line.rstrip("\n")
            if not line.startswith("- "):
                continue
            items += 1
            match = _HANDOVER_RE.match(line)
            if not match:
                table.skip(src, f"{src.path}:{number}", line)
                continue
            recorded_at, system, rid, record_type, result, subject = match.groups()
            rec = {
                "recorded_at": recorded_at,
                "system": system,
                "resource_id": rid,
                "record_type": record_type,
                "result": result,
                "subject_reference": subject,
            }
            emit_lookup_record(table, src, rec, f"{src.path}:{number}", "subject_reference")
            parsed += 1
    table.note_parse(src, "txt", items, parsed, "ok" if items == parsed else "partial")
