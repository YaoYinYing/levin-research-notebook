# Module map, invariants, and where to change X

Nine Python modules, 3 698 lines, no service and no network. The map below is written for the person
about to change behaviour: what each file is responsible for, what it must never do, and which file a
given change belongs in.

```
mcp/runner/
├── plugin_spec.py     58    the only declaration of tool names + argument schemas
├── server.py          17    Contract v3 entrypoint; adds the vendored SDK to sys.path
├── setup_runtime.py   11    runtime install probe; prints the Python version
├── adapter.py         61    MCP handler → Notebook method; preview handling; error mapping
├── notebook.py      1375    manifest schema, lifecycle, gates, Markdown view, index, pruning
├── reporting.py     1255    offline fixed-layout PDF: fonts, layout, tables, figures, math, glyphs
├── units.py          510    dimensional analysis for recorded quantities (no conversion)
├── bibtex_index.py   141    .bib / inline BibTeX → reference records; metadata hygiene
└── latex_export.py   270    generated Markdown → standalone .tex (predictable subset only)
```

## Per-module responsibility and invariants

### `plugin_spec.py` — the schema authority

Declares the plugin and its ten tools (`health`, `preflight`, eight `research_record_*`). One `DEFS`
list holds each tool's JSON schema, a contract-test fixture, and whether the tool mutates files.

**Invariants.** No behaviour lives here. The mutation flag drives `runtime_contract.effect`
(`file_mutation` vs `read`) and `permissionClass`; `remote_ssh=False` is the declared deployment
posture. `tests/test_schema_surface.py` fails if the library accepts an authoring field the schema
does not expose, so a new field is added here and in `notebook.py` together or not at all.

**Change here for:** a new tool, a new argument, a changed enum, a new default, a longer limit on an
argument string.

### `server.py` / `setup_runtime.py` — plumbing

`server.py` is generated from the spec by the Creator CLI: it puts `.levin-plugin/vendor/python` on
`sys.path` and calls `plugin.serve(PLUGIN_ROOT)`. `setup_runtime.py` prints the interpreter version so
the runtime install can verify itself.

**Invariants.** Do not hand-edit `server.py`; regenerate with `compile`. Neither file may acquire
business logic — a bug there is invisible to the test suite.

### `adapter.py` — the only MCP-aware layer

`preflight` reports dependency readiness and the resolved font faces. `invoke` pops `preview` and
`workspace_dir`, renames `experiment_id`→`eid` and `text`→`body` for `Notebook`, dispatches, and wraps
any exception as `PluginError(code='notebook_validation_error', stage=operation)`.

**Invariants.** `preview: true` must return before any record is read, created or finalized — it is a
schema-shape check, and reporting a preview as a performed experiment is the failure mode it exists to
prevent. Every other exception must be converted, because an uncaught traceback crosses the MCP
boundary as a protocol fault rather than a domain error.

**Change here for:** a new tool's dispatch line, the preflight checks, or the error code.

### `notebook.py` — the state machine

The largest module, and the one that owns every rule. Five regions:

| Region | Lines | Content |
|---|---|---|
| constants + schema | 10–178 | `MAX_RECORD`, byte budgets, `SCHEMA` (48 properties), the vague-text blacklist |
| guard + persistence | 179–250 | `__init__`, `_guard`, `_lock`, `_atomic`, `_dir`, `_load`, `_save`, `_write_index` |
| lifecycle | 252–530 | `init`, `mutate`, `checkpoint`, `location`, `register_artifact`, `register_run` |
| gates | 532–648 | `validate_manifest(final=…)`, `validate` |
| output + queries | 649–890 | `finalize`, `prune_reports`, `index` |
| Markdown view | 890–1375 | `_stamp`/`_cell` helpers, per-section builders, `_template`, `markdown` |

**Invariants, each with the reason it is not negotiable:**

- **A managed path never escapes the workspace.** `_guard` rejects any path outside `workspace_dir`
  and any **symlink** on the path (`_guard`, line 189). `Notebook.__init__` additionally rejects a
  symlinked `levin_notebook/` or `levin_scratch/`. This is not a sandbox against a malicious process
  racing the filesystem; it is a guarantee that a write lands where the record says it does.
