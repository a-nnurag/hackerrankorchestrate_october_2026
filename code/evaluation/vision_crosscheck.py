"""Independent cross-check of the committed image transcriptions (code/ghost/manual/*.json).

A local vision model (Ollama, default minicpm-v) reads each screenshot with no knowledge of our
transcription.  We then check that every resource id / email / user id we transcribed also appears in
what the model read.  Disagreement means "look at this image again"; agreement is only evidence, not
proof (the model can fail to read small text).  Offline QA tool: never run by code/main.py.

    python code/evaluation/vision_crosscheck.py [--model minicpm-v] [--only evidence_32]
"""

import argparse
import base64
import csv
import glob
import json
import os
import re
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CODE = os.path.dirname(HERE)
REPO = os.path.dirname(CODE)
sys.path.insert(0, CODE)

PROMPT = (
    "This is a screenshot of an internal business console. Transcribe ALL text you can read in the "
    "detail panel and in the table: every identifier (like account_1234, backup_9287, user_17), "
    "every email address, phone number and date. Output plain text, one item per line, copy exactly."
)


def ask(host, model, image_path, timeout=600):
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    body = {
        "model": model,
        "stream": False,
        "options": {"temperature": 0, "num_ctx": 4096, "num_predict": 700},
        "messages": [{"role": "user", "content": PROMPT, "images": [b64]}],
    }
    req = urllib.request.Request(
        host + "/api/chat", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())["message"]["content"]


def squash(s):
    return re.sub(r"[^a-z0-9@._+-]", "", s.lower())


def load_manifest():
    with open(os.path.join(REPO, "dataset", "evidence_files.csv"), encoding="utf-8") as f:
        return {r["file_id"]: r for r in csv.DictReader(f)}


def check_entries(fid, entries, text, model):
    """Print per-entry agreement between our transcription and what the model read; -> (found, total)."""
    total = agree = 0
    for e in entries:
        want = [e["resource_id"]] + e["identifiers"].get("emails", []) + e["identifiers"].get("user_ids", [])
        miss = [w for w in want if squash(w) not in text]
        total += len(want)
        agree += len(want) - len(miss)
        print(
            f"{fid} {e['resource_id']}: {len(want) - len(miss)}/{len(want)} read by {model}"
            + (f"  NOT FOUND: {miss}" if miss else "")
        )
    return agree, total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="minicpm-v")
    ap.add_argument("--host", default=os.environ.get("GHOST_OLLAMA_HOST", "http://localhost:11434"))
    ap.add_argument("--only", default=None)
    a = ap.parse_args()
    manifest = load_manifest()
    total = agree = 0
    for path in sorted(glob.glob(os.path.join(CODE, "ghost", "manual", "evidence_*.json"))):
        with open(path, encoding="utf-8") as f:
            j = json.load(f)
        fid = j["file_id"]
        if a.only and fid != a.only:
            continue
        img = os.path.join(REPO, "dataset", manifest[fid]["file_path"])
        if not img.lower().endswith(".png"):
            print(f"{fid}: skipped (not an image: {os.path.basename(img)})")
            continue
        found, n = check_entries(fid, j["entries"], squash(ask(a.host, a.model, img)), a.model)
        agree += found
        total += n
    print(f"\nagreement: {agree}/{total} items")


if __name__ == "__main__":
    main()
