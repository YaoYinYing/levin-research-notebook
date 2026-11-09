# Closing a record: validate, finalize, space, pruning

## validate

`research_record_validate(experiment_id)` is read-only. It reports two different things and it is worth
reading them separately:

- `valid` — the record is structurally sound *right now*.
- `final_readiness.errors` — every gate `finalize` will apply, evaluated against the stored manifest.

`final_readiness` will legitimately list pending items before work is finished; it is a checklist, not
a verdict. Warnings never block: an external reference, a non-portable path, a stale report, an
undeclared `derived_from` parent and a missing glyph all appear there.

Also returned: `reports` (counts of total/success/blocked/failed snapshots plus `latest_success`), so
"which PDF is the real one" does not need a manifest read.

## finalize

```text
research_record_finalize(experiment_id, execution_status, interpretation, limitations,
  visualization, request_id?, lessons?, plans?, strategy?, method_plan?, materials?, results?,
  purpose?, environment_location?, footnotes?, remote_space?, quantities?, references?,
  citations?, reference_sections?, extra_sections?, synthesis?, search_strategy?,
  bibtex?/bibtex_path?, record_type?, font_profile?)
```

`execution_status` is `success` or `failed` — how the *run* ended, not what it proved. A successful
execution with an inconclusive result is normal and must be written as such.

Two behaviours that decide whether a second call is safe:

- **Omitted ≠ cleared.** A field you leave out keeps its stored value; an explicit empty list clears
  it. A second finalize that only adds artifacts will not wipe `lessons`/`plans`/`results`.
- **`request_id` memoises a *successful* finalize.** A blocked attempt does not consume it, so after
  clearing a blocked gate you may retry the same id. A changed payload needs a new id.

`interpretation` and `limitations` are required and must be specific. `visualization` is required even
when the answer is no:

```text
{"beneficial": false, "reason": "Single scalar result; a plot would decorate, not inform.",
 "figure_ids": [], "reviewed_by": "parent"}
```

`beneficial: true` requires at least one accepted figure id. Delegate the figure work using
[the visualization brief](visualization-agent.md); the parent keeps scientific acceptance.

## Reading the result

`ok` is not completion. Check:

| Field | Meaning |
|---|---|
| `finalized` | a PDF was delivered |
| `report.render_state` | `success` / `blocked` / `failed` |
| `report.pdf_path` | null when not delivered |
| `validation` | the gates as they stood |
| `space_usage` | measured sizes and the change since `init` |

A **blocked** attempt keeps `execution_status` unchanged, commits interpretation/limitations, and
leaves a source-only `reports/<id>/` folder with `report.md`, `report.qmd`, `report.tex` and no PDF.
That folder is not a result; say so when reporting to a human.

## Staleness

Any mutation after a delivered report makes it stale; `validate` says so, naming the report revision
against the manifest revision. Re-finalize with a new `request_id` when the report must reflect the
change. Nothing re-renders automatically.

## Space accounting

`finalize` measures `levin_notebook/`, `levin_scratch/` and the experiment directory, and reports the
delta against the `init` baseline. The walk is bounded (200k entries, symlinks not followed) and marks
`truncated: true` rather than under-reporting. Report the numbers in human units — KB/MB/GB, never raw
bytes — and state that scratch is retained, never auto-deleted.

For HPC work pass `remote_space: [{host, path, bytes, files?, measured_at?, note?}]`. Flag any entry of
a gigabyte or more; those are the ones a human needs to decide about.

## Pruning

Every finalize copies a whole PDF, so `reports/` grows linearly: 41 finalizes over 8 records reached
88 MB. `research_record_prune_reports(experiment_id, keep='last-success', dry_run?)` deletes old
snapshot folders and their manifest entries.

It always keeps at least one folder — the newest successful snapshot, or the newest attempt when none
succeeded — so a record whose every finalize was blocked is never emptied. It never touches
`revisions/` or artifacts, and pruning bumps the manifest revision, after which `validate` reports the
delivered PDF as stale. Use `dry_run: true` first and report what went.

## Failure modes worth recognising

- A `finalize` that returns `ok: true` with `finalized: false` was blocked, not done.
- An `execution_status` that flipped to `failed` on a blocked attempt was inherited from a failed run,
  not caused by the block.
- A record missing `interpretation` cannot be finalized even with a perfect manifest: the gate is
  about the scientific statement, not the schema.
- Rendering can fail on a figure that went missing or became unreadable; sources are retained and the
  fix is to refresh the artifact, then finalize again.
