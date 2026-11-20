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
| `lesson` | what to do differently next time | it is unactionable or over-applied | `lesson.remedy` + `conditions.applies_to` + record evidence |

These are hard rules: a violating entry is **refused at write time**, not stored and flagged. A
`boundary` without `fails_when` is a fact wearing a cautionary label, and a base that accepts those
cannot be read at face value.

Give every conclusion and boundary a `conditions.applies_to`. A claim with no stated scope reads as
universal, which is almost never what was measured.

## Lessons: operative, not epistemic

A `lesson` is the one kind that does not claim what the world is like — it says what to do next time.
That difference decides its rules:

| Field | Why it exists |
|---|---|
| `lesson.trigger` | the situation that sets it off, so a reader recognises it |
| `lesson.symptom` | what went wrong, concretely enough to match |
| `lesson.remedy` | **required** — a symptom with no remedy is a complaint |
| `lesson.still_unclear` | what is not solved yet, so a half-fix does not read as a fix |

```jsonc
{"agent_id": "agent-a", "topic": "protocol", "kind": "lesson",
 "statement": "BioEmu2 propagate 前必须删掉 OXT 端基，否则 system YAML 解析失败",
 "lesson": {"trigger": "准备 BioEmu2 system YAML 时",
            "symptom": "propagate 连续三次失败，报错指向多余端基",
            "remedy": "由 CIF 重建成 3-entity YAML 并删掉 OXT 后再提交",
            "still_unclear": "OXT 之外是否还有其它端基会触发同一错误"},
 "conditions": {"applies_to": "BioEmu2 propagate 输入准备"},
 "evidence": [{"source": "record", "experiment_id": "exp-…", "checkpoint_id": "checkpoint-…"}],
 "confidence": "provisional"}
```

Three rules are enforced at write time: a remedy, a scope, and **record** evidence. The last one is the
point — a lesson must have been paid for. Literature cannot supply it, and `validate` warns when no
cited checkpoint is a `failure`, because a lesson with no cost voucher behind it is hard to trust later.

### Where lessons do and do not belong

| Content | Home |
|---|---|
| how to operate this plugin or the agent itself ("run long jobs through `bg_run`") | the skill, or Levin's own Lessons — **not here** |
| how a protocol or tool behaves in this domain, and what to change next time | `kind: "lesson"` here |
| what the system under study does | `fact` / `conclusion` / `boundary` |

The test: would this still be true on another machine with another person? Yes and about method →
lesson here. About the object of study → knowledge. About the agent's own behaviour → Levin's Lessons.

### Promoting a failure into a lesson: `research_knowledge_candidates`

```jsonc
research_knowledge_candidates({"workspace_dir": "...", "include_promoted": false})
```

Lists `failure` checkpoints across every record that no lesson cites yet, newest first, with the record
title, whether that record has a delivered report, and the `lesson_id` where one already cites it. Run
it when you finish a task or a campaign: failures sit in records as receipts, and most of them should
stay there — promoting one is a judgement that it will save someone else the same cost.

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
