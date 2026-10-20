"""Real renders across the LY import boundary and candidate-before-apply policy."""
import gzip
import hashlib
import json
from pathlib import Path
import pickle
import shutil
import tempfile
import unittest
from unittest.mock import patch

import server
from bundle_importer import import_plot_bundle
from bundle_bindings import make_portable
from chat_runner import render_candidate
from local_execution import approve
import module_workflow
from shared_modules import encode_module_id


class SharedModuleCandidateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name)
        self.project=root/'demo'
        for directory in ('charts','data','lib'):(self.project/directory).mkdir(parents=True,exist_ok=True)
        (self.project/'project.json').write_text('{"name":"Demo"}',encoding='utf-8')
        self.module=self.project/'lib/theme.py'
        self.original="COLOR = 'blue'\n\nWIDTH = 1\n"
        self.module.write_text(self.original,encoding='utf-8',newline='\n')
        source="""import os
import matplotlib.pyplot as plt
from projects.demo.lib.theme import COLOR, WIDTH
fig, ax = plt.subplots()
ax.plot([0,1],[1,2],color=COLOR,linewidth=WIDTH)
ax.set(xlabel='Time',ylabel='Value')
fig.savefig(os.environ['CHART_OUTPUT'])
"""
        for name in ('a','b'):(self.project/f'charts/{name}.py').write_text(source,encoding='utf-8')
        self.patch=patch.object(server,'PROJECTS',root)
        self.patch.start();self.addCleanup(self.patch.stop)
        approve(self.project)
        self.ident=encode_module_id('theme.py')

    def test_one_shared_location_validates_representative_and_waits_for_apply(self):
        source=self.original.replace('blue','red')
        draft=module_workflow.preview(server,'demo',self.ident,source,'a')
        self.assertEqual(draft['validation_scope'],'representative')
        self.assertEqual(draft['charts'],['a'])
        self.assertEqual(self.module.read_text(),self.original)
        self.assertTrue(module_workflow.apply(server,'demo',self.ident,draft['id'])['applied'])
        self.assertEqual(self.module.read_text(),source)

    def test_distinct_locations_validate_all_and_can_continue_without_applying(self):
        source=self.original.replace('blue','red').replace('WIDTH = 1','WIDTH = 2')
        first=module_workflow.preview(server,'demo',self.ident,source,'a')
        self.assertEqual(first['charts'],['a','b'])
        second=module_workflow.preview(server,'demo',self.ident,source.replace('red','green'),'a')
        self.assertNotEqual(first['id'],second['id'])
        self.assertEqual(self.module.read_text(),self.original)

    def test_multiple_edits_to_one_shared_function_count_as_one_location(self):
        original="def draw():\n    color='blue'\n    label='Time'\n    width=1\n"
        edited=original.replace("'blue'","'red'").replace('width=1','width=2')
        self.assertEqual(module_workflow.changed_locations(original,edited),1)

    def test_external_edit_rejects_stale_candidate(self):
        draft=module_workflow.preview(server,'demo',self.ident,self.original.replace('blue','red'),'a')
        self.module.write_text(self.original+'# someone changed this\n',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'正式代码或数据已变化'):
            module_workflow.apply(server,'demo',self.ident,draft['id'])
        self.assertIn('someone changed this',self.module.read_text())

    def test_chart_entry_change_invalidates_shared_candidate(self):
        draft=module_workflow.preview(server,'demo',self.ident,self.original.replace('blue','red'),'a')
        entry=self.project/'charts/b.py';entry.write_text(entry.read_text()+'\n# newer entry\n')
        with self.assertRaisesRegex(ValueError,'正式代码或数据已变化'):
            module_workflow.apply(server,'demo',self.ident,draft['id'])
        self.assertEqual(self.module.read_text(),self.original)

    def test_one_failed_chart_prevents_multi_location_candidate(self):
        (self.project/'charts/b.py').write_text("raise RuntimeError('broken chart')",encoding='utf-8')
        with self.assertRaises(ValueError):
            module_workflow.preview(server,'demo',self.ident,self.original.replace('blue','red').replace('WIDTH = 1','WIDTH = 3'),'a')
        self.assertEqual(self.module.read_text(),self.original)

    def test_shared_numeric_changes_have_reports_and_need_separate_acknowledgement(self):
        source=self.original+'\nVALUES = [1, 99]\n'
        for chart in ('a','b'):
            path=self.project/f'charts/{chart}.py'
            path.write_text(path.read_text().replace('from projects.demo.lib.theme import COLOR, WIDTH',
                'from projects.demo.lib.theme import COLOR, WIDTH, VALUES').replace('[1,2],color=COLOR','VALUES,color=COLOR'))
        self.module.write_text(self.original+'\nVALUES = [1, 2]\n')
        draft=module_workflow.preview(server,'demo',self.ident,source,'a',force_all=True)
        self.assertTrue(draft['requires_data_review'])
        self.assertEqual(len(draft['checks']),2)
        self.assertTrue(all(c['changed'] for c in draft['checks']))
        with self.assertRaisesRegex(ValueError,'明确确认'):
            module_workflow.apply(server,'demo',self.ident,draft['id'])
        self.assertIn('VALUES = [1, 2]',self.module.read_text())
        self.assertTrue(module_workflow.apply(server,'demo',self.ident,draft['id'],acknowledge_data_changes=True)['applied'])


