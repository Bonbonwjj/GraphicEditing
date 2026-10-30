"""Synthetic local export -> validated project -> chat candidate -> backup/reopen."""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import numpy as np
import project_preparation as prep
from collaboration_sync import CollaborationSync

EXPORTER = '''# Complete synthetic exporter fixture. manifest.json is written by the test's local export capture.
def main():
    return None
'''
RENDERER = '''import json
import hashlib
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt

def list_figures(bundle_dir):
    manifest = json.loads((Path(bundle_dir)/'manifest.json').read_text())
    return [f['figure_id'] for f in manifest['figures']]

def render(bundle_dir, figure_id, output_path, style_overrides=None):
    root = Path(bundle_dir).resolve()
    manifest = json.loads((root/'manifest.json').read_text())
    if manifest['schema_version'] != '1.0' or figure_id not in list_figures(root):
        raise ValueError('Unknown schema or figure')
    for artifact in manifest['artifacts']:
        path = (root/artifact['path']).resolve()
        if not path.is_relative_to(root) or path.stat().st_size != artifact['bytes'] or hashlib.sha256(path.read_bytes()).hexdigest() != artifact['sha256']:
            raise ValueError('Invalid artifact')
    with np.load(root/'arrays/values.npz', allow_pickle=False) as data:
        x, y = data['x'], data['y']
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.plot(x, y, color='blue', linewidth=1.5)
    ax.set(xlabel='Time (s)', ylabel='Value', xlim=(-.2, 3.2), ylim=(.5, 2.5))
    fig.subplots_adjust(left=.18, bottom=.2, right=.94, top=.9)
    fig.savefig(output_path, dpi=120)
    plt.close(fig)
'''


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='plot-preparation-test-')
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.projects=self.root/'app/projects';self.projects.mkdir(parents=True)
        self.source=self.root/'research';self.source.mkdir()
        (self.source/'analysis.py').write_text('print("not executed during import")\n')
        (self.source/'values.csv').write_text('x,y\n0,1\n1,1.3\n2,1.6\n3,2\n')

    def open(self):
        result=prep.open_project(self.projects,str(self.source),'research')
        return self.projects/result['project']

    def plan(self,project):
        result={'status':'pending_local_run','mode':'extract','reason':'Synthetic reference test',
                'figures':[{'figure_id':'line','source_location':'analysis.py:1'}],
                'generated_files':[{'path':'analysis_export.py','role':'export_program','content':EXPORTER},
                                   {'path':'render_plot.py','role':'renderer','content':RENDERER}]}
        with patch('llm_client.chat',return_value=json.dumps(result)):
            return prep.analyze(project,True)

    def package(self):
        root=self.root/'plot-data';(root/'arrays').mkdir(parents=True);(root/'validation').mkdir()
        np.savez(root/'arrays/values.npz',x=np.array([0,1,2,3]),y=np.array([1.,1.3,1.6,2.]))
        reference={'figures':{'line':{'inputs':[{'artifact':'arrays/values.npz','key':'x','original':[0,1,2,3]},
                                             {'artifact':'arrays/values.npz','key':'y','original':[1.,1.3,1.6,2.]}]}}}
        prep.write_json(root/'validation/plot-inputs.json',reference)
        artifacts=[]
        for rel,kind in [('arrays/values.npz','npz'),('validation/plot-inputs.json','json')]:
            path=root/rel;artifacts.append({'path':rel,'format':kind,'sha256':prep.sha(path),'bytes':path.stat().st_size,'role':'plot_values'})
        manifest={'schema_version':'1.0','producer':{'program':'analysis_export.py','source_sha256':hashlib.sha256(EXPORTER.encode()).hexdigest(),'python':'3.11'},
            'figures':[{'figure_id':'line','renderer':'render_line','artifacts':['arrays/values.npz'],'expected_outputs':1}],
            'artifacts':artifacts,'validation':{'plot_input_reference':'validation/plot-inputs.json','numeric_rtol':0.,'numeric_atol':0.}}
        prep.write_json(root/'manifest.json',manifest)
        return root

    def test_import_no_execution_no_cloud_private_and_reopen_preserves_edits(self):
        (self.source/'.env').write_text('KEY=DO_NOT_COPY')
        (self.source/'credentials.json').write_text('{"token":"DO_NOT_COPY"}')
        with patch('llm_client.chat') as model:
            project=self.open();model.assert_not_called()
        self.assertEqual(prep.status(project)['status'],'needs_analysis')
        self.assertFalse((project/'.preparation/source/.env').exists())
        self.assertFalse((project/'.preparation/source/credentials.json').exists())
        self.assertEqual(CollaborationSync.files(self.projects),{})
        self.assertIn('/projects/research/',(self.projects.parent/'.gitignore').read_text())
        marker=project/'charts/custom.py';marker.write_text('# user edits')
        result=prep.open_project(self.projects,str(self.source),'research')
        self.assertTrue(result['reopened']);self.assertEqual(marker.read_text(),'# user edits')

    def test_name_collision_different_source_never_overwrites(self):
        self.open();other=self.root/'other';other.mkdir();(other/'analysis.py').write_text('pass')
        with self.assertRaisesRegex(ValueError,'来源不同'):prep.open_project(self.projects,str(other),'research')

    def test_older_standardizer_layout_is_restored_without_model(self):
        (self.source/'code/charts').mkdir(parents=True)
        (self.source/'code/charts/old.py').write_text('# preserved chart')
        (self.source/'project.json').write_text('{"name":"Old layout"}')
        (self.source/'images/original').mkdir(parents=True)
        (self.source/'images/original/old.png').write_bytes(b'original reference bytes')
        with patch('llm_client.chat') as model:
            result=prep.open_project(self.projects,str(self.source),'older',True)
            model.assert_not_called()
        self.assertEqual(result['status'],'ready')
        self.assertEqual((self.projects/'older/charts/old.py').read_text(),'# preserved chart')
        self.assertTrue(result['can_open'])
        self.assertEqual((self.projects/'older/images/original/old.png').read_bytes(),b'original reference bytes')

    def test_requires_egress_consent_and_never_trusts_model_ready(self):
        project=self.open()
        with patch('llm_client.chat') as model:
            with self.assertRaises(ValueError):prep.analyze(project,False)
            model.assert_not_called()
        with patch('llm_client.chat',return_value='{"mode":"extract","status":"ready"}'):
            with self.assertRaises(ValueError):prep.analyze(project,True)
        result=self.plan(project)
        self.assertEqual(result['status'],'pending_local_run')
        self.assertNotIn('content',result['generated_files'][0])
        self.assertEqual(list((project/'charts').glob('*.py')),[])
        self.assertEqual(prep.read_state(project)['status'],'pending_local_run')

    def test_needs_context_discards_untrusted_generated_files(self):
        project=self.open()
        with patch('llm_client.chat',return_value=json.dumps({'status':'needs_context','mode':None,'generated_files':[{'path':'../evil.py','content':'bad'}]})):
            result=prep.analyze(project,True)
        self.assertEqual(result['generated_files'],[])

    def test_interrupted_state_is_recoverable(self):
        project=self.open();prep.save_state(project,{**prep.read_state(project),'status':'working'})
        self.assertEqual(prep.status(project)['status'],'interrupted')

    def test_manifest_hash_path_traversal_symlink_and_value_mismatch_fail(self):
        bundle=self.package();manifest=json.loads((bundle/'manifest.json').read_text())
        prep.validate_package(bundle)
        for mutate in ('hash','path','values'):
            bad=copy.deepcopy(manifest)
            if mutate=='hash':bad['artifacts'][0]['sha256']='0'*64
            elif mutate=='path':bad['artifacts'][0]['path']='../escape.npz'
            else:
                ref=bundle/'validation/plot-inputs.json';values=json.loads(ref.read_text());values['figures']['line']['inputs'][1]['original'][0]=99
                prep.write_json(ref,values);bad['artifacts'][1].update(sha256=prep.sha(ref),bytes=ref.stat().st_size)
            prep.write_json(bundle/'manifest.json',bad)
            with self.assertRaises(ValueError):prep.validate_package(bundle)

    def test_unsafe_renderer_and_exporter_are_rejected(self):
        for source in (RENDERER+'\nopen("/tmp/unrelated", "w")\n', RENDERER.replace('import json','import socket'),
                       RENDERER.replace('allow_pickle=False','allow_pickle=True')):
            with self.assertRaises(ValueError):prep.validate_renderer(source)
        with self.assertRaises(ValueError):prep.validate_exporter('import requests\n')

    def test_package_symlink_is_rejected(self):
        bundle=self.package();artifact=bundle/'arrays/values.npz'
        original=self.root/'original.npz';artifact.rename(original)
        artifact.symlink_to(original)
        with self.assertRaisesRegex(ValueError,'符号链接'):prep.validate_package(bundle)

    def test_renderer_multiple_saves_never_mark_project_ready(self):
        project=self.open();self.plan(project);bundle=self.package()
        value=prep.read_state(project)
        value['generated_files'][1]['content']=RENDERER.replace('    plt.close(fig)','    fig.savefig(output_path, dpi=120)\n    plt.close(fig)')
        prep.save_state(project,value)
        with patch.dict(os.environ,{'PLOT_FORGE_RENDER_BACKEND':'local'}):
            with self.assertRaisesRegex(ValueError,'只输出选中的一张图'):prep.finalize(project,str(bundle),True)
        self.assertFalse((project/'charts/line.py').exists())

    def test_finalize_requires_review_and_matching_exporter(self):
        project=self.open();self.plan(project);bundle=self.package()
        with self.assertRaises(ValueError):prep.finalize(project,str(bundle),False)
        manifest=json.loads((bundle/'manifest.json').read_text());manifest['producer']['source_sha256']='0'*64;prep.write_json(bundle/'manifest.json',manifest)
        with self.assertRaisesRegex(ValueError,'本轮导出'):prep.finalize(project,str(bundle),True)
        self.assertFalse((project/'charts/line.py').exists())

    def test_direct_independent_entry_is_preserved_and_validated(self):
        from tests.test_chat_integration import SOURCE
        (self.source/'analysis.py').write_text(SOURCE)
        (self.source/'data').mkdir()
        (self.source/'data/values.csv').write_text('x,mean,sem\n0,1,.1\n1,1.3,.1\n2,1.6,.1\n3,2,.1\n')
        project=self.open()
        result={'mode':'direct','status':'ready','reason':'Already independent',
            'figures':[{'figure_id':'line','entry_path':'analysis.py','data_paths':['data/values.csv'],'helper_paths':[]}]}
        with patch('llm_client.chat',return_value=json.dumps(result)):
            plan=prep.analyze(project,True)
        self.assertEqual(plan['status'],'pending_local_run')
        with patch.dict(os.environ,{'PLOT_FORGE_RENDER_BACKEND':'local'}):
            completed=prep.finalize(project,'',True)
        self.assertEqual(completed['status'],'ready')
        self.assertEqual((project/'charts/line.py').read_text(),SOURCE)
        self.assertEqual(completed['validation']['checks'][0]['source'],'unchanged')

    def test_real_render_chat_edit_backup_and_reopen(self):
        project=self.open();self.plan(project);bundle=self.package()
        with patch.dict(os.environ,{'PLOT_FORGE_RENDER_BACKEND':'local'}):
            result=prep.finalize(project,str(bundle),True)
        self.assertEqual(result['status'],'ready')
        self.assertEqual(result['validation']['checks'][0]['inputs_compared'],2)
        self.assertTrue((project/'previews/line.png').read_bytes().startswith(b'\x89PNG'))
        import server
        from chat_harness import ChatHarness
        from chat_agent import ECHO_FIELDS
        contexts=[]
        def agent(context):
            contexts.append(context)
            source=next(f for f in context['source_files'] if f['writable'])
            return {**{k:context[k] for k in ECHO_FIELDS},'status':'candidate',
                'interpreted_request':{'operations':[{'operation_id':'color','target_chart_id':context['chart_id'],
                    'source_quotes':[context['user_message']],'target_element':'line','category':'visual styling',
                    'property':'color','current_value':'blue','desired_change':'red','disposition':'planned',
                    'evidence':[{'path':source['path'],'sha256':source['sha256'],'fact':'blue line'}]}],'preserve':['all plotted values']},
                'intent_check':{'status':'consistent','unresolved_items':[],'implementation_choices':['line color only']},
                'proposed_files':[{'path':source['path'],'base_sha256':source['sha256'],'content':source['content'].replace("color='blue'","color='red'")}],
                'read_data_refs':[{'path':d['path'],'sha256':d['sha256'],'columns':[{'name':k,'role':'plotted input'} for k in d['columns']]} for d in context['plot_data']],
                'reference_usage':[],'affected_chart_ids':[context['chart_id']],
                'expected_effects':[{'operation_id':'color','observable_change':'Red line','preservation_checks':['same x/y'],'verification_status':'unverified'}],
                'layout_policy':{'mode':'avoid_overlap','checks_requested':['whole figure']},'summary':'Blue to red','warnings':[]}
        with patch.object(server,'PROJECTS',self.projects),patch.dict(os.environ,{'PLOT_FORGE_RENDER_BACKEND':'local'}):
            harness=ChatHarness(server,agent=agent)
            session=harness.create('research',['line'])
            turned=harness.turn('research',session['id'],{'user_message':'Make the line red; keep all plotted values.'})
            self.assertEqual(turned['turns'][-1]['results'][0]['status'],'preview_ready',str(turned['turns'][-1]['results']))
            draft=turned['drafts'][-1]
            harness.draft_action('research',session['id'],draft['id'],'apply')
            self.assertIn("color='red'",(project/'charts/line.py').read_text())
            self.assertEqual(contexts[0]['plot_data'][0]['columns'],['x','y'])
            before=harness.snapshot('research','line')[1]
            data=project/'data/plot-data/arrays/values.npz';original=data.read_bytes();data.write_bytes(original+b'x')
            self.assertNotEqual(before,harness.snapshot('research','line')[1]);data.write_bytes(original)
        backup=prep.archive(project)
        with zipfile.ZipFile(io.BytesIO(backup)) as z:
            self.assertIn('research/code/charts/line.py',z.namelist())
            self.assertIn('research/data/plot-data/manifest.json',z.namelist())
            self.assertFalse(any('/.chat/' in p or '/.preparation/' in p for p in z.namelist()))
            restore=self.root/'restore';z.extractall(restore)
        with self.assertRaises(ValueError):prep.open_project(self.projects,str(restore/'research'),'restored')
        opened=prep.open_project(self.projects,str(restore/'research'),'restored',True)
        self.assertEqual(opened['status'],'ready')
        self.assertIn("color='red'",(self.projects/'restored/charts/line.py').read_text())

    def test_strict_extracted_renderer_denies_external_read(self):
        project=self.open();self.plan(project);bundle=self.package()
        value=prep.read_state(project)
        value['generated_files'][1]['content']=RENDERER.replace("root = Path(bundle_dir).resolve()", "root = Path(bundle_dir).resolve()\n    Path('/etc/passwd').read_text()")
        prep.save_state(project,value)
        with patch.dict(os.environ,{'PLOT_FORGE_RENDER_BACKEND':'local'}):
            with self.assertRaisesRegex(ValueError,'outside its package'):prep.finalize(project,str(bundle),True)
        self.assertEqual(prep.read_state(project)['status'],'pending_local_run')
        self.assertFalse((project/'charts/line.py').exists())


if __name__=='__main__':unittest.main()
