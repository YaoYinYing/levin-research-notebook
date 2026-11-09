# The five stages, with a real transcript

A record moves through five stages. The calls below are from a workspace created by this session's
own run of the lifecycle; the return values are trimmed to the fields the next stage consumes.
Argument schemas are not repeated here — [`plugin_spec.py`](../mcp/runner/plugin_spec.py) is the
authority, and [`references/start.md`](../skills/levin-research-notebook-runtime/references/start.md)
onwards is what an agent reads stage by stage.

## Stage 1 — open the record once

```python
research_record_init(workspace_dir="/tmp/walk", task_id="walk-demo", agent_id="main-agent",
                     title="Step-size convergence",
                     objective="Quantify how Euler global error scales with dt.",
                     hypothesis="Error falls first order in dt.",
                     purpose="Follows the earlier setup run; no new simulation.",
                     expected_result="Slope about 1 on log-log axes.",
                     implementer={"kind": "agent", "name": "main-agent"},
                     environment_location="/tmp/walk/levin_scratch/venv")
```

```text
{"experiment_id": "exp-394e92ff…", "revision": 1, "resumed": false,
 "manifest_path": "…/manifest.json", "record_path": "…/record.md", "scratch_dir": "…"}
```

`task_id` is the identity, not a label: calling `init` again with the same `task_id` **and** the same
`title` and `objective` byte-for-byte resumes the existing record (`resumed: true`) instead of
creating a second one. Different text is rejected. Two fields are backfillable on resume
(`implementer`, `environment_location`) and never rewritten once recorded.

Six fields decide whether the finished report reads as science or as a stub — `title`, `objective`,
`purpose`, `hypothesis`, `expected_result`, `implementer`, plus `record_type`. They are the ones the
report cannot reconstruct later; `interpretation` at finalize is the only later repair.

## Stage 2 — record what supports the claims

Artifacts, runs and checkpoints interlock. The order that works:

```python
# 2a. the inputs and the code, by reference; nothing is copied
register_artifact(experiment_id, artifact={"role": "input", "location": "data/trace.csv",
                  "description": "Step-size table", "reference_id": "trace"})
#    → {"artifact_id": "artifact-…", "sha256": "9296bc3dce44…", "checksum_origin": "computed",
#       "availability": "local", "warnings": []}

register_artifact(experiment_id, artifact={"role": "script", "reference_id": "runner-script",
                  "location": "levin_notebook/experiments/<id>/scripts/run.py", …})

# 2b. the execution, naming those inputs
register_run(experiment_id, run={"backend": "local", "execution_status": "success",
             "command": "python run.py out.csv", "environment": {"python": "3.11.11"},
             "input_ids": ["trace", "runner-script"], "reference_id": "run-1"})
#    → {"run_id": "run-a5c2a56b20d9…"}

# 2c. what came out, pinned to that run
register_artifact(experiment_id, artifact={"role": "derived", "reference_id": "out",
                  "location": "…/data/out.csv", "input_ids": ["trace"],
                  "script_id": "runner-script", "run_id": "run-1", …})
register_run(experiment_id, run={"id": "run-1", …same fields…, "output_ids": ["out"]})

# 2d. the scientific statement, tied to evidence
checkpoint(experiment_id, agent_id="main-agent", kind="method",
           text="Explicit forward Euler at four step sizes, compared with the closed form.",
           evidence_ids=["runner-script", "run-1"])
checkpoint(experiment_id, agent_id="main-agent", kind="conclusion",
           text="Error tracks the first-order reference line within the tested range.",
           evidence_ids=["out"])
```

Three behaviours here are not decoration:

- **`reference_id` is an alias you choose.** Every reference field (`input_ids`, `script_id`,
  `run_id`, `run.id`, `evidence_ids`) accepts it, and the canonical `artifact-…`/`run-…` id equally.
  Aliases are canonicalised **before** the entry is stored, so `manifest.json` only ever holds the real
  id; an update that omits `reference_id` keeps the stored alias rather than erasing it.
- **A `conclusion` with no `evidence_ids` is rejected.** So is a `failure` whose text is vague
  (`failed`, `error`, `无结果`).
- **Figures need provenance.** `role: "figure"` requires a producing `run_id`; `input_ids` and
  `script_id` are inherited from that run rather than demanded twice.

## Stage 3 — ask what `finalize` will still reject

```python
research_record_validate(experiment_id)
```

