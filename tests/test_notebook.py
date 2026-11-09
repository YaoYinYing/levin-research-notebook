"""Domain regression tests; all workspaces are retained for inspection.
Run: <venv>/bin/python -m unittest discover -s tests -p test_notebook.py -v
"""
from __future__ import annotations

import os
import copy
import hashlib
import json
import multiprocessing
import socket
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'mcp' / 'runner'))
from notebook import Notebook, NotebookError
import notebook

# Artifact root is overridable so the suite runs on any machine; the default is a
# process-local temp directory, never a hard-coded home path.
SCRATCH = Path(os.environ.get("NOTEBOOK_TEST_SCRATCH")
               or Path(tempfile.gettempdir()) / "levin-research-notebook-tests" / "core-tests")

def concurrent_writer(workspace, agent, queue):
    try:
        n = Notebook(workspace)
        r = n.init('shared', agent, 'Shared task', 'Exercise process serialization')
        for index in range(4):
            n.checkpoint(r['experiment_id'], agent, 'note', f'{agent}:{index}', request_id=f'{agent}-{index}')
        queue.put({'ok': True, 'experiment_id': r['experiment_id']})
    except Exception as exc:
        queue.put({'ok': False, 'error': repr(exc)})

class NotebookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        SCRATCH.mkdir(parents=True, exist_ok=True)
        cls.session = Path(tempfile.mkdtemp(prefix='suite-', dir=SCRATCH))
        print(f'\nRetained test workspaces: {cls.session}', flush=True)

    def setUp(self):
        self.workspace = Path(tempfile.mkdtemp(prefix=self._testMethodName+'-', dir=self.session))
        self.n = Notebook(self.workspace)
        self.initial = self.n.init('task', 'agent-a', 'Synthetic task', 'Test evidence accounting')
        self.eid = self.initial['experiment_id']
        self.directory = Path(self.initial['manifest_path']).parent

    def manifest(self):
        return json.loads(Path(self.initial['manifest_path']).read_text())

    def file(self, name='input.txt', content='immutable original\n'):
        p = self.directory / 'data' / name
        p.write_text(content)
        return p

    def artifact(self, role='input', name='input.txt', **extra):
        p = self.file(name)
        return self.n.register_artifact(self.eid, dict(role=role, location=str(p), description='Test evidence', **extra))

    def run_record(self, **extra):
        return dict(backend='local', execution_status='success', command='python synthetic.py', parameters={'seed':0}, environment={'python':sys.version}, **extra)

    def figure_graph(self, status='success'):
        data = self.artifact('input')['artifact_id']
        script = self.artifact('script', 'analysis.py')['artifact_id']
        run = self.run_record(input_ids=[data,script])
        run['execution_status'] = status
        if status == 'failed': run['failure'] = 'Intentional test failure'
        rid = self.n.register_run(self.eid,run)['run_id']
        fig = self.artifact('figure', 'figure.svg', input_ids=[data],script_id=script,run_id=rid)['artifact_id']
        return data,script,rid,fig

    def test_init_is_idempotent_and_reopens(self):
        m = self.manifest()
        reopened = Notebook(self.workspace).init('task','agent-a','Synthetic task','Test evidence accounting')
        self.assertTrue(reopened['resumed'])
        self.assertEqual(reopened['experiment_id'],self.eid)
        self.assertEqual(m,self.manifest())
        self.assertTrue(Path(reopened['scratch_dir']).is_relative_to(self.workspace/'levin_scratch'))
        self.assertTrue((self.n.root/'.gitignore').is_file())

    def test_resume_adds_agent_once_and_preserves_notes(self):
        notes=self.directory/'notes.md'; notes.write_text('Human notes stay here\n')
        for _ in range(2): self.n.init('task','agent-b','Synthetic task','Test evidence accounting')
        m=self.manifest()
        self.assertEqual(m['agents'],['agent-a','agent-b'])
        self.assertEqual(m['revision'],2)
        self.assertEqual(notes.read_text(),'Human notes stay here\n')

    def test_resume_identity_conflicts(self):
        before=self.manifest()
        with self.assertRaises(NotebookError): self.n.init('task','agent-a','Different title','Test evidence accounting')
        with self.assertRaises(NotebookError): self.n.init('task','agent-a','Synthetic task','Different objective')
        self.assertEqual(before,self.manifest())

    def test_checkpoint_request_id_deduplicates_and_conflicts(self):
        first=self.n.checkpoint(self.eid,'agent-a','note','First note',request_id='request-1')
        replay=self.n.checkpoint(self.eid,'agent-a','note','First note',request_id='request-1')
        self.assertEqual(first['checkpoint_id'],replay['checkpoint_id'])
        self.assertEqual(first['revision'],replay['revision'])
        self.assertTrue(replay['idempotent'])
        with self.assertRaisesRegex(NotebookError,'different content'):
            self.n.checkpoint(self.eid,'agent-a','note','Changed note',request_id='request-1')
        self.assertEqual(len(self.manifest()['checkpoints']),1)

    def test_request_ids_cannot_cross_operations(self):
        self.n.checkpoint(self.eid,'agent-a','note','Note',request_id='shared-id')
        with self.assertRaisesRegex(NotebookError,'different content'):
            self.n.register_artifact(self.eid,{'role':'input','location':str(self.file())},request_id='shared-id')

    def test_artifact_and_run_request_replay(self):
        art={'role':'input','location':str(self.file())}
        a=self.n.register_artifact(self.eid,art,request_id='artifact-1')
        b=self.n.register_artifact(self.eid,art,request_id='artifact-1')
        self.assertEqual(a['artifact_id'],b['artifact_id'])
        run=self.run_record(input_ids=[a['artifact_id']])
        r=self.n.register_run(self.eid,run,request_id='run-1')
        self.assertEqual(r['run_id'],self.n.register_run(self.eid,run,request_id='run-1')['run_id'])

    def test_concurrent_processes_agents_and_checkpoints(self):
        ctx=multiprocessing.get_context('spawn'); queue=ctx.Queue()
        workers=[ctx.Process(target=concurrent_writer,args=(str(self.workspace),f'worker-{i}',queue)) for i in range(4)]
        for p in workers: p.start()
        for p in workers:
            p.join(45)
            if p.is_alive(): p.terminate(); p.join(); self.fail('Concurrent worker exceeded 45 second test deadline')
            self.assertEqual(p.exitcode,0)
        results=[queue.get(timeout=5) for _ in workers]
        self.assertTrue(all(r['ok'] for r in results),results)
        self.assertEqual(len({r['experiment_id'] for r in results}),1)
        eid=results[0]['experiment_id']; m=self.n._load(eid)
        self.assertEqual(len(m['checkpoints']),16)
        self.assertEqual(len(m['agents']),4)
        self.assertEqual(m['revision'],20)
        self.assertTrue(self.n.validate(eid)['valid'])

    def test_failed_run_requires_details_and_preserves_failure(self):
        run=self.run_record(); run['execution_status']='failed'
        with self.assertRaisesRegex(NotebookError,'failure information'): self.n.register_run(self.eid,run)
        run['failure']='Intentional synthetic exception'
        rid=self.n.register_run(self.eid,run)['run_id']
        self.n.checkpoint(self.eid,'agent-a','failure','Calculation failed as recorded',[rid],execution_status='failed')
        self.assertEqual(self.manifest()['execution_status'],'failed')
        self.assertIn('Intentional synthetic exception',(self.directory/'record.md').read_text())

    def test_external_reference_is_unverified_without_contact(self):
        result=self.n.register_artifact(self.eid,{'role':'raw','location':'s3://example-bucket/data.csv','sha256':'a'*64})
        self.assertEqual(result['availability'],'external_unverified')
        self.assertEqual(result['checksum_origin'],'supplied_unverified')
        v=self.n.validate(self.eid)
        self.assertTrue(v['valid']); self.assertTrue(any('not contacted or verified' in w for w in v['warnings']))

    def test_external_credentials_and_unsafe_schemes_rejected(self):
        for location in ['https://user:password@example.org/file','https://example.org/file?token=abc','https://example.org/file#token','file:///etc/passwd','ftp://example.org/a']:
            with self.subTest(location=location),self.assertRaises(NotebookError): self.n.location(location)

    def test_missing_local_reference_is_recorded_then_invalid(self):
        a=self.n.register_artifact(self.eid,{'role':'raw','location':'missing.csv'})
        self.assertEqual(a['availability'],'missing')
        v=self.n.validate(self.eid)
        self.assertFalse(v['valid']); self.assertIn('missing local file',' '.join(v['errors']))

    def test_raw_registration_never_mutates_original(self):
        p=self.file(); original=p.read_bytes(); before=p.stat().st_mtime_ns
        a=self.n.register_artifact(self.eid,{'role':'raw','location':str(p)})
        self.assertEqual(a['sha256'],hashlib.sha256(original).hexdigest())
        self.assertEqual(p.read_bytes(),original); self.assertEqual(p.stat().st_mtime_ns,before)

    def test_raw_change_rejected_and_manifest_retained(self):
        p=self.file(); self.n.register_artifact(self.eid,{'role':'raw','location':str(p)})
        before=self.manifest(); p.write_text('Changed externally\n')
        with self.assertRaisesRegex(NotebookError,'Raw evidence changed'):
            self.n.register_artifact(self.eid,{'role':'raw','location':str(p)})
        self.assertEqual(before,self.manifest())
        self.assertFalse(self.n.validate(self.eid)['valid'])

    def test_raw_and_input_may_not_live_in_scratch(self):
        p=Path(self.initial['scratch_dir'])/'raw.txt'; p.write_text('test')
        for role in ('raw','input'):
            with self.subTest(role=role),self.assertRaisesRegex(NotebookError,'scratch'):
                self.n.register_artifact(self.eid,{'role':role,'location':str(p)})

    def test_supplied_bad_checksum_rejected(self):
        with self.assertRaisesRegex(NotebookError,'checksum'):
            self.n.register_artifact(self.eid,{'role':'input','location':str(self.file()),'sha256':'0'*64})
        self.assertEqual(self.manifest()['artifacts'],[])

    def test_changed_and_deleted_evidence_detected(self):
        self.artifact(); p=self.directory/'data'/'input.txt'; p.write_text('tampered')
        self.assertIn('checksum mismatch',' '.join(self.n.validate(self.eid)['errors']))
        p.unlink()
        self.assertIn('missing local file',' '.join(self.n.validate(self.eid)['errors']))

    def test_markdown_preserves_provenance_and_manual_edits(self):
        _,_,rid,fig=self.figure_graph()
        self.n.checkpoint(self.eid,'agent-a','conclusion','Synthetic evidence only',[fig,rid])
        path=self.directory/'record.md'; md=path.read_text()
        for expected in (fig,rid,'sha256','environment','Synthetic evidence only','科学可复现'):
            self.assertIn(expected,md)
        path.write_text(md+'\nHuman annotation\n')
        self.assertTrue(any('differs' in w for w in self.n.validate(self.eid)['warnings']))
        self.n.checkpoint(self.eid,'agent-a','note','Regenerate view')
        preserved=list((self.directory/'revisions').glob('human-record-*.md'))
        self.assertEqual(len(preserved),1); self.assertIn('Human annotation',preserved[0].read_text())
        self.assertEqual(path.read_text(),Notebook.markdown(self.manifest()))

    def test_unsupported_conclusions_and_dangling_references_rejected(self):
        for evidence in ([],['unknown']):
            with self.subTest(evidence=evidence),self.assertRaises(NotebookError):
                self.n.checkpoint(self.eid,'agent-a','conclusion','Unsupported',evidence)
        with self.assertRaises(NotebookError): self.artifact('derived',input_ids=['unknown'])

    def test_figure_requires_complete_provenance(self):
        p=self.file('figure.svg')
        for extra in ({},{'input_ids':['unknown']},{'script_id':'unknown'},{'run_id':'unknown'}):
            with self.subTest(extra=extra),self.assertRaises(NotebookError):
                self.n.register_artifact(self.eid,dict(role='figure',location=str(p),**extra))
        self.assertEqual(self.manifest()['artifacts'],[])

    def test_figure_provenance_and_run_status_verified(self):
        self.figure_graph(status='wip')
        v=self.n.validate(self.eid)
        self.assertFalse(v['valid']); self.assertIn('not successful',' '.join(v['errors']))

    def test_valid_figure_graph_and_run_output_update(self):
        data,script,rid,fig=self.figure_graph()
        self.n.register_run(self.eid,self.run_record(id=rid,input_ids=[data,script],output_ids=[fig]))
        self.assertEqual(len(self.manifest()['runs']),1)
        self.assertTrue(self.n.validate(self.eid)['valid'])

    def test_integrity_duplicate_ids_and_dangling_links(self):
        self.figure_graph(); m=self.manifest()
        m['artifacts'].append(copy.deepcopy(m['artifacts'][0]))
        self.assertIn('Duplicate evidence identifiers',self.n.validate_manifest(m)['errors'])
        m=self.manifest(); m['artifacts'][-1]['script_id']='missing'
        self.assertIn('invalid script reference',' '.join(self.n.validate_manifest(m)['errors']))

    def test_finalization_blocks_missing_assessment_and_unfinished_runs(self):
        self.n.checkpoint(self.eid,'agent-a','method','Synthetic method')
        self.n.register_run(self.eid,{**self.run_record(),'execution_status':'wip'})
        result=self.n.finalize(self.eid,'success','Inconclusive','Synthetic only',None)
        self.assertFalse(result['finalized']); self.assertEqual(result['report']['render_state'],'blocked')
        self.assertIn('Unfinished run remains',result['validation']['errors'])
        self.assertIn('Visualization assessment required',result['validation']['errors'])
        self.assertIsNone(result['report']['pdf_path'])
        self.assertTrue((self.workspace/result['report']['source_path']).is_file())

    def test_index_reports_invalid_manifest_and_keeps_valid_rows(self):
        bad=self.n.root/'experiments'/('exp-'+'f'*32); bad.mkdir(); (bad/'manifest.json').write_text('{broken')
        rows,errors=self.n.index()
        self.assertEqual([r['experiment_id'] for r in rows],[self.eid])
        self.assertEqual(len(errors),1); self.assertEqual(errors[0]['experiment_id'],bad.name)
        self.assertEqual(self.n.index(query='no-match')[0],[])

    def test_invalid_neighbor_does_not_block_healthy_resume(self):
        bad=self.n.root/'experiments'/('exp-'+'f'*32); bad.mkdir(); (bad/'manifest.json').write_text('{broken')
        resumed=self.n.init('task','agent-a','Synthetic task','Test evidence accounting')
        self.assertEqual(resumed['experiment_id'],self.eid)

    def test_schema_rejection_rolls_back_manifest_and_revisions(self):
        before=self.manifest(); revisions=set((self.directory/'revisions').iterdir())
        with self.assertRaises(Exception):
            self.n.checkpoint(self.eid,'agent-a','invalid-kind','Rejected checkpoint')
        self.assertEqual(before,self.manifest())
        self.assertEqual(revisions,set((self.directory/'revisions').iterdir()))
        self.assertEqual((self.directory/'record.md').read_text(),Notebook.markdown(before))

    def test_finalize_pdf_replay_and_report_integrity(self):
        try:
            from pypdf import PdfReader
        except ImportError:
            self.skipTest("pypdf is a test-only dependency; install it to read the rendered PDF")
            return
        self.n.checkpoint(self.eid,'agent-a','method','Synthetic method; no physical validation')
        args=(self.eid,'success','Inconclusive synthetic test','No empirical data',{'beneficial':False,'reason':'No numerical result to plot','figure_ids':[],'reviewed_by':'automated test'})
        result=self.n.finalize(*args,request_id='final-1')
        self.assertTrue(result['finalized'],result)
        pdf=self.workspace/result['report']['pdf_path']
        self.assertGreater(len(PdfReader(str(pdf)).pages),0)
        replay=self.n.finalize(*args,request_id='final-1')
        self.assertEqual(replay['report']['id'],result['report']['id'])
        self.assertEqual(len(self.manifest()['reports']),1)
        self.assertTrue(self.n.validate(self.eid)['valid'])
        pdf.write_bytes(pdf.read_bytes()+b'\nchanged')
        self.assertIn('Changed report pdf_path',self.n.validate(self.eid)['errors'])

    def test_failed_experiment_can_finalize_with_evidence_of_failure(self):
        self.n.checkpoint(self.eid,'agent-a','failure','Intentional demonstration failure')
        r=self.n.finalize(self.eid,'failed','No result available','Synthetic test',{'beneficial':False,'reason':'No result generated','figure_ids':[],'reviewed_by':'automated test'})
        self.assertTrue(r['finalized'],r)
        self.assertEqual(self.manifest()['execution_status'],'failed')

    def test_figure_script_reference_must_have_script_role(self):
        aid=self.artifact()['artifact_id']
        rid=self.n.register_run(self.eid,self.run_record(input_ids=[aid]))['run_id']
        with self.assertRaisesRegex(NotebookError,'script'):
            self.artifact('figure','plot.svg',input_ids=[aid],script_id=aid,run_id=rid)

    def test_index_search_and_pagination(self):
        self.n.init('task-2','agent-a','Other title','Different objective')
        self.assertEqual(len(self.n.index()[0]),2)
        self.assertEqual(len(self.n.index(limit=1,offset=1)[0]),1)
        self.assertEqual(self.n.index(query='SYNTHETIC')[0][0]['experiment_id'],self.eid)

    def test_managed_root_and_artifact_symlinks_rejected(self):
        outside=Path(tempfile.mkdtemp(prefix='symlink-target-',dir=self.session))
        workspace=Path(tempfile.mkdtemp(prefix='symlink-workspace-',dir=self.session))
        (workspace/'levin_notebook').symlink_to(outside,target_is_directory=True)
        with self.assertRaisesRegex(NotebookError,'Symlink'): Notebook(workspace)
        p=self.file(); link=self.directory/'data'/'link.txt'; link.symlink_to(p)
        with self.assertRaisesRegex(NotebookError,'symlink'):
            self.n.register_artifact(self.eid,{'role':'raw','location':str(link)})

    def test_task_agent_and_experiment_path_escapes_rejected(self):
        for bad in ('../escape','/tmp/escape','a/b','..'):
            with self.subTest(bad=bad),self.assertRaises(NotebookError): self.n.init(bad,'agent-a','Title','Objective')
            with self.subTest(agent=bad),self.assertRaises(NotebookError): self.n.init('task',bad,'Synthetic task','Test evidence accounting')
            with self.subTest(experiment=bad),self.assertRaises(NotebookError): self.n._load(bad)

    def test_reference_outside_workspace_is_explicit_external(self):
        external=Path(tempfile.mkdtemp(prefix='external-',dir=self.session))/'original.txt'; external.write_text('original')
        self.n.register_artifact(self.eid,{'role':'raw','location':str(external)})
        a=self.manifest()['artifacts'][0]
        self.assertTrue(a['external']); self.assertEqual(a['location'],str(external))
        self.assertEqual(external.read_text(),'original')

    def test_report_symlink_cannot_create_outside_workspace(self):
        outside=Path(tempfile.mkdtemp(prefix='report-escape-',dir=self.session))
        reports=self.directory/'reports'; reports.rmdir(); reports.symlink_to(outside,target_is_directory=True)
        self.n.checkpoint(self.eid,'agent-a','method','Synthetic method')
        with self.assertRaises(NotebookError):
            self.n.finalize(self.eid,'success','Inconclusive','Synthetic only',{'beneficial':False,'reason':'No quantitative result','figure_ids':[],'reviewed_by':'test'})
        self.assertEqual(list(outside.iterdir()),[], 'Finalize must reject before creating a directory outside the workspace')
    def test_validate_reports_finalize_gates_as_final_readiness(self):
        v = self.n.validate(self.eid)
        self.assertTrue(v['valid'], 'a fresh wip record is structurally valid')
        self.assertFalse(v['final_readiness']['valid'])
        self.assertTrue(any('Stored execution_status is wip' in e for e in v['final_readiness']['errors']))
    def test_blocked_finalize_does_not_commit_terminal_execution_status(self):
        result = self.n.finalize(self.eid, 'success', 'Interpretation', 'Synthetic limitation',
                                 {'beneficial': False, 'reason': 'No result', 'figure_ids': [], 'reviewed_by': 'test'})
        self.assertFalse(result['finalized'])
        self.assertEqual(result['report']['render_state'], 'blocked')
        self.assertEqual(self.manifest()['execution_status'], 'wip',
                         'a blocked finalization must not let the index claim success')
        self.assertEqual(result['report']['requested_execution_status'], 'success')
    def test_terminal_status_commits_when_gates_pass(self):
        script = self.workspace/'analysis.py'; script.write_text('print(1)\n')
        run = self.n.register_run(self.eid, {'backend': 'local', 'execution_status': 'success',
                                             'command': 'python analysis.py', 'environment': {'python': '3.11'}})
        self.n.checkpoint(self.eid, 'agent-a', 'method', 'Deterministic synthetic procedure')
        done = self.n.finalize(self.eid, 'success', 'Supported within scope', 'Synthetic only',
                               {'beneficial': False, 'reason': 'No quantitative result', 'figure_ids': [], 'reviewed_by': 'test'})
        self.assertTrue(done['finalized'])
        self.assertEqual(self.manifest()['execution_status'], 'success')
        self.assertEqual(self.n.validate(self.eid)['final_readiness']['errors'], [])
        del run
    def test_index_combines_query_terms_with_and(self):
        self.n.checkpoint(self.eid, 'agent-a', 'observation', 'Arrhenius slope fitted over denaturation traces')
        self.assertEqual(len(self.n.index('denaturation Arrhenius')[0]), 1)
        self.assertEqual(len(self.n.index('denaturation absentterm')[0]), 0)
        self.assertEqual(len(self.n.index('denaturation')[0]), 1)
    def test_registration_warns_when_no_checksum_exists(self):
        absent = self.n.register_artifact(self.eid, {'role': 'derived', 'location': 'not-yet-written.csv',
                                                    'description': 'Produced later'})
        self.assertEqual(absent['availability'], 'missing')
        self.assertTrue(any('absent' in w for w in absent['warnings']))
        original = notebook.HASH_BUDGET
        try:
            notebook.HASH_BUDGET = 8
            large = self.n.register_artifact(self.eid, {'role': 'derived', 'location': str(self.file('evidence.csv')),
                                                        'description': 'Over the hashing budget'})
        finally:
            notebook.HASH_BUDGET = original
        self.assertIsNone(large['sha256'])
        self.assertTrue(any('budget' in w for w in large['warnings']))

    def test_external_reference_warns_without_claiming_size(self):
        result = self.n.register_artifact(self.eid, {'role': 'derived', 'location': 's3://bucket/run.tar',
                                                     'description': 'HPC output'})
        self.assertEqual(result['availability'], 'external_unverified')
        self.assertTrue(any('not contacted' in w for w in result['warnings']))
        self.assertFalse(any('budget' in w for w in result['warnings']))

    def test_index_covers_run_and_artifact_fields(self):
        data = self.artifact('input', 'fit_batch_model.py')
        self.n.register_run(self.eid, {'backend': 'local', 'execution_status': 'failed',
                                       'command': 'python fit_batch_model.py', 'failure': 'under-determined design',
                                       'environment': {'python': '3.11'}, 'input_ids': [data['artifact_id']]})
        self.assertEqual(len(self.n.index('fit_batch_model.py')[0]), 1)
        self.assertEqual(len(self.n.index('under-determined')[0]), 1)
        self.assertEqual(len(self.n.index('fit_batch_model.py absentterm')[0]), 0)

    def test_reregistering_a_late_file_refreshes_instead_of_duplicating(self):
        target = self.directory / 'data' / 'late_results.csv'
        first = self.n.register_artifact(self.eid, {'role': 'derived', 'location': str(target),
                                                    'description': 'produced later'})
        self.assertEqual(first['availability'], 'missing')
        self.assertIn('missing local file', str(self.n.validate(self.eid)['errors']))
        target.write_text('x,y\n1,2\n')
        second = self.n.register_artifact(self.eid, {'role': 'derived', 'location': str(target),
                                                     'description': 'produced later'})
        self.assertTrue(second.get('refreshed'))
        self.assertEqual(second['artifact_id'], first['artifact_id'])
        self.assertEqual(len(self.manifest()['artifacts']), 1)
        self.assertEqual(self.n.validate(self.eid)['errors'], [])

    def test_raw_relocation_stays_separate_from_derived_record(self):
        target = self.file('shared.csv')
        derived = self.n.register_artifact(self.eid, {'role': 'derived', 'location': str(target), 'description': 'copy'})
        raw = self.n.register_artifact(self.eid, {'role': 'raw', 'location': str(target), 'description': 'original'})
        self.assertNotEqual(derived['artifact_id'], raw['artifact_id'])
        self.assertEqual(len(self.manifest()['artifacts']), 2)

    def test_raw_registered_absent_refreshes_when_the_file_appears(self):
        target = self.directory / 'data' / 'late_raw.csv'
        first = self.n.register_artifact(self.eid, {'role': 'raw', 'location': str(target), 'description': 'original export'})
        self.assertEqual(first['availability'], 'missing')
        target.write_text('value\n1\n')
        second = self.n.register_artifact(self.eid, {'role': 'raw', 'location': str(target), 'description': 'original export'})
        self.assertTrue(second.get('refreshed'))
        self.assertEqual(second['artifact_id'], first['artifact_id'])
        self.assertEqual(second['availability'], 'local')
        self.assertEqual(len(self.manifest()['artifacts']), 1)
        self.assertEqual(self.n.validate(self.eid)['warnings'], [])

    def test_raw_refresh_still_rejects_changed_content(self):
        target = self.file('raw_immutable.csv', 'first\n')
        recorded = self.n.register_artifact(self.eid, {'role': 'raw', 'location': str(target), 'description': 'original'})
        target.write_text('second\n')
        with self.assertRaises(NotebookError):
            self.n.register_artifact(self.eid, {'role': 'raw', 'location': str(target), 'description': 'original'})
        self.assertEqual([a['id'] for a in self.manifest()['artifacts']], [recorded['artifact_id']])

    def test_retry_after_blocked_finalize_reuses_the_same_request_id(self):
        attempt = self.n.finalize(self.eid, 'success', 'Interpretation', 'Synthetic limitation',
                                  {'beneficial': False, 'reason': 'No result', 'figure_ids': [], 'reviewed_by': 'test'},
                                  request_id='finalize-attempt')
        self.assertFalse(attempt['finalized'])
        self.assertNotIn('finalize-attempt', self.manifest()['requests'])
        self.n.checkpoint(self.eid, 'agent-a', 'method', 'Procedure now recorded')
        retry = self.n.finalize(self.eid, 'success', 'Interpretation', 'Synthetic limitation',
                                {'beneficial': False, 'reason': 'No result', 'figure_ids': [], 'reviewed_by': 'test'},
                                request_id='finalize-attempt')
        self.assertTrue(retry['finalized'])
        self.assertTrue((self.workspace / retry['report']['pdf_path']).is_file())
        replay = self.n.finalize(self.eid, 'success', 'Interpretation', 'Synthetic limitation',
                                 {'beneficial': False, 'reason': 'No result', 'figure_ids': [], 'reviewed_by': 'test'},
                                 request_id='finalize-attempt')
        self.assertTrue(replay.get('idempotent'))

    def test_mutation_after_finalization_warns_that_the_report_is_stale(self):
        self.artifact('input')
        self.n.checkpoint(self.eid, 'agent-a', 'method', 'Procedure recorded')
        done = self.n.finalize(self.eid, 'success', 'Supported', 'Synthetic only',
                               {'beneficial': False, 'reason': 'No result', 'figure_ids': [], 'reviewed_by': 'test'})
        self.assertTrue(done['finalized'])
        self.assertFalse(any('stale' in w for w in self.n.validate(self.eid)['warnings']))
        self.n.checkpoint(self.eid, 'agent-a', 'observation', 'Later evidence')
        self.assertTrue(any('stale' in w for w in self.n.validate(self.eid)['warnings']))

    def test_unknown_experiment_id_reports_missing_record(self):
        with self.assertRaises(NotebookError) as caught:
            self.n._load('exp-' + 'f' * 32)
        self.assertIn('No experiment record exists', str(caught.exception))

    def test_optional_run_strings_may_be_empty(self):
        result = self.n.register_run(self.eid, {'backend': 'local', 'external_id': '', 'failure': '',
                                                'execution_status': 'success', 'command': 'python synthetic.py',
                                                'environment': {'python': '3.11'}})
        self.assertTrue(result['ok'])
        run = self.manifest()['runs'][0]
        self.assertEqual(run['external_id'], '')

    def test_paths_outside_the_workspace_are_flagged_as_non_portable(self):
        outside = Path(tempfile.mkdtemp(prefix='outside-', dir=self.session)) / 'machine_local.csv'
        outside.write_text('a\n1\n')
        self.n.register_artifact(self.eid, {'role': 'input', 'location': str(outside), 'description': 'machine local'})
        self.assertTrue(any('not portable' in w for w in self.n.validate(self.eid)['warnings']))
        inside = self.artifact('input')
        self.assertFalse(any(inside['artifact_id'] in w and 'not portable' in w for w in self.n.validate(self.eid)['warnings']))

    def test_remote_sourced_data_must_name_host_and_original_path(self):
        target = self.file('traj_small.xtc', 'x' * 50)
        original = notebook.LARGE_COPY_BYTES
        notebook.LARGE_COPY_BYTES = 10000
        try:
            with self.assertRaises(NotebookError) as no_host:
                self.n.register_artifact(self.eid, {'role': 'derived', 'location': str(target),
                                                    'description': 'pulled result', 'source_origin': 'remote_copy'})
            self.assertIn('remote_host', str(no_host.exception))
            with self.assertRaises(NotebookError) as no_path:
                self.n.register_artifact(self.eid, {'role': 'derived', 'location': str(target), 'description': 'pulled result',
                                                    'source_origin': 'remote_copy', 'remote_host': 'hpc-node7'})
            self.assertIn('remote_path', str(no_path.exception))
            ok = self.n.register_artifact(self.eid, {'role': 'derived', 'location': str(target), 'description': 'pulled result',
                                                     'source_origin': 'remote_copy', 'remote_host': 'hpc-node7',
                                                     'remote_path': '/scratch/run42/out.csv'})
            self.assertTrue(ok['ok'])
            stored = self.manifest()['artifacts'][0]
            self.assertEqual((stored['remote_host'], stored['remote_path']), ('hpc-node7', '/scratch/run42/out.csv'))
        finally:
            notebook.LARGE_COPY_BYTES = original

    def test_remote_original_needs_permission_and_stays_remote_when_large(self):
        target = self.file('traj.xtc', 'x' * 50)
        original = notebook.LARGE_COPY_BYTES
        notebook.LARGE_COPY_BYTES = 10000
        try:
            with self.assertRaises(NotebookError) as denied:
                self.n.register_artifact(self.eid, {'role': 'raw', 'location': str(target), 'description': 'MD trajectory',
                                                    'source_origin': 'remote_copy', 'remote_host': 'hpc-node7',
                                                    'remote_path': '/scratch/run42/traj.xtc'})
            self.assertIn('remote_copy_permission', str(denied.exception))
            self.assertEqual(self.manifest()['artifacts'], [], 'a refused copy must not create a record')
            allowed = self.n.register_artifact(self.eid, {'role': 'raw', 'location': str(target), 'description': 'MD trajectory',
                                                          'source_origin': 'remote_copy', 'remote_host': 'hpc-node7',
                                                          'remote_path': '/scratch/run42/traj.xtc',
                                                          'remote_copy_permission': 'user approved 2026-11-06'})
            self.assertTrue(allowed['ok'])
            notebook.LARGE_COPY_BYTES = 0
            with self.assertRaises(NotebookError) as too_big:
                self.n.register_artifact(self.eid, {'role': 'raw', 'location': str(self.file('huge.xtc', 'y' * 40)),
                                                    'description': 'large original', 'source_origin': 'remote_copy',
                                                    'remote_host': 'hpc-node7', 'remote_path': '/scratch/huge.xtc',
                                                    'remote_copy_permission': 'user approved 2026-11-06'})
            self.assertIn('must stay on hpc-node7', str(too_big.exception))
        finally:
            notebook.LARGE_COPY_BYTES = original

    def test_external_reference_never_needs_a_permission_but_still_names_the_host(self):
        result = self.n.register_artifact(self.eid, {'role': 'raw', 'location': 'ssh://hpc/scratch/run.xtc',
                                                     'description': 'stays on the cluster'})
        self.assertEqual(result['availability'], 'external_unverified')
        with self.assertRaises(NotebookError):
            self.n.register_artifact(self.eid, {'role': 'raw', 'location': 's3://bucket/x.tar', 'description': 'archive',
                                                'source_origin': 'remote_copy'})

    def test_runs_record_the_executing_host(self):
        local = self.n.register_run(self.eid, {'backend': 'local', 'execution_status': 'success',
                                               'command': 'python synthetic.py', 'environment': {'python': '3.11'}})
        self.assertEqual(self.manifest()['runs'][0]['host'], socket.gethostname())
        with self.assertRaises(NotebookError) as remote:
            self.n.register_run(self.eid, {'backend': 'slurm', 'execution_status': 'success',
                                           'command': 'srun python synthetic.py', 'environment': {'python': '3.11'}})
        self.assertIn('must record host', str(remote.exception))
        slurm = self.n.register_run(self.eid, {'backend': 'slurm', 'host': 'hpc-node7', 'external_id': '48152',
                                               'execution_status': 'success', 'command': 'srun python synthetic.py',
                                               'environment': {'python': '3.11'}})
        self.assertTrue(slurm['ok'])
        record = (self.directory / 'record.md').read_text()
        self.assertIn('| 执行主机 | ', record)
        self.assertIn('hpc-node7', record)
        self.assertIn('| `'+slurm['run_id']+'` | slurm | `hpc-node7` |', record)

    def test_invalid_source_origin_rejected(self):
        with self.assertRaises(NotebookError):
            self.n.register_artifact(self.eid, {'role': 'raw', 'location': str(self.file('x.csv')),
                                                'description': 'bad origin', 'source_origin': 'maybe'})

    def test_finalize_measures_space_change_since_init(self):
        target = self.file('measurement.csv', 'value\n1\n')
        self.artifact('input', 'other.csv')
        self.n.checkpoint(self.eid, 'agent-a', 'method', 'Procedure recorded')
        done = self.n.finalize(self.eid, 'success', 'Supported', 'Synthetic only',
                               {'beneficial': False, 'reason': 'No result', 'figure_ids': [], 'reviewed_by': 'test'})
        space = done['space_usage']
        self.assertIn('notebook', space['delta_since_init'])
        self.assertGreater(space['notebook']['bytes'], 0)
        self.assertGreaterEqual(space['delta_since_init']['notebook']['bytes'], 0)
        self.assertGreater(space['experiment']['files'], 0)
        self.assertFalse(space['notebook']['truncated'])
        report = (self.workspace / done['report']['source_path']).read_text()
        self.assertIn('## 9. 数据空间统计', report)
        self.assertIn('相对立项时增量', report)

    def test_record_shows_copy_provenance_for_human_reviewers(self):
        target = self.file('traj.xtc', 'x')
        original = notebook.LARGE_COPY_BYTES
        try:
            notebook.LARGE_COPY_BYTES = 10000
            self.n.register_artifact(self.eid, {'role': 'raw', 'location': str(target), 'description': 'MD trajectory',
                                                'source_origin': 'remote_copy', 'remote_host': 'hpc-node7',
                                                'remote_path': '/scratch/run42/traj.xtc',
                                                'remote_copy_permission': 'user approved 2026-11-06'})
        finally:
            notebook.LARGE_COPY_BYTES = original
        record = (self.directory / 'record.md').read_text()
        self.assertIn('远程来源', record)
        self.assertIn('主机 `hpc-node7`，原始路径 `/scratch/run42/traj.xtc`', record)
        self.assertIn('拷贝授权：user approved 2026-11-06', record)


