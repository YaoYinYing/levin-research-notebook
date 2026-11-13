# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Entries are written for the two readers the plugin actually has: an agent driving the tools and a
person reading a delivered report. Only changes that alter a rejection, a default, an output or a
contract appear here; internal refactors do not. Scopes name the module that owns the behaviour:
`Records` (`notebook.py`), `Tools` (`plugin_spec.py`), `Report` (`reporting.py`), `Units`
(`units.py`), `Bibliography` (`bibtex_index.py`), `LaTeX` (`latex_export.py`), `Skill` (`skills/**`),
`Docs`, `CI`, `Tests`.

Every entry is checkable. `0.10.4` onward come from `git log`; earlier ones were reconstructed from
the packaged artefacts in `dist/` (each `.levin-plugin.tgz` carries the source, the skill and the test
suite of that release, which is where the test counts come from). Where only a coarse statement is
supportable, the entry stays coarse rather than guessing.

Versions `0.8.x` never existed, and `0.11.8` was committed but never packaged — its content is
recorded under `0.11.9`, which is the release that shipped it.

```text
## TEMPLATE
### Added

### Changed

### Fixed

### Removed

```

## [Unreleased]

## [0.13.1] - 2026-11-13

An independent acceptance round on 0.13.0 passed all four scenarios (pause window in 记录范围,
exclude-keeps-in-manifest, dependency-aware refusals, full lifecycle) and returned seven friction items.
Five were real; this release fixes them.

### Added
- Records:
  - a run may declare `script_id`, the script artifact that executed it. Before this the field did not
    exist, so a figure could never inherit a script from `run_id` alone — the inheritance path the
    skill advertised was unreachable, and the error text told the caller to do something impossible.

### Fixed
- Records:
  - `research_record_exclude` accepts `reference_id` aliases, as every other id field does; the skill
    says "the reference_id is the id you use", and this was the one place it was not true.
  - `restore` no longer erases why the entry was set aside: `exclusion_reason` survives, with
    `restored_at` and `restored_reason` recording the restoration.
  - `index` searches recorded quantities. A record that reports `radius_of_gyration` could not be found
    by that name, which is the number its conclusion rests on.
- Report:
  - an artifact alias prints as 文献 only when it names a bibliography entry; a handle for a local file
    now prints 别名, because calling it literature misleads a reader.

### Changed
- Skill:
  - states that `workspace_dir` must exist before `init` (`mkdir -p`, else `invalid_workspace_dir`).
  - documents both working figure-provenance shapes now that a run can carry `script_id`.
  - states that a rejected `finalize` still writes a blocked snapshot, so `prune_reports` is worth
    calling after a failed attempt.

### Tests
- 193 cases (189 + run script inheritance, alias exclusion, restore audit trail, quantity search).

## [0.13.0] - 2026-11-13

Keeping the recorder out of the record. A session that debugged this plugin while using it wrote the
debugging into the experiment: the record then documented the recorder instead of the science.

### Added
- Records:
  - `research_record_suspend` opens and closes a recording pause. While it is open, `checkpoint`,
    `register_artifact` and `register_run` are refused with `Recording is paused since <time>
    (<reason>)`; `validate`, `finalize`, `index`, `exclude` and the prune tools still work. The reason
    is required, and the report prints every window in 记录范围 — a gap is stated, not silently absent.
  - `research_record_exclude` sets checkpoints, artifacts or runs aside: they leave 实验结果, 材料, the
    artifact table and the run list, and can no longer be cited. Nothing is deleted — the manifest and
    `revisions/` keep the entry, and the appendix table **记录范围：已搁置条目与暂停窗口** names each
    id with its reason. `restore: true` puts it back.
- Tools:
  - ninth and tenth `research_record_*` tools (11 declared in total).

### Changed
- Records:
  - report rendering filters excluded entries at one point — the render entry — so no section builder
    can leak a set-aside observation, artifact or run into the pages.
  - `validate` cross-checks only what the report shows. An excluded entry is neither citable nor
    required to be complete; it also reports a live conclusion that cites excluded evidence as an
    error, because that claim would otherwise look supported while its evidence is invisible.
  - excluding an artifact or run that a live conclusion cites is refused at write time with the
    conclusion named, so the contradiction is caught where it can still be fixed cheaply.

### Tests
- 189 cases (182 + pause, resume, reason guards, exclusion visibility, restore, non-citability, and
  the conclusion guard).

