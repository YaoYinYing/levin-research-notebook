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


if __name__ == '__main__':
    unittest.main(verbosity=2)
