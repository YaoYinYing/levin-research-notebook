# Limits, recovery and ownership

## Tool boundaries and replacements

| Tools | Owned task | Not a replacement for / migration |
|---|---|---|
| init, checkpoint, index | Stable filesystem experiment and progress records | Levin task planning or Knowledge; existing notes can be registered as input references |
| register_artifact | Evidence identity and references | DVC/DataLad storage or transfer; retain existing URLs/paths and checksums |
| register_run | Execution provenance and status history | Levin Jobs, Slurm or MLflow execution/tracking; record their IDs without replacing them |
| validate | Schema, references and bounded integrity | Scientific correctness, statistics review or independent reproduction; supply those as separate checkpoints |
| finalize | Versioned report source and bounded fixed-layout PDF | Full Quarto publishing or journal typesetting; edit/export report.qmd for advanced layouts |

## Data preservation constraints

- The working model is remote-first: raw data lives on the remote host, processing runs there, and
  only lightweight results come back. `source_origin: remote_copy` requires both `remote_host` and
  `remote_path`, so every remote-sourced entry names the machine and the original location, and this
  is rendered into `record.md` and the report. Landing a copy of a remote `raw`/`input` original also
  requires `remote_copy_permission`; a remote original larger than 64 MiB is refused even with
  permission and must be referenced instead. Pulled-back results above 64 MiB produce a warning.
  The plugin itself never copies, moves or contacts anything. `raw`/`input` paths inside
  `levin_scratch/` are rejected: scratch is disposable, evidence is not.
- `finalize` measures `levin_notebook/`, `levin_scratch/` and the experiment directory, and reports
  the change since the `init` baseline. The walk is bounded (200k entries, symlinks not followed) and
  marks `truncated: true` instead of under-reporting silently. Experiments created before 0.4.0 have
  no baseline, so the delta is reported as unavailable.

## Literature index

- BibTeX is read with `bibtexparser==2.1.0` from a workspace `.bib` (`bibtex_path`) or inline text
  (`bibtex`). At most 2000 entries per parse; unparsable blocks are reported as `bibtex_warnings`
  rather than dropped silently.
- Only metadata is read. Attachments referenced by `file = {...}` are never opened or copied, and no
  network request is made to resolve a DOI. DOI presence is recorded, not verified.
- `references` entries override a matching citekey field by field; annotations the export carries
  (`note`, `annote`, `abstract`, `keywords`, `file`) become `key_findings`.

## Practical limits

- Local deployment only in v0.x: persistent notebook operations must address the real workspace,
  not a transient Remote job staging copy. HPC/Slurm data are supported as references. Remote
  execution/staging of the notebook itself has not been validated and is deliberately disabled.
- One manifest at most 2 MB, 500 artifacts/runs/checkpoints each; index at most 10,000 records.
  Split campaigns into experiments. Index responses default to 100 with explicit offset/limit.
- At most 64 MiB hashed per registration and 64 MiB total per validation. Large files remain
  referenced in place; a supplied digest is labeled `supplied_unverified`. External references
  are never fetched. Warnings mean incomplete verification, not missing evidence proof.
- Foreground PDF: at most 200,000 characters, 20 figures and 500 pages. No external process,
  code execution, network, renderer daemon or job scheduler. Larger publications use external
  Quarto/Typst explicitly and register the result with its source/run provenance.
- Report typography is fixed: body text is Songti (宋体) with Times New Roman for Latin; headings and
  bold runs are Heiti (黑体) with Times New Roman; code blocks and inline code use Menlo (the VS Code
  default on macOS) with lightweight syntax highlighting for comments, strings, numbers and keywords
  in `python`, `bash`, `json` and `yaml`. Figure text uses Arial plus Heiti via
  `scripts/plot_style.py`, while captions stay in the body faces. Missing platform fonts fall back to
  bundled Vera/Courier and are reported through `unsupported_codepoints`, never silently substituted.
- ReportLab is mandatory and pinned; Quarto/Typst are optional and not installed automatically.
  QMD export sets execution disabled. Markdown tables/code are literal text; complex math and
  advanced typography need Quarto. Unsupported glyphs are explicit in renderer metadata.
- Local file locks serialize metadata mutations. Atomic replace and immutable prior manifests
  preserve recovery evidence. NFS/distributed locking guarantees are not claimed.
- The plugin never writes original data. Integrity checks can detect changes by other programs;
  filesystem permissions/WORM storage are outside its scope. Symlinked managed output paths are
  rejected; this is not a sandbox against a malicious process racing filesystem replacement.
- `validate` separates `valid` (structural, now) from `final_readiness.errors` (what `finalize`
  will require). A `finalize` blocked by a failed gate does not commit terminal execution status.
- `index` matches every whitespace term (AND, max 8) over titles, objectives, hypotheses,
  checkpoints, interpretation, limitations, artifact locations/descriptions/ids and run
  commands/failures/parameters/environment. It is substring search over a capped 200k haystack, not
  a full-text index; there is no ranking, and results carry summary fields only.
- Re-registering the same location with the same role refreshes that artifact entry (checksum,
  availability, description, links) in place, including a raw entry recorded while the file was
  absent; different roles stay separate records. A raw entry whose recorded checksum differs from
  the file is never refreshed: the change is rejected and the original record is retained. There is
  still no unregister tool.
- Only a successful finalization is stored under its `request_id`. A blocked or render-failed attempt
  leaves the id unconsumed so the identical call can be retried once the gate is cleared.
- After finalization, later mutations are allowed and `validate` warns that the delivered report is
  stale (report revision behind manifest revision). Regenerate deliberately; nothing auto-renders.
- Mutable `manifest.json` is canonical structured state. Immutable `revisions/*.json` retain
  history; record.md is a generated readable view. Manual edits to record.md are preserved under
  `revisions/human-record-*.md` before refresh. Edit notes.md for continuing human notes.
- Reports are new snapshot folders on each finalize attempt, including blocked ones (source files,
  no PDF). `final_readiness` describes the stored manifest, so its "Stored execution_status is wip"
  line is expected before the first successful finalize, not a blocker.
- Reports are new snapshot folders on each finalize attempt. `render_state=failed` or `blocked`
  means not finalized; editable sources survive. A successful finalization retry uses a new
  request ID if the previous failed attempt was recorded. Never silently reuse a stale PDF.
- On an interrupted write inspect manifest, revisions and pending scratch files. Validation is
  read-only and never repairs evidence. Atomic canonical manifest publication can precede the
  generated Markdown/index; a later authorized mutation refreshes views. Do not automatically
  roll back to an older manifest or delete scratch.
- Failed runs retain failure text and previous revisions. Resume uses the existing experiment;
  append a resume checkpoint and record a new run attempt or update an existing run explicitly.
- Metadata may itself be sensitive. No tool uploads anything. Notebook .gitignore excludes the
  data folder and common large-data extensions; it is not a comprehensive Git size policy.

No mandatory database, web service, cloud account, dashboard, telemetry, or model download.
