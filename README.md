# Levin Research Notebook

A personal Levin plugin (v0.11.9) that keeps scientific evidence alive past the chat window. It is a
**record-lifecycle** plugin over a real filesystem workspace: it records what was done, what produced
it, and what was concluded. It does **not** run your science — compute stays in Levin Jobs, Slurm, or
your own process, and this plugin captures their provenance.

Eight `research_record_*` MCP tools mutate one canonical `manifest.json` per experiment; `finalize`
turns it into an editable Markdown/Quarto/LaTeX source and a fixed-layout PDF. No database, no service,
no network, no telemetry, no LLM in the write path.

**Start here:** [why this and not an ELN](docs/why-not-an-eln.md) ·
[the five stages with a real transcript](docs/lifecycle.md) ·
[how the docs are organised](docs/README.md)

## Quickstart

The plugin runtime installs five pinned packages (`jsonschema`, `filelock`, `reportlab`, `matplotlib`,
`bibtexparser`). Two steps get you a working toolchain — `compile` vendors the SDK that the schema test
imports, and the suite runs on the standard library alone:

```bash
node <creator>/scripts/levin-plugin-creator.cjs compile .   # vendors .levin-plugin/ (gitignored)
python -m unittest discover -s tests                        # 161 cases in the working tree (156 in release 0.11.5)
python examples/computational_demo.py --workspace /tmp/notebook-demo
```

