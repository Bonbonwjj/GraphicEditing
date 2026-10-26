"""Scope previews must not execute, truncate, or silently drop local imports."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import analysis_scope as scope
import project_preparation as prep


class AnalysisScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='plot-scope-test-')
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.source=self.root/'original'
        for folder in ('fig1','fig2','common'):(self.source/folder).mkdir(parents=True)
        (self.source/'fig1/render.py').write_text('from common.helper import data\nraise RuntimeError("never execute")\n')
        (self.source/'common/__init__.py').write_text('# package initializer\n')
        (self.source/'common/helper.py').write_text('from .values import data\n')
        (self.source/'common/values.py').write_text('data = [1, 2, 3]\n')
        (self.source/'fig2/large.py').write_text('#'+ 'x'*190000+'\n')
        (self.source/'fig1/values.csv').write_text('x,y\n1,2\n')
        prep.open_project(self.root/'projects',self.source,'example')
        self.project=self.root/'projects/example'

    def test_options_and_whole_scope_do_not_truncate_or_call_model(self):
        with patch('llm_client.chat') as model:
            result=scope.options(self.project)
            plan=scope.build(self.project)
            self.assertFalse(plan['within_limit'])
            self.assertIn('fig2/large.py',plan['files'])
            self.assertGreater(plan['chars'],190000)
            self.assertTrue(any(o['scope']=='fig1' for o in result['options']))
            with self.assertRaisesRegex(ValueError,'超过单次'):prep.start_analysis(self.project,True)
            model.assert_not_called()
        self.assertNotIn(str(self.project),prep.RUNNING)
        self.assertEqual(prep.read_state(self.project)['status'],'needs_analysis')

    def test_transitive_imports_relative_imports_and_initializers_included(self):
        plan=scope.build(self.project,'fig1')
        self.assertEqual(set(plan['files']),{'fig1/render.py','common/helper.py','common/values.py','common/__init__.py'})
        self.assertEqual(len(plan['added_dependencies']),3)
        self.assertTrue(plan['within_limit'])
        self.assertNotIn('sources',scope.public(plan))
        self.assertIn('fig2/large.py',scope.public(plan)['omitted_files'])
        self.assertEqual(plan['chars'],sum(len(v['content']) for v in plan['sources']))
        with patch('llm_client.chat',return_value=json.dumps({'status':'needs_context','reason':'Synthetic missing input'})) as model:
            result=prep.analyze(self.project,True,plan=plan)
        sent=json.loads(model.call_args.args[0][1]['content'])
        self.assertEqual({s['path'] for s in sent['sources']},set(plan['files']))
        self.assertEqual(sent['requested_scope'],'fig1')
        self.assertIn('fig2/large.py',sent['source_catalog'])
        self.assertEqual(result['analysis_scope'],'fig1')
        self.assertEqual(result['status'],'needs_context')

    def test_preview_token_changes_and_stale_or_unconsented_scope_never_sent(self):
        plan=scope.build(self.project,'fig1')
        with patch('llm_client.chat') as model:
            with self.assertRaises(ValueError):prep.start_analysis(self.project,False,'fig1',plan['confirmation_token'])
            with self.assertRaisesRegex(ValueError,'重新预览'):prep.start_analysis(self.project,True,'fig1','wrong')
            file=self.project/'.preparation/source/common/values.py'
            file.write_text('data = [4, 5, 6]\n')
            with self.assertRaisesRegex(ValueError,'重新预览'):prep.start_analysis(self.project,True,'fig1',plan['confirmation_token'])
            model.assert_not_called()

    def test_oversized_dependency_is_not_dropped(self):
        (self.project/'.preparation/source/fig1/render.py').write_text('from fig2.large import values\n')
        plan=scope.build(self.project,'fig1/render.py')
        self.assertIn('fig2/large.py',plan['files'])
        self.assertFalse(plan['within_limit'])

    def test_dynamic_dependencies_are_disclosed_and_unsafe_paths_rejected(self):
        file=self.project/'.preparation/source/fig1/render.py'
        file.write_text('import importlib\nmodule=importlib.import_module(name)\n')
        self.assertTrue(scope.build(self.project,'fig1')['warnings'])
        for invalid in ('../original','/tmp','unknown','fig1/../fig2'):
            with self.assertRaises(ValueError):scope.build(self.project,invalid)
        file.unlink();file.symlink_to(self.source/'fig1/render.py')
        with self.assertRaisesRegex(ValueError,'不安全'):scope.build(self.project,'fig1')

    def test_rename_updates_metadata_only_and_reopens_with_same_id(self):
        before={p.relative_to(self.project):p.read_bytes() for p in self.project.rglob('*') if p.is_file() and p.name!='project.json'}
        result=prep.rename_project(self.project,'新的工程名称')
        self.assertEqual(result['display_name'],'新的工程名称')
        self.assertEqual(result['project'],'example')
        after={p.relative_to(self.project):p.read_bytes() for p in self.project.rglob('*') if p.is_file() and p.name!='project.json'}
        self.assertEqual(before,after)
        self.assertEqual(prep.open_project(self.root/'projects',self.source,'example')['display_name'],'新的工程名称')
        for invalid in ('', 'x'*101, 'a\nb', None):
            with self.assertRaises(ValueError):prep.rename_project(self.project,invalid)
        prep.RUNNING.add(str(self.project))
        try:
            with self.assertRaises(ValueError):prep.rename_project(self.project,'busy')
        finally:prep.RUNNING.discard(str(self.project))


if __name__=='__main__':unittest.main()
