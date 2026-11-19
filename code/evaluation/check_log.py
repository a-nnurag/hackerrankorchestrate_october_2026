"""Check log.txt (the submitted chat transcript) against the format required by AGENTS.md section 5.

    python code/evaluation/check_log.py [log.txt] [--trace SESSION.jsonl] [--index]

Format rules checked
  header         "## [ISO-8601 UTC] title", title at most 80 characters
  per-turn       "User Prompt (verbatim, secrets redacted):", "Agent Response Summary:" (2 to 5 sentences),
                 "Actions:" with bullets, "Context:" with exactly one populated tool=, model=, branch=, repo_root=,
                 worktree=, parent_agent= each
  tool / model   tool is a real harness name, model starts with "claude-" (never unknown, generic or a placeholder)
  session start  one SESSION START entry with tool, model, repo root, branch, worktree, parent agent, language
  safety         no API keys or account e-mail addresses
  order          timestamps never decrease
With --trace (the Claude Code session .jsonl) the real time of every human message is read from it, the entry
timestamps are compared with those times, and --index prints a Markdown table of the real turns.
Entries written before the "LOG CORRECTION" entry are legacy: the correction records their approximate timestamps and
their format deviations (the log is append-only, so they were not edited). Their problems are listed as
"documented", only entries from the correction on must pass; exit code 1 when one of those breaks a rule.
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

HEADER = re.compile(r"^## \[(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ)\] (.*)$", re.M)
SECTIONS = ["User Prompt (verbatim, secrets redacted):", "Agent Response Summary:", "Actions:", "Context:"]
CONTEXT_KEYS = ["tool", "model", "branch", "repo_root", "worktree", "parent_agent"]
SESSION_KEYS = ["tool", "model", "Repo Root", "Branch", "Worktree", "Parent Agent", "Language", "Time Remaining"]
SECRET = re.compile(r"gsk_[A-Za-z0-9]{8,}|sk-[A-Za-z0-9]{16,}|AKIA[0-9A-Z]{12,}|[A-Za-z0-9._%+-]+@gmail\.com")
GENERIC_TOOLS = {"", "ai", "unknown", "<exact_harness_or_coding_agent_name>"}


def parse_entries(text):
    """-> list of dicts: ts, title, body, line (1-based line of the header)."""
    marks = list(HEADER.finditer(text))
    out = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        out.append(
            {
                "ts": m.group(1),
                "title": m.group(2),
                "body": text[m.end() : end],
                "line": text.count("\n", 0, m.start()) + 1,
            }
        )
    return out


def sentences(text):
    """Rough sentence count: terminal punctuation followed by space or end."""
    return len([s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()])


def section(body, name):
    """Text of one section, up to the next known section header."""
    start = body.find(name)
    if start < 0:
        return None
    rest = body[start + len(name) :]
    nxt = [rest.find(s) for s in SECTIONS + ["Notes:"] if s != name and rest.find(s) >= 0]
    return rest[: min(nxt)] if nxt else rest


def kv(text, key):
    return re.findall(rf"^\s*{re.escape(key)}\s*[=:]\s*(.*)$", text, re.M)


def _single_value(text, key):
    """The one populated value of ``key``, or None when it is missing, empty or repeated."""
    vals = kv(text, key)
    return vals[0].strip() if len(vals) == 1 and vals[0].strip() else None


def _check_session_start(body):
    return [f"session start: {key} missing or repeated" for key in SESSION_KEYS if _single_value(body, key) is None]


def _check_summary_and_actions(body):
    problems = []
    summary = section(body, "Agent Response Summary:")
    if summary is not None and not 2 <= sentences(summary) <= 5:
        problems.append(f"summary has {sentences(summary)} sentences (2 to 5 required)")
    actions = section(body, "Actions:")
    if actions is not None and not re.search(r"^\s*[*-] ", actions, re.M):
        problems.append("Actions has no bullet")
    return problems


def _check_context(body):
    context = section(body, "Context:") or ""
    problems = [
        f"context: {key}= missing, empty or repeated" for key in CONTEXT_KEYS if _single_value(context, key) is None
    ]
    tool = (kv(context, "tool") or [""])[0].strip()
    model = (kv(context, "model") or [""])[0].strip()
    if tool.lower() in GENERIC_TOOLS:
        problems.append(f"tool={tool!r} is generic")
    if not model.startswith("claude-"):
        problems.append(f"model={model!r} is not an exact model identifier")
    return problems


def check_entry(e):
    """-> list of problems for one entry."""
    title, body = e["title"], e["body"]
    problems = [f"title is {len(title)} characters (limit 80)"] if len(title) > 80 else []
    if title.strip() == "SESSION START":
        return problems + _check_session_start(body)
    problems += [f"missing section {name!r}" for name in SECTIONS if name not in body]
    return problems + _check_summary_and_actions(body) + _check_context(body)


def human_turns(trace_path):
    """Real (timestamp, text) of every human message in a Claude Code session file."""
    turns = []
    for line in Path(trace_path).read_text(encoding="utf-8").splitlines():
        if not line.startswith("{"):
            continue
        d = json.loads(line)
        if d.get("type") != "user" or (d.get("origin") or {}).get("kind") != "human":
            continue
        content = d["message"]["content"]
        text = (
            content if isinstance(content, str) else " ".join(p.get("text", "") for p in content if isinstance(p, dict))
        )
        text = re.sub(
            r"<system-reminder>.*?</system-reminder>|<ide_[a-z_]+>.*?</ide_[a-z_]+>", "", text, flags=re.S
        ).strip()
        turns.append((d["timestamp"][:19] + "Z", re.sub(r"\s+", " ", text)))
    return turns


def parse_ts(ts):
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("log", nargs="?", default=str(Path(__file__).resolve().parents[2] / "log.txt"))
    ap.add_argument("--trace", default=None)
    ap.add_argument("--index", action="store_true")
    return ap.parse_args()


def report_entry_problems(entries, cut):
    """Print every entry problem; -> (problems that count, legacy deviations that are documented)."""
    counted = documented = 0
    for i, e in enumerate(entries):
        for p in check_entry(e):
            legacy = i < cut
            documented += legacy
            counted += not legacy
            print(
                f"  line {e['line']:>5} [{e['ts']}] {e['title'][:50]!r}: {p}"
                + ("   (documented in the correction entry)" if legacy else "")
            )
    return counted, documented


def report_order_and_secrets(text, entries, cut):
    """-> number of secret leaks plus timestamp reversals after the correction entry."""
    bad = 0
    for m in SECRET.finditer(text):
        print(f"FAIL possible secret or account address in the log: {m.group(0)[:12]}...")
        bad += 1
    stamps = [e["ts"] for e in entries]
    for a, b in zip(stamps[cut:], stamps[cut + 1 :], strict=False):
        if b < a:
            print(f"FAIL timestamp goes backwards after the correction: {a} then {b}")
            bad += 1
    return bad


def report_trace(entries, trace, show_index):
    """Compare entry timestamps with the real human message times of the session file."""
    turns = human_turns(trace)
    first_real, first_log = parse_ts(turns[0][0]), parse_ts(entries[0]["ts"])
    print(
        f"real first human message {turns[0][0]}; first log entry {entries[0]['ts']} "
        f"({abs((first_real - first_log).total_seconds()) / 3600:.1f} h apart)"
    )
    far = sum(
        1 for e in entries if min(abs((parse_ts(e["ts"]) - parse_ts(t)).total_seconds()) for t, _ in turns) > 3600
    )
    print(f"{far} of {len(entries)} entry timestamps are more than an hour from every real human message")
    if show_index:
        print("\n| # | real time (UTC) | message |\n|---|---|---|")
        for i, (t, msg) in enumerate(turns, 1):
            print(f"| {i} | {t} | {msg[:90].replace('|', '/')} |")


def main():
    args = parse_args()
    text = Path(args.log).read_text(encoding="utf-8")
    entries = parse_entries(text)
    print(f"{args.log}: {len(entries)} entries")
    bad = 0
    if len([e for e in entries if e["title"].strip() == "SESSION START"]) != 1:
        print("FAIL expected exactly one SESSION START entry")
        bad += 1
    cut = next((i for i, e in enumerate(entries) if e["title"].startswith("LOG CORRECTION")), 0)
    counted, documented = report_entry_problems(entries, cut)
    bad += counted + report_order_and_secrets(text, entries, cut)
    print(
        f"{documented} legacy deviation(s) documented, {cut} legacy entries, "
        f"{len(entries) - cut} entries checked strictly"
    )
    if args.trace:
        report_trace(entries, args.trace, args.index)
    print("\nLOG OK" if not bad else f"\n{bad} PROBLEM(S) FOUND")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
