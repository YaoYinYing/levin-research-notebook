# Evidence: checkpoints, artifacts, runs

## Checkpoints

`research_record_checkpoint(experiment_id, agent_id, kind, text, ...)` with
`kind ∈ method | observation | failure | conclusion | conditional | resume | note`.

One meaningful finding per checkpoint, not one per command. Give each a short `title`: the report
renders methods, observations, failures and conclusions as numbered subsections grouped under their
section, and the title is the heading.

| Field | Effect |
|---|---|
| `replica`, `retry` | appends `replica #n` / `retry #n` to the heading |
| `when_note` | a quoted line under the heading, for a method that spans dates |
| `refers_to` | `见 1. <title>` — cite an earlier entry instead of restating it; a `checkpoint-…` id must exist |
| `supersedes` | corrects an earlier `conclusion`/`observation`/`method`/`note`; the original stays visible, struck through, naming its correction |
| `evidence_ids` | artifacts and runs that support the claim; required for `conclusion` |
| `execution_status` | `wip`/`success`/`failed` as the record's current state |

A `failure` checkpoint may not be superseded: the failure happened, and rewriting it would be the one
thing this plugin exists to prevent. Record the recovery as a separate `resume`.

A `conditional` checkpoint is counterfactual reasoning — "if that preprint holds, this model is dead".
It carries no `evidence_ids` (there is no direct evidence for a counterfactual) and requires
`refers_to` naming the observation or conclusion it depends on. It renders in its own
**条件推演与可证伪预测** section. Do not force such reasoning into a `conclusion` (which would need an
irrelevant citation) or a `note` (which renders at the end, out of the argument).

A `note` may be corrected by a later `note`, but a `note` may not replace an `observation`, `method`
or `conclusion`: the correction would land in 恢复与备注 while the superseded finding stayed in
实验结果, struck through and pointing at nothing. Correct a finding with a finding.

`resume` and `note` checkpoints are not methods or results, so they are rendered in a trailing
**恢复与备注** section instead of the numbered lists: a "picked up the next day" note belongs there, not
as method 3.2. That section exists only when such a checkpoint exists, so the fixed spine keeps its
numbering otherwise.

Vague text is rejected for failures (`无结果`, `failed`, `error` alone). State what broke.

## References resolve by alias

Every reference field accepts **either** the server id (`artifact-…`, `run-…`) **or** the
`reference_id` you supplied at registration:

`artifact.input_ids`, `artifact.script_id`, `artifact.run_id`, `run.input_ids`, `run.output_ids`,
`run.id`, `checkpoint.evidence_ids`.

So register with an alias and use that everywhere instead of copying uuids:

```text
register_artifact(..., artifact={"role": "input", "location": "data/trace.csv",
                                 "description": "...", "reference_id": "alt-build-data"})
register_run(..., run={"reference_id": "run-figs", "backend": "local", ...})
register_artifact(..., artifact={"role": "figure", "run_id": "run-figs", ...})
```

The alias is resolved **before** the entry is stored, so what lands in `manifest.json` is always the
canonical id — a record cannot be valid at registration and invalid at `validate`. An update that omits
`reference_id` keeps the stored one, so a routine refresh never destroys the alias.

Two rules the error messages also state: `evidence_ids` takes artifacts and runs, **never** checkpoint
ids; and `run.id` on a fresh run means *update*, so omit it to create.

## Artifacts

`research_record_register_artifact(experiment_id, artifact={role, location, description, ...})`.
Registration reads the file; it never copies, moves or modifies it.

Roles: `raw`, `input`, `derived`, `script`, `figure`, `log`, `table`, `deliverable`.

`deliverable` is a finished artefact meant for a human reader (a briefing, a document). `derived` stays
an intermediate computation result. Neither name refers to `finalize`'s own PDF, which lives in
`reports/`.

Provenance fields:

- `sha256` computed in-process (bounded to 64 MiB per operation); a supplied checksum is recorded as
  `supplied_unverified`. A missing checksum means unverified evidence, never integrity proof.
- A path that does not exist yet is stored as `availability: missing` and reported by `validate`;
  re-register the same location and role once it exists and the entry refreshes in place.
- Paths outside `workspace_dir`, or scheme URLs (`ssh://`, `s3://`, `https://`, `slurm://`), are
  accepted but warned as non-portable, and are **never contacted**.