class RegressionTests(unittest.TestCase):
    """Behaviours that a hand-off review found broken in a real campaign."""

    def setUp(self):
        root = Path(tempfile.mkdtemp(prefix='regression-', dir=SCRATCH))
        self.workspace = root
        self.n = Notebook(root)
        self.initial = self.n.init('task', 'agent-a', 'Regression task', 'Guard corrected behaviour')
        self.eid = self.initial['experiment_id']
        self.directory = Path(self.initial['manifest_path']).parent

    def manifest(self):
        return json.loads((self.directory / 'manifest.json').read_text())

    def file(self, name='input.txt', content='immutable original\n'):
        target = self.directory / 'data' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        return target

    def artifact(self, role='input', name='input.txt', **extra):
        return self.n.register_artifact(self.eid, dict(role=role, location=str(self.file(name)),
                                                       description='Test evidence', **extra))

    def run_record(self, **extra):
        return dict(backend='local', execution_status='success', command='python synthetic.py',
                    parameters={'seed': 0}, environment={'python': sys.version}, **extra)

    def finalize_ok(self, request_id='f'):
        return self.n.finalize(self.eid, 'success', 'Interpretation', 'Synthetic limitation',
                               {'beneficial': False, 'reason': 'No result', 'figure_ids': [], 'reviewed_by': 'test'},
                               request_id=request_id)

    def test_second_finalize_that_omits_lessons_keeps_the_stored_ones(self):
        self.n.checkpoint(self.eid, 'agent-a', 'method', 'Procedure recorded once')
        self.n.finalize(self.eid, 'success', 'First reading', 'Synthetic limitation',
                        {'beneficial': False, 'reason': 'No result', 'figure_ids': [], 'reviewed_by': 'test'},
                        lessons=['Never trust an unverified number'], request_id='one')
        self.n.checkpoint(self.eid, 'agent-a', 'observation', 'Second look')
        done = self.finalize_ok('two')
        self.assertTrue(done['finalized'])
        self.assertEqual(self.manifest()['lessons'], ['Never trust an unverified number'])

    def test_explicit_empty_lessons_clears_them(self):
        self.n.checkpoint(self.eid, 'agent-a', 'method', 'Procedure recorded once')
        self.n.finalize(self.eid, 'success', 'First reading', 'Synthetic limitation',
                        {'beneficial': False, 'reason': 'No result', 'figure_ids': [], 'reviewed_by': 'test'},
                        lessons=['Withdrawn lesson'], request_id='one')
        self.n.checkpoint(self.eid, 'agent-a', 'observation', 'Second look')
        self.n.finalize(self.eid, 'success', 'First reading', 'Synthetic limitation',
                        {'beneficial': False, 'reason': 'No result', 'figure_ids': [], 'reviewed_by': 'test'},
                        lessons=[], request_id='two')
        self.assertEqual(self.manifest()['lessons'], [])

    def test_unconventional_unit_blocks_until_acknowledged(self):
        self.n.checkpoint(self.eid, 'agent-a', 'method', 'Measured the distance')
        blocked = self.n.finalize(self.eid, 'success', 'Interpretation', 'Synthetic limitation',
                                  {'beneficial': False, 'reason': 'No result', 'figure_ids': [], 'reviewed_by': 'test'},
                                  quantities=[{'name': 'rmsd', 'value': 2.1, 'unit': 'nm', 'unit_acknowledged': False}],
                                  request_id='blocked')
        self.assertFalse(blocked['finalized'])
        accepted = self.n.finalize(self.eid, 'success', 'Interpretation', 'Synthetic limitation',
                                   {'beneficial': False, 'reason': 'No result', 'figure_ids': [], 'reviewed_by': 'test'},
                                   quantities=[{'name': 'rmsd', 'value': 2.1, 'unit': 'nm', 'unit_acknowledged': True}],
                                   request_id='accepted')
        self.assertTrue(accepted['finalized'])

    def test_unknown_quantity_name_needs_a_declared_dimension(self):
        self.n.checkpoint(self.eid, 'agent-a', 'method', 'Measured the attack distance')
        undecided = self.n.finalize(self.eid, 'success', 'Interpretation', 'Synthetic limitation',
                                    {'beneficial': False, 'reason': 'No result', 'figure_ids': [], 'reviewed_by': 'test'},
                                    quantities=[{'name': 'd_attack', 'value': 12.0, 'unit': 'Å'}],
                                    request_id='undecided')
        self.assertFalse(undecided['finalized'])
        declared = self.n.finalize(self.eid, 'success', 'Interpretation', 'Synthetic limitation',
                                   {'beneficial': False, 'reason': 'No result', 'figure_ids': [], 'reviewed_by': 'test'},
                                   quantities=[{'name': 'd_attack', 'value': 12.0, 'unit': 'Å', 'dimension': 'L'}],
                                   request_id='declared')
        self.assertTrue(declared['finalized'])
        wrong = self.n.finalize(self.eid, 'success', 'Interpretation', 'Synthetic limitation',
                                {'beneficial': False, 'reason': 'No result', 'figure_ids': [], 'reviewed_by': 'test'},
                                quantities=[{'name': 'd_attack', 'value': 12.0, 'unit': 'Å', 'dimension': 'M L^2 T^-2'}],
                                request_id='wrong')
        self.assertFalse(wrong['finalized'])

    def test_observation_and_method_can_be_superseded(self):
        first = self.n.checkpoint(self.eid, 'agent-a', 'observation', 'Value was 1.9', title='First reading')
        corrected = self.n.checkpoint(self.eid, 'agent-a', 'observation', 'Value was 2.4',
                                      title='Re-read after recalibration', supersedes=first['checkpoint_id'])
        self.assertTrue(corrected['ok'])
        method = self.n.checkpoint(self.eid, 'agent-a', 'method', 'Ran 10 ns')
        self.n.checkpoint(self.eid, 'agent-a', 'method', 'Ran 100 ns', supersedes=method['checkpoint_id'])
        record = (self.directory / 'record.md').read_text()
        # The wrong value stays visible, struck through, so the record shows the correction.
        self.assertIn('~~First reading~~', record)
        self.assertIn('已由「Re-read after recalibration」更正', record)
        self.assertIn('~~方法~~（已由第 2 条方法更正）', record)

    def test_a_conclusion_may_not_supersede_a_failure_note(self):
        failed = self.n.checkpoint(self.eid, 'agent-a', 'failure', 'Solver diverged at step 40')
        with self.assertRaises(NotebookError):
            self.n.checkpoint(self.eid, 'agent-a', 'conclusion', 'Diverged', supersedes=failed['checkpoint_id'])

    def test_implementer_can_be_added_on_resume(self):
        resumed = Notebook(self.workspace).init('task', 'agent-b', 'Regression task', 'Guard corrected behaviour',
                                                implementer={'kind': 'agent', 'name': 'Reviewer', 'model': 'claude'})
        self.assertTrue(resumed['resumed'])
        self.assertEqual(self.manifest()['implementer'], {'kind': 'agent', 'name': 'Reviewer', 'model': 'claude'})
        # A second resume must not rewrite who did the work.
        Notebook(self.workspace).init('task', 'agent-b', 'Regression task', 'Guard corrected behaviour',
                                      implementer={'kind': 'user', 'name': 'Someone else'})
        self.assertEqual(self.manifest()['implementer']['name'], 'Reviewer')

    def test_implementer_as_a_string_explains_the_expected_shape(self):
        with self.assertRaises(NotebookError) as caught:
            self.n.init('task2', 'agent-a', 'Other task', 'Explain the shape',
                        implementer='{"kind": "agent"}')
        self.assertIn('implementer must be an object', str(caught.exception))

    def test_prune_reports_keeps_the_newest_success_and_all_revisions(self):
        data = self.directory / 'data' / 'in.csv'
        data.write_text('a\n1\n')
        self.n.register_artifact(self.eid, {'role': 'input', 'location': str(data), 'description': 'Input'})
        self.n.checkpoint(self.eid, 'agent-a', 'method', 'Ran three finalizes')
        for index in range(3):
            self.assertTrue(self.finalize_ok(f'snapshot-{index}')['finalized'])
        before = len(list((self.directory / 'reports').iterdir()))
        self.assertEqual(before, 3)
        result = self.n.prune_reports(self.eid)
        self.assertEqual(result['removed_count'], 2)
        self.assertEqual(len(list((self.directory / 'reports').iterdir())), 1)
        self.assertEqual(len(self.manifest()['reports']), 1)
        self.assertTrue(self.n.validate(self.eid)['valid'])
        self.assertGreater(len(list((self.directory / 'revisions').iterdir())), 0)
        self.assertIn(result['kept'][0], [p.name for p in (self.directory / 'reports').iterdir()])

    def test_prune_reports_dry_run_deletes_nothing(self):
        data = self.directory / 'data' / 'in.csv'
        data.write_text('a\n1\n')
        self.n.register_artifact(self.eid, {'role': 'input', 'location': str(data), 'description': 'Input'})
        self.n.checkpoint(self.eid, 'agent-a', 'method', 'Ran two finalizes')
        for index in range(2):
            self.finalize_ok(f'snapshot-{index}')
        plan = self.n.prune_reports(self.eid, dry_run=True)
        self.assertEqual(plan['removed_count'], 1)
        self.assertEqual(len(list((self.directory / 'reports').iterdir())), 2)

    def test_prune_reports_never_empties_a_record_with_only_blocked_attempts(self):
        self.finalize_ok('no-method-yet')  # blocked: no method checkpoint recorded
        self.assertTrue((self.directory / 'reports').is_dir())
        self.n.prune_reports(self.eid)
        self.assertGreaterEqual(len(list((self.directory / 'reports').iterdir())), 1)

    def test_validate_separates_delivered_reports_from_blocked_attempts(self):
        data = self.directory / 'data' / 'in.csv'
        data.write_text('a\n1\n')
        self.n.register_artifact(self.eid, {'role': 'input', 'location': str(data), 'description': 'Input'})
        # A blocked attempt first: no method checkpoint yet.
        blocked = self.finalize_ok('blocked-attempt')
        self.assertEqual(blocked['report']['render_state'], 'blocked')
        self.n.checkpoint(self.eid, 'agent-a', 'method', 'Recorded the procedure')
        self.assertTrue(self.finalize_ok('delivered')['finalized'])
        summary = self.n.validate(self.eid)['reports']
        self.assertEqual(summary['total'], 2)
        self.assertEqual(summary['success'], 1)
        self.assertEqual(summary['blocked'], 1)
        self.assertEqual(summary['pending_snapshots'], 1)
        self.assertEqual(summary['latest_success'], self.manifest()['reports'][-1]['id'])

    def test_a_reference_id_works_wherever_an_id_works(self):
        self.artifact('input')
        # give a second artifact a caller-chosen alias, as a real record does
        target = self.file('alias.csv')
        aliased = self.n.register_artifact(self.eid, {'role': 'input', 'location': str(target),
                                                      'description': 'Aliased input',
                                                      'reference_id': 'alt-build-data'})['artifact_id']
        script = self.file('plot.py')
        self.n.register_artifact(self.eid, {'role': 'script', 'location': str(script),
                                            'description': 'Plotter', 'reference_id': 'b5-make'})
        # a run may name its inputs by alias and be updated by alias
        run = self.n.register_run(self.eid, dict(self.run_record(input_ids=['alt-build-data']),
                                                 reference_id='run-figs'))
        self.assertTrue(run['ok'])
        # a figure may name the script by alias
        figure = self.n.register_artifact(self.eid, {'role': 'figure', 'location': str(self.file('f.svg')),
                                                     'description': 'Figure', 'input_ids': ['alt-build-data'],
                                                     'script_id': 'b5-make', 'run_id': 'run-figs'})
        self.assertTrue(figure['ok'])
        # checkpoint evidence may be named by alias too
        note = self.n.checkpoint(self.eid, 'agent-a', 'observation', 'Looked at the trace',
                                 evidence_ids=['alt-build-data'])
        self.assertTrue(note['ok'])
        stored = self.manifest()
        resolved = next(c for c in stored['checkpoints'] if c['id'] == note['checkpoint_id'])
        self.assertEqual(resolved['evidence_ids'][0], aliased)

    def test_unknown_reference_reports_what_was_expected(self):
        with self.assertRaises(NotebookError) as caught:
            self.n.register_artifact(self.eid, {'role': 'figure', 'location': str(self.file('g.svg')),
                                                'description': 'Figure', 'input_ids': ['made-up'],
                                                'script_id': self.artifact('script', 'p.py')['artifact_id'],
                                                'run_id': 'nope'})
        message = str(caught.exception)
        self.assertIn('artifact_id', message)
        self.assertIn('reference_id', message)

    def test_update_run_by_alias_and_explain_a_wrong_id(self):
        self.artifact('input')
        self.n.register_run(self.eid, dict(self.run_record(), reference_id='run-figs'))
        updated = self.n.register_run(self.eid, dict(self.run_record(), id='run-figs', command='python v2.py'))
        self.assertTrue(updated['ok'])
        with self.assertRaises(NotebookError) as caught:
            self.n.register_run(self.eid, dict(self.run_record(), id='run-does-not-exist'))
        self.assertIn('omit run.id', str(caught.exception))

    def test_checkpoint_ids_are_not_evidence(self):
        evidence = self.artifact('input')['artifact_id']
        first = self.n.checkpoint(self.eid, 'agent-a', 'observation', 'First reading', evidence_ids=[evidence])
        with self.assertRaises(NotebookError) as caught:
            self.n.checkpoint(self.eid, 'agent-a', 'conclusion', 'Concluded', evidence_ids=[first['checkpoint_id']])
        self.assertIn('not checkpoint ids', str(caught.exception))

    def test_deliverable_is_a_role(self):
        result = self.n.register_artifact(self.eid, {'role': 'deliverable',
                                                    'location': str(self.file('briefing.html')),
                                                    'description': 'Human-facing briefing'})
        self.assertTrue(result['ok'])

    def test_a_figure_inherits_provenance_from_its_run(self):
        data = self.artifact('input')['artifact_id']
        script = self.artifact('script', 'plot.py')['artifact_id']
        run = self.n.register_run(self.eid, self.run_record(input_ids=[data, script]))['run_id']
        # only the run is named; inputs and script come from the run
        figure = self.n.register_artifact(self.eid, {'role': 'figure', 'location': str(self.file('f.svg')),
                                                     'description': 'Figure', 'run_id': run})
        self.assertTrue(figure['ok'])
        stored = next(a for a in self.manifest()['artifacts'] if a['id'] == figure['artifact_id'])
        self.assertEqual(stored['input_ids'], [data, script])
        self.assertEqual(stored['script_id'], script)

    def test_a_figure_without_any_provenance_still_fails(self):
        with self.assertRaises(NotebookError) as caught:
            self.n.register_artifact(self.eid, {'role': 'figure', 'location': str(self.file('h.svg')),
                                                'description': 'Figure'})
        self.assertIn('run that produced them', str(caught.exception))

    def test_index_can_report_per_record_counts(self):
        self.artifact('input')
        self.n.checkpoint(self.eid, 'agent-a', 'method', 'Procedure recorded')
        self.finalize_ok('one')
        rows, errors = self.n.index('', include_summary=True)
        self.assertEqual(errors, [])
        summary = rows[0]['summary']
        self.assertEqual(summary['artifacts'], 1)
        self.assertEqual(summary['artifact_roles'], {'input': 1})
        self.assertEqual(summary['checkpoints']['method'], 1)
        self.assertEqual(summary['reports'], 1)
        self.assertEqual(summary['quantities'], 0)
        # the default shape stays small
        plain, _errors = self.n.index('')
        self.assertNotIn('summary', plain[0])

    def test_an_alias_is_stored_as_the_canonical_id(self):
        # Registration accepted an alias but persisted it verbatim, so the record was
        # valid on write and invalid at validate.
        script = self.artifact('script', 'plot.py', reference_id='b5-make')['artifact_id']
        data = self.artifact('input', 'trace.csv', reference_id='alt-build-data')['artifact_id']
        run = self.n.register_run(self.eid, dict(self.run_record(input_ids=['alt-build-data']),
                                                 reference_id='run-figs'))['run_id']
        figure = self.n.register_artifact(self.eid, {'role': 'figure', 'location': str(self.file('f.svg')),
                                                     'description': 'Figure', 'input_ids': ['alt-build-data'],
                                                     'script_id': 'b5-make', 'run_id': 'run-figs'})
        stored = next(a for a in self.manifest()['artifacts'] if a['id'] == figure['artifact_id'])
        self.assertEqual(stored['input_ids'], [data])
        self.assertEqual(stored['script_id'], script)
        self.assertEqual(stored['run_id'], run)
        self.assertTrue(self.n.validate(self.eid)['valid'], self.n.validate(self.eid)['errors'])

    def test_updating_a_run_keeps_its_alias(self):
        self.artifact('input')
        self.n.register_run(self.eid, dict(self.run_record(), reference_id='run-figs'))
        self.n.register_run(self.eid, dict(self.run_record(), id='run-figs', command='python v2.py'))
        stored = self.manifest()['runs'][0]
        self.assertEqual(stored['reference_id'], 'run-figs')
        # and the alias still resolves afterwards
        self.assertTrue(self.n.register_run(self.eid, dict(self.run_record(), id='run-figs',
                                                            command='python v3.py'))['ok'])

    def test_refreshing_an_artifact_keeps_its_alias(self):
        self.artifact('input', reference_id='alt-build-data')
        self.artifact('input', reference_id=None)
        stored = self.manifest()['artifacts'][0]
        self.assertEqual(stored['reference_id'], 'alt-build-data')

    def test_recovery_and_notes_are_rendered(self):
        # `resume` and `note` were accepted, given ids, and never appeared anywhere,
        # while the skill tells the author to record recovery as `resume`.
        evidence = self.artifact('input')['artifact_id']
        self.n.checkpoint(self.eid, 'agent-a', 'resume', 'Picked up after the scheduler preempted the job',
                          title='第二天续做', evidence_ids=[evidence])
        self.n.checkpoint(self.eid, 'agent-a', 'note', 'Cluster noticeboard said node7 was rebooted',
                          title='环境备注')
        record = (self.directory / 'record.md').read_text()
        self.assertRegex(record, r'## \d+\. 恢复与备注')
        self.assertIn('Picked up after the scheduler preempted the job', record)
        self.assertIn('Cluster noticeboard said node7 was rebooted', record)
        self.assertIn('**续做**', record)
        self.assertIn('**备注**', record)

    def test_a_record_without_notes_keeps_the_plain_spine(self):
        self.artifact('input')
        self.n.checkpoint(self.eid, 'agent-a', 'method', 'Procedure recorded')
        record = (self.directory / 'record.md').read_text()
        self.assertNotIn('恢复与备注', record)

    def test_derived_from_records_the_campaign_hierarchy(self):
        parent = Notebook(self.workspace).init('parent-task', 'agent-a', 'Parent', 'Upstream work')['experiment_id']
        child = Notebook(self.workspace).init('child-task', 'agent-a', 'Child', 'Downstream work',
                                              derived_from=[parent])['experiment_id']
        manifest = json.loads((self.workspace / 'levin_notebook' / 'experiments' / child / 'manifest.json').read_text())
        self.assertEqual(manifest['derived_from'], [parent])

    def test_derived_from_rejects_an_id_that_is_not_an_experiment(self):
        with self.assertRaises(NotebookError):
            self.n.init('task3', 'agent-a', 'Third', 'Bad parent id', derived_from=['parent-task'])

    def test_cross_record_reference_without_a_declared_parent_warns(self):
        other = Notebook(self.workspace).init('other-task', 'agent-a', 'Other', 'Separate work')['experiment_id']
        other_manifest = self.workspace / 'levin_notebook' / 'experiments' / other / 'manifest.json'
        other_file = other_manifest.parent / 'data' / 'shared.csv'
        other_file.write_text('x\n1\n')
        Notebook(self.workspace).register_artifact(other, {'role': 'input', 'location': str(other_file),
                                                           'description': 'Shared input'})
        self.n.checkpoint(self.eid, 'agent-a', 'method', 'Used the shared table')
        self.n.register_artifact(self.eid, {'role': 'input', 'location': str(other_file),
                                            'description': 'Borrowed from the other record'})
        warnings = self.n.validate(self.eid)['warnings']
        self.assertTrue(any('derived_from' in w and other in w for w in warnings))

    def test_declaring_the_parent_silences_the_cross_record_warning(self):
        other = Notebook(self.workspace).init('other-task', 'agent-a', 'Other', 'Separate work')['experiment_id']
        other_file = self.workspace / 'levin_notebook' / 'experiments' / other / 'data' / 'shared.csv'
        other_file.write_text('x\n1\n')
        Notebook(self.workspace).register_artifact(other, {'role': 'input', 'location': str(other_file),
                                                           'description': 'Shared input'})
        declared = Notebook(self.workspace).init('task', 'agent-a', 'Regression task', 'Guard corrected behaviour',
                                                 derived_from=[other])['experiment_id']
        Notebook(self.workspace).register_artifact(declared, {'role': 'input', 'location': str(other_file),
                                                              'description': 'Borrowed from the other record'})
        Notebook(self.workspace).checkpoint(declared, 'agent-a', 'method', 'Used the shared table')
        warnings = Notebook(self.workspace).validate(declared)['warnings']
        self.assertFalse(any('derived_from' in w for w in warnings))


if __name__ == '__main__':
    unittest.main(verbosity=2)