# How this documentation is organised

This page is the rule, not a suggestion. Every fact in this repository has exactly one home; every
other place that needs it carries a sentence and a link. If you add documentation and cannot say
which row of the table below owns your fact, the fact is not ready to be written down.

## Four surfaces, four jobs

| Surface | Reader, and the moment they read it | Shape | Owns |
|---|---|---|---|
| [`README.md`](../README.md) | someone deciding whether to install this, and someone doing their first run | short, declarative, link-heavy | identity, install, one quickstart, the honest headline limits, this map |
| `docs/` (this directory) | a human reasoning about the design, away from a task | explanatory, why-shaped, one argument per page | rationale, provenance, module responsibilities, what is unverified, how to contribute and release |
| [`skills/levin-research-notebook-runtime/`](../skills/levin-research-notebook-runtime/SKILL.md) | an agent in the middle of a task, one lifecycle stage at a time | imperative, stage-ordered, short | what the next call looks like, which gate will reject it, how to recover |
| the code | whoever changes behaviour | — | [`mcp/runner/plugin_spec.py`](../mcp/runner/plugin_spec.py) owns tool names and argument schemas; the constants in `notebook.py` and `reporting.py` own the numbers; the error text owns the rejection reason |

## The decision procedure

Ask these in order. The first `yes` decides the surface.

1. **Does it change what the next tool call looks like?** → skill reference file for that stage.
   Argument names, required fields, gate conditions, recovery steps. An agent that has to read a
   `docs/` page mid-task has already paid too much context for the answer.
2. **Does it change whether someone adopts this, or how they change the code?** → a `docs/` page.
   Why the manifest is canonical, what a module is allowed to do, which platform branch is untested,
   how a release is cut.
3. **Is it needed to decide whether to keep reading?** → `README.md`, at most two sentences plus a
   link. The README is a lens, not a manual.
4. **Is it a number, an enum, or a message?** → the source constant, `plugin_spec.py`, or the error
   string. Prose quotes it *with its file path* and never becomes the authority.

## Consequences you will notice

- **Tool schemas are never restated in prose.** `plugin_spec.py` drifts within days; a prose copy
  drifts silently. Pages describe intent and name the field, then link the spec.
- **The limit numbers live in code.** `MAX_RECORD` / `HASH_BUDGET` in `notebook.py` and
  `MAX_TEXT_CHARS` / `MAX_FIGURES` / `MAX_PAGES` in `reporting.py` are the authority. Four prose
  places quote them by need: the README's guarantee list (a caller deciding whether the size fits),
  the skill's `references/limits.md` (an agent about to hit one), the renderer invariants in
  [architecture](architecture.md) (a maintainer changing one), and the index cap in
  [limitations](limitations.md) (a maintainer reasoning about search). None of those may become the
  place a number is decided — when a constant changes, grep for the number and update every quoting,
  or delete the quoting and keep the constant.
- **Report rendering rules are owned by the skill.** [`references/report.md`](../skills/levin-research-notebook-runtime/references/report.md)
  carries the section-to-field map because that is what an agent needs at `finalize` time. The
  `docs/` sibling, [manifest-and-report](manifest-and-report.md), owns the *other* axis: which call
  writes each field and which fields never reach the page. One table, one axis, each.
- **Operational limits and unverified behaviour are different pages.** What the tool refuses lives
  in [`references/limits.md`](../skills/levin-research-notebook-runtime/references/limits.md); what
  the maintainer knows was never executed on this or any host lives in [limitations](limitations.md).
  Neither repeats the other.

## Before adding text, grep for it

```bash
# a phrase you are about to write; if it already exists, link instead of copying
grep -rn --include='*.md' 'phrase you are about to write' README.md docs skills
```

Duplication is not a style problem here; it is the defect that produced the 0.11.5 skill split. The
glyph rules, alias resolution and snapshot lifecycle had each been written twice — once in `SKILL.md`
and once in `references/limits.md` — and that is how two copies drift apart. The split left one home
for each fact and a link everywhere else.

## The pages

| Page | Answers |
|---|---|
| [why-not-an-eln](why-not-an-eln.md) | is this the right tool, and what does it deliberately not do |
| [lifecycle](lifecycle.md) | the five stages, with one real transcript from this repository's demo |
| [manifest-and-report](manifest-and-report.md) | where every manifest field comes from, and which of them reach the report |
| [architecture](architecture.md) | module map, the invariant each module enforces, and where to change X |
| [limitations](limitations.md) | known gaps, including platform branches never executed |
| [CONTRIBUTING](../CONTRIBUTING.md) | tests, compile, package, release, and the doc rules above |
| [CHANGELOG](../CHANGELOG.md) | what changed between released versions |

## Keeping links honest

Every relative link in every tracked `*.md` must resolve. Two checks exist; run the offline one
before you commit, because it needs no network and no plugin runtime:

```bash
python3 .github/scripts/check_links.py     # every relative link and #anchor
python3 .github/scripts/check_structure.py # SKILL.md size, skill links, version agreement
```

`.github/` is maintained separately; the commands above are the ones a documentation change needs.
