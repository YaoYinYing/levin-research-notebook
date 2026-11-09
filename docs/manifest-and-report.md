# Every manifest field: where it comes from, and what the report does with it

This page exists because the two questions get conflated and then answered wrongly. "Where does this
field come from" is a question about calls. "Does it reach the report" is a question about rendering.
A field can be written by one call and used by the other in a non-obvious way, and a substantial group
of top-level properties is stored, validated and deliberately never printed at all. Every table below
marks those with `—`, so the tables — not a count in this sentence — are the answer.

The schema itself is [`SCHEMA`](../mcp/runner/notebook.py) in `notebook.py` — 48 top-level
properties, 20 of them required. Read it there; it drifts and this page does not restate it.

## The three writers

Almost every field has exactly one writer:

| Writer | What it may set |
|---|---|
| `init` | identity and the a-priori frame: `title`, `objective`, `hypothesis`, `purpose`, `expected_result`, `implementer`, `environment_location`, `record_type`, `derived_from`, `retention`, plus the `usage_at_init` baseline |
| `checkpoint` / `register_artifact` / `register_run` | the three evidence arrays: `checkpoints`, `artifacts`, `runs` — and `agents` |
| `finalize` | the interpretation and everything the report template slots in: `interpretation`, `limitations`, `visualization`, `lessons`, `plans`, `strategy`, `method_plan`, `materials`, `results`, `footnotes`, `remote_space`, `quantities`, `references`, `citations`, `reference_sections`, `extra_sections`, `synthesis`, `search_strategy`, `bibtex_*`, `font_profile`, `usage_at_finalize` |

Machine-written bookkeeping — `schema_version`, `experiment_id`, `revision`, `created_at`,
`updated_at`, `reports`, `requests`, `workspace_dir` — has no user-facing writer. `revision`
increments once per successful mutation, and `requests` is the `request_id` memo.

Two override rules matter because they are asymmetric:

- `finalize` uses **omitted ≠ cleared**: a `None` keeps the stored value, an explicit `[]` clears it.
  The scalar `purpose`, `environment_location`, `record_type` and `font_profile` follow the usual
  "empty string means keep" convention.
- `init` on resume **backfills but never rewrites** `implementer`, `environment_location`,
  `expected_result` and `derived_from`. There is no edit path for them afterwards.

## Field by field

`Writer` names the call. `Report` names the section in `record.md` / the PDF; a dash means the field
is stored, validated, and deliberately not printed.

### Identity and frame

| Field | Writer | Report |
|---|---|---|
| `title` | `init` | H1 title, and the running title on every page |
| `objective` | `init` | **本项目在做什么** line of the header block |
| `task_id` | `init` | — (searchable via `index`, not printed) |
| `experiment_id` | machine | — (it is the directory name) |
| `hypothesis` | `init` | **为什么要做** — but only when `purpose` is empty |
| `purpose` | `init`, re-settable by `finalize` | **为什么要做**, and section 1's opening paragraph |
| `expected_result` | `init` | **预期结果** line of the header block |
| `implementer` | `init` (backfill only on resume) | 实施人 row of the fact table |
| `environment_location` | `init` / `finalize` | 环境位置 row of the fact table and of section 4 |
| `record_type` | `init` / `finalize` | which middle sections exist at all |
| `derived_from` | `init` (backfill only) | — ; `validate` warns about undeclared cross-record references |
| `retention` | `init` | 保存与复现 closing section |

`record_type` is the switch that changes the spine, and it is the single most consequential field
for a reader. Measured from the same three-call record:

- `experiment` → 1 实验目的 · 2 实验策略 · 3 实验方法和计划 · 4 实验材料 · 5 实验结果 · 6 实验结论和不足
- `analysis` → 1 实验目的与依据 · 2 分析策略 · 3 方法与流程 · 4 数据与工具 · 5 分析结果 · 6 证据综合 · 7 结论与不足
- `literature_review` → 1 研究问题与范围 · 2 检索策略 · 3 文献清单 · 4 证据综合 · 5 复算与核验 · 6 结论与不足

The tail (下一步计划 · 经验教训 · 数据空间统计) and the trailing 工件与溯源 / 保存与复现 do not vary.

### The three evidence arrays