## [0.12.1] - 2026-11-13

Figure placement and in-text citation, reported as "we seem to be writing Microsoft Office": every
plot was collected at one point in 实验结果 and nothing in the prose pointed at it.

### Added
- Report:
  - `\fig{artifact-id}` prints `图 N` and puts the plot directly after the enclosing paragraph, so
    the reference point decides the position. The key may also be the image file's stem.
  - `\figure{artifact-id}` is now idempotent: a figure cited from several entries is placed once, at
    its earliest citation.
- Records:
  - `finalize` emits `\figure{…}` for a figure listed in a checkpoint's `evidence_ids`, so a plot
    cited by an observation lands beside that observation with no extra authoring.

### Changed
- Report:
  - figures are numbered by first appearance in the document, not by registration order. A figure
    cited in passage 3 is 图 1 even if it was the fifth artifact registered; the number is reserved on
    first sight and reused, so reordering the body renumbers correctly.
  - the uncited-figure plate now carries a 图表 heading and, when some figures were placed inline,
    one sentence saying the rest were not cited individually.
  - 材料 (§4) lists `raw`/`input` evidence only; derived tables and figures are results, not materials.
    Above three items the row summarizes and the full list follows as bullets.
  - non-default parameters are summarized and pointed at the appendix 执行溯源 when long. A
    600-character JSON blob inside a table cell was unreadable and looked authoritative while being
    truncated.
