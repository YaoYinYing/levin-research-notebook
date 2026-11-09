# Standard research-notebook recipe

Version-agnostic stage chain for computational or experimental scientific work. The plugin is a
record lifecycle over a real filesystem workspace; it never executes the science.

## Dependency manifest

| Layer | Self-contained? | Requirement |
|---|---|---|
| Record storage, validation, PDF | yes | plugin runtime (jsonschema, filelock, reportlab) |
| Compute / job execution | no | external: Levin Jobs, Slurm, or the user's own process |
| Visualization | no | built-in `Agent` tool (`general-purpose` worker) + optional plotting skills |
| Advanced typesetting | no | optional external Quarto/Typst; never required |

When an external layer is missing: compute missing means record only the method and finalize as
`failed` (aborted) with the reason; visualization missing means record
`beneficial: true` with `figure_ids: []` **only if** the run is not being finalized as success —
otherwise the figure must be produced or the assessment changed to `beneficial: false` with a
scientific reason. Never silently finalize a success that claims figures it does not have.

## Stages

| # | Stage | Preferred engine | Replacement engine | Degradation if all missing |
|---|---|---|---|---|
| 1 | Initialize record | `research_record_init` | create `levin_notebook/experiments/<id>/` by hand from schema | abort: no record means no traceable work |
| 2 | Scratch allocation | `init` return value | `mkdir levin_scratch/<task>/<agent>` | manual directory, same layout |
| 3 | Execute science | Levin Job / Slurm / local process | — | record method only, then `failed` finalize |
| 4 | Register raw inputs | `research_record_register_artifact` (role `raw`/`input`) | edit manifest + validate | manual JSON edit plus `research_record_validate` |
| 5 | Register execution | `research_record_register_run` | — | manual manifest edit, then validate |
| 6 | Progress notes | `research_record_checkpoint` | append to `notes.md` | notes.md only; states limitation |
| 7 | Visualization decision | explicit checkpoint + `visualization` field | — | required decision; no automatic figure |
| 8 | Figures | delegated specialist via `Agent` | parent-authored script registered as `script` | skip figure, record reason |
| 9 | Validation | `research_record_validate` | read `manifest.schema.json` and inspect | abort finalization |
| 10 | Finalize | `research_record_finalize` | write own report and register it as artifact | record stays `wip`; state explicitly |
| 11 | PDF | pinned ReportLab in `finalize` | external Quarto/Typst on `report.qmd`, register output | keep editable source, `render_state=failed` |
| 12 | Index/search | `research_record_index` | `grep` over manifests | filesystem search |

## Minimal end-to-end call order

```text
research_record_init(workspace_dir, task_id, agent_id, title, objective, hypothesis)
research_record_register_artifact(experiment_id, artifact={role:"raw", location:"data/input.csv", description:...})
research_record_register_artifact(experiment_id, artifact={role:"script", location:"levin_notebook/experiments/<id>/scripts/analyze.py", ...})
research_record_register_run(experiment_id, run={backend:"local", execution_status:"success",
   command:"python analyze.py", environment:{...}, input_ids:[...], output_ids:[...]})
research_record_register_artifact(experiment_id, artifact={role:"derived", location:".../data/result.csv",
   input_ids:[raw_id], script_id:script_id, run_id:run_id, ...})
research_record_register_artifact(experiment_id, artifact={role:"figure", location:".../figures/f1.png",
   input_ids:[derived_id], script_id:script_id, run_id:run_id, ...})
research_record_checkpoint(experiment_id, agent_id, kind:"observation", text:"...", evidence_ids:[derived_id])
research_record_checkpoint(experiment_id, agent_id, kind:"conclusion", text:"...", evidence_ids:[derived_id])
research_record_validate(experiment_id)
research_record_finalize(experiment_id, execution_status:"success", interpretation, limitations,
   visualization={beneficial:true, reason:"...", figure_ids:[figure_id], reviewed_by:"parent-agent"})
research_record_index(workspace_dir, query="")
```

Figure registration requires the run to exist first; then update the run with `run.id` and the
new `output_ids`. Exact arguments: `skills/levin-research-notebook-runtime/examples/calls.json`.

## Non-negotiables

- Raw data are referenced, never rewritten; nothing is copied to scratch as a substitute.
- `execution_status` is execution, not scientific truth. Interpretation and limitations are separate.
- Conclusions require evidence IDs; a schema-valid manifest does not prove reproducibility.
- No automatic scratch deletion, no uploads, no external fetch during validation.