| Field | Writer | Report |
|---|---|---|
| `checkpoints[]` | `checkpoint` | numbered subsections of their section: `method`→3.x, `observation`→5.1 bullets, `failure`→5.3, `conclusion`→6.x. `resume` and `note` are deliberately not methods or results, so they render in a trailing 恢复与备注 section that exists only when such a checkpoint exists — the numbered spine is untouched otherwise |
| `artifacts[]` | `register_artifact` | 工件与溯源 table (id, role, availability, origin) plus a 位置与校验和 block per artifact |
| `runs[]` | `register_run` | 执行溯源 block; also the source of 4's hosts, platforms and software versions |
| `agents[]` | `checkpoint`, `init` | — (who contributed, not what) |

Only checkpoints are **never editable**: they append, and correction happens by `supersedes` on a
`conclusion`/`observation`/`method`, which leaves the original visible and struck through. A
`failure` may not be superseded at all.

### What `finalize` fills

| Field | Report |
|---|---|
| `interpretation` | **结论解读** paragraph in the conclusions section. Required; may be inconclusive, may not be empty |
| `limitations` | **不足** paragraph. Required |
| `visualization` | — ; it is a *gate*, not content. `beneficial: true` with no figure is rejected |
| `strategy[{title,text}]` | section 2, one numbered subsection each |
| `method_plan[]` | bullet list at the head of the methods section, before the numbered method checkpoints |
| `materials{datasets,software,notes}` | section 4 rows, merged with software versions harvested from `runs[].environment` |
| `results{expected_seen,unexpected_seen,expected_not_seen,incidents}` | 5.1 / 5.1 / 5.2 / 5.3. Observation checkpoints are appended to 5.1; incident strings already contained in a failure checkpoint's text are de-duplicated out of 5.3 |
| `quantities[]` | 5.4 dimensional table, plus explicit issue lines under it |
| `footnotes[{label,text}]` | the 尾注 block, rendered as `[label] text` lines |
| `plans[]`, `lessons[]` | the 下一步计划 and 经验教训 sections — in every record type these are the two sections immediately before 数据空间统计 |
| `remote_space[]` | section 9, second table, entries ≥1 GiB flagged |
| `references[]`, `reference_sections[]` | a 文献依据 section in `experiment`/`analysis` when references exist, and the 文献清单 section of `literature_review` (grouped by section, `[n]` continuous) |
| `citations[]` | 引用关系 table — `literature_review` only |
| `synthesis` | 证据综合 — `analysis` and `literature_review` only; an `experiment` record stores it and prints nothing |
| `search_strategy{databases,query,window,languages,screening}` | section 1's scope block in every type, and the 检索策略 section of a `literature_review` |
| `bibtex_source` | — ; stored so the parse is traceable, but the rendered 文献来源 line reads `references[].source` (the resolved `.bib` path or `inline`). `bibtex_path` is declared in `SCHEMA` and never written, and `bibtex_warnings` is stored and never rendered |
| `extra_sections[{title,text}]` | appended after the type's middle, before the tail; it cannot reorder the spine |
| `font_profile` | — ; it selects faces, and the renderer records what it resolved under `report.fonts` |
| `usage_at_finalize` | section 9's first table, including the delta against `usage_at_init` |

`visualization`, `font_profile` and `derived_from` are the three fields a reader of the report never
sees and a caller must still get right: two are gates and one is a warning source. `usage_at_init` is
the quiet fourth — never printed itself, but its delta is section 9's 相对立项时增量 row.

## The one thing that surprises people

Empty is not absent. A section with no data prints an explicit "未记录…" line — `未记录策略说明。`,
`未记录缺失的预期结果。`, `未登记带单位的数值；本记录因此无法做量纲核对。` — so a gap in your record is
visible in the PDF rather than silently omitted. Numbering follows the sections that actually
render, so a record with no strategy has no `2.x` subsections at all.

## Where the rendering rules themselves live

Not here. Section-by-section rendering for an agent at `finalize` time — quantities and the
dimensional check, math, figures, glyph coverage, editable sources, font profiles — is
[`references/report.md`](../skills/levin-research-notebook-runtime/references/report.md). This page
owns the field-to-call and field-to-section mapping only. If you change the section template in
`Notebook._template`, that file and this table both need the same edit, which is exactly why the
mapping is written down twice *(once per audience)* and nowhere else.