- A `raw` entry whose recorded checksum no longer matches is rejected; restore the bytes or use a new
  `task_id`.
- `role=figure` needs a producing `run_id`. Omit `input_ids` and `script_id` and they are inherited from
  that run; a figure with no run at all is rejected, because a picture without provenance is decoration.

## Runs

`research_record_register_run(experiment_id, run={backend, execution_status, command, environment,
host?, parameters?, input_ids?, output_ids?, failure?, external_id?, reference_id?})`.

`backend ∈ local | levin | slurm | external`. `host` is auto-filled for local/levin and required
otherwise — record the machine the computation actually ran on. `environment` is required: the
software, versions and seeds that make the run repeatable. Failed runs require `failure` text.

Order that works: register the script artifact and inputs → register the run with `input_ids` →
register figures against that run → update the run with `output_ids`. Run objects accept only the
declared fields, so link scripts through artifacts, not the run.

## Remote and HPC data

Raw remote data **stays remote**. Compute there and bring back only lightweight results.

- Register the original with `source_origin: remote_copy` plus `remote_host` and `remote_path`; an
  `ssh://` or `s3://` URL is the normal form.
- Landing an actual copy of a remote `raw`/`input` original additionally needs
  `remote_copy_permission` naming who authorized it, and is refused for large originals.
- Large pulled-back derived results produce a warning: keep them on the host and reference them.
- Report space on the host with `remote_space` at finalize, flagging entries of a gigabyte or more.

## Non-negotiables

Never overwrite originals, upload private data, silently fetch an external reference, delete scratch,
or commit large datasets. Completion implies no retention policy. Keep secrets out of commands,
metadata and URLs — URLs carrying userinfo or query strings are rejected outright.

## Figure provenance: the two working shapes

A figure must end up with `input_ids` and `script_id`. A run may now declare `script_id` itself, so both
shapes work:

| Shape | Calls |
|---|---|
| figure carries it | `register_artifact(role="figure", run_id=<run>, input_ids=[...], script_id=<script>)` |
| run carries it | register the script, then `register_run(script_id=<script>, input_ids=[...])`, then `register_artifact(role="figure", run_id=<run>)` |

The second shape is the tidier one: the run records what executed and what it read, and every figure it
produced inherits that without repeating it. Before this existed the run had no `script_id` field, so
the inheritance path the skill advertised could not be completed at all.

## Keeping the recorder out of the record

Work that is not the experiment must not become part of it. Two mechanisms exist, and they are
different: a pause prevents writing, an exclusion takes back what was already written.

### Pause: stop writing while you are working on something else

```
research_record_suspend(experiment_id, agent_id, action="pause",
                        reason="debugging the notebook plugin itself, out of scope")
...                                  # no checkpoint/artifact/run can be added here
research_record_suspend(experiment_id, agent_id, action="resume")
```

While a pause is open, `checkpoint`, `register_artifact` and `register_run` are refused with
`Recording is paused since <time> (<reason>)`. The reason is required and must say why the work is out
of scope — the report prints every window in 记录范围, so a gap in the record is stated instead of
silently missing. `validate`, `finalize`, `index`, `exclude` and the prune tools still work.

Use it the moment you notice the session is about the tooling rather than the science: fixing a plugin,
retrying an MCP call, inspecting your own report markup.

### Exclusion: set an entry aside without deleting it

```
research_record_exclude(experiment_id, agent_id, targets=["checkpoint-…", "artifact-…"],
                        reason="this recorded the recorder, not the experiment")
research_record_exclude(…, reason="restored after scope review", restore=True)
```

An excluded entry is not rendered: it disappears from 实验结果, from 材料, from the artifact table and
from the run list, and it can no longer be cited (an alias that resolves to it is "unknown"). It is not
deleted: the manifest keeps it, `revisions/` keeps every snapshot, and the appendix gains a
**记录范围：已搁置条目与暂停窗口** table listing each id with its reason. `restore` puts it back.

Two guards keep this honest rather than convenient:

- a reason of at least 8 characters is required for both actions;
- an artifact or run that a **live conclusion** cites cannot be excluded until that conclusion is
  corrected or excluded too. Otherwise the report would carry a supported-looking claim whose evidence
  is invisible.

What exclusion cannot do: it does not repair wrong scientific content. Fix an incorrect finding by
superseding it with `note`/`observation`, not by hiding it.
