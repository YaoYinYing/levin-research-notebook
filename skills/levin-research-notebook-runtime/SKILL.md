---
name: levin-research-notebook-runtime
description: "Maintain scientific experiment records, register evidence and execution provenance, recover interrupted work, and finalize reproducible reports in a filesystem notebook."
---

# Research notebook

Use for computational or experimental scientific tasks whose evidence must survive the conversation.
This is a record-lifecycle pipeline plugin; it records work and does not execute scientific jobs.
Logical MCP alias server_name: "levin-research-notebook__runner"; the enabled deployment is
`levin-research-notebook__runner__local`. v0.x is local-only: no Remote SSH transfer, so do not
address a Remote job workspace for notebook writes (record HPC data as external references instead).

## Start or resume

1. Call `research_record_init` once with the actual project `workspace_dir`, stable `task_id`,
   `agent_id`, title, objective, a priori hypothesis and `expected_result` when one exists. The
   report opens with a three-sentence summary (what / why / expected) and a fact table built from
   these fields plus the recorded runs. Also pass `purpose` (why this follows from earlier work),
   `implementer` (`{kind: "user"|"agent", name, model}`) and `environment_location` (the uv/conda
   environment path actually used). For a campaign of several records pass
   `derived_from: [parent_experiment_id]`; an undeclared cross-record artifact reference is warned about.
2. Keep the returned `experiment_id`. Repeated task identity resumes the same record only when
   `title` and `objective` match byte-exactly; otherwise the tool rejects the call rather than
   silently creating a duplicate. Recover the exact stored strings with `research_record_index`
   (its rows return both) or by reading `manifest.json`, then resume with those values verbatim.
3. Put all generated temporary work under the returned `levin_scratch/<task_id>/<agent_id>/`.
   Preserve raw data outside scratch. Persistent scripts, small data and figures belong under
   `levin_notebook/experiments/<experiment_id>/`. Keep original raw files in place.
4. Read `record.md` and the relevant manifest fields when resuming; do not rely on chat memory.

## During work

- Append meaningful methods, observations, failures and decision changes with
  `research_record_checkpoint`; avoid per-command narration or full log dumps. Give each one a short
  `title`: sections are rendered as numbered subsections (`1. <title>`) grouped under Methods,
  Observations, Failures and Conclusions. Use `replica`/`retry` for repeats, `refers_to` to point at
  an earlier numbered entry instead of restating a method, and `when_note` only when a run spans
  dates (it renders as a quoted line; timestamps never appear in headings).
- Use `research_record_register_artifact` for raw/input references, scripts, derived data,
  tables, figures and logs. Registration reads files without copying or changing them.
  Register a path only after the file exists; if it is still absent the record keeps
  `availability: missing` and validate reports an error until you register the same location and
  role again, which refreshes that entry in place instead of creating a duplicate. A path outside
  `workspace_dir` (or a scheme URL) is accepted and hashed, but validate warns that the record is
  not portable — prefer keeping evidence inside the workspace or registering it as an explicit
  external reference. Copy an analysis
  script into the experiment folder and run that copy, so the registered checksum matches the code
  that produced the outputs.
- Use `research_record_register_run` for local, Levin Job and Slurm provenance. Record the executing
  `host` (auto-filled for `local`/`levin`, required for `slurm`/`external`), command, parameters,
  effective seeds, software versions, inputs, outputs and failure information.
  Submit work with existing Levin/compute tools; this plugin has no scheduler.
- Register artifacts and runs before referencing their returned IDs in a checkpoint; a guessed ID is
  rejected. Never edit old text: correct a `conclusion`, `observation` or `method` by appending a new
  checkpoint with `supersedes: <checkpoint_id>`; the original stays visible, struck through.
- Batch a meaningful observation into one checkpoint. Use a stable `request_id` on retries;
  changed payloads require new request IDs. Update a run with its returned `run_id` as `run.id`.
- Remote raw data stays remote. Compute on the remote machine and bring back only lightweight
  results; register the original with `source_origin: remote_copy` plus `remote_host` and
  `remote_path` (an `ssh://`, `s3://` or Slurm path is the normal form — the plugin never contacts it).
  Landing an actual copy of a remote `raw`/`input` original additionally requires
  `remote_copy_permission` recording who authorized it, and is refused for large originals.
  Large pulled-back results warn too: keep them on the remote host and reference them instead.
- Never overwrite original data, upload private data, silently fetch external references,
  remove scratch or commit large datasets. No retention policy is inferred from task completion.
  Keep secrets out of commands, metadata and URLs. URLs with userinfo/query strings are rejected.
- Artifact and run IDs connect evidence. Conclusions require evidence IDs. Figure registration
  requires dataset `input_ids`, `script_id` and `run_id`; register the run before its figures,
  then update its `output_ids`. Preserve units, replicates and conditions in artifact metadata.
- Re-registering a location whose checksum was never recorded refreshes that entry in place, including
  raw entries; a raw location whose checksum no longer matches is rejected. After any post-finalization
  change `validate` warns the report is stale — re-finalize when it must reflect the change.
- In `register_run`, passing `run.id` means update; omit it to create. Run objects accept only the
  declared fields, so link scripts through artifacts, not the run.
- A blocked `finalize` keeps `execution_status` unchanged and records `render_state` `blocked`; only a
  passing gate commits `success` or `failed`, and only a successful finalization is memoized.
