# Numbers, math, figures and editable report sources

## Quantities and the dimensional check

Every numeric result belongs in `quantities`, not buried in prose:

```text
research_record_finalize(..., quantities=[
  {"name": "rmsd",      "value": 2.1,   "unit": "Å"},
  {"name": "delta_g",   "value": -42.3, "unit": "kJ/mol", "uncertainty": 3.1},
  {"name": "occupancy", "value": 0.94,  "unit": "%"},
])
```

The report prints them as table 5.4 with the recorded unit, the canonical unit for that kind
of quantity, and the dimension formula. Severity is deliberate:

| Situation | Effect |
|---|---|
| Wrong dimension (a temperature recorded in `ps`) | blocks finalization |
| Unit missing while the name implies one (`rmsd` with no unit) | blocks finalization |
| Unparsable unit (`furlong`) | blocks finalization |
| Legal but unconventional unit (`kcal/mol` where the notebook uses `kJ/mol`) | warning only |
| Same quantity in two different scales (`rmsd` in both `Å` and `nm`) | blocks finalization |

The checker **never converts or rewrites your value** — it reports, and you decide. Omit
`unit` only for genuinely dimensionless scores. Accepted spellings include `Å`, `nm`, `ps`,
`fs`, `kJ/mol`, `kcal mol-1`, `kJ mol-1 nm-2`, `ns^-1`, `g/cm3`, `Å²`, `Å³`, `nm/ns`, `°`,
`%`, `frames`. A harmonic force constant (`kJ mol-1 nm-2`) and a force (`kJ/mol/nm`) are
different dimensions on purpose.

## Math

Inline `$E_a = 59.5\ \mathrm{kJ\,mol^{-1}}$` and display `$$ \Delta G = \Delta H - T\Delta S $$`
are rendered offline through matplotlib's mathtext — no TeX installation is required, and
nothing leaves the machine. A formula that cannot be parsed is shown as the literal `$…$`
text rather than dropped, so check the rendered PDF when a formula looks unusual. Math is
rasterised, so it is not searchable in the PDF text layer; the surrounding prose is.

## Figure placement

`\\figures` dumps every accepted figure at one point. Prefer `\\figure{artifact-id}` at the
place the claim is made, so a reader sees the plot next to the sentence it supports. Any
figure not referenced that way is appended under 其余图表. Figures are sized to the page
(about 62% of the printable height) and move to a new page instead of being shrunk below
readability; captions come from the artifact description. An unknown `artifact-id` prints a
visible placeholder instead of failing the render.

## Editable sources produced by finalize

Each report folder holds:

| File | Role |
|---|---|
| `report.md` | authority; regenerated from the manifest |
| `report.qmd` | Quarto wrapper, `execute: enabled: false` |
| `report.tex` | standalone xelatex/lualatex source (article class, xeCJK, Times/Menlo) |
| `report.pdf` | fixed-layout deliverable produced by ReportLab |

The shipped PDF never depends on TeX; `report.tex` is for readers who want to typeset the
same content themselves. Regenerate rather than hand-edit `report.md` — edits are archived to
`revisions/human-record-*.md` and the view is rebuilt from the manifest.
