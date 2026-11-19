"""Physical line formats of the service logs, normalised to (format, timestamp, field dict).

Every log line starts with an ISO timestamp followed by one of six layouts (JSON object, bracketed, pipe separated,
cloud key=value with a quoted message, RFC 5424 syslog, plain logfmt). All layouts are reduced to the same fields:
`trace_id`, `level`, `service`, `event` plus whatever key=value pairs the line carried.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable

LogFields = dict[str, str | None]

_KEY_VALUE_RE = re.compile(r'([A-Za-z_]\w*)=("(?:[^"\\]|\\.)*"|\S+)')
_TIMESTAMP_RE = re.compile(r"\d{4}-\d\d-\d\dT[\d:]{8}Z$")
_BRACKET_RE = re.compile(r"\[(\w+)\] \[(\w+)\] \[([^\]]+)\] (\w+): ?(.*)")
_CLOUD_MESSAGE_RE = re.compile(r'message="(.*)"\s*$')
_SYSLOG_RE = re.compile(r"<\d+>1 (\S+) (\S+) (\S+) - - (.*)$")
_EVENT_PAIR_RE = re.compile(r"\bevent=")
_PIPE_PARTS = 6


def key_values(text: str) -> LogFields:
    """key=value pairs of a log message; quoted values lose their quotes and escaped quotes."""
    pairs: LogFields = {}
    for key, value in _KEY_VALUE_RE.findall(text):
        pairs[key] = value[1:-1].replace('\\"', '"') if value.startswith('"') else value
    return pairs


def _parse_json(line: str, rest: str) -> LogFields | None:
    fields: LogFields = {k: (v if isinstance(v, str) else str(v)) for k, v in json.loads(rest).items()}
    fields["trace_id"] = fields.get("trace_id")
    fields["level"] = fields.get("severity")
    return fields


def _parse_bracket(line: str, rest: str) -> LogFields | None:
    match = _BRACKET_RE.match(rest)
    if not match:
        return None
    fields = key_values(match.group(5))
    fields.update(level=match.group(1), service=match.group(2), trace_id=match.group(3), event=match.group(4))
    return fields


def _parse_pipe(line: str, rest: str) -> LogFields | None:
    parts = line.split(" | ", _PIPE_PARTS - 1)
    if len(parts) < _PIPE_PARTS:
        return None
    fields = key_values(parts[5])
    fields.update(level=parts[1], service=parts[2], trace_id=parts[3], event=parts[4])
    return fields


def _parse_cloud(line: str, rest: str) -> LogFields | None:
    match = _CLOUD_MESSAGE_RE.search(rest)
    if not match:
        return None
    fields = key_values(match.group(1).replace('\\"', '"'))
    head = key_values(rest[: match.start()])
    fields["trace_id"] = head.get("requestId")
    fields["level"] = head.get("level")
    fields["service"] = head.get("function")
    return fields


def _parse_syslog(line: str, rest: str) -> LogFields | None:
    match = _SYSLOG_RE.match(rest)
    if not match:
        return None
    fields = key_values(match.group(4))
    fields.update(service=match.group(2), trace_id=match.group(3))
    return fields


def _parse_logfmt(line: str, rest: str) -> LogFields | None:
    return key_values(rest)


# (format name, "does this layout apply to the text after the timestamp?", parser). The first layout that applies
# decides: if its parser rejects the line, the line is unparsed and later layouts are not tried.
_FORMATS: tuple[tuple[str, Callable[[str], object], Callable[[str, str], LogFields | None]], ...] = (
    ("json", lambda rest: rest.startswith("{"), _parse_json),
    ("bracket", lambda rest: rest.startswith("[") and _BRACKET_RE.match(rest), _parse_bracket),
    ("pipe", lambda rest: rest.startswith("| "), _parse_pipe),
    ("cloud", lambda rest: "requestId=" in rest and 'message="' in rest, _parse_cloud),
    ("syslog", _SYSLOG_RE.match, _parse_syslog),
    ("logfmt", _EVENT_PAIR_RE.search, _parse_logfmt),
)


def parse_log_line(line: str) -> tuple[str, str, LogFields] | None:
    """Parse one log line into (format name, timestamp, fields); None when it matches no known layout."""
    parts = line.split(" ", 1)
    if len(parts) < 2:
        return None
    timestamp, rest = parts
    if not _TIMESTAMP_RE.match(timestamp):
        return None
    for name, applies, parse in _FORMATS:
        if applies(rest):
            fields = parse(line, rest)
            return None if fields is None else (name, timestamp, fields)
    return None
