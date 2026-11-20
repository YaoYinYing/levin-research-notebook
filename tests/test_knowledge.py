"""Knowledge-layer regression tests: typing rules, provenance and rot detection.

Run: <venv>/bin/python -m unittest discover -s tests -p test_knowledge.py
All workspaces are retained for inspection, like the notebook suite.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'mcp' / 'runner'))
from knowledge import Knowledge, basis_of  # noqa: E402
from notebook import Notebook, NotebookError  # noqa: E402

SCRATCH = Path(os.environ.get("NOTEBOOK_TEST_SCRATCH")
               or Path(tempfile.gettempdir()) / "levin-research-notebook-tests" / "knowledge-tests")


class KnowledgeTests(unittest.TestCase):
    def setUp(self):
        SCRATCH.mkdir(parents=True, exist_ok=True)
        self.workspace = Path(tempfile.mkdtemp(prefix=self._testMethodName + '-', dir=SCRATCH))
        self.n = Notebook(self.workspace)
        self.k = Knowledge(self.workspace)
        self.eid = self.n.init('task', 'agent-a', 'Knowledge task',
                               'Produce records that knowledge can cite')['experiment_id']

    # ---------- helpers ----------
    def observation(self, text_value='界面接触数与盖子开合无单调联动，rho=-0.34', title='界面接触'):
        return self.n.checkpoint(self.eid, 'agent-a', 'observation', text_value, title=title)['checkpoint_id']

    def fact(self, **extra):
        payload = {'agent_id': 'agent-a', 'topic': 'structural', 'kind': 'fact',
                   'statement': '+FoTO1 系综内界面接触数与盖子间隙无单调联动（rho=-0.34，n=300）',
                   'evidence': [{'source': 'record', 'experiment_id': self.eid}],
                   'confidence': 'provisional'}
        payload.update(extra)
        return self.k.upsert(payload)

    def prior(self, **extra):
        payload = {'agent_id': 'agent-a', 'topic': 'literature', 'kind': 'conclusion',
                   'statement': '共折叠预测的链间落位不足以支撑界面几何判断',
                   'conditions': {'applies_to': 'AF3 类模型输出'},
                   'evidence': [{'source': 'external', 'citation': 'Doe 2024, DOI 10.1000/xyz'}],
                   'confidence': 'provisional'}
        payload.update(extra)
        return self.k.upsert(payload)

    # ---------- storage layout ----------
    def test_topics_are_separate_shelves_under_levin_knowledge(self):
        fact = self.fact()
        prior = self.prior()
        root = self.workspace / 'levin_knowledge'
        self.assertTrue((root / 'topics' / 'structural' / 'index.json').is_file())
        self.assertTrue((root / 'topics' / 'literature' / 'index.json').is_file())
        self.assertTrue((root / 'catalog.json').is_file())
        self.assertTrue((root / 'brief.md').is_file())
        self.assertEqual(fact['topic'], 'structural')
        self.assertEqual(prior['topic'], 'literature')
        # A topic index holds only its own entries: that is what makes it a shelf.
        import json
        shelf = json.loads((root / 'topics' / 'structural' / 'index.json').read_text(encoding='utf-8'))
        self.assertEqual([e['id'] for e in shelf['entries']], [fact['knowledge_id']])
        catalog = json.loads((root / 'catalog.json').read_text(encoding='utf-8'))
        self.assertEqual([t['topic'] for t in catalog['topics']], ['literature', 'structural'])

    def test_a_bad_topic_name_is_refused(self):
        with self.assertRaises(Exception) as caught:
            self.fact(topic='Bad Topic/Name')
        self.assertIn('topic must match', str(caught.exception))

    # ---------- typing rules ----------
    def test_a_boundary_must_state_where_it_fails(self):
        # Without this rule `boundary` is just a fact wearing a cautionary label.
        with self.assertRaises(Exception) as caught:
            self.k.upsert({'agent_id': 'agent-a', 'topic': 'structural', 'kind': 'boundary',
                           'statement': '该否证仅在单一采样协议下成立',
                           'evidence': [{'source': 'record', 'experiment_id': self.eid}]})
        self.assertIn('fails_when', str(caught.exception))
        made = self.k.upsert({'agent_id': 'agent-a', 'topic': 'structural', 'kind': 'boundary',
                              'statement': '该否证仅在 lag 10 单协议下成立，高 lag 对照不可用',
                              'conditions': {'applies_to': 'BioEmu2 系综比较',
                                             'fails_when': ['lag 1000 对照通过率 88/300 与 3/300']},
                              'evidence': [{'source': 'record', 'experiment_id': self.eid}],
                              'confidence': 'provisional'})
        brief = (self.workspace / 'levin_knowledge' / 'brief.md').read_text(encoding='utf-8')
        self.assertIn('失效条件', brief)
        self.assertIn('88/300', brief)
        self.assertEqual(made['kind'], 'boundary')

    def test_a_fact_cannot_rest_on_literature(self):
        with self.assertRaises(Exception) as caught:
            self.k.upsert({'agent_id': 'agent-a', 'kind': 'fact',
                           'statement': '文献报道该界面在体外条件下稳定',
                           'evidence': [{'source': 'external', 'citation': 'Smith 2023, DOI 10.1000/abc'}]})
        self.assertIn('measured in this workspace', str(caught.exception))

    def test_a_derivation_needs_more_than_one_step(self):
        with self.assertRaises(Exception) as caught:
            self.k.upsert({'agent_id': 'agent-a', 'kind': 'derivation',
                           'statement': '综合两条独立证据得出不构成夹持机制的结论',
                           'evidence': [{'source': 'record', 'experiment_id': self.eid}],
                           'steps': [{'claim': '只有一步', 'from': ['规则']}]})
        self.assertIn('two ordered steps', str(caught.exception))

    def test_an_unsupported_conclusion_is_refused(self):
        with self.assertRaises(Exception) as caught:
            self.k.upsert({'agent_id': 'agent-a', 'kind': 'conclusion',
                           'statement': '这是一个没有任何依据的判断句子'})
        self.assertIn('nothing supports this claim', str(caught.exception))

    def test_a_refutation_must_say_what_refuted_it(self):
        with self.assertRaises(Exception) as caught:
            self.prior(confidence='refuted')
        self.assertIn('refuted_by', str(caught.exception))
        made = self.prior(confidence='refuted', refuted_by='2026 preprint 的环氧化物结论与该模型冲突')
        self.assertEqual(made['confidence'], 'refuted')
        brief = (self.workspace / 'levin_knowledge' / 'brief.md').read_text(encoding='utf-8')
        self.assertIn('已否定', brief)

    def test_external_evidence_may_not_name_an_experiment(self):
        with self.assertRaises(Exception) as caught:
            self.k.upsert({'agent_id': 'agent-a', 'kind': 'conclusion',
                           'statement': '外部依据却声称来自本工作区的实验记录',
                           'evidence': [{'source': 'external', 'citation': 'Doe 2024 DOI 10.1/x',
                                         'experiment_id': self.eid}]})
        self.assertIn('must not name an experiment', str(caught.exception))

    # ---------- lessons ----------
    def failure(self, text_value='BioEmu2 无 FoTO1 对照连续三次失败，最终删掉 OXT 端基才跑通', title='对照失败'):
        return self.n.checkpoint(self.eid, 'agent-a', 'failure', text_value, title=title)['checkpoint_id']

    def lesson(self, **extra):
        payload = {'agent_id': 'agent-a', 'topic': 'protocol', 'kind': 'lesson',
                   'statement': 'BioEmu2 propagate 前必须删掉 OXT 端基，否则 system YAML 解析失败',
                   'lesson': {'trigger': '准备 BioEmu2 system YAML 时',
                              'symptom': 'propagate 连续三次失败，报错指向多余端基',
                              'remedy': '由 CIF 重建成 3-entity YAML 并删掉 OXT 后再提交'},
                   'conditions': {'applies_to': 'BioEmu2 propagate 输入准备'},
                   'evidence': [{'source': 'record', 'experiment_id': self.eid,
                                 'checkpoint_id': self.failure()}],
                   'confidence': 'provisional'}
        payload.update(extra)
        payload['lesson'] = extra.get('lesson', payload['lesson'])
        return self.k.upsert(payload)

    def test_a_lesson_needs_a_remedy(self):
        # A symptom with no remedy is a complaint; it gives the next reader nothing to do.
        with self.assertRaises(Exception) as caught:
            self.lesson(lesson={'trigger': '准备 YAML 时', 'symptom': '三次失败'})
        self.assertIn('remedy', str(caught.exception))

    def test_a_lesson_needs_a_scope(self):
        with self.assertRaises(Exception) as caught:
            self.lesson(conditions={})
        self.assertIn('applies_to', str(caught.exception))

    def test_a_lesson_must_have_been_paid_for(self):
        with self.assertRaises(Exception) as caught:
            self.k.upsert({'agent_id': 'agent-a', 'kind': 'lesson',
                           'statement': '提交长任务前应当先做小样本冒烟测试',
                           'lesson': {'remedy': '先跑 3 帧确认能过再提交 300 帧'},
                           'conditions': {'applies_to': '任何长任务'},
                           'evidence': [{'source': 'external', 'citation': 'Doe 2024, DOI 10.1/x'}]})
        self.assertIn('paid for', str(caught.exception))

    def test_a_lesson_renders_its_remedy_and_leaves_the_unclear_part_visible(self):
        made = self.lesson(lesson={'trigger': '准备 BioEmu2 system YAML 时',
                                   'symptom': 'propagate 连续三次失败',
                                   'remedy': '由 CIF 重建成 3-entity YAML 并删掉 OXT',
                                   'still_unclear': 'OXT 之外是否还有其它端基会触发同一错误'})
        self.assertEqual(made['kind'], 'lesson')
        brief = (self.workspace / 'levin_knowledge' / 'brief.md').read_text(encoding='utf-8')
        for expected in ('经验教训', '触发情境', '现象', '改法', '仍未解决'):
            self.assertIn(expected, brief)
        self.assertIn('3-entity YAML', brief)

    def test_a_lesson_resting_on_a_non_failure_is_flagged(self):
        observation = self.observation('观察：清理端基后 propagate 一次通过')
        self.lesson(evidence=[{'source': 'record', 'experiment_id': self.eid,
                               'checkpoint_id': observation}])
        warnings = self.k.validate()['warnings']
        self.assertTrue(any('cost voucher' in w for w in warnings), warnings)

    def test_a_lesson_on_a_failure_is_not_flagged(self):
        self.lesson()
        warnings = self.k.validate()['warnings']
        self.assertFalse(any('cost voucher' in w for w in warnings), warnings)

    # ---------- promotion review ----------
    def test_candidates_lists_unpromoted_failures_only(self):
        promoted = self.failure('第一个失败：propagate 连续三次失败后删 OXT 才通过', title='已提升')
        unpromoted = self.failure('第二个失败：上传 20 个快照撞 Cloudflare 524', title='未提升')
        self.n.checkpoint(self.eid, 'agent-a', 'observation', '一条观察，不是失败，不该出现在候选里')
        self.lesson(evidence=[{'source': 'record', 'experiment_id': self.eid, 'checkpoint_id': promoted}])
        listing = self.k.candidates()
        ids = [row['checkpoint_id'] for row in listing['candidates']]
        self.assertIn(unpromoted, ids)
        self.assertNotIn(promoted, ids)
        self.assertEqual(listing['already_promoted'], 1)
        with_promoted = self.k.candidates(include_promoted=True)
        rows = {row['checkpoint_id']: row for row in with_promoted['candidates']}
        self.assertTrue(rows[promoted]['promoted'])
        self.assertEqual(rows[promoted]['lesson_id'],
                         next(r['lesson_id'] for r in with_promoted['candidates']
                              if r['checkpoint_id'] == promoted))

    def test_candidates_skip_excluded_failures(self):
        kept = self.failure('留在记录里的失败：对照三次不通过', title='保留')
        dropped = self.failure('被搁置的失败：调试工具本身造成的报错', title='搁置')
        self.n.exclude(self.eid, 'agent-a', [dropped], 'recorder debugging, not the experiment')
        ids = [row['checkpoint_id'] for row in self.k.candidates()['candidates']]
        self.assertIn(kept, ids)
        self.assertNotIn(dropped, ids)

    # ---------- provenance ----------
    def test_dangling_and_corrected_evidence_are_refused_at_write_time(self):
        with self.assertRaises(Exception) as caught:
            self.k.upsert({'agent_id': 'agent-a', 'kind': 'fact',
                           'statement': '引用了不存在的实验记录的事实陈述',
                           'evidence': [{'source': 'record', 'experiment_id': 'exp-' + '0' * 32}]})
        self.assertIn('no such experiment', str(caught.exception))

        first = self.observation('初版观察：界面接触数偏高')
        self.n.checkpoint(self.eid, 'agent-a', 'observation', '更正：接触数在误差内无差异',
                          title='更正观察', supersedes=first)
        with self.assertRaises(Exception) as caught:
            self.k.upsert({'agent_id': 'agent-a', 'kind': 'fact',
                           'statement': '建立已被更正的观察之上的事实',
                           'evidence': [{'source': 'record', 'experiment_id': self.eid,
                                         'checkpoint_id': first}]})
        self.assertIn('corrected by', str(caught.exception))

    def test_validate_finds_support_that_was_corrected_after_writing(self):
        # The failure this whole module exists to catch: the entry was sound when written.
        live = self.observation('界面接触数与开合无单调联动')
        made = self.fact(evidence=[{'source': 'record', 'experiment_id': self.eid,
                                    'checkpoint_id': live}])
        self.assertEqual(self.k.validate()['valid'], True)
        self.n.checkpoint(self.eid, 'agent-a', 'observation', '更正：该相关系数并不显著',
                          title='更正接触数', supersedes=live)
        verdict = self.k.validate()
        self.assertFalse(verdict['valid'])
        self.assertTrue(any('corrected by' in e for e in verdict['errors']),
                        verdict['errors'])
        self.assertTrue(any(made['knowledge_id'] in e for e in verdict['errors']))

    # ---------- cross-topic structure ----------
    def test_a_derivation_may_rest_on_another_topic(self):
        fact = self.fact()
        prior = self.prior()
        made = self.k.upsert({'agent_id': 'agent-a', 'topic': 'structural', 'kind': 'derivation',
                              'statement': '综合本地区综证据与外部先验得出不构成闸门的判断',
                              'derived_from': [fact['knowledge_id'], prior['knowledge_id']],
                              'steps': [{'claim': '接触数与开合无联动', 'from': [fact['knowledge_id']]},
                                        {'claim': '无联动即不构成夹持', 'from': ['机制定义']}],
                              'confidence': 'provisional'})
        self.assertEqual(made['basis'], 'derived')
        brief = (self.workspace / 'levin_knowledge' / 'brief.md').read_text(encoding='utf-8')
        # The cross-topic dependency is named in the brief with its shelf.
        self.assertIn('［literature］', brief)

    def test_updating_by_id_keeps_the_entry_on_its_original_shelf(self):
        made = self.fact()
        updated = self.k.upsert({'agent_id': 'agent-a', 'id': made['knowledge_id'],
                                 'statement': '+FoTO1 系综内界面接触数与盖子间隙无单调联动（rho=-0.31，n=300）',
                                 'topic': 'literature'})
        self.assertEqual(updated['topic'], 'structural')
        self.assertEqual(updated['revision'], 2)
        hit = self.k.query(topic='literature')
        self.assertEqual(hit['total'], 0)

    def test_id_is_global_across_topics(self):
        made = self.fact()
        with self.assertRaises(Exception) as caught:
            self.k.upsert({'agent_id': 'agent-a', 'id': 'kn-' + '1' * 32,
                           'statement': '不存在的知识条目更新请求语句'})
        self.assertIn('no knowledge entry', str(caught.exception))

    # ---------- setting aside ----------
    def test_setting_aside_needs_a_reason_and_hides_without_deleting(self):
        made = self.fact()
        with self.assertRaises(Exception) as caught:
            self.k.upsert({'agent_id': 'agent-a', 'id': made['knowledge_id'], 'retired': True})
        self.assertIn('retire_reason', str(caught.exception))
        self.k.upsert({'agent_id': 'agent-a', 'id': made['knowledge_id'], 'retired': True,
                       'retire_reason': '该结论已被更宽的协议覆盖，暂不作为依据'})
        brief = (self.workspace / 'levin_knowledge' / 'brief.md').read_text(encoding='utf-8')
        self.assertIn('已搁置', brief)
        self.assertEqual(self.k.query()['total'], 0)
        # Not deleted: the index still holds it, and the brief names it in the retired table.
        self.assertEqual(self.k.query(include_retired=True)['total'], 1)
        self.assertIn(made['knowledge_id'], brief)

    # ---------- read paths ----------
    def test_query_separates_priors_from_results(self):
        self.fact()
        self.prior()
        self.assertEqual(self.k.query(basis='external')['total'], 1)
        self.assertEqual(self.k.query(basis='workspace')['total'], 1)
        everything = self.k.query('界面')
        self.assertEqual(everything['basis']['external'], 1)

    def test_a_brief_hand_edit_is_reported_and_repairable(self):
        self.fact()
        brief = self.workspace / 'levin_knowledge' / 'brief.md'
        brief.write_text('# 手改过的知识库\n', encoding='utf-8')
        self.assertTrue(any('hand-edited' in w for w in self.k.validate()['warnings']))
        out = self.k.export()
        self.assertEqual(out['entries'], 1)
        self.assertIn('主题：structural', brief.read_text(encoding='utf-8'))

    def test_repeated_create_with_a_request_id_does_not_duplicate(self):
        payload = {'agent_id': 'agent-a', 'topic': 'structural', 'kind': 'fact',
                   'statement': '幂等创建测试用的足够长陈述',
                   'evidence': [{'source': 'record', 'experiment_id': self.eid}],
                   'confidence': 'provisional'}
        first = self.k.upsert(payload, request_id='k1')
        second = self.k.upsert(payload, request_id='k1')
        self.assertEqual(first['knowledge_id'], second['knowledge_id'])
        self.assertTrue(second.get('idempotent'))
        self.assertEqual(self.k.query()['total'], 1)


class SpecVocabularyTests(unittest.TestCase):
    """The kind vocabulary is declared twice — once in the code, once per tool schema.

    A kind the library accepts but a tool schema rejects is invisible in unit tests and fatal
    through the MCP boundary, so the two declarations are compared here rather than trusted.
    """

    def test_every_kind_the_library_accepts_is_accepted_by_every_tool_that_filters_on_kind(self):
        import re
        from knowledge import KINDS
        spec = (ROOT / 'mcp' / 'runner' / 'plugin_spec.py').read_text(encoding='utf-8')
        enums = re.findall(r"'kind':\{'enum':\[((?:'[a-z]+',?)+)\]", spec)
        knowledge_enums = [[part.strip().strip("'") for part in enum.split(',') if part.strip()]
                           for enum in enums]
        knowledge_enums = [enum for enum in knowledge_enums if 'fact' in enum]
        self.assertEqual(len(knowledge_enums), 2, 'expected one entry kind enum and one query filter')
        for enum in knowledge_enums:
            with self.subTest(enum=enum):
                self.assertEqual(set(enum), set(KINDS),
                                 'plugin_spec.py declares a different kind vocabulary than knowledge.py')


if __name__ == '__main__':
    unittest.main(verbosity=2)