- `research_record_register_artifact` returns `warnings` when no checksum exists (absent file or the
  64 MiB budget). Treat them as unverified evidence, never as integrity proof.

## Report outline (what the PDF will contain)

| Section | Filled from |
|---|---|
| Summary + fact table | objective / purpose / expected_result, implementer, runs, environment_location |
| 1. 实验目的 | `purpose`(fallback `hypothesis`) and objective |
| 2. 实验策略 | `strategy: [{title, text}]` → numbered 2.1, 2.2 … |
| 3. 实验方法和计划 | `method_plan` bullets + method checkpoints numbered 3.1, 3.2 … (replica/retry/refers_to) |
| 4. 实验材料 | hosts/arch, dataset and script artifacts, `materials`, software versions, non-default params |
| 5. 实验结果 | 5.1 看到了什么 / 5.2 没看到什么 / 5.3 意外与处置 from `results.*`, observation and failure checkpoints; 5.4 量纲与单位核对 from `quantities` |
| 6. 实验结论和不足 | conclusion checkpoints (with `supersedes`), `interpretation`, `limitations` |
| 7. 下一步计划 | `plans` |
| 8. 经验教训 | `lessons` |
| 9. 数据空间统计 | measured `levin_notebook`/`levin_scratch` + `remote_space` for HPC hosts |
| 尾注 / 工件与溯源 | `footnotes`, then artifacts on a new page |

### Numbers, math, figures and editable sources

Put numeric results in `quantities` (`{name, value, unit, uncertainty?}`): table 5.4 checks
each unit against the quantity's dimension, blocks a wrong one (temperature in `ps`) and warns
on an unconventional one, without ever converting your value. `$…$` / `$$…$$` render offline
via matplotlib mathtext (no TeX install). Place a plot beside its claim with `\\figure{artifact-id}`
instead of dumping all of them at `\\figures`. `finalize` writes `report.md` (authority),
`report.qmd` and a standalone `report.tex`. Details: [report format](references/report-format.md).

### Literature index from BibTeX

For `literature_review` (and any record that cites papers) pass a `.bib` instead of typing entries:

```text
research_record_finalize(..., bibtex_path="data/library.bib",
  references=[{"id": "Doe2024", "evidence_level": "同行评议", "read_full_text": true}])
```

`bibtexparser` v2 parses the file; `references` then *overrides* fields on a matching citekey and
adds judgement the .bib cannot carry. Follow the EndNoteTweak hygiene rules: prefer a DOI, fall back
to the title, keep the export's own annotation, and never pretend messy metadata is clean — entries
missing DOI/year/title/venue/authors are listed under 需人工核对的元数据 and repeated in the
参考文献 list. `bibtex` accepts inline BibTeX for the same parser. Link fetched structures or
re-computations with `reference_id` on the artifact or run so 复算与核验 ties each result to a paper.

Use `[^label]` inline and a matching `footnotes` entry for side remarks.

**You choose `font_profile`** (scientific-cjk / cjk-sans / latin-only) — see
[report format](references/report-format.md#fonts); check `preflight.fonts.cjk_available` first.
Failure text must state what went wrong: `无结果` / `failed` / `error` shorthand is rejected.

1. Assess whether visualization helps answer the objective. Record an explicit reason either way.
2. When justified, delegate to a dedicated scientific-visualization worker using
   [the specialist brief](references/visualization-agent.md). Give verified dataset references,
   the exact experiment, acceptance criteria and one bounded output scope. The parent accepts
   scientific interpretation. Do not create a decorative figure to satisfy a requirement.
3. Call `research_record_validate`. `valid` is structural validity now; `final_readiness.errors`
   lists every gate `finalize` will apply, so resolve both before finalizing. External/HPC references
   stay explicitly unverified; do not equate schema validity with reproduction.
5. Call `research_record_finalize` with terminal execution status (`success` or `failed`),
   interpretation, limitations, visualization assessment including reviewer and figure IDs, plus
   `lessons` and `plans`. Lessons and future plans close the record; leaving them empty is allowed
   but reported as "None recorded".
   Check `finalized`, `report.render_state` and `validation`; `ok` alone is not completion, and a
   blocked or render-failed attempt still leaves a source-only `reports/<id>/` folder with no PDF.
6. Artifacts open on a new page after a divider, with digests and paths in code blocks and data in
   tables. Read `space_usage` from the finalize result (or `record.md` → *Space usage*): it reports
   `levin_notebook` and `levin_scratch` bytes/files and the change since `research_record_init`.
   Report those numbers; state that scratch is retained, never auto-deleted. Each finalize copies a
   full PDF, so after repeated finalizes call `research_record_prune_reports` (add `dry_run: true`
   first) to drop older snapshots — revisions and artifacts are never touched.
7. Return concise evidence paths and remaining limitations. A successful execution can still have an
   inconclusive or negative scientific interpretation.

## Boundaries and recovery

Limits and recovery: [references/limits.md](references/limits.md). Stage sequence:
[workflow](../../workflows/standard-research-notebook.md). Argument shapes: [calls.json](examples/calls.json).
No automatic task hooks or native agent-type installation are claimed. The skill drives checkpoints.
If MCP is unavailable, read `levin_notebook` JSON/Markdown with ordinary file tools, or call the
portable `mcp/runner/notebook.py` classes from Python; there is no standalone CLI yet.
Preview calls only validate schema shape; never report them as performed experiments.
