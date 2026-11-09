---
name: levin-research-notebook-runtime
description: "Maintain scientific experiment records, register evidence and execution provenance, recover interrupted work, and finalize reproducible reports in a filesystem notebook."
---

# Research notebook

Use for computational or experimental scientific tasks whose evidence must survive the conversation.
This is a record-lifecycle pipeline plugin: it records work, it does not execute scientific jobs.

Logical MCP alias `levin-research-notebook__runner`; the enabled deployment is
`levin-research-notebook__runner__local`. v0.x is local-only — no Remote SSH transfer, so never
address a Remote job workspace for notebook writes (register HPC data as external references).

## Read only the branch the current stage needs

| Stage | Load |
|---|---|
| First call, resuming, workspace layout | [start](references/start.md) |
| Checkpoints, artifacts, runs, references, remote data | [evidence](references/evidence.md) |
| Report sections, numbers, math, figures, fonts | [report](references/report.md) |
| Citing papers, BibTeX, reference list | [bibliography](references/bibliography.md) |
| validate, finalize, space accounting, pruning | [finalize](references/finalize.md) |
| Handing figure work to a worker | [visualization brief](references/visualization-agent.md) |
| Limits, failure modes, recovery | [limits](references/limits.md) |
| Exact argument shapes | [calls.json](examples/calls.json) |

Do not read the whole tree up front. A record-lifecycle task touches start → evidence → report →
finalize, in that order, and each file is short enough to load when its stage begins.

## The five stages

1. `research_record_init` — once per task identity; returns `experiment_id` and a scratch directory.
2. `research_record_checkpoint` — methods, observations, failures, evidence-linked conclusions.
3. `research_record_register_artifact` / `research_record_register_run` — the evidence itself.
4. `research_record_validate` — structural validity now plus every gate `finalize` will apply.
5. `research_record_finalize` — sources, PDF, space accounting; then `prune_reports` if needed.

## Invariants — these override convenience

- Never invent a result, number, citation or figure. A conclusion needs evidence ids; a failure
  needs a reason, and vague text (`无结果`, `failed`, `error`) is rejected.
- Raw evidence is immutable. Never overwrite an original, work inside `levin_scratch/`, or land a
  large remote original locally without an explicit permission recorded on the artifact.
- Units are checked, never converted. A value you recorded is the value the report prints.
- Nothing is deleted automatically: scratch is retained, revisions are kept, and only
  `research_record_prune_reports` removes old PDF snapshots, on explicit call.
- `ok` is not completion. Read `finalized`, `report.render_state` and `validation`; a blocked attempt
  leaves a source-only report folder with no PDF.
- You choose `font_profile` from the report's content; see [report](references/report.md#fonts).

## Boundaries

No automatic task hooks or native agent-type installation are claimed; this skill drives the
checkpoints. There is no scheduler — submit compute with Levin/existing tools. If MCP is unavailable,
read `levin_notebook` JSON/Markdown with ordinary file tools or import `mcp/runner/notebook.py`, whose
`Notebook` class is the same code the tools call. `preview: true` validates argument shape only:
never report a preview as a performed experiment.
