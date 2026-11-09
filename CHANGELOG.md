# Changelog

Version history for `levin-research-notebook`. Format: what changed for a *user of the plugin* —
an agent driving the tools, or a human reading a report. Internal refactors appear only when they
changed a rejection, a default or an output.

Every entry below is checkable: `0.10.4` onward from `git log`, everything earlier from the packaged
artefacts in `dist/` (each `.levin-plugin.tgz` contains the source, the skill and the test suite of
that release, which is how the numbers here were taken). Versions are not backfilled with guesses;
where the artefacts only support a coarse statement, the entry stays coarse.

## Unreleased — documentation system

No behaviour change; no source, test or workflow file was touched.

- **Added `docs/`** as the human-facing design layer, with a written placement rule that decides
  whether a fact belongs in `README.md`, a `docs/` page or a skill reference:
  [docs/README.md](docs/README.md).
  - [docs/why-not-an-eln.md](docs/why-not-an-eln.md) — adoption decision and what is refused.
  - [docs/lifecycle.md](docs/lifecycle.md) — the five stages with a transcript from a real run.
  - [docs/manifest-and-report.md](docs/manifest-and-report.md) — writer and report section for every
    manifest field, including the 14 that never render.
  - [docs/architecture.md](docs/architecture.md) — module map, the invariant each module enforces,
    and a "where does X go" table.
  - [docs/limitations.md](docs/limitations.md) — never-executed platform branches, test-suite gaps,
    renderer limits, record-model limits.
- **Rewrote `README.md`** as a front door: one-page identity, a two-command quickstart, the eight
  tools by intent (schemas stay in `plugin_spec.py`), enforced guarantees, honest limits, and a
  reading map. Removed the duplicated tool-schema prose that had already drifted.
- **Added `CONTRIBUTING.md`** — test invocation with the two prerequisites that actually bite,
  compile/validate/package, the release checklist, and the documentation rules.
- **Added this changelog.**
- **Fixed two factual errors in skill references** found while checking claims against source:
  - `references/start.md` and `references/report.md` said section 1 实验目的 falls back to `hypothesis`
    when `purpose` is absent. It does not: `Notebook._sec_questions` reads `purpose` only and prints
    `未记录研究问题。` otherwise; `hypothesis` feeds the header's **为什么要做** line.
  - `references/report.md` and `references/limits.md` described Markdown tables as literal text and
    an unparsable formula as literal `$…$`. Tables render as a real grid (long cells truncated with
    `…`), a pipe line without a `---` row is literal, a multi-line `$$` block is not recognised, and
    math that mathtext accepts is rasterised rather than printed.
- **Corrected the same table claim in `README.md`** — it was the version a new user read first.

## 0.11.5

- **Split the skill into a tree loaded by stage.** `SKILL.md` had reached 11 989 characters against a
  12 000-character validator ceiling — 11 characters of headroom — and duplicated content that also
  lived in `references/limits.md`. It is now a 3 508-character routing entry point: five stages, the
  invariants, a table of which reference file to load at which stage.
- `references/report-format.md` is gone, replaced by `references/report.md` (sections, quantities,
  math, figures, glyph coverage, editable sources, fonts) plus new `references/start.md`,
  `references/evidence.md`, `references/bibliography.md` and `references/finalize.md`.
- Content duplicated between `SKILL.md` and `limits.md` was deduplicated so each fact has one home.

## 0.11.4

- **Reference aliases resolve everywhere.** `input_ids`, `script_id`, `run_id`, `run.id` and
  `evidence_ids` accept either the server id (`artifact-…`, `run-…`) or the `reference_id` you
  registered. Previously an alias was "unknown" in every field except the one it was registered on;
  five of twelve rejected calls in one real campaign session were that.
- **Units stop at molecular dynamics no longer.** `molarity` (mol/L, M, mM, µM, nM, pM) and
  `potential` (V, mV) are families; `L` became a real volume unit, so `mol/L` parses.
- **`role=deliverable`** for the artefact a task hands a human, distinct from a `derived` intermediate.
- **A figure may name only its producing `run_id`** and inherit `input_ids`/`script_id` from it.
- **`validate` reports missing glyphs per codepoint with context**, before `finalize` rather than
  inside the delivered PDF. Prose is probed against serif+CJK faces, code against mono separately.
- **`index(include_summary: true)`** adds per-record counts (artifacts by role, runs by status,
  checkpoints by kind, quantities, references, reports, `derived_from`).
- 156 test cases.

## 0.11.3

Fixed a release-notes defect rather than a behaviour one: the `0.11.2` README still said *seven*
`research_record_*` tools after `prune_reports` shipped, and this release corrected it to eight.
`validate` result payload gained the `reports` block (total / success / blocked / failed /
`latest_success` / `pending_snapshots`) so "which PDF is the real one" no longer needs a manifest read.
145 test cases.

## 0.11.2

Five behaviours found by a real campaign review (8 records, 41 finalizes):

- **`finalize` no longer wipes fields you omit.** `None` keeps the stored value; an explicit `[]`
  clears it. A second finalize that only added artifacts had been silently deleting
  `lessons`/`plans`/`results`/`quantities`.
