# Citing papers: BibTeX, reference list, synthesis

## Pass a .bib, not typed entries

For a `literature_review` — and for any record that cites papers — point at a bibliography file:

```text
research_record_finalize(..., bibtex_path="data/library.bib",
  references=[{"id": "Doe2024", "evidence_level": "同行评议", "read_full_text": true}])
```

`bibtexparser` v2 reads the file. `references` then *overrides* fields on a matching citekey and adds
the judgement a `.bib` cannot carry: whether the full text was read, how strong the evidence is, why it
matters here. `bibtex` accepts inline BibTeX through the same parser.

Metadata that the parser derives is **not** overridable — a stale hand-written issue cannot overwrite a
freshly parsed one. Fix the `.bib`, not the record.

## Metadata hygiene (EndnoteTweak rules)

- Prefer the DOI as the identity; fall back to the title when there is no DOI.
- Keep the export's own annotation instead of replacing it with a summary of your own.
- Never pretend messy metadata is clean. Entries missing DOI, year, title, venue or authors are listed
  under 需人工核对的元数据 and repeated in the reference list, so a reader knows which citations need a
  human check.
- A citation you did not open is still a citation; do not upgrade `read_full_text` to make a claim look
  better supported.

## Reference list format

Single entry:

```text
第一作者 et al, 末位作者, 年, 期刊, 标题, DOI
```

Grouped into sections, each led by a sentence stating what that group reports, with `[n]` numbering
**continuous across sections**:

```text
以下文献报道了 b5 在细胞色素 P450 电子传递链中的位置

[1]. ...
[2]. ...

以下文献报道了同一家族中 heme 轴向配体的差异

[3]. ...
[4]. ...
```

Implement it with `reference_sections: [{title, text}]` plus `section` on each reference. A reference
with no `section` falls into the leading group.

## Synthesis and citation graph

- `search_strategy: {databases, query, window, languages, screening}` records how the literature was
  found — a review without a search strategy is an opinion.
- `synthesis` is the prose that draws the papers together. Write the argument here, not inside the
  reference list.
- `citations: [{from, to, relation}]` records edges between reference ids (supports / contradicts /
  extends / replicates). This is how a small citation tree becomes explicit instead of implied.
- Link fetched structures or re-computations with `reference_id` on the artifact or run, so 复算与核验
  ties each result back to the paper it came from.

## Judgement that stays yours

A literature review's conclusions still follow the normal rule: a `conclusion` checkpoint needs
evidence ids. In a review the evidence is usually the reference-linked artifacts and runs, not a
figure. State in `limitations` what the search could not reach — paywalls, language, date window — since
"no paper found" is rarely the same as "no such result".
