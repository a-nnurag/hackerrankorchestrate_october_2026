# Token usage and cost report

Final full-dataset run: `python code/main.py` (518 requests, produces `output.csv`).

| Item | Value |
|---|---|
| Model providers | none |
| Model names | none |
| Model calls | 0 |
| Input tokens | 0 |
| Output tokens | 0 |
| Total tokens | 0 |
| Average tokens per request | 0 |
| Estimated total cost | USD 0.00 |
| Estimated cost per request | USD 0.00 |

The submitted pipeline is deterministic Python (parsing, identity resolution, linking with
confidence scores, a rule table and a step builder). The final run calls no language model, so there
is nothing to meter, no API key, and no network access.

An optional local-LLM adjudicator for conflicting request text exists behind `--llm` (Ollama,
`qwen3:4b`, off by default). Run with `--llm` on the 518 real requests it made 0 calls, because no
request is conflicting or unknown, and `output.csv` is byte-identical to the run without it.
During development it made a few dozen calls on our own test requests (see
`llm_benchmark.py`: 26 requests, about 7.5k prompt and 1k output tokens, about 3 s per call on an
RTX 3050 6 GB), at no cost.

Measured resources of the final run (Windows 11, Python 3.14, single process):

| Item | Value |
|---|---|
| Wall-clock time, ingestion of all 94 evidence files | about 0.15 s |
| Wall-clock time, full run (ingest, learn offset tables, audit 518 cases, write CSV, validate), final run | about 6.6 s (three runs: 6.5, 6.7, 6.6) |
| Per-request time | about 13 ms |

Where a model was used: during development, an AI coding assistant (Claude, run through Claude
Code) helped analyse the dataset and write the code; the transcripts are in the submitted
`chat_transcript` (`log.txt`). The images and PDFs under `dataset/evidence/` were transcribed once
by a vision-capable model into `code/ghost/manual/*.json`; those files are static inputs checked
into the repository, not run-time calls, and their token usage is not part of the final run above.
