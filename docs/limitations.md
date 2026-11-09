# Known limitations, honestly stated

Two categories, kept apart on purpose: what the code **refuses** (documented for callers in
[`references/limits.md`](../skills/levin-research-notebook-runtime/references/limits.md)) and what
the maintainer **has not verified**. This page is the second category, plus the sharp edges the first
one does not make obvious.

## Never executed on a real host

The font candidate chains name macOS, Linux and Windows paths
([`reporting.py`](../mcp/runner/reporting.py), `_LATIN_SERIF` … `_CJK_SANS`). Here is what has actually
been run:

| Branch | Status | Evidence |
|---|---|---|
| macOS 27.0.1 arm64, Python 3.11.11 | executed, this session | `resolve_fonts('scientific-cjk')` → `cjk_available: true`, faces `Songti.ttc`/`STHeiti Medium.ttc`; the demo renders a 5-page PDF |
| Linux candidate paths (Liberation, DejaVu, Noto CJK, arphic, wqy) | **never executed** | paths exist in the chains only; no Linux host has run the renderer |
| Windows candidate paths (`times.ttf`, `consola.ttf`, `simsun.ttc`, `msyh.ttc`) | **never executed** | same; written from font-file conventions, not from a run |
| macOS without a CJK face | **not executed on real hardware** | simulated by emptying every CJK chain: `cjk_available: false`, `notes` names both roles, and Chinese renders as `[U+XXXX]` — the mechanism works, the real-host case is unverified |
| The `.otf` rejection path | never exercised with an actual CFF font | `_register_once` tolerates `TTFError`; no `.otf` was ever attempted |

A Linux or Windows user is the first person to run those branches. The failure mode is designed to be
loud — `preflight.fonts.cjk_available` and `report.fonts.notes` — but "designed to be loud" is not
"tested".

## Remote and multi-host

- **Local deployment only.** `plugin_spec.py` declares `remote_ssh=False` and the compiled manifest
  declares `remoteSsh.supported: false` with `default: false`. This is a deliberate refusal, not an
  untested feature: notebook writes must address the real workspace, never a transient Remote staging
  copy.
- **HPC data is supported as references, not as transfer.** `source_origin: remote_copy` records a
  host and a path; the plugin never contacts either. `remote_space` at finalize is a number the
  calling agent measured with `du`, not a measurement taken here.
- **NFS / distributed locking is not claimed.** Mutations take a `FileLock`, which is advisory and
  local. Two processes on two machines sharing a notebook can interleave.

## The test suite's own gaps

Run at this session: `Ran 161 tests … OK` on macOS with every runtime dependency plus `pypdf`
present. The repository's committed state at `0.11.5` has 156 cases. Two caveats:

- **`pypdf` is optional in the design but not in practice for a clean run.** Six `test_reporting.py`
  cases read a page through a `reader()` helper that calls `skipTest` without it, while
  `test_notebook.py::test_finalize_pdf_replay_and_report_integrity` imports `PdfReader` unguarded and
  therefore **errors**. On a host without `pypdf` the suite reports `FAILED (errors=1, skipped=6)`,
  which reads as a real failure. Verified by running the release suite in the plugin's own managed
  environment, which does not ship `pypdf`.
- **The suite needs the vendored SDK.** `tests/test_schema_surface.py` imports
  `mcp/runner/plugin_spec.py`, which imports `levin_plugin_sdk` from `.levin-plugin/vendor/`, which is
  gitignored. A fresh clone without `creator compile` fails one test for that reason alone.

## Renderer limitations

These are behaviours, not bugs, but each has surprised someone:

- **A Markdown table becomes a grid, and long cells are truncated with `…`.** Verified: a 200-character
  cell in a two-column table renders 91 characters plus `…`. The full text stays in `record.md`; the
  PDF is a layout, not a data copy.
- **A pipe line without a separator row is literal text.** `| a | b |` followed by `| just | text |`
  prints as-is. Tables need the `| --- |` row.
- **Multiline display math (`$$` on its own line) is not recognised.** One-line `$$ … $$` renders
  through matplotlib mathtext; the multiline form leaves literal `$` characters in the output.
  Verified against the current renderer.
- **Math is a raster image, so it is absent from the text layer.** It cannot be found by search or
  copied out of the PDF. A page containing `energy $E = mc^2$ done.` extracts as `energy  done.` —
  the image is there, the characters are not. Verified in this session.
- **Literal fallback happens only when the expression is truly unrenderable.** An empty expression
  (`a $ $ b`) raises inside `math_image` and prints as literal `$ $`; a malformed one such as
  `$\frac{1}{$` is accepted by mathtext and becomes an image, so it is *rasterised*, not literal.
- **No `.tex` compilation is attempted or tested.** `report.tex` is generated and never built; no TeX,
  Quarto or Typst binary exists on the machine this was checked on.
- **Complex typography needs an external typesetter.** Edit `report.qmd` yourself and register the
  rendered output as an artifact.

## Record-model limitations

- **`manifest.bibtex_path` is declared in the schema and never written.** Only `bibtex_source` (the
  path or inline text actually parsed) and `bibtex_warnings` are stored. Do not read a `bibtex_path`
  key out of a manifest; it will not be there.
- **There is no unregister.** Artifacts, runs and checkpoints accumulate; re-registering the same
  location+role refreshes in place, but nothing removes an entry.
- **`derived_from` and `implementer` cannot be corrected after `init`** — only backfilled when empty.
  A wrong `implementer` needs a new `task_id`.
- **The supersede path is narrow by design.** `conclusion`, `observation` and `method` can be
  superseded; a `failure` cannot, and a `resume`/`note` cannot be the target of `supersedes`.
- **`validate` cannot fail loudly.** Any internal exception is caught and returned as
  `{"ok": true, "valid": false, "errors": [...]}`, so a bug in validation looks like an invalid
  record.
- **`index` is substring search, not an index.** AND over at most 8 whitespace terms against a haystack
  capped at 200 000 characters per record, no ranking, and a workspace is capped at 10 000 records.

## Scope this page deliberately excludes

What the tools refuse (byte budgets, path rejections, credential-bearing URLs, scratch-resident raw
evidence) is caller-facing and lives in
[`references/limits.md`](../skills/levin-research-notebook-runtime/references/limits.md). The design
decisions behind these limitations — why a filesystem, why no signatures, why references instead of
copies — are in [why-not-an-eln](why-not-an-eln.md).
