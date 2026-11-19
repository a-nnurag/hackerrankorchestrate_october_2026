"""Write a readable, complete conversation transcript from a Claude Code session file (.jsonl).

    python code/evaluation/export_transcript.py SESSION.jsonl OUT.md

Content: every human message verbatim (pasted blocks included) and every visible assistant reply, each with its
real UTC time taken from the session file.  Left out on purpose: tool calls and their results, hidden reasoning,
harness-injected system reminders and IDE context tags, and messages that background tasks sent back
to the session.  Tool activity is recorded in the session file itself; this file is the dialogue.
The result is checked for API keys and the account e-mail address before it is written.
"""

import json
import re
import sys
from pathlib import Path

NOISE = re.compile(
    r"<system-reminder>.*?</system-reminder>|<ide_[a-z_]+>.*?</ide_[a-z_]+>|<command-[a-z]+>.*?</command-[a-z]+>"
    r"|<local-command-[a-z]+>.*?</local-command-[a-z]+>",
    re.S,
)
SECRET = re.compile(r"gsk_[A-Za-z0-9]{8,}|sk-[A-Za-z0-9]{16,}|[A-Za-z0-9._%+-]+@gmail\.com")


def clean(text):
    return NOISE.sub("", text).strip()


def message_text(message):
    """Visible text blocks of a message; tool_use, tool_result and thinking blocks are skipped."""
    content = message["content"]
    if isinstance(content, str):
        return clean(content)
    parts = [p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"]
    return clean("\n".join(parts))


def timeline(path):
    """Yield (timestamp, role, text, model) for human messages and visible assistant replies, in order."""
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.startswith("{"):
            continue
        d = json.loads(line)
        kind = d.get("type")
        if kind == "user" and (d.get("origin") or {}).get("kind") == "human":
            text = message_text(d["message"])
            if text:
                yield d["timestamp"], "human", text, None
        elif kind == "assistant":
            text = message_text(d["message"])
            if text:
                yield d["timestamp"], "assistant", text, d["message"].get("model")


def render(path):
    out = [
        "# Conversation transcript",
        "",
        f"Source: Claude Code session `{Path(path).stem}`. Times are UTC from the session file. "
        "Tool calls, hidden reasoning and "
        "harness reminders are omitted; see the session files for those.",
        "",
    ]
    turn = 0
    for ts, role, text, model in timeline(path):
        stamp = ts[:19].replace("T", " ") + " UTC"
        if role == "human":
            turn += 1
            out += [f"## Turn {turn} - {stamp} - human", "", text, ""]
        else:
            out += [f"### Assistant - {stamp} - {model or 'model unknown'}", "", text, ""]
    return "\n".join(out)


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    text = render(sys.argv[1])
    leaks = SECRET.findall(text)
    if leaks:
        print(
            f"refusing to write: {len(leaks)} possible secret(s) or account address(es) found, e.g. {leaks[0][:10]}..."
        )
        return 1
    Path(sys.argv[2]).write_text(text, encoding="utf-8")
    print(f"wrote {sys.argv[2]}: {len(text):,} characters")
    return 0


if __name__ == "__main__":
    sys.exit(main())