- **An unconventional unit blocks instead of warning**, with `unit_acknowledged: true` as the explicit
  escape hatch (reported as 惯例差异). An unknown quantity name now requires a declared `dimension`.
- **`conclusion`, `observation` and `method` checkpoints can be superseded** — the original stays
  visible, struck through, naming its correction. A `failure` still cannot.
- **New tool `research_record_prune_reports`** deletes old PDF snapshot folders, always keeping at
  least one, never touching `revisions/` or artifacts, with `dry_run` listing first. This is the
  eighth tool; 0.11.0–0.11.1 had seven.
- `derived_from` records a campaign hierarchy and `validate` warns on an undeclared cross-record
  artifact reference; `quantities.replica` separates three runs from three quantities and blocks a
  duplicate name per replica; `implementer` and `environment_location` can be backfilled on resume
  but never rewritten.
- 144 test cases.

## 0.11.1

- The skill now tells the agent to **choose a font profile** (`scientific-cjk` / `cjk-sans` /
  `latin-only`) from what the report contains, and to check `preflight.fonts.cjk_available` first.
  0.11.0 made profiles resolvable but nothing used them, so every report silently took the default.
- Font detail moved into `references/report-format.md` to stay inside the skill size limit.

## 0.11.0

- **Per-report font profiles with cross-platform CJK chains.** `resolve_fonts(profile)` returns an
  immutable per-report resolution; previously fonts were a module-level mutable dict resolved once per
  process, so two reports with different typefaces could corrupt each other.
- A host with no CJK face no longer renders Chinese as `[U+XXXX]` silently: `preflight` reports
  `cjk_available` before rendering and `report.fonts.notes` records what was resolved.
- Candidate chains cover macOS, Linux (Liberation, DejaVu, Noto CJK, arphic, wqy) and Windows
  (times, consola, simsun, msyh). Only `.ttf`/`.ttc` — ReportLab rejects `.otf` CFF outlines.
- 126 test cases.

## 0.10.4 — 0.10.0

Fourth-patch releases in this range changed dimensional-check edge cases and renderer glyph
handling, not the record model:

- **0.10.4** — superscript/subscript characters rendered as caret notation are now tracked
  separately (`transliterated_codepoints`) instead of being reported as missing glyphs.
- **0.10.3** — the caret-notation substitution itself: sub/superscript glyphs missing from the
  embedded faces are rewritten (`m⁻¹` → `m^-1`) rather than printed as tofu.
- **0.10.2** — dimension formulas printed with Unicode superscripts, one of which (U+207B) no text
  face could draw; formulas now use plain caret notation. `rate`'s preferred unit became `1/s`.
- **0.10.1** — short quantity-name aliases must match the whole name: `k` no longer swallows
  `k_times_dt_max`. `unit_scale` issues report as 惯例差异 rather than 需修正.
- **0.10.0** — **dimensional checking** (`units.py`, `quantities` on `finalize`) and **standalone
  LaTeX export** (`latex_export.py`, `report.tex` next to the PDF). 120 test cases, 9 modules.

## 0.9.0 — 0.9.3

- **0.9.0** — bibliography support: `bibtex_index.py`, `bibtex` / `bibtex_path` on `finalize`,
  `references`, `reference_sections`, `citations`, `synthesis`, `search_strategy`; and the three
  record types (`experiment`, `analysis`, `literature_review`) that switch the report's middle
  sections. 93 test cases.
- **0.9.1 — 0.9.3** — patches to reference rendering and metadata hygiene.

## 0.1.0 — 0.7.2

The pre-`0.9` line established the model these pages describe: one canonical `manifest.json` per
experiment, immutable `revisions/`, append-only checkpoints, artifact/run registration by reference,
`validate` separated from `finalize`, and the ReportLab fixed-layout PDF with the numbered Chinese
section spine. What the packaged artefacts show across the range:

| Versions | Test cases | Modules | Notes |
|---|---|---|---|
| 0.1.0 – 0.1.1 | 49 | 6 | `adapter`, `notebook`, `plugin_spec`, `reporting`, `server`, `setup_runtime` |
| 0.2.0 – 0.5.0 | 54 → 72 | 6 | the stage chain and `workflows/` appear |
| 0.6.0 – 0.7.2 | 72 → 80 | 6 | `test_schema_surface.py` guards spec↔library agreement; skill grows past 10 KB |
| 0.9.0 | 93 | 7 | `bibtex_index.py`, `test_record_types.py` |

## How these entries were produced

```bash
git log --oneline                       # 0.10.4 onward carries the detail above
for v in 0.1.0 0.5.0 0.9.0 0.10.4 0.11.5; do
  tar xzf dist/levin-research-notebook-$v.levin-plugin.tgz -C /tmp/$v
  grep -rhc 'def test' /tmp/$v/tests/*.py   # test counts
  ls /tmp/$v/mcp/runner/*.py                # module set
done
```

Anything not supported by one of those two sources is absent from this file on purpose. In
particular there is no per-version date column: the tarball mtimes are build times, not release
dates, and inventing dates would make the file less true than its absence.