class BundleCandidateTests(unittest.TestCase):
    def test_border_and_group_survive_relocation_and_render_as_real_candidates(self):
        for analysis in ('border','group'):
            with self.subTest(analysis=analysis),tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary);studio=root/'studio';studio.mkdir()
                for file in ('bundle_runtime.py','bundle_bindings.py'):
                    shutil.copy2(server.ROOT/file,studio/file)
                code=root/'runtime/behavior_analysis'
                (code/analysis).mkdir(parents=True)
                (code/'__init__.py').touch();(code/analysis/'__init__.py').touch()
                if analysis=='border':
                    code_source="""import matplotlib.pyplot as plt
def render_count_artifact(artifact, output_dir):
    fig,ax=plt.subplots()
    ax.plot(artifact['x'],artifact['y'],color='blue')
    ax.set(xlabel='Time',ylabel='Value')
    path=output_dir/'selected.png';fig.savefig(path);plt.close(fig)
    return [path]
render_eta_artifact=render_count_artifact
render_fate_artifact=render_count_artifact
render_roaming_dwell_artifact=render_count_artifact
"""
                    payload={'x':[0,1],'y':[1,2]}
                    spec={'theme':'counts','kind':'count_all','filename':'selected.png','payload':'data'}
                    key='data'
                else:
                    code_source="""import matplotlib.pyplot as plt
def visualize_group(result, output_dir, config=None, analysis_type=None):
    fig,ax=plt.subplots()
    ax.plot([0,1],result.metrics['lv_time'],color='blue')
    ax.set(xlabel='Time',ylabel='Value')
    path=output_dir/'selected.png';fig.savefig(path);plt.close(fig)
    return [path]
"""
                    payload={'lv_time':[1,2]}
                    spec={'kind':'linear_velocity_time','filename':'selected.png'}
                    key='metrics'
                (code/analysis/'visualization.py').write_text(code_source,encoding='utf-8',newline='\n')
                bundle=root/'input';bundle.mkdir()
                with gzip.open(bundle/'data.pkl.gz','wb') as stream:pickle.dump(payload,stream)
                (bundle/'plot_specs.json').write_text(json.dumps({'analysis':analysis,'plots':[spec]}),encoding='utf-8')
                def record(name):
                    data=(bundle/name).read_bytes()
                    return {'path':name,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}
                (bundle/'manifest.json').write_text(json.dumps({'format':'behavior-analysis-plot-bundle','version':1,
                    'analysis':analysis,'payloads':{key:record('data.pkl.gz')},'plot_specs':record('plot_specs.json')}),encoding='utf-8')
                result=import_plot_bundle(studio,bundle,project_id='demo',name='Demo',mode='upload',trusted=True,runtime_source=code.parent)
                project=studio/'projects/demo';make_portable(project,'embedded')
                self.assertNotIn(str(root), (project/'data_sources.json').read_text())
                moved=root/'other-computer/demo';moved.parent.mkdir();shutil.copytree(project,moved)
                approve(moved)
                chart=result['charts'][0];source=(moved/f'charts/{chart}.py').read_text()
                image=server.render(moved,source)
                self.assertTrue(image.startswith(b'\x89PNG'))
                report=render_candidate(moved,f'charts/{chart}.py',{f'charts/{chart}.py':source+'\n# candidate\n'},root/'candidate')
                self.assertEqual(report['data_report']['status'],'unchanged')
                self.assertTrue(Path(report['image_path']).is_file())
