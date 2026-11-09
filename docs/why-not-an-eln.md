# What this is, and when an ELN is the better answer

One page, for the decision. The claim this plugin makes is narrow: **a scientific task leaves a
record that survives the conversation, and that record is a directory you can read, diff and keep.**
Everything else is someone else's job.

## The shape

`levin-research-notebook` is a Levin plugin with eight `research_record_*` MCP tools. Each mutates
one canonical `manifest.json` per experiment under `<workspace>/levin_notebook/`, plus a ReportLab
renderer that turns the manifest into an editable Markdown/Quarto/LaTeX source and a fixed-layout
PDF. Compute stays where it already runs — a Levin Job, Slurm, your laptop — and this plugin records
what ran, on what, with which inputs, and what was concluded.

Deterministic tools, no LLM in the write path, no database, no service, no network, no telemetry.

## Use it when

- The work is **computational or experimental but already executable elsewhere**, and the missing
  piece is the write-up that keeps its provenance.
- You need the record to be **offline and durable**: a folder, a JSON manifest, immutable revisions,
  a PDF — not a subscription.
- Several agent sessions (or one human the next morning) must **resume** the same task without
  re-deriving what happened.
- The evidence is **large and remote** (trajectories, fastq, cluster scratch) and you want references
  with checksums, not copies.
- You want a **fixed report shape** — 目的 / 策略 / 方法 / 材料 / 结果 / 结论 / 计划 / 教训 — because a
  free-form notebook page lets you skip 不足 and 下一步计划, and the template will not.

## Use a real ELN instead when

This list is what the code does **not** implement; it is not a criticism of ELN products.

| Need | This plugin | A hosted ELN |
|---|---|---|
| Multi-user identity, per-record permissions, "who read what" | none — the workspace filesystem decides | core feature |
| Electronic signatures, regulatory audit trails | none | core feature (and the reason ELNs cost money) |
| Sample/inventory tracking, instrument integration, protocol execution | none | core feature |
| Full-text search across thousands of records | `research_record_index`: substring AND over a capped per-record haystack, no ranking ([limits](../skills/levin-research-notebook-runtime/references/limits.md)) | indexed search |
| Equations and typesetting to journal standard | rasterised mathtext subset; Markdown tables render as a truncated grid | usually pandoc/TeX-class output |
| Guaranteed rendering of arbitrary Unicode | missing glyphs are reported, not fixed — a host without a CJK face prints `[U+XXXX]` | font bundles |

If two or more rows on the right matter to you, stop here. If none do, the left column is a feature:
nothing to authenticate against, nothing to lose access to.

## What it deliberately refuses to do

These are enforced, not aspirational. Most are a literal rejection in `mcp/runner/notebook.py` with a
test behind them; the two that are absences (no execution, no science check) are absence of code, and
the renderer's no-network claim is asserted by patching `urlopen`/`os.system` in
`tests/test_reporting.py`.

- **Not run science.** No subprocess, no scheduler, no code execution anywhere in the tool path.
- **Not overwrite originals.** `raw`/`input` artifacts are referenced and hashed in place; a changed
  raw file is *rejected* rather than silently re-registered.
- **Not fetch external references.** `ssh://`, `s3://`, `https://` are recorded and never contacted;
  they stay `external_unverified`.
- **Not delete automatically.** Scratch is retained, prior manifests are kept, and only an explicit
  `prune_reports` call removes old PDF snapshots.
- **Not convert your numbers.** Units are dimension-checked; a wrong dimension blocks `finalize`, an
  unconventional-but-legal unit is reported as a convention difference. No value is rewritten.
- **Not prove the science.** Schema validity and matching checksums prove structure and identity.
  They never prove that a conclusion is correct or reproducible; that is stated in every report.

## Where the rest of the answer lives

- Five stages, one real transcript: [lifecycle](lifecycle.md).
- What each field is and which call writes it: [manifest-and-report](manifest-and-report.md).
- Module responsibilities and where to change things: [architecture](architecture.md).
- What has never been executed: [limitations](limitations.md).
- How these pages are chosen and kept honest: [docs/README](README.md).
