# The report: sections, numbers, figures, fonts

## Section map

The report is a fixed spine with a per-type middle chosen by `record_type`. Empty fields render as
an explicit "not recorded" line rather than disappearing, so a gap is visible instead of silent.

| Section | Filled from |
|---|---|
| Title + `***YYYY-MM-DD HH:MM:SS — YYYY-MM-DD HH:MM:SS***` | `title`, record timestamps |
| Three-sentence summary + fact table | `objective` / `purpose` / `expected_result`, `implementer`, runs, `environment_location` |
| 1. 实验目的 | `purpose` only; when it is empty the section prints 未记录研究问题。 (`hypothesis` feeds the header's 为什么要做 line instead) |
| 2. 实验策略 | `strategy: [{title, text}]` → 2.1, 2.2 … |
| 3. 实验方法和计划 | `method_plan` bullets, then method checkpoints as 3.1, 3.2 … |
| 4. 实验材料 | hosts/arch, dataset and script artifacts, `materials`, software versions, non-default parameters |
| 5. 实验结果 | 5.1 看到了什么 / 5.2 没看到什么 / 5.3 意外与处置 from `results.*` and observation/failure checkpoints; 5.4 量纲与单位核对 from `quantities` |
| 6. 实验结论和不足 | conclusion checkpoints, `interpretation`, `limitations` |
| 7. 下一步计划 | `plans` |
| 8. 经验教训 | `lessons` |
| 9. 数据空间统计 | measured notebook/scratch usage, `remote_space` for HPC hosts |
| 尾注 | `footnotes` |
| 工件与溯源 (new page) | artifacts and runs, digests and paths in code blocks |

`record_type` changes sections 2–6: `experiment` uses the table above, `analysis` reframes the middle
around data and method, `literature_review` around search strategy, reference list and synthesis.
`extra_sections` appends only; it cannot reorder the spine.

Only rendered sections consume numbers, so a record with no strategy has no 2.x at all.

## Quantities and the dimensional check

Every numeric result belongs in `quantities`, not buried in prose:

```text
research_record_finalize(..., quantities=[
  {"name": "rmsd",     "value": 2.1,   "unit": "Å"},
  {"name": "delta_g",  "value": -42.3, "unit": "kJ/mol", "uncertainty": 3.1},
  {"name": "kd",       "value": 4e-10, "unit": "M",      "replica": 1},
])
```

Table 5.4 prints the recorded unit, the canonical unit for that kind of quantity, and the dimension
formula. Severity is deliberate:

| Situation | Effect |
|---|---|
| Wrong dimension (a temperature recorded in `ps`) | blocks finalization |
| Unit missing while the name implies one (`rmsd` with no unit) | blocks finalization |
| Unparsable unit (`furlong`) | blocks finalization |
| Unknown quantity name with no declared `dimension` | blocks finalization |
| Legal but unconventional scale (`kcal/mol` where the notebook uses `kJ/mol`) | blocks unless acknowledged |
| One name in two different scales (`rmsd` in both `Å` and `nm`) | blocks finalization |
| The same name twice for one replica | blocks finalization |

Two escape hatches exist because a notebook default is not always the field's convention:

```text
{"name": "d_attack", "value": 12.0, "unit": "Å", "dimension": "L"}     # domain-specific name
{"name": "delta_g",  "value": -10.1, "unit": "kcal/mol", "unit_acknowledged": true}
```

`dimension` takes a dimension formula (`L`, `M L^2 T^-2 N^-1`, `1`), not a unit — it says what kind of
quantity this is. `unit_acknowledged` says "deliberately this unit", and the row becomes 惯例差异
instead of blocking. Neither converts the value.

Add `replica` for replicates: three trajectories reporting the same `rmsd` stay three rows with an
explicit replica column.

Known families cover length, time, mass, amount, molarity (mol/L, M, mM, µM, nM, pM), temperature,
energy, potential (V, mV), force, force constant, pressure, area, volume, density, rate, velocity,
angle and fraction. Ordinary decades of a family's unit (mV, µM) are conventional and do not warn; a
genuinely different scale does. If a name is not in any family, declare `dimension` rather than hoping.

The checker **never converts or rewrites a value** — it reports and you decide. Omit `unit` only for a
genuinely dimensionless score. A harmonic force constant (`kJ mol-1 nm-2`) and a force (`kJ/mol/nm`)
are different dimensions on purpose.

## Math

Inline `$E_a = 59.5\ \mathrm{kJ\,mol^{-1}}$` and a one-line display `$$ \Delta G = \Delta H - T\Delta S $$`
render offline through matplotlib's mathtext: no TeX installation, nothing leaves the machine. An
expression mathtext cannot render at all (empty, or plain broken) falls back to literal `$…$` text
rather than being dropped. Math is rasterised and therefore not searchable in the text layer; the
surrounding prose is. Put display math on **one** line — a multi-line `$$` block is not recognised and
prints its `$` delimiters literally.

## Figures

`\figures` dumps every accepted figure at one point. Prefer `\figure{artifact-id}` where the claim is
made, so a plot sits beside the sentence it supports; anything unreferenced is appended under 其余图表.
Figures are sized to roughly 62% of the printable height and move to a new page rather than being
shrunk below readability. Captions come from the artifact description. An unknown `artifact-id` prints
a visible placeholder instead of failing the render.

Never shrink a figure to make the layout tidy; let it take its page.

## Glyph coverage

`validate` checks the text that will be rendered against the faces the chosen profile actually
resolves, and warns per missing codepoint with a short context snippet. Prose is checked against the
serif and CJK faces, code blocks against the mono face separately — Menlo has `⇒`, so checking prose
against mono passed a character that still printed as tofu. Sub- and superscripts are transliterated to
caret notation and are not reported.

The warning is advisory. `unsupported_codepoints` in the render result stays the authoritative
post-render record. Because checkpoints are append-only, the fix is to reword before finalizing or
supersede the checkpoint, not to edit old text.

## Editable sources

Each report folder holds:

| File | Role |
|---|---|
| `report.md` | authority; regenerated from the manifest |
| `report.qmd` | Quarto wrapper, `execute: enabled: false` |
| `report.tex` | standalone xelatex/lualatex source (article, xeCJK, Times/Menlo) |
| `report.pdf` | fixed-layout deliverable produced by ReportLab |

The shipped PDF never depends on TeX; `report.tex` is for a reader who wants to typeset the same content
themselves. Regenerate rather than hand-edit `report.md` — edits are archived to
`revisions/human-record-*.md` and the view is rebuilt from the manifest.

## Fonts

The renderer never asks the user to pick a typeface. It resolves a **profile** — a named typographic
intent — against the faces installed on the host, and records what it used.

| Profile | Body (Latin + CJK) | Use when |
|---|---|---|
| `scientific-cjk` (default) | Times + Songti serif | Chinese body, English terms, formal record |
| `cjk-sans` | Times + Heiti sans body | Dense technical brief with many short sections |
| `latin-only` | Times + Songti fallback | English report with a little Chinese |

Choose by content, not preference. `auto` resolves to the default.

Two host facts matter. A missing CJK face is **silent in the PDF but loud in two places**:
`preflight.fonts.cjk_available` before rendering and `report.fonts.notes` afterwards — check the first,
because when it is false Chinese becomes `[U+XXXX]` regardless of profile. Second, only
TrueType-outline files (`.ttf`, `.ttc`) are usable; ReportLab rejects `.otf` CFF outlines, which rules
out most Source Han and Noto CJK OTF builds, so the candidate chains carry several platform spellings
instead of one expected name.

Code fences get Menlo (or a platform monospace) with keyword/string/comment highlighting — tag the
fence with its language. Figure text is drawn by matplotlib in Arial + Heiti; captions use the body
faces.
