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
| Reusable facts, conclusions, boundaries, derivations across records | [knowledge](references/knowledge.md) |
| Limits, failure modes, recovery | [limits](references/limits.md) |
| Exact argument shapes | [calls.json](examples/calls.json) |

Do not read the whole tree up front. A record-lifecycle task touches start → evidence → report →
finalize, in that order, and each file is short enough to load when its stage begins.

## The five stages

1. `research_record_init` — once per task identity; returns `experiment_id` and a scratch directory.
   Pass `experiment_id` to take over work another session started, even if the wording differs.
2. `research_record_checkpoint` — methods, observations, failures, evidence-linked conclusions, and
   `conditional` entries for counterfactual reasoning (requires `refers_to`, no `evidence_ids`).
3. `research_record_register_artifact` / `research_record_register_run` — the evidence itself.
4. `research_record_validate` — structural validity now plus every gate `finalize` will apply.
5. `research_record_finalize` — sources, PDF, space accounting; then `prune_reports` / 
   `prune_revisions` if needed.

`research_knowledge_*` is the **other** family: it records what is now *known*, not what was done.
Promote a finding into it when it should outlive the record — a measured relationship, a mechanism you
can defend, the limit where a model stops holding, the chain connecting them, or what to do differently
next time. Five kinds exist because they fail differently — `fact` / `conclusion` / `boundary` /
`derivation` / `lesson` — and a hard rule per kind is enforced at write time: a boundary without
`conditions.fails_when`, or a lesson without `lesson.remedy`, is refused. Support is `record` (measured
here) or `external` (literature), and the two are never mixed in the brief. A lesson is operative, not
epistemic: it must also have been paid for by a local failure, and `research_knowledge_candidates` lists
the failures you have not promoted yet.

## Three roles you are not

This skill drives the work. Three other roles exist because the agent doing the work cannot
credibly audit or review itself:

| Role | What it does | Where it lives |
|---|---|---|
| **auditor** | deterministic checks only: checksums, cross-references, orphan evidence, success without a report | `research_record_audit` — run it, read it, never hand-wave it |
| **reviewer** | does this evidence actually support this claim | skill `levin-record-reviewer`, run as an independent worker |
| **advisor** | what to do next, ordered by information per unit cost | skill `levin-research-advisor`, run as an independent worker |

Run `research_record_audit` before asking for a review, and hand its report to the reviewer; a
reviewer should never spend its attention re-deriving what code already checked.

## Invariants — these override convenience

- Never invent a result, number, citation or figure. A conclusion needs evidence ids; a failure
  needs a reason, and vague text (`无结果`, `failed`, `error`) is rejected.
- Raw evidence is immutable. Never overwrite an original, work inside `levin_scratch/`, or land a
  large remote original locally without an explicit permission recorded on the artifact.
- Units are checked, never converted. A value you recorded is the value the report prints.
- Nothing is deleted automatically: scratch is retained, revisions are kept, and only
  `research_record_prune_reports` / `research_record_prune_revisions` remove old snapshots, on
  explicit call.
- A regenerated figure is a normal event: re-register the same `(location, role)` and it records
  `revision N+1` with a warning, while changed `raw`/`input` evidence stays an error. To retire an
  obsolete artifact, register its replacement with `supersedes`, or pass `retired: true`.
- Knowledge is not a scrapbook: an entry needs support that resolves to a real record, and a
  conclusion needs a stated scope. Prefer `boundary` when what you actually learned is where
  the claim stops holding.
- The record is about the experiment, not about the tooling. If the session turns to debugging the
  notebook itself, pause recording (`research_record_suspend`), and set any entry that already
  slipped in aside with `research_record_exclude` — never by editing or deleting history.
- `ok` is not completion. Read `finalized`, `report.render_state` and `validation`; a blocked attempt
  leaves a source-only report folder with no PDF.
- You choose `font_profile` from the report's content; see [report](references/report.md#fonts).

## Boundaries

No automatic task hooks or native agent-type installation are claimed; this skill drives the
checkpoints. There is no scheduler — submit compute with Levin/existing tools. If MCP is unavailable,
read `levin_notebook` JSON/Markdown with ordinary file tools or import `mcp/runner/notebook.py`, whose
`Notebook` class is the same code the tools call. `preview: true` validates argument shape only:
never report a preview as a performed experiment.