- Records:
  - `refers_to` renders as `（见「<标题>」）` using the target's heading. It printed `(see checkpoint-<32
    hex>)` — English boilerplate around an unreadable id — and the evidence label is now 证据 rather
    than `Evidence:` in an otherwise Chinese document.

### Fixed
- Records:
  - `validate` reports figures no body checkpoint cites in one aggregated warning that names the two
    repairs. Eighteen per-file warnings buried the real finding among noise.

### Tests
- 182 cases (175 + placement, numbering, plate, materials and warning regressions).

## [0.12.0] - 2026-11-13

A record-model release driven by a 13-item review of v0.11.10 (one real 95-revision analysis
record) plus five rendering defects found by reading a delivered 52-page PDF.

### Added
- Records:
  - `conditional` checkpoint kind for counterfactual reasoning and falsifiable predictions. It
    requires `refers_to` and accepts no `evidence_ids`, because it has no direct evidence by
    construction; it renders in its own 条件推演与可证伪预测 section instead of being forced into a
    `conclusion` (which required evidence) or a `note` (which renders at the end).
  - artifacts carry `revision` (incremented on every in-place refresh) and `retired`, and a new
    artifact may name `supersedes`. A retired artifact keeps its history and stops producing
    file-existence and checksum errors.
  - `init` resumes by explicit `experiment_id` even when the title or objective wording changed, so
    a parent session can take over work a subagent started.
- Tools:
  - `research_record_prune_revisions` reclaims old revision snapshots, keeping the newest N; copies
    of hand edits (`human-record-*.md`) are never removed. Ninth tool.
- Report:
  - straight double quotes around Chinese become Chinese quotes; quotes inside a code span, a fenced
    block or a JSON parameter stay literal, because rewriting those changes a value a reader copies.

### Changed
- Records:
  - a `note` may now be corrected by a later `note`; it was the most frequently wrong kind and the
    only one that could never be revised.
  - a `note` may no longer replace an `observation`, `method` or `conclusion`. The correction would
    render in the trailing 恢复与备注 while the superseded finding stayed in 实验结果, struck
    through and pointing at nothing.
  - `refers_to` naming a `checkpoint-…` id must exist. It was free text nobody checked.
  - `reference_id` must be unique across artifacts. Two artifacts could share an alias and
    resolution silently returned the first, so a citation pointed at the wrong evidence with no
    error anywhere.
- Report:
  - a changed checksum is graded by role: `raw` and `input` evidence keeps the error, while
    `figure`/`derived` output reports "checksum changed since revision N" as a warning and names
    both repair paths. A regenerated figure is a normal scientific event, not tampering.
  - the hash budget verifies small files first; it used to be spent in manifest order, so one large
    trajectory could consume all 64 MiB and leave every figure unchecked while the record still
    reported valid.

### Fixed
- Report:
  - decode HTML entities: a record is Markdown, where `&lt;160` means `<160`; the entity was printed
    verbatim (8 × `&lt;`, 6 × `&gt;` in one real report).
  - resolve a sub/superscript run as one unit. Per-character resolution produced `κ^-¹`, because the
    missing minus became `^-` while the Latin-1 `¹` stayed a real glyph; a run is now either fully
    drawn or fully caret (`κ^-1`), and `R²`/`Å³` keep their true superscripts.
  - never break a machine-readable token across two lines. Table columns now take a floor width from
    their longest unbreakable token, so an `artifact-…` id stays copyable (37 were split mid-hash).
  - the glyph probe now checks a code block against the faces the renderer actually uses, CJK
    included. Probing code against the mono face alone reported every Chinese character inside a
    fenced block as missing — 55 false warnings on one record while it rendered correctly.
- Records:
  - section 1 no longer reprints the header's 为什么要做 paragraph verbatim; it points at it. One
    real record opened with the same 469-character paragraph twice.

### Tests
- 175 cases (161 + one regression per fix and per new behaviour).

## [0.11.10] - 2026-11-13

### Added
- Skill:
  - `skills/levin-labnote/`, a human-facing skill describing the workflow, installation, usage and
    current limits, alongside the existing agent-facing `levin-research-notebook-runtime`.
- Docs:
  - the README names both skills and says which reader each is for.

## [0.11.9] - 2026-11-10

The release CI signed off. Contains what `0.11.8` committed but never packaged.

### Fixed
- CI:
  - two POSIX-only path regexes (`levin_notebook/experiments/…`, `reports/report-…/`) also match a
    Windows separator.
  - install a TrueType CJK face on Linux: `fonts-noto-cjk` ships OpenType/CFF outlines, which
    ReportLab rejects, so the job installed a font the renderer could not use.
  - resolve `NOTEBOOK_TEST_SCRATCH`, because `/tmp` is a symlink on macOS and an unresolved path
    tripped two assertions; make the concurrency deadline platform-aware on win32.
- Records:
  - read and write text files with an explicit encoding; the default was cp1252 on Windows, so a
    record containing Chinese could not be reloaded.

## [0.11.7] - 2026-11-09

### Fixed
- Records:
  - decode a Windows drive letter as a path, not a URL scheme (`urlsplit` read `D:\…` as scheme `d`).
  - pass `encoding="utf-8"` at every `read_text()`/`write_text()` in the runner.

## [0.11.6] - 2026-11-09

### Added
- Docs:
  - `docs/` as the human-facing design layer with a written placement rule deciding whether a fact
    belongs in the README, a `docs/` page or a skill reference; `why-not-an-eln`, `lifecycle`,
    `manifest-and-report`, `architecture`, `limitations`.
  - `CONTRIBUTING.md` and this changelog.
- CI:
  - `ci.yml` running the suite on ubuntu, macOS and Windows with no `continue-on-error`.
  - `structure.yml`: skill size and link tree, offline link/anchor check, dependency-pin drift,
    plugin-spec dry run, and a Creator-level validation of the published package.

### Changed
- Docs:
  - README rewritten as a front door; duplicated tool-schema prose that had already drifted removed.

### Fixed
- Skill:
  - four factual errors: section 1 reads `purpose` only (it does not fall back to `hypothesis`);
    tables render as a real grid; a multi-line `$$` block is not recognised; math that mathtext
    accepts is rasterised rather than printed.
- Records:
  - `note` and `resume` checkpoints render in the trailing 恢复与备注 section instead of vanishing.

## [0.11.5] - 2026-11-09

### Changed
- Skill:
  - split into a tree loaded by stage. `SKILL.md` had reached 11 989 characters against a 12 000
    ceiling and duplicated `references/limits.md`; it is now a 3 508-character routing entry.
  - `references/report-format.md` replaced by `references/report.md`, plus new `start.md`,
    `evidence.md`, `bibliography.md` and `finalize.md`.

## [0.11.4] - 2026-11-09

### Added
- Records:
  - reference aliases resolve in `input_ids`, `script_id`, `run_id`, `run.id` and `evidence_ids`, not
    only in the field the alias was registered on.
  - `role=deliverable` for the artefact a task hands a human.
  - `index(include_summary: true)` adds per-record counts.
- Units:
  - `molarity` (mol/L, M, mM, µM, nM, pM) and `potential` (V, mV) families; `L` became a real volume
    unit, so `mol/L` parses.
- Report:
  - `validate` reports missing glyphs per codepoint with context before `finalize`, probing prose
    against serif+CJK faces and code against mono separately.

### Changed
- Records:
  - a figure may name only its producing `run_id` and inherit `input_ids`/`script_id` from it.

## [0.11.3] - 2026-11-09

### Fixed
- Docs:
  - the `0.11.2` README still said seven `research_record_*` tools after `prune_reports` shipped.

### Added
- Records:
  - `validate` returns a `reports` block (total / success / blocked / failed / `latest_success` /
    `pending_snapshots`), so "which PDF is the real one" no longer needs a manifest read.

## [0.11.2] - 2026-11-09

Five behaviours found by a real campaign review (8 records, 41 finalizes).

### Fixed
- Records:
  - `finalize` no longer wipes fields you omit: `None` keeps the stored value, an explicit `[]`
    clears it. A second finalize that only added artifacts had been deleting `lessons`/`plans`/
    `results`/`quantities`.
  - `conclusion`, `observation` and `method` checkpoints can be superseded; the original stays
    visible, struck through, naming its correction. A `failure` still cannot.
- Units:
  - an unconventional unit blocks instead of warning, with `unit_acknowledged: true` as the explicit
    escape hatch; an unknown quantity name requires a declared `dimension`.

### Added
- Tools:
  - `research_record_prune_reports` deletes old PDF snapshot folders, always keeping at least one,
    never touching `revisions/` or artifacts, with `dry_run` listing first. Eighth tool.
- Records:
  - `derived_from` records a campaign hierarchy; `validate` warns on an undeclared cross-record
    artifact reference.
  - `quantities.replica` separates three runs from three quantities and blocks a duplicate name per
    replica.
  - `implementer` and `environment_location` can be backfilled on resume but never rewritten.

## [0.11.1] - 2026-11-09

### Fixed
- Skill:
  - tells the agent to choose a font profile from what the report contains and to check
    `preflight.fonts.cjk_available` first; `0.11.0` made profiles resolvable but nothing used them.

## [0.11.0] - 2026-11-09

### Added
- Report:
  - per-report font profiles with cross-platform CJK chains. `resolve_fonts(profile)` returns an
    immutable per-report resolution; fonts had been a module-level mutable dict resolved once per
    process, so two reports with different typefaces could corrupt each other.
  - a host with no CJK face no longer renders Chinese as `[U+XXXX]` silently: `preflight` reports
    `cjk_available` and `report.fonts` records what was resolved.
  - candidate chains cover macOS, Linux and Windows; only `.ttf`/`.ttc`, because ReportLab rejects
    `.otf` CFF outlines.
- Tools:
  - `preflight` reports the renderer, dependency versions and font coverage.

## [0.10.4] - 2026-11-09

### Fixed
- Report:
  - superscript/subscript characters drawn as caret notation are tracked separately
    (`transliterated_codepoints`) instead of being reported as missing glyphs.

## [0.10.3] - 2026-11-09

### Fixed
- Report:
  - sub/superscript glyphs missing from the embedded faces are rewritten (`m⁻¹` → `m^-1`) rather than
    printed as tofu.

## [0.10.2] - 2026-11-09

### Fixed
- Units:
  - dimension formulas use plain caret notation; the Unicode superscript minus (U+207B) existed in no
    text face. `rate`'s preferred unit became `1/s`.

## [0.10.1] - 2026-11-09

### Fixed
- Units:
  - short quantity-name aliases must match the whole name; `k` no longer swallowed `k_times_dt_max`.
  - `unit_scale` issues report as 惯例差异 rather than 需修正.

## [0.10.0] - 2026-11-09

### Added
- Units:
  - dimensional checking (`quantities` on `finalize`): a recorded number carries a unit, a dimension
    and an uncertainty, and a wrong dimension blocks before the conclusion is written.
- LaTeX:
  - standalone `report.tex` next to the PDF as an optional same-source export; it is never compiled
    and the PDF never depends on TeX.
- Report:
  - inline `\figure{id}` places a plot beside its claim instead of only in a trailing figure block.

## [0.9.3] - 2026-11-08

### Fixed
- Bibliography:
  - metadata hygiene from EndnoteTweak: a reference list renders as
    `第一作者 et al, 末位作者, 年, 期刊, 标题, DOI` grouped under "以下文献报道了…", with `[n]`
    continuous across sections.

## [0.9.2] - 2026-11-08

### Fixed
- Records:
  - literature reference rendering and author-name handling.

## [0.9.1] - 2026-11-08

### Fixed
- Records:
  - a flag read helper no longer depends on a previously imported symbol.
- Report:
  - clip over-long table cells without breaking a code span in half.

## [0.9.0] - 2026-11-07

### Added
- Bibliography:
  - `bibtex_index.py` plus `bibtex`/`bibtex_path` on `finalize`, and the `references`,
    `reference_sections`, `citations`, `synthesis`, `search_strategy` fields.
- Records:
  - three record types (`experiment`, `analysis`, `literature_review`) that switch the report's
    middle sections while keeping the numbered spine.

## [0.7.2] - 2026-11-07

### Fixed
- Report:
  - main title renders in the heading face rather than the body face.

## [0.7.1] - 2026-11-07

### Added
- Report:
  - CJK-aware tokenisation and per-glyph font registration, so one paragraph can mix Times, Songti
    and Menlo without tofu.
  - `examples/plot_style.py` as the plotting style the skill tells an agent to use.

## [0.7.0] - 2026-11-07

### Added
- Report:
  - the numbered Chinese section spine (目的 / 策略 / 方法和计划 / 材料 / 结果 / 结论和不足 / 下一步 /
    经验教训 / 空间统计) with numbered subsections, `replica #n` / `retry #n` suffixes and the fact
    table under the header.
  - footnotes and endnotes.

