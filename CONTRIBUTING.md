# Contributing

One maintainer, no CI secrets, no build server. Everything below runs on a laptop, offline. If you
only want to *use* the plugin, stop at [README.md](README.md) or [docs/lifecycle.md](docs/lifecycle.md).

Before you write anything, read the placement rule in [docs/README.md](docs/README.md#the-decision-procedure).
It decides whether your change belongs in the code, in the skill tree, here, or in `docs/`.

## What may be edited by hand

| Path | Edit by hand? | Why |
|---|---|---|
| `mcp/runner/*.py` (except the four below) | yes | the implementation |
| `mcp/runner/plugin_spec.py` | yes | the tool declaration; `compile` reads it |
| `mcp/runner/server.py` | **no** | generated from `plugin_spec.py` by `compile` |
| `.levin-plugin/` | **no** | compiled manifest + vendored SDK, gitignored |
| `dist/` | **no** | packaged `.levin-plugin.tgz` per release, gitignored |
| `tests/` | yes | the specification of record |
| `skills/**` | yes | `SKILL.md` has a hard size ceiling — see below |
| `workflows/` | yes | the stage chain as a Levin workflow |
| `README.md`, `docs/`, `CONTRIBUTING.md`, `CHANGELOG.md` | yes | this documentation system |

`examples/plot_style.py` and `skills/levin-research-notebook-runtime/scripts/plot_style.py` are
byte-identical on purpose: the skill ships the style for a worker that only has the skill, the demo
imports the copy next to it. Change both or neither; a `diff` between them is the check.

## Setting up

The plugin's managed runtime installs five pinned packages
(`jsonschema==4.23.0`, `filelock==3.16.1`, `reportlab==4.2.5`, `matplotlib==3.9.4`,
`bibtexparser==2.1.0`) declared in `plugin_spec.py`. If Levin has already deployed the plugin, that
environment exists under the Levin application-support directory and can run the suite directly:

```bash
"$HOME/Library/Application Support/Levin Harness/plugins/envs/levin-research-notebook/runner/<hash>/bin/python" \
  -m unittest discover -s tests
```

Otherwise create an equivalent environment — `uv venv && uv pip install` the five pins — or use any
Python 3.11 with them importable. Nothing else is required.

Add `pypdf` if you want a clean run; see [Running the tests](#running-the-tests) for why.

## Running the tests

```bash
node <creator>/scripts/levin-plugin-creator.cjs compile .   # 1. vendor the SDK
python -m unittest discover -s tests -v                     # 2. the whole suite
```

The working tree has 161 cases at the time of writing, 156 of which are in release `0.11.5`;
`grep -c 'def test' tests/*.py` is the authority, not this paragraph.

**Both steps are required, and the reason is not obvious.** `.levin-plugin/` is gitignored, so a
fresh clone has no vendored SDK, and `tests/test_schema_surface.py` imports `plugin_spec.py`, which
imports `levin_plugin_sdk`. Without `compile` the suite prints `ModuleNotFoundError: No module named
'levin_plugin_sdk'` and reports `Ran 149 tests … FAILED (errors=1)` — one *error* covering the whole
schema-surface file, not a skip. Measured on a fresh `git ls-files` export of this working tree
(161 cases): 149 ran before `compile`, 161 after.

**`pypdf` is optional in the design and not optional for a clean run.**
`tests/test_notebook.py::test_finalize_pdf_replay_and_report_integrity` imports `PdfReader` inside the
test body with no guard, so without `pypdf` it **errors**; the six tests in `test_reporting.py` that
read a page go through a `reader()` helper that calls `skipTest`, so they skip. The plugin's own
managed environment ships no `pypdf`, and running the release suite there reports exactly
`Ran 156 tests … FAILED (errors=1, skipped=6)`. If you see that, install `pypdf`; do not go looking
for a domain bug.

Single files, when you are iterating:

```bash
python -m unittest tests.test_notebook -v
python -m unittest tests.test_units -v
```

The suite writes scratch workspaces under `$TMPDIR/levin-research-notebook-tests/` and leaves them
there for inspection; override with `NOTEBOOK_TEST_SCRATCH`. Nothing in the suite touches the network,
and `tests/test_reporting.py` asserts that by patching `urlopen` and `os.system`.

### The end-to-end demo

```bash
python examples/computational_demo.py --workspace /tmp/notebook-demo
```

Synthetic Euler-vs-analytic decay: raw input → script → run → derived → figure → method/observation/
conclusion checkpoints → validate → finalize → index. It writes a real `levin_notebook/` and a
5-page PDF, prints the report path, and exits non-zero if `finalized` is false. This is the fastest
way to see what the tools produce, and it doubles as a smoke test of the whole lifecycle.

## Compile, validate, package

All commands run from the Creator skill directory; `<plugin-source>` is this repository root:

```bash
node scripts/levin-plugin-creator.cjs compile <plugin-source>
node scripts/levin-plugin-creator.cjs validate <plugin-source>
node scripts/levin-plugin-creator.cjs contract-test <plugin-source>
node scripts/levin-plugin-creator.cjs package <plugin-source>
```

What each one actually does, from running them:

| Command | Effect | Failure you will meet |
|---|---|---|
| `compile` | regenerates `mcp/runner/server.py`, `.levin-plugin/plugin.json`, `.levin-plugin/sdk.json`, vendors the SDK | none observed; it also *removes* a stale vendor `__pycache__` |
| `validate` | compiles nothing; checks the compiled manifest against the spec | `Vendored SDK file set differs from the current SDK; run creator compile` — caused by `__pycache__` inside `.levin-plugin/vendor/` |
| `contract-test` | starts the real MCP server and runs each tool's success fixture | `preflight reported ready=false` — the pinned packages are not importable by the Python on `PATH` |
| `package` | `compile`, then writes `dist/levin-research-notebook-<version>.levin-plugin.tgz` | refuses `__pycache__` outside excluded names, symlinks, hard links, oversized files |

Two operational notes:

- **A stale vendor `__pycache__` breaks `validate` but `compile` is the fix.** Confirmed both ways:
  create `.levin-plugin/vendor/python/levin_plugin_sdk/__pycache__/x.pyc`, `validate` fails, `compile`
  succeeds and the directory is gone, `validate` passes. `package` is not blocked by it (it runs
  `compile` first), so do not use `package` as a substitute for understanding the failure.
- **`contract-test` needs the runtime packages on `PATH`.** With the managed environment first on
  `PATH` it passes; with a bare `python3` whose `reportlab` version differs it fails on
  `preflight` readiness, which is a real signal about the environment, not about the code.

`validate` does **not** check the version string in `README.md`; the structure gate below does. It
also does not check `docs/`, so a broken documentation link is invisible to it — see
[Documentation checks](#documentation-checks).

## Cutting a release

`version` lives in `mcp/runner/plugin_spec.py` and is compiled into `.levin-plugin/plugin.json`. The
README quotes it, and `.github/scripts/check_structure.py` fails if the two disagree. So:

1. **Decide the number.** Patch for fixes, minor for a new tool or a new authoring field, `0.x` means
   the manifest schema may still gain fields.
2. **Bump `version='X.Y.Z'`** in `mcp/runner/plugin_spec.py`.
3. **Bump the version in `README.md`** (it is in the first sentence, as `(vX.Y.Z)`).
4. **Write the `CHANGELOG.md` entry** under a new `## X.Y.Z` heading, moving anything from
   *Unreleased* up. Describe effects on callers and readers, not internals.
5. **Run the gates:**
   ```bash
   python3 .github/scripts/check_structure.py   # SKILL.md size, skill links, version agreement
   python3 .github/scripts/check_links.py       # every relative link and #anchor
   python -m unittest discover -s tests
   python examples/computational_demo.py --workspace /tmp/release-check
   ```
6. **`compile`, then `validate`, then `contract-test`, then `package`** as above. The tarball lands
   in `dist/`, which is gitignored — publish it wherever you publish releases, do not commit it.
7. **Commit** `plugin_spec.py`, `README.md`, `CHANGELOG.md` and whatever changed with a message that
   states the behaviour change, then tag `X.Y.Z`.

Do not hand-edit `.levin-plugin/plugin.json` to bump the version: `compile` overwrites it and the
SDK hash in `sdk.json` would no longer match the vendored tree.

## Editing the skill tree

`skills/levin-research-notebook-runtime/SKILL.md` is capped at **12 000 characters** and currently
sits at 3 508, so there is room — but the shape is the point, not the room:

- `SKILL.md` is a router: five stages, the invariants, and a table naming which reference file to load
  at which stage. It is not a manual, and it must not restate a reference file.
- One fact, one reference file. If something is needed at two stages, it belongs in the earlier file
  and the later one links it.
- Imperative, short, stage-ordered. An agent reads these mid-task.
- Version 0.11.5 split the tree precisely because `SKILL.md` had reached 11 989 characters with
  duplicated content that had started to disagree with `references/limits.md`. Do not undo that.

`check_structure.py` enforces the size, the frontmatter `name` matching the directory, and that every
relative link in `SKILL.md` resolves (including `#anchors`). It *warns* about a reference file not
linked from `SKILL.md` — that warning means the file is dead weight in a tree that is supposed to be
loaded selectively.

## Documentation checks

```bash
python3 .github/scripts/check_links.py        # relative files and #anchors, all tracked *.md
python3 .github/scripts/check_structure.py    # SKILL.md ceiling, skill links, version agreement
```

Both are offline. `check_links.py` skips fenced code and inline code, so examples like
`[start](references/start.md)` inside a fence are not checked — write real links as real links.
`.github/` is maintained separately from this documentation; if a documentation change needs a new CI
step, ask rather than editing a workflow.

## What a change usually touches

| Change | Files, in the order you will need them |
|---|---|
| new authoring field | `SCHEMA` + writer in `notebook.py` → `plugin_spec.py` schema → `tests/test_schema_surface.py` → `docs/manifest-and-report.md` |
| new gate or rejection | `validate_manifest` or the writer → a test in `tests/test_notebook.py` → `skills/.../references/limits.md` |
| section template change | `Notebook._template` → `tests/test_record_types.py` → `skills/.../references/report.md` **and** `docs/manifest-and-report.md` |
| renderer behaviour | `reporting.py` → `tests/test_reporting.py` → `skills/.../references/report.md` → `docs/limitations.md` if a limit moved |
| new unit family | `units.py` → `tests/test_units.py` → `skills/.../references/report.md` |
| new tool | `plugin_spec.py` → `adapter.py` dispatch → `Notebook` method → tests → `README.md` tool table → `CHANGELOG.md` |

## Style

- Python: standard library plus the five pins; no new runtime dependency without a reason that
  survives the README's "no service, no network" claim. Type hints are welcome, not required.
- Prose in the repository is English; the report's own section names, table headers and generated
  lines are Chinese because the reports are. Do not translate the template.
- Comments explain *why* a rule exists. The existing code does this; match it.
- Claims in prose must be checkable in source. If you cannot point at a file, constant or test, do not
  write the claim — or state it as unverified. [docs/limitations.md](docs/limitations.md) is where
  unverified lives.
