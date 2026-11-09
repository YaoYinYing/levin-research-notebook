# Evidence: checkpoints, artifacts, runs

## Checkpoints

`research_record_checkpoint(experiment_id, agent_id, kind, text, ...)` with
`kind ∈ method | observation | failure | conclusion | resume | note`.

One meaningful finding per checkpoint, not one per command. Give each a short `title`: the report
renders methods, observations, failures and conclusions as numbered subsections grouped under their
section, and the title is the heading.

| Field | Effect |
|---|---|
| `replica`, `retry` | appends `replica #n` / `retry #n` to the heading |
| `when_note` | a quoted line under the heading, for a method that spans dates |
| `refers_to` | `见 1. <title>` — cite an earlier entry instead of restating it |
| `supersedes` | corrects an earlier `conclusion`/`observation`/`method`; the original stays visible, struck through, naming its correction |
| `evidence_ids` | artifacts and runs that support the claim; required for `conclusion` |
| `execution_status` | `wip`/`success`/`failed` as the record's current state |

A `failure` checkpoint may not be superseded: the failure happened, and rewriting it would be the one
thing this plugin exists to prevent. Record the recovery as a separate `resume`.

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