### Changed
- Records:
  - `_specific()` rejects vague failure text (`failed`, `无结果`, `见日志`), enforcing the lab-record
    rule that a failure states what broke.

## [0.6.2] - 2026-11-07

### Fixed
- Records:
  - space usage is reported in human units (B/KB/MB/GB), not raw bytes.

## [0.6.1] - 2026-11-07

### Changed
- Tools:
  - tightens the declared input schemas to what the library actually accepts.

## [0.6.0] - 2026-11-07

The report-format release: the renderer became a real fixed-layout typesetter.

### Added
- Report:
  - tables as a real grid, fenced code blocks with language highlighting, inline code, restrained
    bold/italic, `~~strikethrough~~` with a stated reason, and underline for key data.
  - a page break between the record body and the 工件与溯源 section.
  - `\pagebreak` and a bounded figure pipeline with captions.

## [0.5.0] - 2026-11-06

### Added
- Skill:
  - documents the `uv`-managed `levin_scratch/.venv` the examples run in.

## [0.4.1] - 2026-11-06

### Changed
- Records:
  - remote originals stay remote: raw data is not copied back, processing runs on the host, and only
    lightweight results come back. A remote-sourced entry names `remote_host` + `remote_path`, and
    landing a copy also needs `remote_copy_permission`.

