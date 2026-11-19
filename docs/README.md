# Ghost Data Still Exists: project notes

Working notes from the analysis and build phase (2026-10-24 to 2026-10-25). The solution is in `code/` (see `code/README.md`); the notes in 01 to 05 were written before it and describe the analysis, so where they differ (for example thresholds) `code/evaluation/evaluation_report.md` is current. These files record what we learned about the problem and the dataset, the decisions we made, the weaknesses we found in the design, and what is still open.

| File | Contents |
|---|---|
| [RESEARCH.md](RESEARCH.md) | **Start here for the research:** every question asked, web sources with links, internal measurements, what changed, gaps, how to reproduce |
| [01_problem_and_data.md](01_problem_and_data.md) | The task, the output contract, every dataset file, evidence formats, identity facts |
| [02_rules_and_decisions.md](02_rules_and_decisions.md) | Rule table with conditions, decision table, ordering, `evidence_id` choice, time rules, validation checks |
| [03_design_critique.md](03_design_critique.md) | Principal-engineer critique: where accuracy can be lost, image and text input hazards, fixes |
| [04_open_questions_and_roadmap.md](04_open_questions_and_roadmap.md) | Unsettled rules, cases that depend on images, test plan, build order, status of pending work |
| [06_handling_limitations.md](06_handling_limitations.md) | How each stated limitation was researched and handled: robustness analysis, status filter, image checks, rare categories |
| [07_conditions_and_log.md](07_conditions_and_log.md) | Retention/hold dates, attachment ownership and shared context: web research, what is rules and what is LLM, log gap |
| [08_interview_notes.md](08_interview_notes.md) | Talking points for the AI interview: architecture, evaluation, decisions, weak points |
| [09_small_data_thresholds.md](09_small_data_thresholds.md) | Web research on tuning thresholds with little labelled data, and how it applies |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Data flow, module map, design rules, how to extend, quality gates |
| [CODE_QUALITY.md](CODE_QUALITY.md) | Lint, type, complexity gates; before/after measurements; how the refactor was verified |
| [05_ingestion_prototype_results.md](05_ingestion_prototype_results.md) | Measured results of the ingestion prototype: parse coverage, sample reproduction rate, false links, confidence scheme, parsing recipes |

## Evidence level

Every statement in these notes has one of three levels:

- **Verified**: checked directly against the data, or reproduced on all 32 sample answers.
- **Reported**: found by a research agent and, where noted, spot-checked by us.
- **Guess**: reasoned from the rules or conventions but not shown by any data. Marked "(guess)".

Guesses must be treated as hypotheses until a test shows otherwise.

## How the research was done

Five read-only research agents analysed the dataset: identity and activity, evidence formats, reverse-engineering of the 32 sample answers, image and PDF transcription, and (still running when these notes were written) open-rule analysis and an ingestion prototype. Their working files are in the session scratchpad, not in the repo.

All agents have now finished. The solution was built afterwards in `code/`; see `code/README.md` and `code/evaluation/evaluation_report.md` for the final design and results.