- **The canonical manifest is published atomically, and history is immutable.** `_atomic` writes to
  `levin_scratch/notebook-system/writer/`, `fsync`s, then `os.replace`s. `_save` first snapshots the
  current manifest to `revisions/NNNNNN-<uuid>.json`, archives a hand-edited `record.md` to
  `revisions/human-record-<uuid>.md`, then writes snapshot → `manifest.json` → `record.md` →
  `index.md`. Nothing ever rewrites a `NNNNNN-*.json`.
- **Validation happens before persistence, in both directions.** `_load` validates what it reads;
  `_save` validates what it writes. A rejected mutation therefore leaves manifest, revisions and
  `record.md` byte-identical — `tests/test_notebook.py::test_schema_rejection_rolls_back_manifest_and_revisions`
  asserts exactly that.
- **Only a *successful* finalize is memoised.** `mutate` fingerprints the payload and, when
  `request_id` is supplied, stores the receipt in `manifest.requests`. `finalize` passes
  `memoize=lambda result: bool(result.get('finalized'))`, so a blocked or render-failed attempt leaves
  the id unconsumed and the same call can be retried after clearing the gate. Reusing an id with a
  different payload raises `request_id reused with different content`.
- **One lock per mutation.** `init`, `mutate` and pruning take a `FileLock` on
  `levin_notebook/.notebook.lock` with a 10 s timeout. `index` and `validate` do not lock — `validate`
  writes nothing at all, which is why it is safe to call at any time.
- **Omitted ≠ cleared in `finalize`.** `provided[...]` records whether a list/dict argument was
  `None`; only provided ones are assigned. Scalar `purpose`, `environment_location`, `record_type`,
  `font_profile` and `synthesis` use truthiness instead.
- **Raw evidence is immutable.** Re-registering the same `(location, role)` refreshes the entry in
  place — except that a `raw` entry whose recorded SHA-256 differs from the file is **rejected** and
  the existing record is retained (`register_artifact`, line 378). A path that does not exist yet is
  stored as `availability: missing` and re-registered later in place.
- **Nothing is deleted except report snapshots, on explicit request.** `prune_reports` keeps at least
  one snapshot (newest success, or newest attempt when none succeeded), touches only
  `reports/report-<32hex>/`, and bumps the revision.

**Change here for:** a new authoring field, a new gate, a rejection message, the section template
(`_template`), the space accounting, index semantics, or the pruning policy.

**Do not change here:** the layout of a report section without reading
[manifest-and-report](manifest-and-report.md) and
[`references/report.md`](../skills/levin-research-notebook-runtime/references/report.md) — both name
the same mapping for different readers.

### `reporting.py` — offline rendering

Markdown is treated as data. Recognised constructs: headings, fenced code (with a small tokeniser),
tables (a real grid), block quotes, bullets, footnote lines, rules, `\pagebreak`, `\figures`,
`\figure{artifact-id}`, display math, and inline styles. Everything else is literal text.

**Invariants.**

- **No external process, network, or renderer daemon.** A `urlopen`/`os.system` guard is asserted by
  `tests/test_reporting.py::test_markdown_html_and_code_are_inert`. Math is rasterised locally by
  matplotlib's mathtext, so no TeX install is implied.
- **Fonts resolve per report, never globally.** `resolve_fonts(profile)` is `lru_cache`d and returns an
  immutable resolution; three profiles (`scientific-cjk`, `cjk-sans`, `latin-only`) plus `auto`. A
  missing CJK face is reported in two places — `preflight.fonts.cjk_available` before rendering and
  `report.fonts.notes` after — because otherwise it is silent in the PDF.
- **Only TrueType outlines are usable.** ReportLab raises `TTFError` on `.otf` CFF outlines, which is
  why each candidate chain carries several platform spellings rather than one expected name.
- **Missing glyphs are visible, not dropped.** They print as `[U+XXXX]` and are listed in
  `unsupported_codepoints`; sub/superscripts are transliterated to caret notation and listed in
  `transliterated_codepoints`. `check_glyphs` probes prose against serif+CJK faces and code against
  mono separately — probing prose against Menlo passed a `⇒` that still printed as tofu.
- **Bounded work.** `MAX_TEXT_CHARS` 200 000, `MAX_FIGURES` 20, `MAX_PAGES` 500, `MAX_IMAGE_BYTES`
  25 MiB, 40 M pixels; wide tables shrink type and truncate cells with `…` (the full text stays in
  `record.md`), so the grid never overflows the page.

**Change here for:** a new Markdown construct, typography, figure placement, page geometry, the
glyph probe, or a renderer limit.

### `units.py` — dimensional checking