## [0.4.0] - 2026-11-06

### Added
- Records:
  - `source_origin` (`local_original`/`remote_copy`/`unspecified`) with `remote_host`, `remote_path`
    and `remote_copy_permission`; a remote original above 64 MiB is refused even with permission.
  - space usage and its delta, measured against an init baseline.

## [0.3.2] - 2026-11-06

### Fixed
- Records:
  - index search covers run commands, failures, parameters, environments and artifact locations, so a
    script name or a failure reason is findable.

## [0.3.1] - 2026-11-06

### Fixed
- Records:
  - re-registering a raw artifact whose file was absent at first registration refreshes it in place
    instead of appending a duplicate that `validate` then warns about forever.

## [0.3.0] - 2026-11-06

### Fixed
- Records:
  - a blocked `finalize` leaves `execution_status` at `wip` instead of committing a terminal status
    with no PDF.

## [0.2.0] - 2026-11-06

### Changed
- Docs:
  - README rewritten to say what the plugin is for and what it refuses to do.

## [0.1.1] - 2026-11-06

### Fixed
- Report:
  - inline styling no longer drops text at a run boundary.

## [0.1.0] - 2026-11-06

### Added
- Records:
  - stable `exp-<uuid32>` identities, one canonical `manifest.json` per experiment, immutable
    `revisions/`, append-only checkpoints, artifact and run registration by reference, and
    `validate` separated from `finalize`.
  - filelock plus atomic writes, schema validation, and a bounded SHA-256 over registered files.
- Tools:
  - the seven `research_record_*` tools: `init`, `checkpoint`, `register_artifact`, `register_run`,
    `validate`, `finalize`, `index`.
- Report:
  - fixed-layout A4 PDF via ReportLab with an embedded font stack, and the rule that PDF is a
    generated deliverable, never the canonical record.
- Skill:
  - `levin-research-notebook-runtime`, the agent-facing workflow.
