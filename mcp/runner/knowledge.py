"""Cross-experiment knowledge: what the records together establish, organised by topic.

An experiment record answers *what did we do, and what did it show*. This module answers
the next question — *what do we now know, under which conditions, and how did we get
there* — and refuses to answer it without a path back to the support.

Four kinds, kept apart because they fail in different ways and a reader needs to know
which failure they are looking at:

- ``fact``       something measured here. Wrong when the measurement is wrong.
- ``conclusion`` what follows from facts. Wrong when it is over-general.
- ``boundary``   where a conclusion stops holding. Useless without its limit stated, so
                 ``boundary`` requires ``conditions.fails_when``: without a limit it is
                 just another fact wearing a cautionary label.
- ``derivation`` the chain from evidence to conclusion, written step by step so a
                 reviewer can attack one link instead of the whole argument.

Support is either **record** evidence (measured in this workspace) or **external** evidence
(literature, prior knowledge). The distinction is load-bearing: ``basis`` is derived from
the evidence and never hand-set, the brief renders the two in separate blocks, and a claim
resting only on literature is reported as a prior — not as something this workspace
established.

One base per workspace, partitioned by topic because a programme outgrows one list::

    <workspace>/levin_knowledge/
        topics/<topic>/index.json       canonical entries for that topic
        topics/<topic>/revisions/NNNNNN-<uuid>.json
        topics/<topic>/notes.md         human scratch, never written here
        catalog.json                    derived: which topics exist and how big
        brief.md                        derived: the whole base as one document

`catalog.json` and `brief.md` are rebuilt from the topic indexes on every write, so they
cannot disagree with the entries — the failure mode of every hand-maintained index.

Cross-topic references are allowed: `derived_from` may point at an entry in another topic,
because a conclusion in one area routinely rests on a fact established in another.

``validate`` re-reads every cited experiment and reports support that has since been
corrected, excluded or deleted — the failure mode that silently rots a knowledge base while
it still looks pristine.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path

from filelock import FileLock
from jsonschema import Draft202012Validator

from notebook import (EXP, NotebookError, canonical, now, safe_name, text, uid,
                      human_bytes, usage)

MAX_KNOWLEDGE = 4_000_000
MAX_ENTRIES = 5000
DEFAULT_TOPIC = 'general'
TOPIC = re.compile(r'^[a-z0-9][a-z0-9_-]{0,40}$')
KID = re.compile(r'^kn-[0-9a-f]{32}$')
KINDS = ('fact', 'conclusion', 'boundary', 'derivation')
KIND_LABELS = {'fact': '事实', 'conclusion': '结论', 'boundary': '可行边界', 'derivation': '推导过程'}
CONFIDENCE = ('established', 'provisional', 'refuted')
# How a claim is supported. Derived from evidence, never stored, so it cannot drift.
BASIS = ('workspace', 'mixed', 'external', 'derived', 'none')
BASIS_LABELS = {
    'workspace': '本工作区已验证',
    'mixed': '工作区证据 + 外部依据',
    'external': '外部依据（本工作区未验证）',
    'derived': '由其他条目推导',
    'none': '无依据',
}

EVIDENCE_SCHEMA = {
    'type': 'object', 'additionalProperties': False, 'required': ['source'],
    'properties': {
        'source': {'enum': ['record', 'external']},
        'experiment_id': {'type': 'string', 'pattern': '^exp-[0-9a-f]{32}$'},
        'checkpoint_id': {'type': 'string', 'maxLength': 120},
        'artifact_id': {'type': 'string', 'maxLength': 120},
        'citation': {'type': 'string', 'maxLength': 1000},
        'note': {'type': 'string', 'maxLength': 500},
    },
    'allOf': [
        {'if': {'properties': {'source': {'const': 'record'}}, 'required': ['source']},
         'then': {'required': ['experiment_id']}},
        {'if': {'properties': {'source': {'const': 'external'}}, 'required': ['source']},
         'then': {'required': ['citation'], 'not': {'required': ['experiment_id']}}},
    ],
}
STEP_SCHEMA = {
    'type': 'object', 'additionalProperties': False, 'required': ['claim', 'from'],
    'properties': {
        'claim': {'type': 'string', 'minLength': 1, 'maxLength': 4000},
        # What this step rests on: a knowledge id, a checkpoint id, an artifact id, or a
        # short description of the inference rule ("by the triangle inequality").
        'from': {'type': 'array', 'maxItems': 20, 'items': {'type': 'string', 'maxLength': 140}},
    },
}
CONDITIONS_SCHEMA = {
    'type': 'object', 'additionalProperties': False,
    'properties': {
        'applies_to': {'type': 'string', 'maxLength': 2000},
        'holds_when': {'type': 'array', 'maxItems': 30, 'items': {'type': 'string', 'maxLength': 1000}},
        'fails_when': {'type': 'array', 'maxItems': 30, 'items': {'type': 'string', 'maxLength': 1000}},
    },
}
ENTRY_SCHEMA = {
    'type': 'object', 'additionalProperties': False,
    'required': ['id', 'kind', 'statement', 'agent_id', 'created_at', 'updated_at',
                 'revision', 'confidence', 'evidence', 'derived_from', 'conditions',
                 'tags', 'steps', 'retired'],
    'properties': {
        'id': {'type': 'string', 'pattern': '^kn-[0-9a-f]{32}$'},
        'kind': {'enum': list(KINDS)},
        'statement': {'type': 'string', 'minLength': 1, 'maxLength': 4000},
        'detail': {'type': 'string', 'maxLength': 20000},
        'conditions': CONDITIONS_SCHEMA,
        'evidence': {'type': 'array', 'maxItems': 200, 'items': EVIDENCE_SCHEMA},
        'derived_from': {'type': 'array', 'maxItems': 50,
                         'items': {'type': 'string', 'pattern': '^kn-[0-9a-f]{32}$'}},
        'steps': {'type': 'array', 'maxItems': 50, 'items': STEP_SCHEMA},
        'confidence': {'enum': list(CONFIDENCE)},
        'tags': {'type': 'array', 'maxItems': 30, 'items': {'type': 'string', 'maxLength': 60}},
        'supersedes': {'type': ['string', 'null']},
        'superseded_by': {'type': ['string', 'null']},
        'refuted_by': {'type': 'string', 'maxLength': 4000},
        'retired': {'type': 'boolean'},
        'retired_reason': {'type': 'string', 'maxLength': 2000},
        'agent_id': {'type': 'string', 'maxLength': 100},
        'created_at': {'type': 'string'},
        'updated_at': {'type': 'string'},
        'revision': {'type': 'integer', 'minimum': 1},
    },
}
TOPIC_INDEX_SCHEMA = {
    'type': 'object', 'additionalProperties': False,
    'required': ['schema_version', 'topic', 'revision', 'updated_at', 'entries'],
    'properties': {
        'schema_version': {'const': 1},
        'topic': {'type': 'string'},
        'revision': {'type': 'integer', 'minimum': 0},
        'updated_at': {'type': 'string'},
        'entries': {'type': 'array', 'maxItems': MAX_ENTRIES, 'items': ENTRY_SCHEMA},
        'requests': {'type': 'object'},
    },
}
CATALOG_SCHEMA = {
    'type': 'object', 'additionalProperties': False,
    'required': ['schema_version', 'updated_at', 'topics'],
    'properties': {
        'schema_version': {'const': 1},
        'updated_at': {'type': 'string'},
        'topics': {'type': 'array', 'items': {'type': 'object', 'additionalProperties': False,
                                              'required': ['topic', 'entries', 'revision', 'updated_at'],
                                              'properties': {'topic': {'type': 'string'},
                                                             'title': {'type': 'string'},
                                                             'entries': {'type': 'integer', 'minimum': 0},
                                                             'revision': {'type': 'integer', 'minimum': 0},
                                                             'updated_at': {'type': 'string'}}}},
    },
}
VALIDATOR = Draft202012Validator(TOPIC_INDEX_SCHEMA)
CATALOG_VALIDATOR = Draft202012Validator(CATALOG_SCHEMA)


def basis_of(entry):
    """Where an entry's support comes from.

    Derived from the evidence list on every read: a stored copy would eventually disagree
    with the evidence it describes, and the whole point is that a reader can trust it.
    """
    sources = {item['source'] for item in entry['evidence']}
    if not sources:
        return 'derived' if entry['derived_from'] else 'none'
    if sources == {'record'}:
        return 'workspace'
    if sources == {'external'}:
        return 'external'
    return 'mixed'


def _blank(topic):
    return {'schema_version': 1, 'topic': topic, 'revision': 0, 'updated_at': now(),
            'entries': [], 'requests': {}}


class Knowledge:
    """The workspace knowledge base: upsert, query, validate, export, across topics."""

    def __init__(self, workspace):
        self.workspace = Path(workspace).expanduser().resolve()
        self.root = self.workspace / 'levin_knowledge'
        self.topics_root = self.root / 'topics'
        self.notebook = self.workspace / 'levin_notebook'
        self.tmp = self.workspace / '.levin_knowledge_tmp'

    # ---------- plumbing: same invariants as the notebook ----------
    def _guard(self, path):
        path = Path(path)
        current = path
        while True:
            if current.is_symlink():
                raise NotebookError(f'Symlink managed path rejected: {current}')
            if current == self.workspace or current.parent == current:
                return path
            current = current.parent

    def _lock(self):
        self.root.mkdir(parents=True, exist_ok=True)
        return FileLock(str(self._guard(self.root / '.knowledge.lock')), timeout=10)

    def _atomic(self, path, content):
        path = self._guard(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.tmp.mkdir(parents=True, exist_ok=True)
        tmp = self.tmp / (uuid.uuid4().hex + '.pending')
        with open(tmp, 'x', encoding='utf-8') as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)

    # ---------- topics ----------
    @staticmethod
    def check_topic(topic):
        if not isinstance(topic, str) or not TOPIC.fullmatch(topic) or topic in ('.', '..'):
            raise NotebookError(f'topic must match ^[a-z0-9][a-z0-9_-]{{0,40}}$ (lowercase, no spaces); '
                                f'got {topic!r}. Use a short subject name such as structural or electrostatics')
        return topic

    def _topic_dir(self, topic):
        return self.topics_root / self.check_topic(topic)

    def topic_names(self):
        if not self.topics_root.is_dir():
            return []
        return sorted(p.name for p in self.topics_root.iterdir()
                      if p.is_dir() and (p / 'index.json').is_file())

    def _load_topic(self, topic):
        path = self._topic_dir(topic) / 'index.json'
        if not path.is_file():
            return _blank(topic)
        try:
            index = json.loads(path.read_text(encoding='utf-8'))
        except json.JSONDecodeError as error:
            raise NotebookError(f'levin_knowledge/topics/{topic}/index.json is not valid JSON: {error}')
        VALIDATOR.validate(index)
        return index

    def load(self):
        """Every topic merged into one base, each entry remembering where it lives."""
        base = {'topics': {}, 'entries': [], 'updated_at': now(), 'revision': 0}
        for topic in self.topic_names():
            index = self._load_topic(topic)
            base['topics'][topic] = index
            base['revision'] += index['revision']
            base['updated_at'] = max(base['updated_at'], index['updated_at'])
            for entry in index['entries']:
                merged = dict(entry)
                merged['_topic'] = topic
                base['entries'].append(merged)
        return base

    def _save_topic(self, topic, index):
        VALIDATOR.validate(index)
        index['revision'] += 1
        index['updated_at'] = now()
        body = canonical(index)
        if len(body.encode()) > MAX_KNOWLEDGE:
            raise NotebookError(f'Topic {topic} exceeds {human_bytes(MAX_KNOWLEDGE)}; split it into two topics')
        folder = self._topic_dir(topic)
        self._atomic(folder / 'revisions' / f"{index['revision']:06d}-{uuid.uuid4().hex}.json", body)
        self._atomic(folder / 'index.json', body)
        # Catalog and brief are derived, so they are rebuilt here rather than maintained:
        # a hand-kept index is the classic way a knowledge base starts lying.
        self._rebuild()

    def catalog(self, base=None):
        """The catalog as data. Pure: a read must never rewrite the base."""
        base = base or self.load()
        topics = []
        for name in self.topic_names():
            index = base['topics'][name]
            live = sum(1 for e in index['entries'] if not e.get('retired'))
            topics.append({'topic': name, 'entries': live,
                           'revision': index['revision'], 'updated_at': index['updated_at']})
        catalog = {'schema_version': 1, 'updated_at': now(), 'topics': topics}
        CATALOG_VALIDATOR.validate(catalog)
        return catalog

    def _rebuild(self):
        base = self.load()
        catalog = self.catalog(base)
        self._atomic(self.root / 'catalog.json', canonical(catalog))
        self._atomic(self.root / 'brief.md', self.render(base))
        return catalog

    # ---------- provenance ----------
    def _manifest(self, eid, cache):
        if eid in cache:
            return cache[eid]
        path = self.notebook / 'experiments' / eid / 'manifest.json'
        value = None
        if path.is_file():
            try:
                value = json.loads(path.read_text(encoding='utf-8'))
            except json.JSONDecodeError:
                value = None
        cache[eid] = value
        return value

    def _check_evidence(self, evidence, cache, strict):
        """Resolve every citation and report support that no longer holds.

        ``strict`` (write time) raises, so a dangling or stale citation cannot be
        introduced. Validation is softer where the distinction matters: a citation that was
        fine when written and has since been corrected is exactly what a knowledge base has
        to notice, and refusing it at write time would not have helped.
        """
        problems = []
        for item in evidence:
            if item.get('source') == 'external':
                if len((item.get('citation') or '').strip()) < 8:
                    problems.append('cites external evidence without a checkable citation; name the source '
                                    '(author, year, DOI, or a stable URL) so a reader can verify it')
                continue
            eid = item.get('experiment_id') or ''
            manifest = self._manifest(eid, cache)
            if manifest is None:
                problems.append(f'records {eid or "(no experiment)"} but no such experiment exists in levin_notebook/')
                continue
            checkpoints = {c['id']: c for c in manifest.get('checkpoints') or []}
            artifacts = {a['id']: a for a in manifest.get('artifacts') or []}
            cited_checkpoint = item.get('checkpoint_id')
            cited_artifact = item.get('artifact_id')
            if cited_checkpoint and cited_checkpoint not in checkpoints:
                problems.append(f'records {eid} checkpoint {cited_checkpoint}, which does not exist')
                continue
            if cited_artifact and cited_artifact not in artifacts:
                problems.append(f'records {eid} artifact {cited_artifact}, which does not exist')
                continue
            # Support the record itself has set aside or corrected cannot carry knowledge.
            if cited_checkpoint:
                entry = checkpoints[cited_checkpoint]
                if entry.get('excluded'):
                    problems.append(f'records {eid} checkpoint {cited_checkpoint}, which the record excludes '
                                    f'as out of scope ({entry.get("exclusion_reason") or "no reason given"})')
                else:
                    correctors = [c for c in checkpoints.values()
                                  if c.get('supersedes') == cited_checkpoint and not c.get('excluded')]
                    if correctors:
                        problems.append(f'records {eid} checkpoint {cited_checkpoint}, which was corrected by '
                                        f'{correctors[0]["id"]}; rest the claim on the correction instead')
            if cited_artifact and artifacts[cited_artifact].get('excluded'):
                problems.append(f'records {eid} artifact {cited_artifact}, which the record excludes as out of scope')
        if strict and problems:
            raise NotebookError('Evidence does not resolve: ' + '; '.join(problems[:3]) +
                                (f' (and {len(problems) - 3} more)' if len(problems) > 3 else ''))
        return problems

    # ---------- rules ----------
    def _kind_problems(self, entry, cache=None):
        """What makes a kind mean something: (hard errors, advisory warnings).

        Split because "a boundary must state where it fails" is a rule, while "state your
        scope" is advice. Collapsing them turned every hint into a rejection.
        """
        hard, soft = [], []
        kind, evidence = entry['kind'], entry['evidence']
        basis = basis_of(entry)
        conditions = entry['conditions']
        if not evidence and not entry['derived_from']:
            hard.append('no evidence and no derived_from: nothing supports this claim')
        if kind == 'fact' and not any(item['source'] == 'record' for item in evidence):
            hard.append('a fact is something measured in this workspace: cite at least one record. '
                        'An external or derived claim is a conclusion or a prior, not a fact')
        if kind == 'conclusion' and not (evidence or entry['derived_from']):
            hard.append('a conclusion needs evidence or derived_from, otherwise it is an opinion')
        if kind == 'boundary' and not conditions['fails_when']:
            hard.append('a boundary without conditions.fails_when is just a fact; state where it stops holding')
        if kind == 'derivation' and len(entry['steps']) < 2:
            hard.append('a derivation needs at least two ordered steps; one step is a restatement')
        if kind in ('conclusion', 'boundary') and not conditions['applies_to']:
            soft.append('state conditions.applies_to: a conclusion with no stated scope reads as universal')
        if basis == 'external' and entry['confidence'] == 'established':
            soft.append('marked established but every citation is external; in this workspace that is a '
                        'prior, not a result — provisional is the honest label until a record supports it')
        if entry['confidence'] == 'established' and len(evidence) < 2 and not entry['derived_from']:
            if cache is None or not self._supported_by_finalized(entry, cache):
                soft.append('established on a single piece of evidence is usually provisional')
        if kind == 'boundary' and basis == 'external':
            soft.append('a boundary derived from literature alone still needs a local record before anyone '
                        'relies on it for this system')
        return hard, soft

    def _supported_by_finalized(self, entry, cache):
        for item in entry['evidence']:
            if item.get('source') != 'record':
                continue
            manifest = self._manifest(item.get('experiment_id', ''), cache)
            if manifest and any((r or {}).get('render_state') == 'success' for r in manifest.get('reports') or []):
                return True
        return False

    # ---------- write ----------
    def upsert(self, payload, topic=None, request_id=None):
        """Create or update one entry. Omitting an id creates; passing one updates in place.

        A new entry lands in ``topic`` (default ``general``). An update finds its entry in
        whatever topic already holds it, so an id is a global handle and a topic is a shelf.
        """
        if not isinstance(payload, dict):
            raise NotebookError('entry must be an object')
        allowed = {'id', 'topic', 'kind', 'statement', 'detail', 'conditions', 'evidence',
                   'derived_from', 'steps', 'confidence', 'tags', 'supersedes', 'refuted_by',
                   'retired', 'retire_reason', 'agent_id'}
        unknown = set(payload) - allowed
        if unknown:
            raise NotebookError('Unknown knowledge fields: ' + ', '.join(sorted(unknown)))
        agent_id = safe_name(payload.get('agent_id') or '', 'agent_id')
        payload_topic = payload.get('topic') or topic or DEFAULT_TOPIC
        self.check_topic(payload_topic)
        if payload.get('id') is not None and not KID.fullmatch(str(payload['id'])):
            raise NotebookError(f'id must look like kn-<32 hex>; got {payload["id"]!r}')
        for field, limit in (('statement', 4000), ('detail', 20000), ('refuted_by', 4000)):
            if payload.get(field) is not None:
                text(payload[field], field, field == 'statement', limit=limit)
        if payload.get('statement') is not None and len(payload['statement'].strip()) < 12:
            raise NotebookError('statement must be a full sentence stating the claim (at least 12 '
                                'characters); a two-word label is not knowledge')

        with self._lock():
            base = self.load()
            # An id is global: find which shelf already holds it before deciding the topic.
            home = None
            if payload.get('id'):
                home = next((e['_topic'] for e in base['entries'] if e['id'] == payload['id']), None)
                if home is None:
                    raise NotebookError(f'no knowledge entry {payload["id"]!r}; omit id to create one')
                payload_topic = home
            entries = {e['id']: e for e in base['entries']}
            index = base['topics'].get(payload_topic) or _blank(payload_topic)

            if request_id:
                safe_name(request_id, 'request_id')
                recorded = (index.get('requests') or {}).get(request_id)
                if recorded:
                    statement = payload.get('statement')
                    if statement is not None and recorded.get('statement') != statement.strip():
                        raise NotebookError('request_id reused with different content')
                    return {'knowledge_id': recorded['knowledge_id'], 'topic': payload_topic,
                            'idempotent': True}

            cache = {}
            existing = next((e for e in index['entries'] if e['id'] == payload.get('id')), None)

            kind = payload.get('kind') or (existing or {}).get('kind')
            if kind not in KINDS:
                raise NotebookError(f'kind must be one of {", ".join(KINDS)}')
            statement = payload.get('statement') or (existing or {}).get('statement')
            if not statement:
                raise NotebookError('statement is required')

            conditions = payload.get('conditions', (existing or {}).get('conditions') or {})
            if not isinstance(conditions, dict):
                raise NotebookError('conditions must be an object with applies_to / holds_when / fails_when')
            unknown_conditions = set(conditions) - {'applies_to', 'holds_when', 'fails_when'}
            if unknown_conditions:
                raise NotebookError('Unknown condition fields: ' + ', '.join(sorted(unknown_conditions)))
            normalised_conditions = {
                'applies_to': str(conditions.get('applies_to') or '').strip(),
                'holds_when': [str(x).strip() for x in (conditions.get('holds_when') or []) if str(x).strip()],
                'fails_when': [str(x).strip() for x in (conditions.get('fails_when') or []) if str(x).strip()],
            }

            evidence = payload.get('evidence', (existing or {}).get('evidence') or [])
            if not isinstance(evidence, list):
                raise NotebookError('evidence must be a list of {source, experiment_id|citation, ...}')
            for item in evidence:
                if not isinstance(item, dict):
                    raise NotebookError('each evidence entry must be an object')
                source = item.get('source')
                if source not in ('record', 'external'):
                    raise NotebookError("each evidence entry needs source: 'record' (measured here) or "
                                        "'external' (literature or prior knowledge)")
                if source == 'record' and not EXP.fullmatch(str(item.get('experiment_id') or '')):
                    raise NotebookError('record evidence needs experiment_id matching exp-<32 hex>; '
                                        'for literature use source=external with a citation')
                if source == 'external':
                    text(item.get('citation') or '', 'citation', True, limit=1000)
                    if 'experiment_id' in item or 'checkpoint_id' in item or 'artifact_id' in item:
                        raise NotebookError('external evidence must not name an experiment, checkpoint or '
                                            'artifact: it was not measured in this workspace')
            self._check_evidence(evidence, cache, strict=True)

            derived_from = payload.get('derived_from', (existing or {}).get('derived_from') or [])
            for parent in derived_from:
                if parent not in entries:
                    raise NotebookError(f'derived_from names unknown knowledge {parent!r}; create it first')
                if existing and parent == existing['id']:
                    raise NotebookError('an entry cannot derive from itself')

            steps = payload.get('steps', (existing or {}).get('steps') or [])
            if not isinstance(steps, list):
                raise NotebookError('steps must be a list of {claim, from}')
            for step in steps:
                if not isinstance(step, dict) or not str(step.get('claim') or '').strip():
                    raise NotebookError('each step needs a non-empty claim')
                if not isinstance(step.get('from'), list) or not step['from']:
                    raise NotebookError('each step needs from: what it rests on (knowledge id, checkpoint id, or rule)')

            supersedes = payload.get('supersedes')
            if supersedes and supersedes not in entries:
                raise NotebookError(f'supersedes names unknown knowledge {supersedes!r}')
            if supersedes and existing and supersedes == existing['id']:
                raise NotebookError('an entry cannot supersede itself')

            confidence = payload.get('confidence') or (existing or {}).get('confidence') or 'provisional'
            if confidence not in CONFIDENCE:
                raise NotebookError(f'confidence must be one of {", ".join(CONFIDENCE)}')
            refuted_by = payload.get('refuted_by', (existing or {}).get('refuted_by') or '')
            if confidence == 'refuted' and not str(refuted_by).strip():
                raise NotebookError('confidence=refuted must say what refuted it (refuted_by); an earned '
                                    'refutation is the most reusable thing in a knowledge base')

            tags = payload.get('tags', (existing or {}).get('tags') or [])
            if not isinstance(tags, list) or len(tags) > 30:
                raise NotebookError('tags must be a list of at most 30 strings')

            entry = {
                'id': existing['id'] if existing else uid('kn'),
                'kind': kind,
                'statement': statement.strip(),
                'detail': (payload.get('detail', (existing or {}).get('detail') or '')).strip(),
                'conditions': normalised_conditions,
                'evidence': evidence,
                'derived_from': list(derived_from),
                'steps': steps,
                'confidence': confidence,
                'tags': [str(t).strip() for t in tags if str(t).strip()],
                'supersedes': supersedes or (existing or {}).get('supersedes'),
                'superseded_by': (existing or {}).get('superseded_by'),
                'refuted_by': str(refuted_by).strip() if confidence == 'refuted' else '',
                'retired': bool(payload.get('retired', (existing or {}).get('retired', False))),
                'retired_reason': str(payload.get('retire_reason',
                                                 (existing or {}).get('retired_reason') or '')).strip(),
                'agent_id': agent_id,
                'created_at': existing['created_at'] if existing else now(),
                'updated_at': now(),
                'revision': (existing['revision'] + 1) if existing else 1,
            }
            # A superseded entry must point forward, so a reader landing on the old claim is
            # one hop from the current one — even when the replacement sits on another shelf.
            if supersedes:
                old = entries[supersedes]
                old['superseded_by'] = entry['id']
                old['updated_at'] = now()
                old_index = base['topics'].get(old['_topic'])
                if old_index is not None and old['_topic'] != payload_topic:
                    self._save_topic(old['_topic'], old_index)

            previously_retired = bool((existing or {}).get('retired'))
            if entry['retired'] and not previously_retired and len(entry['retired_reason']) < 8:
                raise NotebookError('setting an entry aside needs retire_reason (at least 8 characters) '
                                    'saying why it is no longer authoritative; an unexplained gap is '
                                    'worse than a wrong claim')
            # A hard rule violation means the entry is not what its kind claims, so it is
            # refused here rather than written and flagged: a boundary without its limit is
            # a mislabeled fact, and a base that tolerates those cannot be read at face value.
            hard, soft = self._kind_problems(entry, cache)
            if hard:
                raise NotebookError(f'{KIND_LABELS[kind]} 不成立：' + '；'.join(hard))
            if existing:
                index['entries'][index['entries'].index(existing)] = entry
            else:
                index['entries'].append(entry)
            # Recorded before saving so a retried call cannot produce a second identical entry.
            if request_id:
                index.setdefault('requests', {})[request_id] = {
                    'statement': entry['statement'], 'knowledge_id': entry['id']}
            self._save_topic(payload_topic, index)
            return {'knowledge_id': entry['id'], 'topic': payload_topic, 'revision': entry['revision'],
                    'created': existing is None, 'kind': kind, 'confidence': confidence,
                    'basis': basis_of(entry),
                    # Only advice survives to here; anything fatal was refused above.
                    'warnings': soft}

    def retire(self, kid, agent_id, reason, restore=False):
        """Keep an entry out of the brief without deleting it."""
        safe_name(agent_id, 'agent_id')
        text(reason, 'reason')
        if len(reason.strip()) < 8:
            raise NotebookError('a retire or reinstate needs a reason (at least 8 characters)')
        with self._lock():
            base = self.load()
            target = next((e for e in base['entries'] if e['id'] == kid), None)
            if target is None:
                raise NotebookError(f'no knowledge entry {kid!r}')
            topic = target['_topic']
            index = base['topics'][topic]
            entry = next(e for e in index['entries'] if e['id'] == kid)
            entry['retired'] = not restore
            entry['retired_reason'] = reason.strip() if not restore else entry.get('retired_reason', '')
            entry['updated_at'] = now()
            entry['revision'] += 1
            self._save_topic(topic, index)
            return {'knowledge_id': kid, 'topic': topic, 'retired': entry['retired'], 'reason': reason.strip()}

    # ---------- read ----------
    def query(self, text_query='', kind=None, tag=None, confidence=None, basis=None, topic=None,
              include_retired=False, limit=50, offset=0):
        if kind and kind not in KINDS:
            raise NotebookError(f'kind must be one of {", ".join(KINDS)}')
        if basis and basis not in BASIS:
            raise NotebookError(f'basis must be one of {", ".join(BASIS)}')
        if topic:
            self.check_topic(topic)
        base = self.load()
        terms = [t for t in (text_query or '').lower().split()[:8]]
        rows = []
        for entry in base['entries']:
            if entry.get('retired') and not include_retired:
                continue
            if topic and entry['_topic'] != topic:
                continue
            entry_basis = basis_of(entry)
            if kind and entry['kind'] != kind:
                continue
            if tag and tag not in entry['tags']:
                continue
            if confidence and entry['confidence'] != confidence:
                continue
            if basis and entry_basis != basis:
                continue
            if terms:
                haystack = ' '.join([
                    entry['statement'], entry.get('detail', ''), entry['id'],
                    entry['conditions'].get('applies_to', ''),
                    ' '.join(entry['conditions'].get('holds_when') or []),
                    ' '.join(entry['conditions'].get('fails_when') or []),
                    ' '.join(entry['tags']),
                    ' '.join(step['claim'] for step in entry['steps']),
                    ' '.join(item.get('experiment_id') or item.get('citation') or ''
                             for item in entry['evidence']),
                ]).lower()
                if not all(term in haystack for term in terms):
                    continue
            rows.append({
                'id': entry['id'], 'topic': entry['_topic'], 'kind': entry['kind'],
                'confidence': entry['confidence'], 'basis': entry_basis,
                'statement': entry['statement'],
                'applies_to': entry['conditions'].get('applies_to', ''),
                'fails_when': list(entry['conditions'].get('fails_when') or []),
                'tags': list(entry['tags']),
                'evidence_count': len(entry['evidence']),
                'experiments': sorted({item['experiment_id'] for item in entry['evidence']
                                       if item.get('experiment_id')}),
                'citations': [item.get('citation') for item in entry['evidence'] if item.get('citation')],
                'derived_from': list(entry['derived_from']),
                'superseded_by': entry.get('superseded_by'),
                'retired': bool(entry.get('retired')),
                'revision': entry['revision'],
            })
        live = [e for e in base['entries'] if not e.get('retired')]
        return {'entries': rows[offset:offset + limit], 'total': len(rows),
                'returned': len(rows[offset:offset + limit]),
                'topics': {name: sum(1 for e in live if e['_topic'] == name) for name in base['topics']},
                'kinds': {k: sum(1 for e in live if e['kind'] == k) for k in KINDS},
                'basis': {b: sum(1 for e in live if basis_of(e) == b) for b in BASIS}}

    # ---------- check ----------
    def validate(self):
        """Re-read every citation, in every topic. A base that is not re-read quietly rots."""
        errors, warnings = [], []
        if not self.topic_names():
            return {'valid': True, 'errors': [], 'warnings': ['knowledge base is empty; nothing to check'],
                    'stats': {}}
        try:
            base = self.load()
        except NotebookError as error:
            return {'valid': False, 'errors': [str(error)], 'warnings': [], 'stats': {}}

        entries = {e['id']: e for e in base['entries']}
        if len(entries) != len(base['entries']):
            errors.append('duplicate knowledge ids across topics; an id must be unique in the whole base')
        live = {kid: e for kid, e in entries.items() if not e.get('retired')}
        cache = {}

        for entry in base['entries']:
            label = f"{entry['id']} ({KIND_LABELS[entry['kind']]} · {entry['_topic']})"
            # A retired entry is history: its citations may legitimately have moved on, so
            # its problems are advisory rather than fatal.
            target = warnings if entry.get('retired') else errors
            for problem in self._check_evidence(entry['evidence'], cache, strict=False):
                target.append(f'{label}: {problem}')
            for parent in entry['derived_from']:
                if parent not in entries:
                    errors.append(f'{label}: derived_from names missing knowledge {parent}')
                elif entries[parent].get('retired'):
                    warnings.append(f'{label}: derives from retired knowledge {parent}')
            if entry.get('supersedes') and entry['supersedes'] not in entries:
                errors.append(f'{label}: supersedes names missing knowledge {entry["supersedes"]}')
            if entry.get('superseded_by'):
                if entry['superseded_by'] not in entries:
                    errors.append(f'{label}: superseded_by names missing knowledge {entry["superseded_by"]}')
                elif entries[entry['superseded_by']].get('supersedes') != entry['id']:
                    errors.append(f'{label}: superseded_by points at {entry["superseded_by"]} which does not '
                                  'name it back')
            if entry.get('retired'):
                continue
            hard, soft = self._kind_problems(entry, cache)
            for problem in hard:
                errors.append(f'{label}: {problem}')
            for problem in soft:
                warnings.append(f'{label}: {problem}')
            if entry.get('superseded_by'):
                warnings.append(f'{label}: superseded by {entry["superseded_by"]} but still live; '
                                'retire it if the replacement is authoritative')

        # A derivation that leads back to itself cannot be followed.
        for start in entries:
            seen, stack = set(), [start]
            while stack:
                current = stack.pop()
                if current in seen:
                    errors.append(f'{start}: derived_from contains a cycle')
                    break
                seen.add(current)
                stack.extend(entries.get(current, {}).get('derived_from') or [])

        # Derived files must match the entries they claim to describe.
        try:
            catalog_path = self.root / 'catalog.json'
            if not catalog_path.is_file():
                warnings.append('catalog.json is missing; call export to rebuild it')
            else:
                catalog = json.loads(catalog_path.read_text(encoding='utf-8'))
                on_disk = sorted(catalog.get('topics') and [t.get('topic') for t in catalog['topics']] or [])
                if on_disk != self.topic_names():
                    warnings.append('catalog.json lists different topics than the folders on disk; '
                                    'call export to rebuild it')
            brief = self.root / 'brief.md'
            if not brief.is_file():
                warnings.append('brief.md is missing; call export to regenerate it')
            elif brief.read_text(encoding='utf-8') != self.render(base):
                warnings.append('brief.md differs from the entries (hand-edited?); call export to regenerate '
                                'and keep human notes in notes.md')
        except (json.JSONDecodeError, KeyError, TypeError):
            warnings.append('catalog.json could not be read; call export to rebuild it')

        stats = {
            'total': len(base['entries']), 'live': len(live),
            'retired': len(base['entries']) - len(live),
            'topics': {name: sum(1 for e in live.values() if e['_topic'] == name) for name in base['topics']},
            'kinds': {k: sum(1 for e in live.values() if e['kind'] == k) for k in KINDS},
            'confidence': {c: sum(1 for e in live.values() if e['confidence'] == c) for c in CONFIDENCE},
            'basis': {b: sum(1 for e in live.values() if basis_of(e) == b) for b in BASIS},
            'experiments_cited': len({item['experiment_id'] for e in live.values()
                                      for item in e['evidence'] if item.get('experiment_id')}),
        }
        return {'valid': not errors, 'errors': errors, 'warnings': warnings, 'stats': stats}

    # ---------- human view ----------
    def render(self, base):
        live = [e for e in base['entries'] if not e.get('retired')]
        retired = [e for e in base['entries'] if e.get('retired')]
        counts = {k: sum(1 for e in live if e['kind'] == k) for k in KINDS}
        priors = [e for e in live if basis_of(e) == 'external']
        lines = ['# 知识库', '',
                 f"***{base['updated_at'][:19].replace('T', ' ')}***", '',
                 (f"可用条目 {len(live)}（事实 {counts['fact']} / 结论 {counts['conclusion']} / "
                  f"可行边界 {counts['boundary']} / 推导 {counts['derivation']}）"
                  + (f"，已搁置 {len(retired)}" if retired else '')
                  + (f"，其中外部依据 {len(priors)} 条" if priors else '')), '']
        if not live:
            lines += ['尚无条目。实验记录产生的事实与结论由 `research_knowledge_upsert` 收入此处，'
                      '按主题分区存放。', '']
            # Deliberately no early return: a base whose every entry has been set aside still
            # has to show the 已搁置 table, because that is exactly when a reader needs to
            # know the work exists but is not being relied on.

        for topic in sorted({e['_topic'] for e in live}):
            shelf = [e for e in live if e['_topic'] == topic]
            lines += [f'## 主题：{topic}', '',
                      (f"本主题 {len(shelf)} 条"), '']
            grounded = [e for e in shelf if basis_of(e) != 'external']
            external = [e for e in shelf if basis_of(e) == 'external']
            for heading, subset, lead in (
                (None, grounded, None),
                ('### 先验假设（外部依据，本工作区未验证）', external,
                 '下列条目的依据全部来自文献或先验知识，**本工作区没有任何记录支撑它们**。'
                 '引用时必须写明这是外部依据，不得当作本工作区的结论。'),
            ):
                if not subset:
                    continue
                if heading:
                    lines += [heading, '', lead, '']
                for kind in KINDS:
                    group = [e for e in subset if e['kind'] == kind]
                    if not group:
                        continue
                    # A prior is already nested under its own heading, so it gets one level less.
                    lines += [('#### ' if heading else '### ') + KIND_LABELS[kind], '']
                    for number, entry in enumerate(group, 1):
                        lines.append(f"#### {number}. {entry['statement']}" if heading
                                     else f"### {number}. {entry['statement']}")
                        lines.append('')
                        conditions = entry['conditions']
                        if conditions.get('applies_to'):
                            lines.append(f"- 适用于：{conditions['applies_to']}")
                        if conditions.get('holds_when'):
                            lines.append('- 成立条件：' + '；'.join(conditions['holds_when']))
                        if conditions.get('fails_when'):
                            # The limit is the point of a boundary, so it is never omitted.
                            lines.append('- 失效条件：' + '；'.join(conditions['fails_when']))
                        if entry.get('detail'):
                            lines += ['', entry['detail'], '']
                        if entry['steps']:
                            lines += ['', '**推导链**', '']
                            for step_number, step in enumerate(entry['steps'], 1):
                                basis = '、'.join(f'`{b}`' for b in step['from'])
                                lines.append(f'{step_number}. {step["claim"]}　← {basis}')
                            lines.append('')
                        if entry['evidence']:
                            cited = []
                            for item in entry['evidence']:
                                if item['source'] == 'external':
                                    cited.append(f"外部：{item.get('citation', '')}")
                                    continue
                                pointer = item['experiment_id']
                                if item.get('checkpoint_id'):
                                    pointer += '/' + item['checkpoint_id']
                                if item.get('artifact_id'):
                                    pointer += '/' + item['artifact_id']
                                cited.append(f'`{pointer}`')
                            lines.append('- 证据：' + '、'.join(cited))
                        if entry['derived_from']:
                            names = []
                            for parent in entry['derived_from']:
                                source = next((e for e in base['entries'] if e['id'] == parent), None)
                                where = f"［{(source or {}).get('_topic', '')}］" if source else ''
                                names.append(f'{(source or {}).get("statement", parent)[:60]}'
                                             f'（`{parent}`{where}）')
                            lines.append('- 依赖：' + '；'.join(names))
                        if entry['confidence'] == 'refuted' and entry.get('refuted_by'):
                            lines.append(f"- ~~已否定~~：{entry['refuted_by']}")
                        lines.append(f"- 置信度：{entry['confidence']} · 依据：{BASIS_LABELS[basis_of(entry)]}")
                        if entry['tags']:
                            lines.append('- 标签：' + '、'.join(entry['tags']))
                        lines += ['', f"`{entry['id']}` · revision {entry['revision']}", '']

        if retired:
            lines += ['## 已搁置', '',
                      '下列条目不再进入结论，但保留在索引与 `revisions/` 中。', '',
                      '| ID | 主题 | 类型 | 陈述 |', '| --- | --- | --- | --- |']
            for entry in retired:
                statement = entry['statement'].replace('|', '\\|').replace('\n', ' ')[:120]
                lines.append(f"| `{entry['id']}` | {entry['_topic']} | {KIND_LABELS[entry['kind']]} | {statement} |")
            lines.append('')
        return '\n'.join(lines)

    def export(self):
        """Rebuild `catalog.json` and `brief.md` from the topic indexes."""
        with self._lock():
            catalog = self._rebuild()
            base = self.load()
            live = [e for e in base['entries'] if not e.get('retired')]
            return {'brief_path': str((self.root / 'brief.md').relative_to(self.workspace)),
                    'catalog_path': str((self.root / 'catalog.json').relative_to(self.workspace)),
                    'topics': [t['topic'] for t in catalog['topics']],
                    'entries': len(live),
                    'external_only': sum(1 for e in live if basis_of(e) == 'external'),
                    'characters': len(self.render(base)),
                    'space': {'knowledge': human_bytes(usage(self.root)['bytes'])}}

    def topics(self):
        """The shelves: topic, live entry count, revision. Read-only."""
        return {'topics': self.catalog()['topics'], 'default': DEFAULT_TOPIC}
