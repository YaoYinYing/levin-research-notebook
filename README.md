# Levin Research Notebook

A personal Levin plugin (v0.11.1) that keeps scientific evidence alive past the chat window.
It is a **record-lifecycle** plugin over a real filesystem workspace: it records what was done,
what produced it, and what was concluded. It does **not** run your science — compute stays in
Levin Jobs, Slurm, or your own process, and this plugin captures their provenance.

## What it does

- **Record skill** — `skills/levin-research-notebook-runtime/SKILL.md` drives the agent through
  init → checkpoints → artifact/run registration → validate → finalize, with the stage chain in
  `workflows/standard-research-notebook.md` and limits/recovery in `references/limits.md`.
- **Deterministic MCP tools** — seven `research_record_*` tools that mutate one canonical
  `manifest.json` per experiment. Same inputs, same filesystem result; no LLM in the write path.
- **Delegated visualization** — when figures help the objective, the parent hands the specialist
  brief in `references/visualization-agent.md` to a general-purpose worker; the parent keeps
  scientific acceptance and supplies `reviewed_by`.
- **Dimensional checking** — numeric results are recorded with units in `quantities`; a wrong
  dimension blocks `finalize`, an unconventional-but-legal unit only warns, and no value is ever
  silently converted.
- **Report generation** — `finalize` writes an editable `report.md`, `report.qmd` and a standalone
  `report.tex`, plus a guaranteed fixed-layout `report.pdf` rendered by pinned ReportLab.
  Math (`$...$`, `$$...$$`) renders offline via matplotlib mathtext, so no TeX install is required;
  `report.tex` is for readers who do have one.

## On-disk layout

Everything lives under the chosen `workspace_dir`. `manifest.json` is canonical; `record.md` is a
generated readable view; `notes.md` is for hand-written human notes.

```
workspace_dir/
├── levin_notebook/
│   ├── index.md                 # generated catalog (manifests are authoritative)
│   ├── manifest.schema.json     # written on first init
│   └── experiments/exp-<32hex>/
│       ├── manifest.json        # canonical state (immutable history in revisions/)
│       ├── record.md            # generated view
│       ├── notes.md             # editable human notes
│       ├── scripts/  figures/  data/  reports/  revisions/
│       ├── report.md  report.qmd  report.pdf   # written by finalize
│       └── revisions/NNNNNN-<uuid>.json         # prior manifests
└── levin_scratch/<task_id>/<agent_id>/          # transient work; never holds raw evidence
```

## MCP tools

- `research_record_init` — create or resume an experiment by stable `task_id`; allocate scratch.
- `research_record_checkpoint` — append a method/observation/failure/conclusion/resume note.
- `research_record_register_artifact` — reference a file (raw/input/derived/script/figure/log/table)
  without copying; bounded SHA-256, figures require `input_ids`/`script_id`/`run_id`.
- `research_record_register_run` — record execution provenance (local/levin/slurm/external),
  command, environment, seeds, inputs, outputs; update an existing run by `run.id`.
- `research_record_validate` — read-only schema, reference, local-file and bounded integrity check.
- `research_record_finalize` — validate terminal status + visualization assessment, emit report
  sources and fixed-layout PDF; check `finalized`, `report.render_state`, `validation` (not `ok` alone).
- `research_record_index` — search manifests by title/objective/ID with offset/limit paging.

## Filesystem-as-source-of-truth guarantees

- No database, web service, scheduler, telemetry, model download, or external process.
- Never overwrites original data — raw/input files are referenced, never copied or rewritten.
- External references (e.g. `s3://…`) are **never fetched**; they stay `external_unverified`.
- No automatic deletion — scratch, old revisions, and failed records persist for inspection.
- Symlinked managed roots/output paths are rejected, and any managed path escaping the workspace
  is rejected before a write. (Not a sandbox against a racing malicious process.)
- Bounded work: manifest ≤ 2 MB and ≤ 500 artifacts/runs/checkpoints; ≤ 64 MiB hashed per
  registration and ≤ 64 MiB total per validation (a supplied digest stays `supplied_unverified`);
  report ≤ 200 000 characters, 20 figures, 500 pages. Larger inputs are referenced, not absorbed.
- Local file locks serialize metadata mutations; canonical manifest is published atomically and
  prior revisions are immutable (NFS/distributed locking guarantees are not claimed).

## Running tests and the demo

Use the plugin's uv virtualenv (created by the runtime; paths below assume the plugin directory
is the working directory). The demo resolves its own `mcp/runner` path, so it needs no `PYTHONPATH`.

```bash
# Automated regression + offline reporting tests
levin_scratch/.venv/bin/python -m unittest discover -s tests -v

# Representative end-to-end workflow (synthetic Euler-vs-analytic decay) in a scratch workspace
levin_scratch/.venv/bin/python examples/computational_demo.py --workspace /tmp/notebook-demo
```

## Building with the Creator CLI

From the Creator skill directory, with `<plugin-source>` pointing at this plugin folder:

```bash
node scripts/levin-plugin-creator.cjs compile <plugin-source>
node scripts/levin-plugin-creator.cjs validate <plugin-source>
node scripts/levin-plugin-creator.cjs contract-test <plugin-source>
node scripts/levin-plugin-creator.cjs package <plugin-source>
```

## Deployment

Plugin id: `levin-research-notebook`. Logical MCP alias: `server_name: "levin-research-notebook__runner"`;
the one enabled physical deployment is `levin-research-notebook__runner__local`. v0.x is local-only:
there is **no Remote SSH transfer support** (runtime `remoteSsh: false`). Point `workspace_dir` at the
real local workspace — never a transient remote staging copy — and record HPC/Slurm data as external
references rather than notebook writes.

## Limitations (honest)

- Local-only in v0.x; Remote SSH transfer is unsupported, not merely untested.
- Quarto and Typst are optional and are **not** installed; the guaranteed output is the ReportLab
  fixed-layout PDF. Edit `report.qmd` yourself and register any external render as an artifact.
- Markdown tables and complex math render as **literal text** in the PDF; real typesetting needs Quarto.
- No automatic task-lifecycle hook and no installable subagent type — both are skill-driven, invoked
  through the existing `Agent` tool with `general-purpose` workers.
- Schema validity and matching checksums prove structure and identity only; they do **not** prove the
  science is correct or independently reproducible.
