"""In-memory observation table that the parsers fill and the SQLite writer persists."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from .identifiers import Identifier
from .vocab import res_of


@dataclass(frozen=True)
class Source:
    """One evidence file: manifest file id, absolute path and the time the snapshot was captured."""

    file_id: str
    path: str
    captured_at: str


@dataclass
class Table:
    """Collects observations, their identifiers, coverage facts, per-file parse stats and unparsed lines."""

    obs: list[tuple] = field(default_factory=list)
    ids: list[tuple] = field(default_factory=list)
    cov: list[tuple] = field(default_factory=list)
    parse: list[tuple] = field(default_factory=list)  # (file_id, path, format, items, parsed, note)
    unparsed: list[tuple] = field(default_factory=list)  # (file_id, source_ref, text)

    def add(
        self,
        src: Source,
        observed_at: str | None,
        rid: str | None,
        system: str | None,
        category: str | None,
        state: str | None,
        source_ref: str,
        idents: Iterable[Identifier] = (),
        kind: str = "record",
        extras: dict[str, Any] | None = None,
    ) -> int:
        """Append one observation (and its de-duplicated identifiers); returns its obs_id.

        Missing system/category are filled in from the resource-id prefix. When `observed_at` is absent the capture
        time of the file is used and the timestamp is marked as file-level instead of record-level.
        """
        obs_id = len(self.obs) + 1
        implied = res_of(rid) if rid else None
        if implied:
            system = system or implied[0]
            category = category or implied[1]
        self.obs.append(
            (
                obs_id,
                src.file_id,
                src.captured_at,
                observed_at or src.captured_at,
                "record" if observed_at else "file",
                rid,
                system,
                category,
                state,
                source_ref,
                kind,
                json.dumps(extras or {}, sort_keys=True),
            )
        )
        self.ids.extend((obs_id, *ident) for ident in dict.fromkeys(idents) if ident[1] not in (None, ""))
        return obs_id

    def cover(
        self, src: Source, system: str | None, scope_kind: str, scope_time: str, level: str, source_ref: str
    ) -> None:
        """Record what a file proves about one system (e.g. FULL, SAMPLE, EMPTY, LOOKUPS coverage)."""
        self.cov.append((src.file_id, system, scope_kind, scope_time, level, source_ref))

    def note_parse(self, src: Source, fmt: str, items: int, parsed: int, note: str) -> None:
        """Record how many items of a file were found and how many were understood."""
        self.parse.append((src.file_id, src.path, fmt, items, parsed, note))

    def skip(self, src: Source, source_ref: str, text: str) -> None:
        """Record a line or section that no parser understood."""
        self.unparsed.append((src.file_id, source_ref, text))
