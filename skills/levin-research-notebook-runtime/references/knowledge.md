# Knowledge: what the records together establish

A record answers *what did we do, and what did it show*. Knowledge answers the next question:
*what do we now know, under which conditions, and how did we get there* — and it must stay
traceable, because a knowledge base that cites nothing is a rumour with good formatting.

Use this module when you have findings worth reusing **outside** the record that produced them: a
measured relationship, a mechanism you can defend, the limit beyond which a model stops working, or
the argument that connects them.

## One base, organised by topic

```
<workspace>/levin_knowledge/
    topics/<topic>/index.json      canonical entries for that topic
    topics/<topic>/revisions/…     every past state
    topics/<topic>/notes.md        human scratch, never written by the tools
    catalog.json                   derived: which topics exist
    brief.md                       derived: the whole base as one document
```

`catalog.json` and `brief.md` are **rebuilt from the topic indexes on every write**, so they cannot
disagree with the entries. A hand-maintained index is the classic way a knowledge base starts lying.

Topic names are `^[a-z0-9][a-z0-9_-]{0,40}$` — short subject words: `structural`, `electrostatics`,
`assay_protocol`. A new entry lands in the topic you name (default `general`). An **id is global**: an
update finds its entry on whatever shelf already holds it, so pass `id` alone to change content.

Cross-topic references are allowed and expected: a conclusion in `structural` routinely rests on a
fact in `electrostatics`. `derived_from` may point anywhere in the base.

## Four kinds — chosen by how they fail

| Kind | Answers | Fails when | Enforced |
|---|---|---|---|
| `fact` | what was measured here | the measurement is wrong | ≥1 **record** evidence |
| `conclusion` | what follows from facts | it is over-general | evidence or `derived_from` |
| `boundary` | where a conclusion stops holding | the limit is missing | `conditions.fails_when` non-empty |
| `derivation` | how support leads to the claim | a link breaks | ≥2 ordered `steps` |

These are hard rules: a violating entry is **refused at write time**, not stored and flagged. A
`boundary` without `fails_when` is a fact wearing a cautionary label, and a base that accepts those
cannot be read at face value.

Give every conclusion and boundary a `conditions.applies_to`. A claim with no stated scope reads as
universal, which is almost never what was measured.

## Evidence: measured here, or taken from literature

Every evidence item declares its `source`:

```jsonc
{"source": "record",   "experiment_id": "exp-…", "checkpoint_id": "checkpoint-…"}   // measured here
{"source": "external", "citation": "Doe 2024, DOI 10.1038/…"}                        // literature / prior
```

* `record` must resolve: the experiment must exist in `levin_notebook/`, and the checkpoint or
  artifact must exist inside it.
* `external` must carry a checkable `citation` and **must not** name an experiment — it was not
  measured here, and pretending otherwise is how a prior becomes a "result".

`basis` is **derived** from the evidence, never stored, so it cannot drift from what it describes:

| basis | meaning |
|---|---|
| `workspace` | every citation is a local record |
| `mixed` | local records plus literature |
| `external` | literature only — rendered under 先验假设, explicitly not verified here |
| `derived` | no direct evidence; follows from other knowledge entries |
| `none` | nothing supports it — refused |

An external-only entry marked `established` is allowed but warned: in this workspace that means "well
established in the literature", not "we reproduced it".

## Writing an entry

```jsonc
research_knowledge_upsert({
  "workspace_dir": "...", "topic": "structural",
  "entry": {
    "agent_id": "agent-a",
    "kind": "boundary",
    "statement": "该否证仅在 lag 10 单协议下成立，高 lag 对照不可用",
    "conditions": {
      "applies_to": "BioEmu2 系综比较",
      "holds_when": ["两侧在同一协议下各有 300 帧通过物理化筛选"],
      "fails_when": ["lag 1000 对照通过率 88/300 与 3/300，不能与 lag 10 直接比较"]
    },
    "evidence": [{"source": "record", "experiment_id": "exp-…", "checkpoint_id": "checkpoint-…"}],
    "confidence": "provisional"
  }
})
```

A refutation is the most reusable thing in a base — it saves someone else the same dead end — so
`confidence: "refuted"` **requires** `refuted_by` saying what disproved it.

Setting an entry aside (`retired: true`) requires `retire_reason`; the entry stays in the index and in
`revisions/`, appears in the brief's 已搁置 table, and stops being returned by `query`.

## Reading it

```jsonc
research_knowledge_query({"workspace_dir": "...", "query": "界面 接触数", "basis": "workspace"})
```

Terms are AND-ed over statement, detail, conditions, derivation steps, tags, cited experiments and
citations. Filters: `topic`, `kind`, `tag`, `confidence`, `basis`, `include_retired`. Every row carries
its `topic`, `basis`, `fails_when` and cited `experiments`, so a caller can tell a local result from a
prior without opening the brief.

## Keeping it from rotting — `validate`

The dangerous failure is not a wrong entry, it is an entry that was right when written. `validate`
re-reads every citation and reports support that has since:

- been **corrected** in its record (`supersedes`) — rest the claim on the correction;
- been **excluded** from its record as out of scope;
- been deleted, or a whole experiment removed.

It also reports broken `derived_from` targets, cycles, asymmetric `supersedes`/`superseded_by`, type
violations (a hand-edited index), and a `brief.md` or `catalog.json` that no longer matches the entries.

Run it before `export`, and after any record that the base cites gets corrected.

## Boundaries of this module

- No contradiction detection: two conclusions that disagree can only be judged by a reader.
- No automatic extraction from records: turning prose into claims is generating facts.
- No cross-workspace merge: one workspace, one evidence base.
- No vector search: the base is small and offline by design.
- Corrections are made by superseding, never by editing text in place — the old claim stays readable.
