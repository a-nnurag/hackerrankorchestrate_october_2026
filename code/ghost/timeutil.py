"""Timestamp parsing and resource-id helpers shared by the linking modules."""

from __future__ import annotations

from datetime import datetime

TS_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def parse_ts(text: str) -> datetime:
    """Parse a UTC timestamp such as 2026-09-15T11:44:55Z."""
    return datetime.strptime(text, TS_FORMAT)


def format_ts(moment: datetime) -> str:
    """Format a datetime the way the data stores timestamps (lexicographically comparable)."""
    return moment.strftime(TS_FORMAT)


def resource_type(rid: str) -> str:
    """Resource type prefix of an id: search_17 -> search."""
    return rid.rsplit("_", 1)[0]
