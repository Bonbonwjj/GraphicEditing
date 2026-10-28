"""Whole-project batches: coverage, consent, resume and real merge validation."""
import json
from pathlib import Path
import shutil
import time
import unittest
from unittest.mock import patch

import analysis_scope
import project_batch as batch
import project_preparation as prep
import tests.test_project_preparation as fixtures
from tests.test_project_preparation import EXPORTER, RENDERER


class BatchTests(unittest.TestCase):
    setUp = fixtures.PreparationTests.setUp
    open = fixtures.PreparationTests.open
    package = fixtures.PreparationTests.package

    def project(self):
        (self.source/'a.py').write_text('# a\n'+'#x\n'*35000)
        (self.source/'b.py').write_text('# b\n'+'#y\n'*35000)
        return self.open()

    def response(self):
        return json.dumps({'mode':'extract','status':'pending_local_run','reason':'Synthetic complete extraction',
                           'figures':[{'figure_id':'line','source_location':'analysis.py:1'}],
                           'generated_files':[{'path':'analysis_export.py','role':'export_program','content':EXPORTER},
                                              {'path':'render_plot.py','role':'renderer','content':RENDERER}]})

    def wait(self, project):
        deadline=time.monotonic()+30
        while str(project) in prep.RUNNING and time.monotonic()<deadline:time.sleep(.02)
        self.assertNotIn(str(project),prep.RUNNING)
        return prep.status(project)

    def test_plan_covers_every_target_once_without_sending_code(self):
        project=self.project()
        with patch('llm_client.chat') as model:
            plan=batch.plan(project)
            model.assert_not_called()
        targets=[p for j in plan['jobs'] for p in j['target_files']]
        self.assertEqual(sorted(targets),['a.py','analysis.py','b.py'])
        self.assertEqual(len(targets),len(set(targets)))
        self.assertEqual(len(plan['jobs']),2)
        self.assertTrue(all(j['chars']<=analysis_scope.LIMIT for j in plan['jobs']))
        self.assertNotIn('sources',batch.public_plan(plan)['jobs'][0])

    def test_consent_and_stale_plan_rejected_before_model(self):
        project=self.project();plan=batch.plan(project)
        with patch('llm_client.chat') as model:
            for consent,token in [(False,plan['confirmation_token']),(True,'stale')]:
                with self.assertRaises(ValueError):batch.start(project,consent,token)
            model.assert_not_called()
        self.assertFalse(batch.batch_path(project).exists())

    def test_failure_resume_preserves_successful_batch(self):
        project=self.project();plan=batch.plan(project)
        with patch('llm_client.chat',side_effect=[ValueError('synthetic outage'),self.response()]) as model:
            batch.start(project,True,plan['confirmation_token']);self.wait(project)
            self.assertEqual(model.call_count,2)
        jobs=batch.read(project)['jobs']
        self.assertEqual([j['status'] for j in jobs],['failed','pending_local_run'])
        preserved=(batch.child_path(project,jobs[1]['id'])/'.preparation/state.json').read_bytes()
        with patch('llm_client.chat',return_value=self.response()) as model:
            batch.start(project,True,plan['confirmation_token']);self.wait(project)
            self.assertEqual(model.call_count,1)
        self.assertEqual((batch.child_path(project,jobs[1]['id'])/'.preparation/state.json').read_bytes(),preserved)
        self.assertEqual(prep.status(project)['status'],'pending_local_run')
        self.assertFalse(any((project/'charts').glob('*.py')))

    def test_all_batches_validate_and_merge_same_ids_without_collisions(self):
        project=self.project();plan=batch.plan(project)
        original={p.name:p.read_bytes() for p in self.source.iterdir() if p.is_file()}
        with patch('llm_client.chat',return_value=self.response()) as model:
            batch.start(project,True,plan['confirmation_token']);self.wait(project)
            self.assertEqual(model.call_count,2)
        jobs=batch.read(project)['jobs'];bundle=self.package()
        output=self.root/'all-exports';output.mkdir()
        for job in jobs:shutil.copytree(bundle,output/job['id'])
        # One bad package cannot install partial success into the parent.
        bad=output/jobs[1]['id']/'manifest.json';saved=bad.read_bytes()
        bad.write_text('{}')
        batch.start_finalize(project,str(output),True);result=self.wait(project)
        self.assertNotEqual(result['status'],'ready')
        self.assertFalse(any((project/'charts').glob('*.py')))
        self.assertEqual([j['status'] for j in batch.read(project)['jobs']],['ready','validation_failed'])
        bad.write_bytes(saved)
        batch.start_finalize(project,str(output),True);result=self.wait(project)
        self.assertEqual(result['status'],'ready')
        self.assertTrue(batch.read(project)['installed'])
        self.assertEqual({p.stem for p in (project/'charts').glob('*.py')},{j['id']+'__line' for j in jobs})
        self.assertEqual(len(list((project/'previews').glob('*.png'))),2)
        self.assertEqual(original,{p.name:p.read_bytes() for p in self.source.iterdir() if p.is_file()})
        self.assertTrue(batch.archive(project).startswith(b'PK'))
        with self.assertRaises(ValueError):batch.start(project,True,plan['confirmation_token'])

    def test_unchanged_missing_context_is_not_sent_again(self):
        project=self.project();plan=batch.plan(project)
        response=json.dumps({'mode':'extract','status':'needs_context','reason':'missing dynamic renderer'})
        with patch('llm_client.chat',return_value=response) as model:
            batch.start(project,True,plan['confirmation_token']);self.wait(project)
            self.assertEqual(model.call_count,len(plan['jobs']))
        saved=batch.batch_path(project).read_bytes()
        with patch('llm_client.chat') as model:
            with self.assertRaisesRegex(ValueError,'没有可直接重试'):
                batch.start(project,True,plan['confirmation_token'])
            model.assert_not_called()
        self.assertEqual(saved,batch.batch_path(project).read_bytes())
        value=batch.read(project)
        self.assertEqual(len(value['attempt']['returned']),len(plan['jobs']))

    def test_retry_counts_only_current_attempt_and_preserves_context_result(self):
        project=self.project();plan=batch.plan(project)
        missing=json.dumps({'mode':'extract','status':'needs_context','reason':'missing dynamic renderer'})
        with patch('llm_client.chat',side_effect=[missing,ValueError('network interrupted')]):
            batch.start(project,True,plan['confirmation_token']);self.wait(project)
        previous=batch.read(project)['jobs'][0].copy()
        with patch('llm_client.chat',return_value=self.response()) as model:
            batch.start(project,True,plan['confirmation_token']);self.wait(project)
            self.assertEqual(model.call_count,1)
        value=batch.read(project)
        self.assertEqual(value['jobs'][0],previous)
        self.assertEqual(value['attempt']['jobs'],[value['jobs'][1]['id']])
        self.assertEqual(value['attempt']['returned'],value['attempt']['jobs'])
        self.assertGreaterEqual(value['jobs'][1]['finished_at'],value['jobs'][1]['started_at'])

    def test_oversized_single_closure_is_visible_and_never_ready(self):
        (self.source/'big.py').write_text('#'+'z'*200000)
        project=self.open();plan=batch.plan(project)
        self.assertTrue(any(not j['within_limit'] for j in plan['jobs']))
        with patch('llm_client.chat',return_value=self.response()):
            batch.start(project,True,plan['confirmation_token']);self.wait(project)
        self.assertTrue(any(j['status']=='blocked' for j in batch.read(project)['jobs']))
        with self.assertRaises(ValueError):batch.merge_verified(project,batch.read(project))

    def test_exact_duplicate_text_keeps_all_paths(self):
        content='# helper\n'+'#x\n'*35000
        (self.source/'a.py').write_text(content);(self.source/'b.py').write_text(content)
        project=self.open();plan=batch.plan(project)
        self.assertEqual(len(plan['jobs']),1)
        job=plan['jobs'][0]
        expanded={}
        for item in job['sources']:
            for name in [item['path'],*item.get('identical_paths',[])]:expanded[name]=item['content']
        self.assertEqual(expanded,analysis_scope.sources_for(project))
        self.assertGreater(job['raw_chars'],job['chars'])

    def test_literal_import_path_keeps_independent_groups_separate(self):
        for folder in ('group/code','group/native','other'):(self.source/folder).mkdir(parents=True)
        (self.source/'group/code/main.py').write_text("from pathlib import Path\nimport sys\nROOT=Path(__file__).resolve().parents[1]\nsys.path.insert(0,str(ROOT/'native'))\nimport helper\n")
        (self.source/'group/native/helper.py').write_text('VALUE=1\n')
        (self.source/'other/helper.py').write_text('VALUE=2\n')
        project=self.open();plan=analysis_scope.build(project,'group/code/main.py')
        self.assertIn('group/native/helper.py',plan['files'])
        self.assertNotIn('other/helper.py',plan['files'])


if __name__=='__main__':unittest.main()
