import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import project_preparation as prep
import universal_project
from chat_runner import CandidateRenderError


SOURCE = '''from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt

frame = pd.read_csv(Path("values.csv"))
fig, ax = plt.subplots()
ax.plot(frame.x, frame.y, color="blue")
fig.savefig("line.png", dpi=120)
fig2, ax2 = plt.subplots()
ax2.scatter(frame.x, frame.y, color="green")
plt.savefig("scatter.png", dpi=120)
'''


class UniversalProjectTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('PLOT_FORGE_REAL_UNIVERSAL')=='1','real isolated render opt-in')
    def test_configured_class_entry_bypasses_gui_main_and_uses_headless_backend(self):
        source=self.root/'configured';source.mkdir()
        (source/'plot.py').write_text('''import matplotlib
import matplotlib.pyplot as plt
import pandas as pd
matplotlib.use('TkAgg')
class Analyzer:
    def draw(self, data_path):
        data=pd.read_csv(data_path)
        fig,ax=plt.subplots()
        ax.plot(data.x,data.y)
        fig.savefig('result.png')
if __name__ == '__main__':
    raise RuntimeError('interactive main must not run')
''',encoding='utf-8')
        (source/'values.csv').write_text('x,y\n1,2\n2,4\n')
        opened=prep.open_project(self.projects,source,'configured')
        project=self.projects/opened['project']
        prep.write_json(project/'run-config.json',{'schema':'plot-forge-run/1','entries':[
            {'path':'plot.py','symbol':'Analyzer','method':'draw','kwargs':{'data_path':'values.csv'}}]})
        result=universal_project.prepare(project)
        self.assertTrue(result['can_open'])
        self.assertEqual(len(result['figures']),1)
        registry=json.loads((project/'universal-project.json').read_text())
        self.assertIn('values.csv',next(iter(registry['figures'].values()))['input_files'])

    @unittest.skipUnless(os.environ.get('PLOT_FORGE_REAL_UNIVERSAL')=='1','real isolated render opt-in')
    def test_real_large_input_copy_is_not_limited_to_png_size(self):
        source=self.root/'large-input';source.mkdir()
        (source/'draw.py').write_text('''from pathlib import Path
import matplotlib.pyplot as plt
with Path('large.csv').open('rb') as stream:
    stream.seek(40*1024*1024-1)
    assert stream.read(1) == b'\\0'
fig, ax = plt.subplots()
ax.plot([0, 1], [1, 2])
fig.savefig('figure.png')
''',encoding='utf-8')
        with (source/'large.csv').open('wb') as stream:
            stream.truncate(40*1024*1024)
        opened=prep.open_project(self.projects,source,'large-input')
        project=self.projects/opened['project']
        result=universal_project.prepare(project)
        self.assertTrue(result['can_open'])
        self.assertEqual(len(result['figures']),1)
        registry=json.loads((project/'universal-project.json').read_text())
        self.assertIn('large.csv',next(iter(registry['figures'].values()))['input_files'])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='universal-project-test-')
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.root = root
        self.projects = root/'app/projects';self.projects.mkdir(parents=True)
        self.source = root/'ordinary';self.source.mkdir()
        (self.source/'plot_results.py').write_text(SOURCE, encoding='utf-8')
        (self.source/'values.csv').write_text('x,y\n0,1\n1,3\n', encoding='utf-8')
        opened=prep.open_project(self.projects,self.source,'ordinary')
        self.project=self.projects/opened['project']

    def test_static_discovery_exposes_general_local_path(self):
        result=universal_project.discover(self.project)
        self.assertEqual([item['entry_path'] for item in result['candidates']],['plot_results.py'])
        self.assertEqual([item['kind'] for item in result['candidates'][0]['output_sites']],['savefig','savefig'])
        status=prep.status(self.project)
        self.assertTrue(status['universal_available'])
        self.assertEqual(status['universal_discovery']['candidate_count'],1)

    def test_inventory_accepts_data_over_two_gib_without_reading_it(self):
        large=self.source/'large.csv'
        with large.open('wb') as stream:
            stream.truncate(3*1024**3)
        _,files,_=prep.inventory(self.source)
        self.assertEqual(next(item['bytes'] for item in files if item['path']=='large.csv'),3*1024**3)

    def test_large_data_snapshot_does_not_count_towards_source_limit(self):
        from chat_runner import _snapshot
        data=self.project/'lib/universal/source'
        data.mkdir(parents=True)
        (data/'plot.py').write_text('pass\n')
        (data/'large.csv').write_text('x,y\n'+'1,2\n'*10000)
        ident='large_1'
        (self.project/'charts'/f'{ident}.py').write_text(universal_project.adapter_source(ident))
        prep.write_json(self.project/'universal-project.json',{
            'schema':universal_project.SCHEMA,'source_root':'lib/universal/source',
            'figures':{ident:{'entry_path':'plot.py','output_index':1,'source_files':['plot.py']}}})
        with patch('chat_runner.MAX_INPUT_BYTES',2000):
            hashes=_snapshot(self.project,self.root/'snapshot',{},entry=f'charts/{ident}.py')
        copied=self.root/'snapshot/lib/universal/source/large.csv'
        self.assertEqual(copied.read_bytes(),(data/'large.csv').read_bytes())
        self.assertEqual(hashes['lib/universal/source/large.csv'],'sha256:'+prep.sha(copied))
        import server
        from chat_harness import ChatHarness, scoped_plot_data
        (data/'large.csv').write_text('x,y\n'+'1,2\n'*100000)
        registry=json.loads((self.project/'universal-project.json').read_text())
        registry['figures'][ident]['input_files']=['large.csv']
        prep.write_json(self.project/'universal-project.json',registry)
        with patch.object(server,'PROJECTS',self.projects):
            files,_=ChatHarness(server).snapshot('ordinary',ident)
        csv_item=files['lib/universal/source/large.csv']
        self.assertLess(len(csv_item['content']),10000)
        self.assertEqual(csv_item['sha256'],'sha256:'+prep.sha(data/'large.csv'))
        self.assertEqual(csv_item['content_scope'],'truncated_sample')
        self.assertIsNone(csv_item['source_row_count'])
        # A reader mention makes the sample relevant but must not promote it
        # to a complete data table or invent a full row count.
        files['lib/universal/source/plot.py']['content']="pd.read_csv('large.csv')"
        model_data=scoped_plot_data(files,ident)
        self.assertEqual(model_data[0]['content_scope'],'truncated_sample')
        self.assertIsNone(model_data[0]['source_row_count'])

    def callable_project(self):
        source=self.root/'callable';source.mkdir()
        (source/'drawing.py').write_text('''import matplotlib.pyplot as plt
def any_function_name():
    fig, ax = plt.subplots()
    ax.bar([1, 2], [3, 4])
    return fig
''',encoding='utf-8')
        opened=prep.open_project(self.projects,source,'callable')
        return self.projects/opened['project']

    def test_discovery_does_not_require_build_or_main_function_names(self):
        project=self.callable_project()
        candidates=universal_project.discover(project)['candidates']
        self.assertEqual(candidates[0]['entry_symbol'],'any_function_name')
        self.assertTrue(candidates[0]['capture_return'])

    def orchestration_project(self):
        source=self.root/'orchestrated';(source/'scripts').mkdir(parents=True)
        (source/'scripts/main.py').write_text('''import argparse
from drawing import draw
if __name__ == '__main__':
    argparse.ArgumentParser().parse_args()
    draw('values.csv')
''',encoding='utf-8')
        (source/'scripts/drawing.py').write_text('''import pandas as pd
import matplotlib.pyplot as plt
def draw(path):
    frame=pd.read_csv(path)
    fig, ax=plt.subplots()
    ax.plot(frame.x, frame.y)
    fig.savefig('result.png')
''',encoding='utf-8')
        (source/'values.csv').write_text('x,y\n1,2\n2,4\n',encoding='utf-8')
        opened=prep.open_project(self.projects,source,'orchestrated')
        return self.projects/opened['project']

    def test_main_entry_follows_plotting_dependency(self):
        project=self.orchestration_project()
        candidates=universal_project.discover(project)['candidates']
        main=next(item for item in candidates if item['entry_path']=='scripts/main.py')
        self.assertEqual(main['runnable_evidence'],'main_guard_with_plot_dependency')

    @unittest.skipUnless(os.environ.get('PLOT_FORGE_REAL_UNIVERSAL')=='1','real isolated render opt-in')
    def test_real_subdirectory_import_argparse_and_data_binding(self):
        project=self.orchestration_project()
        result=universal_project.prepare(project)
        self.assertTrue(result['can_open'])
        figure=next(item for item in result['figures'] if item['original_entry']=='scripts/main.py')
        registry=json.loads((project/'universal-project.json').read_text())
        binding=registry['figures'][figure['figure_id']]
        self.assertIn('values.csv',binding['input_files'])
        self.assertIn('scripts/drawing.py',binding['source_files'])
        self.assertEqual((project/'lib/universal/source/values.csv').read_text(),'x,y\n1,2\n2,4\n')

    def test_prepare_splits_runtime_outputs_and_installs_only_reproducible_results(self):
        def render(project,entry,files,directory,strict_io=False,preview_dpi=None):
            registry=json.loads((Path(project)/'universal-project.json').read_text())
            ident=Path(entry).stem;index=registry['figures'][ident]['output_index']
            if index>2:
                raise CandidateRenderError(f'Selected plotting output {index} was not reached; observed 2')
            return {'output_count':1,'image_bytes':b'png-'+str(index).encode(),
                    'artists':[{'key':'axes_0.line_0','data_hash':'data-'+str(index),'visibility':{},'style':{}}],
                    'axes':[{'xlim':[0,1],'ylim':[1,3]}], 'render_size_px':[640,480],
                    'layout_signature':{'size_inches':[6.4,4.8]},'render_backend':'test','os_sandbox':True}
        with patch('chat_runner._one_render',side_effect=render):
            result=universal_project.prepare(self.project)
        self.assertEqual(result['status'],'ready')
        self.assertEqual(result['mode'],'universal')
        self.assertTrue(result['can_open'])
        self.assertEqual(sorted(path.name for path in (self.project/'charts').glob('*.py')),
                         ['plot_results_1.py','plot_results_2.py'])
        registry=json.loads((self.project/'universal-project.json').read_text())
        self.assertEqual([item['output_index'] for item in registry['figures'].values()],[1,2])
        self.assertTrue((self.project/'lib/universal/source/values.csv').is_file())
        validation=json.loads((self.project/'validation/universal.json').read_text())
        self.assertEqual(validation['state'],'passed')
        self.assertEqual(sum(item.get('render')=='passed' for item in validation['checks']),2)
        from panel_index import source_files
        chart=self.project/'charts/plot_results_1.py'
        chart.write_text(chart.read_text().replace('UNIVERSAL_SOURCE_EDITS = {}',
            'UNIVERSAL_SOURCE_EDITS = {"plot_results.py": [{"old": "color=\\"blue\\"", "new": "color=\\"red\\""}]}'))
        sources=source_files(self.project,'plot_results_1')
        original=next(value for path,value in sources.items() if path.endswith('/plot_results.py'))
        self.assertIn('color="red"',original)
        from panel_index import local_edit, effective_sources
        updated=local_edit(chart.read_text(),'plot_results.py','color="red"','color="purple"')
        effective=effective_sources({
            'charts/plot_results_1.py':updated,
            'lib/universal/source/plot_results.py':SOURCE})
        self.assertIn('color="purple"',effective['lib/universal/source/plot_results.py'])

    def test_verified_cache_reuses_outputs_and_invalidates_on_data_change(self):
        def render(project,entry,files,directory,**kwargs):
            registry=json.loads((Path(project)/'universal-project.json').read_text())
            index=registry['figures'][Path(entry).stem]['output_index']
            if index>1:
                raise CandidateRenderError(f'Selected plotting output {index} was not reached; observed 1')
            return {'output_count':1,'image_bytes':b'cached-image','artists':[],
                    'input_trace':['plot_results.py','values.csv']}
        with patch('chat_runner._one_render',side_effect=render) as renderer, \
                patch.object(prep,'install_verified',side_effect=OSError('installation interrupted')):
            with self.assertRaisesRegex(OSError,'installation interrupted'):
                universal_project.prepare(self.project)
            self.assertEqual(renderer.call_count,3)
        self.assertTrue((self.project/'.preparation/universal-cache').exists())
        with patch('chat_runner._one_render',side_effect=render) as renderer, \
                patch.object(prep,'install_verified',side_effect=OSError('installation interrupted')):
            with self.assertRaisesRegex(OSError,'installation interrupted'):
                universal_project.prepare(self.project)
            self.assertEqual(renderer.call_count,1)
            diagnostics=json.loads((self.project/'.preparation/universal-diagnostics.json').read_text())
            self.assertEqual(diagnostics['cache_hits'],1)
        csv_path=self.project/'.preparation/source/values.csv'
        csv_path.write_text('x,y\n0,5\n1,9\n')
        state=prep.read_state(self.project)
        item=next(item for item in state['files'] if item['path']=='values.csv')
        item.update(bytes=csv_path.stat().st_size,sha256=prep.sha(csv_path))
        prep.save_state(self.project,state)
        with patch('chat_runner._one_render',side_effect=render) as renderer:
            result=universal_project.prepare(self.project)
            self.assertEqual(renderer.call_count,3)
            self.assertEqual(result['universal_progress']['cache_hits'],0)
        self.assertFalse((self.project/'.preparation/universal-cache').exists())
        self.assertTrue((self.project/'charts/plot_results_1.py').is_file())
        self.assertTrue((self.project/'previews/plot_results_1.png').is_file())

    def test_failed_decomposition_preserves_per_entry_diagnostics(self):
        with patch('chat_runner._one_render',side_effect=CandidateRenderError('ModuleNotFoundError: missing_reader')):
            with self.assertRaisesRegex(ValueError,'missing_reader'):
                universal_project.prepare(self.project)
        report=json.loads((self.project/'.preparation/universal-diagnostics.json').read_text())
        self.assertEqual(report['checks'][0]['entry_path'],'plot_results.py')
        self.assertIn('missing_reader',report['checks'][0]['reason'])
        self.assertFalse(list((self.project/'charts').glob('*.py')))

    def test_identical_pixels_from_different_entries_do_not_drop_figures(self):
        source=prep.source_root(self.project)
        second=source/'another.py'
        second.write_text(SOURCE)
        state=prep.read_state(self.project)
        state['files'].append({'path':'another.py','kind':'code',
                               'bytes':second.stat().st_size,'sha256':prep.sha(second)})
        prep.save_state(self.project,state)
        def render(project,entry,files,directory,**kwargs):
            registry=json.loads((Path(project)/'universal-project.json').read_text())
            item=registry['figures'][Path(entry).stem]
            if item['output_index']>1:
                raise CandidateRenderError('Selected plotting output 2 was not reached; observed 1')
            return {'output_count':1,'image_bytes':b'same-pixels','artists':[],
                    'output_provenance':{'source_path':item['entry_path'],'line':8,'symbol':'<module>'}}
        with patch('chat_runner._one_render',side_effect=render):
            result=universal_project.prepare(self.project)
        self.assertEqual(len(result['figures']),2)
        self.assertEqual({item['original_entry'] for item in result['figures']},{'another.py','plot_results.py'})

    @unittest.skipUnless(os.environ.get('PLOT_FORGE_REAL_UNIVERSAL')=='1','real isolated render opt-in')
    def test_real_runtime_captures_two_outputs_with_relative_csv(self):
        result=universal_project.prepare(self.project)
        self.assertEqual(result['status'],'ready')
        self.assertEqual(len(result['figures']),2)
        registry=json.loads((self.project/'universal-project.json').read_text())
        self.assertTrue(all('values.csv' in item['input_files'] for item in registry['figures'].values()))
        passed=[item for item in result['validation']['checks'] if item.get('render')=='passed']
        self.assertTrue(all(item['output_provenance']['source_path']=='plot_results.py' for item in passed))
        for figure in result['figures']:
            image=self.project/'previews'/(figure['figure_id']+'.png')
            self.assertEqual(image.read_bytes()[:8],b'\x89PNG\r\n\x1a\n')
        import server
        first_source=(self.project/result['figures'][0]['entry_path']).read_text(encoding='utf-8')
        gallery=server.render(self.project,first_source)
        self.assertEqual(gallery[:8],b'\x89PNG\r\n\x1a\n')
        from chat_runner import render_candidate
        first=result['figures'][0]['figure_id']
        path='charts/'+first+'.py'
        original=(self.project/path).read_text(encoding='utf-8')
        edited=original.replace('def customize(figure):\n    pass',
            "def customize(figure):\n    for line in figure.axes[0].lines:\n        line.set_color('red')")
        report=render_candidate(self.project,path,{path:edited},self.root/'candidate',baseline_files={path:original})
        self.assertEqual(report['visual_change']['status'],'changed')
        self.assertEqual(report['data_report']['status'],'unchanged')

    @unittest.skipUnless(os.environ.get('PLOT_FORGE_REAL_UNIVERSAL')=='1','real isolated render opt-in')
    def test_real_runtime_captures_figure_returned_by_arbitrary_function(self):
        project=self.callable_project()
        result=universal_project.prepare(project)
        self.assertEqual(result['status'],'ready')
        self.assertEqual(len(result['figures']),1)
        self.assertIn('any_function_name',result['figures'][0]['figure_id'])


if __name__ == '__main__':
    unittest.main()
