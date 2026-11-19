"""Ask the local LLM about every real request text and compare with the rule classifier.

The LLM here is only a second opinion for evaluation: it decides nothing in the pipeline.  A
disagreement points at either a request the rules mislabel or a model error; each is listed so a
human can look.  Results are cached (code/.cache/llm_cache.json), so reruns are fast.

    python code/evaluation/llm_second_opinion.py [--limit N]
"""

import argparse
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from ghost import ingest, pipeline  # noqa: E402
from ghost.classify import classify_request, sanitize  # noqa: E402
from ghost.llm import LLM, adjudicate_request  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    if not LLM.available():
        print("Ollama is not reachable")
        return 1
    reqs = pipeline.read_csv(os.path.join(ingest.DS, "deletion_requests.csv")) + pipeline.read_csv(
        os.path.join(ingest.DS, "sample_deletion_requests.csv")
    )
    by_text = {}
    for r in reqs:
        by_text.setdefault(r["request_text"], []).append(r["case_id"])
    texts = sorted(by_text)
    if a.limit:
        texts = texts[: a.limit]
    llm = LLM(timeout=180)
    print(f"{len(reqs)} requests, {len(by_text)} unique texts, model {llm.model}")
    agree = rejected = 0
    disagree = []
    t0 = time.time()
    for i, text in enumerate(texts, 1):
        rule, _ = classify_request(text)
        got, why = adjudicate_request(llm, sanitize(text)[0])
        if got is None:
            rejected += 1
            disagree.append((by_text[text][:3], rule, "REJECTED", text[:110]))
        elif got == rule:
            agree += 1
        else:
            disagree.append((by_text[text][:3], rule, got, text[:110]))
        if i % 50 == 0:
            print(f"  {i}/{len(texts)} done, {time.time() - t0:.0f}s", flush=True)
    n = len(texts)
    print(
        f"\nrules vs LLM on unique texts: agree {agree}/{n}, rejected-by-guards {rejected}, "
        f"disagree {len(disagree) - rejected}"
    )
    for cases, rule, llm_says, text in disagree:
        print(f"  {cases} rules={rule} llm={llm_says} | {text}")
    print("usage:", llm.usage)
    return 0


if __name__ == "__main__":
    sys.exit(main())