```text
{"valid": true, "errors": [], "warnings": [],
 "reports": {...},
 "final_readiness": {"errors": [
   "Stored execution_status is wip; …this line clears when finalize is called with success or failed",
   "Explicit limitations required",
   "Explicit interpretation required (may be inconclusive)",
   "Visualization assessment required"]}}
```

`valid` describes the record **now**; `final_readiness.errors` is the full gate list `finalize` will
apply, so before the last stage it legitimately lists pending work. It is a checklist, not a verdict.
`validate` is read-only: it never repairs, never re-renders, never writes.

## Stage 4 — finalize

```python
research_record_finalize(experiment_id, execution_status="success",
    interpretation="Euler error decreased in proportion to dt across the tested range.",
    limitations="One solver family, four step sizes, no replicates.",
    visualization={"beneficial": False,
                   "reason": "A single scalar slope; a plot would decorate, not inform.",
                   "figure_ids": [], "reviewed_by": "main-agent"},
    quantities=[{"name": "rmsd", "value": 2.1, "unit": "Å"}],
    request_id="final-1")
```

```text
{"finalized": true, "report": {"render_state": "success", "pdf_path": "…/reports/report-200d…/report.pdf"},
 "space_usage": {"display": {"notebook": "56.9 KB", "scratch": "0 B", "experiment": "39.1 KB", …}}}
```

What the call actually did, in order: evaluated every gate against a *candidate* manifest; wrote the
report snapshot folder (`report.md`, `report.qmd`, `report.tex`); rendered `report.pdf` only if the
gates passed; committed the terminal `execution_status` only if they passed; measured space against
the `init` baseline.

Two behaviours decide whether a second call is safe:

- **Omitted ≠ cleared.** A field left out keeps its stored value; an explicit empty list clears it.
  A second `finalize` that only adds artifacts therefore cannot wipe `lessons`/`plans`/`results`.
- **`request_id` memoises a *successful* finalize.** An identical replay returns the same report
  (`"idempotent": true`) instead of writing a second snapshot. A blocked attempt does **not**
  consume the id, so after clearing a gate you may retry the same id; a changed payload needs a new
  one (`request_id reused with different content`).

`ok: true` with `finalized: false` means blocked: a source-only folder with no PDF. That folder is
not a result. Read `finalized`, `report.render_state`, `report.pdf_path`, `validation`.

## Stage 5 — search, and reclaim disk when the snapshots annoy you

```python
research_record_index(workspace_dir="/tmp/walk", query="euler", include_summary=True)
# → one row: execution_status "success", revision 9, summary {artifacts: 3, runs: 1,
#   checkpoints {method: 1, conclusion: 1}, quantities: 1, reports: 1}

research_record_prune_reports(experiment_id, dry_run=True)   # lists first
research_record_prune_reports(experiment_id, keep="last-success")
```

Every finalize copies a whole PDF, so `reports/` grows linearly. Pruning always keeps at least one
snapshot — the newest successful one, or the newest attempt when none succeeded — never touches
`revisions/` or artifacts, and bumps the manifest revision, after which `validate` reports the
delivered PDF as stale. Re-finalize deliberately; nothing re-renders automatically.

## What the record looks like afterwards

```text
/tmp/walk/levin_notebook/experiments/exp-394e92ff…/
├── manifest.json          canonical, mutable, schema-validated on every save
├── record.md               generated view; the section spine below
├── notes.md               yours
├── revisions/             one immutable JSON per save, plus archived human edits
├── data/ scripts/ figures/ reports/
└── reports/report-200d…/{report.md, report.qmd, report.tex, report.pdf}
```

`record.md` for this record numbered: 1 实验目的 · 2 实验策略 · 3 实验方法和计划 · 4 实验材料 ·
5 实验结果 (5.1–5.4) · 6 实验结论和不足 · 7 下一步计划 · 8 经验教训 · 9 数据空间统计 ·
工件与溯源 · 保存与复现. Sections with no content still print an explicit "未记录…" line rather than
disappearing, so a gap is visible instead of silent. Which field fills which section is
[manifest-and-report](manifest-and-report.md)'s subject.

## Where this page stops

Rendering rules (font profiles, glyph coverage, figures, math) belong to the agent that calls
`finalize`, so they live in
[`references/report.md`](../skills/levin-research-notebook-runtime/references/report.md). Rejection
conditions and recovery paths live in
[`references/limits.md`](../skills/levin-research-notebook-runtime/references/limits.md). This page
owns the sequence and the return-value contract.