Eighteen named quantity families (`length`, `time`, `mass`, `amount`, `molarity`, `potential`,
`temperature`, `molar_energy`, `force`, `force_constant`, `pressure`, `area`, `volume`, `density`,
`rate`, `velocity`, `angle`, `fraction`), a unit table with SI factors, and `check` / `check_all` /
`summary`.

**Invariants.**

- **It never converts and never rewrites a value.** `check` reads `quantity["value"]` and appends
  issues; nothing assigns back into the dict. The report prints the recorded unit next to the
  canonical one and leaves the number alone.
- **Severity is deliberate.** Wrong dimension, unparsable unit, missing unit for a name that implies
  one, unknown name with no declared `dimension`, negative uncertainty, uncertainty/unit mismatch,
  one name in two scales, duplicate name per replica — all block `finalize`. A legal but
  unconventional scale does not block when `unit_acknowledged: true`; it is reported as 惯例差异.
- **`dimension` is a formula, not a unit.** `L`, `M L^2 T^-2 N^-1`, `1`. It replaces the alias table
  for domain-specific names such as `d_attack`; it does not change the number.
- **Conventional decades do not warn.** `mM`, `µM`, `mV` are declared conventional per family so that
  a warning still means something: `rmsd` in `nm` against an Å notebook still reports.

**Change here for:** a new unit spelling, a new family, a conventional-set change, or a new issue code
(and then add it to `BLOCKING_UNIT_CODES` in `notebook.py` if it must block).

### `bibtex_index.py` — references

Parses a workspace-relative `.bib` or inline text with `bibtexparser` v2 (max 2 000 entries), maps
each entry to a reference record, derives `citation` and `metadata_issues`, and merges explicit
overrides field by field.

**Invariants.** Only metadata is read: a `file = {...}` attachment is never opened, and no DOI is
resolved over the network. Derived fields (`DERIVED_FIELDS = ("metadata_issues",)`) are recomputed and
cannot be overridden by stale hand-written text. Unparsable blocks become `bibtex_warnings`, never
silent drops.

**Change here for:** field mapping, the hygiene rules, or the entry cap.

### `latex_export.py` — the .tex sibling

Translates the *generated* Markdown into a standalone `article` for xelatex/lualatex. Deliberately
narrow: only constructs the notebook itself emits, everything unrecognised passes through escaped.

**Invariant.** It is a convenience artefact. The shipped PDF never depends on it, a failure is written
into the `.tex` as a comment rather than failing `finalize`, and it never compiles anything.

## Where does X go?

| I want to… | File |
|---|---|
| add or rename a tool argument | `plugin_spec.py` + the corresponding `Notebook` method + `tests/test_schema_surface.py` expectation |
| add a field to the manifest | `SCHEMA` in `notebook.py`, the writer method, the `finalize` plumbing if it is report content, then [manifest-and-report](manifest-and-report.md) |
| tighten a gate or change a rejection message | `validate_manifest` (gates) or the writer method (input validation) |
| change the section order or a heading | `Notebook._template` (+ both doc tables named above) |
| change how a section is laid out | the relevant `_sec_*` builder in `notebook.py` |
| change page layout, fonts, table or figure behaviour | `reporting.py` |
| add a quantity family or unit | `units.py` |
| change reference parsing | `bibtex_index.py` |
| change what an agent is told to do | `skills/levin-research-notebook-runtime/` |
| change how a *human* understands the design | `docs/` — see [docs/README](README.md) |

## The test suite

156 test cases at commit `15195ea` (`0.11.5`), in seven files, standard library only:

```bash
python -m unittest discover -s tests
```

`tests/test_notebook.py` (81) covers the lifecycle, rollback, memoisation, gates and pruning;
`test_reporting.py` (21) the renderer; `test_units.py` (17) dimensional cases; `test_latex_export.py`
(13) the TeX subset; `test_schema_surface.py` (12) guards spec↔library agreement; `test_record_types.py`
(7) the three spines; `test_bibtex_index.py` (5) parsing and merge. Six `test_reporting.py` cases read
a page through a `reader()` helper that skips when `pypdf` is absent, and one `test_notebook.py` case
imports `PdfReader` unguarded and therefore errors without it — see [limitations](limitations.md).

Counts are quoted at a commit on purpose: this page is not the authority for them, `grep -c 'def test'
tests/*.py` is.

Tests are the specification of record for the invariants above; when prose and test disagree, the test
runs and the prose does not.
