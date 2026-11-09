# Starting or resuming a record

## init

```text
research_record_init(workspace_dir, task_id, agent_id, title, objective,
  hypothesis?, expected_result?, purpose?, implementer?, environment_location?,
  record_type?: experiment|analysis|literature_review, derived_from?, retention?)
```

Pass the **actual project workspace**, so `levin_notebook/` and `levin_scratch/` land beside the
work they describe. `task_id` and `agent_id` are stable slugs, not prose.

Fields that decide whether the report reads as science or as a stub:

| Field | What it becomes |
|---|---|
| `title`, `objective` | report title, and the first sentence of the three-sentence summary |
| `purpose` | section 1 实验目的 — why this follows from earlier work (a prior MD setup, a gap in the data) |
| `hypothesis`, `expected_result` | the a priori expectation, and section 1's fallback when `purpose` is absent |
| `implementer` | `{"kind": "user"|"agent", "name": ..., "model": ...}` — the fact table's 实施人 row |
| `environment_location` | the uv/conda environment path actually used, not the interpreter name |
| `record_type` | which middle sections the report uses (see [report](report.md)) |
| `derived_from` | `[exp-...]` parents; a campaign organised as tracks → summary needs this |

A vague objective produces a vague report; the tool cannot fix that afterwards except through
`interpretation` at finalize.

## Resume identity

Repeated `task_id` resumes only when `title` **and** `objective` match the stored strings
byte-exactly. Different text is rejected rather than silently forking a second record. Recover the
exact strings from `research_record_index` (rows carry both) or from `manifest.json`, then resume with
those values verbatim. Use a new `task_id` when the work really is different.

`implementer`, `environment_location` and `derived_from` may be **backfilled** on resume when the
stored value is empty, and are never rewritten once recorded. That is a repair path for an init that
omitted them, not an edit path.

## Where files go

```text
<workspace>/levin_scratch/<task_id>/<agent_id>/     disposable working files
<workspace>/levin_notebook/experiments/<exp-id>/
    manifest.json      canonical structured state
    record.md           generated readable view (do not hand-edit)
    notes.md            yours; the place for human commentary
    revisions/          immutable manifest snapshots
    data/  scripts/  figures/  reports/
<workspace>/levin_notebook/index.md
```

Persistent scripts, small datasets and figures belong inside the experiment folder. Keep original raw
files where they already are and register them by reference; raw or input evidence located inside
`levin_scratch/` is rejected because scratch is disposable. When an analysis script matters for
reproduction, copy it into the experiment folder and run *that* copy, so the registered checksum
matches the code that produced the outputs.

## Reading an existing record

Start with `record.md`, not the manifest. It is generated from the manifest and shows the same
sections the report will. Then `research_record_validate` for current structural state, and
`research_record_index(include_summary: true)` to see counts per record without opening JSON.