Counts drift; `grep -c 'def test' tests/*.py` is the authority. The demo is a synthetic Euler-vs-analytic
decay study: raw input → script → run → derived data → figure → method/observation/conclusion
checkpoints → validate → finalize → index. It writes a real `levin_notebook/` with a 5-page PDF, and
it is the fastest way to see what the tools actually produce. Why both prerequisites are necessary —
and the two failures you will hit without them — is in
[CONTRIBUTING](CONTRIBUTING.md#running-the-tests).

## What it does

- **Record skill, not a manual** — `SKILL.md` is a 3 508-character entry point that routes one
  lifecycle stage at a time into `references/`. An agent mid-task loads `start` → `evidence` →
  `report` → `finalize`, never the whole tree. The stage chain also exists as a workflow:
  [`workflows/standard-research-notebook.md`](workflows/standard-research-notebook.md).
- **Deterministic tools** — same inputs, same filesystem result. Each call validates before and after,
  publishes the manifest atomically, and keeps every prior revision.
- **Dimensional checking** — numeric results are recorded with units in `quantities`; a wrong dimension
  blocks `finalize`, a legal-but-unconventional unit is reported as a convention difference, and **no
  value is ever converted or rewritten**.
- **Delegated visualization** — when figures help the objective, the parent hands the specialist brief
  in `references/visualization-agent.md` to a general-purpose worker and keeps scientific acceptance,
  supplying `reviewed_by` itself.
- **Reports that survive the tool** — `finalize` writes `report.md` (authority), `report.qmd`,
  `report.tex`, and a ReportLab PDF. Math renders offline through matplotlib mathtext, so no TeX
  install is required; `report.tex` is for readers who have one.

## On-disk layout

Everything lives under the chosen `workspace_dir`. `manifest.json` is canonical; `record.md` is a
generated view; `notes.md` is yours.

```
workspace_dir/
├── levin_notebook/
│   ├── index.md                 # generated catalog (manifests are authoritative)
│   ├── manifest.schema.json     # written on first init
│   └── experiments/exp-<32hex>/
│       ├── manifest.json        # canonical state
│       ├── record.md            # generated view
│       ├── notes.md             # editable human notes
│       ├── scripts/  figures/  data/  reports/  revisions/
│       ├── report.md  report.qmd  report.tex  report.pdf   # written by finalize
│       └── revisions/NNNNNN-<uuid>.json                    # prior manifests, immutable
└── levin_scratch/<task_id>/<agent_id>/          # transient work; never holds raw evidence
```

## The eight tools, in one line each

Intent only — argument schemas live in [`mcp/runner/plugin_spec.py`](mcp/runner/plugin_spec.py), which
is the authority and is not restated here.

| Tool | Owns |
|---|---|
| `research_record_init` | create or resume an experiment by stable `task_id`; allocate per-agent scratch |
| `research_record_checkpoint` | append a method / observation / failure / conclusion / resume / note entry |
| `research_record_register_artifact` | reference a file by role without copying; bounded SHA-256 and figure provenance |
| `research_record_register_run` | execution provenance — backend, host, command, environment, seeds, inputs, outputs |
| `research_record_validate` | read-only structural check **plus** every gate `finalize` will apply |
| `research_record_finalize` | emit report sources and the PDF; commit terminal status only if the gates pass |
| `research_record_prune_reports` | delete old PDF snapshot folders on explicit request; `dry_run` lists first |
| `research_record_index` | search records by term, with optional per-record counts |

## Guarantees the code enforces

Most of these are a rejection in [`mcp/runner/notebook.py`](mcp/runner/notebook.py) rather than a
convention; the renderer's no-network property is an absence of code, asserted by a test that patches
`urlopen` and `os.system`.

- Never overwrites original data — `raw`/`input` files are referenced and hashed in place; a changed
  raw file is rejected rather than silently re-registered.
- Never fetches an external reference — `ssh://`, `s3://`, `https://` stay `external_unverified`.
- Never deletes automatically — scratch, old revisions and failed records persist; only an explicit
  `prune_reports` removes report snapshots, and it always keeps one.
- Never writes outside the workspace, and rejects any symlink on a managed path.
- Bounded work: manifest ≤ 2 MB, ≤ 500 artifacts/runs/checkpoints, ≤ 64 MiB hashed per registration,
  ≤ 64 MiB total per validation; report ≤ 200 000 characters, 20 figures, 500 pages. Larger inputs are
  referenced, not absorbed.
- Local file locks serialize mutations; the manifest is published atomically and prior revisions are
  immutable (`revisions/NNNNNN-*.json` is never rewritten). NFS/distributed locking is not claimed.

## Deployment

Plugin id `levin-research-notebook`; logical MCP alias `server_name: "levin-research-notebook__runner"`;
one enabled physical deployment, `levin-research-notebook__runner__local`. v0.x is **local-only** —
the manifest declares `remoteSsh.supported: false`, and that is a deliberate refusal, not an untested
feature. Point `workspace_dir` at the real local workspace, never a transient remote staging copy, and
record HPC/Slurm data as external references.

## Limitations, honestly

- **Local-only**, as above. Remote SSH transfer is unsupported.
- **Font coverage is platform-shaped.** macOS is the executed path; the Linux and Windows candidate
  chains have never run on a real host. A machine with no CJK face prints `[U+XXXX]` and says so in
  `preflight.fonts.cjk_available` — see [docs/limitations.md](docs/limitations.md).
- **The renderer is a layout, not a typesetter.** Tables become a grid and long cells are truncated
  with `…` (the full text stays in `record.md`); a pipe line without a `| --- |` separator prints
  literally; one-line `$$ … $$` renders as a raster image and is not searchable; a multi-line `$$`
  block is not recognised. Quarto/Typst are not installed.
- **No automatic task-lifecycle hook and no installable subagent type** — both are skill-driven,
  invoked through the existing `Agent` tool with `general-purpose` workers.
- **`ok` is not completion.** Read `finalized`, `report.render_state` and `validation`; a blocked
  attempt leaves a source-only folder with no PDF.
- **Structure is not science.** Schema validity and matching checksums prove identity and consistency.
  They never prove a conclusion correct or independently reproducible.

The full accounting — what has never been executed, what the test suite hides, what the record model
cannot express — is [docs/limitations.md](docs/limitations.md).

## Where to read what

| Question | Page |
|---|---|
| Is this the right tool instead of an ELN? | [docs/why-not-an-eln.md](docs/why-not-an-eln.md) |
| How do I actually run a task through it? | [docs/lifecycle.md](docs/lifecycle.md) |
| Where does this field come from, and will it print? | [docs/manifest-and-report.md](docs/manifest-and-report.md) |
| Which file do I change? | [docs/architecture.md](docs/architecture.md) |
| What does not work? | [docs/limitations.md](docs/limitations.md) |
| Tests, release, doc rules | [CONTRIBUTING.md](CONTRIBUTING.md) |
| What changed between versions | [CHANGELOG.md](CHANGELOG.md) |
| What an agent should do at this stage | [`skills/levin-research-notebook-runtime/SKILL.md`](skills/levin-research-notebook-runtime/SKILL.md) |

## Building with the Creator CLI

Run from the Creator skill directory, with `<plugin-source>` pointing at this folder:

```bash
node scripts/levin-plugin-creator.cjs compile <plugin-source>
node scripts/levin-plugin-creator.cjs validate <plugin-source>
node scripts/levin-plugin-creator.cjs contract-test <plugin-source>
node scripts/levin-plugin-creator.cjs package <plugin-source>
```

`validate` needs a clean tree: a stale `__pycache__` inside `.levin-plugin/vendor/` fails the vendored
SDK file-set check, and `compile` is the fix. `contract-test` runs the real MCP server, so the pinned
packages must be importable on `PATH`. Both failure modes are documented in
[CONTRIBUTING.md](CONTRIBUTING.md#compile-validate-package).
