import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

import native_project as native
import project_preparation as prep
from chat_runner import _one_render


class NativeProjectTests(unittest.TestCase):
    def test_snapshot_traverses_only_selected_figure_dependencies(self):
        from chat_runner import _snapshot
        with tempfile.TemporaryDirectory() as temp:
            project=Path(temp)/'project';output=Path(temp)/'snapshot'
            (project/'charts').mkdir(parents=True);output.mkdir()
            (project/'charts/fig1.py').write_text("NATIVE_FIGURE='fig1'")
            prep.write_json(project/'native-project.json',{'schema':'plot-forge-native/1','figures':{'fig1':{},'fig2':{}}})
            for kind in ('lib','data'):
                for figure in ('fig1','fig2'):
                    folder=project/kind/'native'/figure;folder.mkdir(parents=True)
                    (folder/('helper.py' if kind=='lib' else 'values.csv')).write_text('x=1')
            visited=[];original=Path.rglob
            def track(path,pattern):
                visited.append(path.relative_to(project).as_posix())
                return original(path,pattern)
            with patch.object(Path,'rglob',track):
                hashes=_snapshot(project,output,{},entry='charts/fig1.py')
            self.assertIn('lib/native/fig1',visited)
            self.assertNotIn('lib',visited)
            self.assertNotIn('data',visited)
            self.assertIn('lib/native/fig1/helper.py',hashes)
            self.assertFalse(any('/fig2/' in path for path in hashes))

    def test_selection_rejects_unknown_or_traversing_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp);(p/'charts').mkdir()
            prep.write_json(p/'native-project.json',{'schema':'plot-forge-native/1','figures':{'fig1':{},'../escape':{}}})
            entry='charts/one.py'
            for source in ["NATIVE_FIGURE='../escape'", "NATIVE_FIGURE='fig2'", 'pass']:
                with self.assertRaises(ValueError):native.selection(p,entry,{entry:source})
            self.assertEqual(native.selection(p,entry,{entry:"NATIVE_FIGURE='fig1'"}),'fig1')

    def test_local_execution_requires_consent_before_any_work(self):
        with patch.object(native,'prepare') as execute:
            with self.assertRaises(ValueError):native.start(Path('/unused'),False)
            execute.assert_not_called()

    def test_failed_figure_does_not_install_and_retry_reuses_verified_figure(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'original';source.mkdir()
            (source/'README.md').write_text('mini_DG 冻结 plotting package')
            profiles={key:('plot.py','render','import plot\nplot.render()') for key in ('fig1','fig2')}
            program='''from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt
ROOT=Path(__file__).resolve().parents[1]
def render():
    values=pd.read_csv(ROOT/'data/values.csv')
    fig,ax=plt.subplots(figsize=(2,2))
    ax.plot(values.x,values.y)
    fig.savefig(ROOT/'output/figure.png',dpi=80)
'''
            for key in profiles:
                folder=source/key
                for directory in ('code','data','reference'):(folder/directory).mkdir(parents=True)
                (folder/'run.py').write_text('# old independent entry')
                (folder/'code/plot.py').write_text(program)
                (folder/'data/values.csv').write_text('x,y\n1,3\n2,4\n')
                Image.new('RGB',(2,2),'white').save(folder/'reference'/(key+'.png'))
            broken=source/'fig2/code/plot.py'
            broken.write_text(program.replace('values=pd.read_csv',"raise ValueError('broken figure')\n    values=pd.read_csv"))
            with patch.object(native,'PROFILES',profiles),patch('llm_client.chat') as cloud:
                projects=root/'app/projects'
                value=prep.open_project(projects,str(source),'example')
                project=projects/value['project']
                with self.assertRaisesRegex(ValueError,'broken figure'):native.prepare(project,source)
                self.assertFalse(any((project/'charts').glob('*.py')))
                self.assertFalse(prep.can_open(project))
                self.assertTrue((project/'.preparation/native-cache/fig1.json').is_file())
                broken.write_text(program)
                with patch('chat_runner._one_render',wraps=_one_render) as render:
                    result=native.prepare(project,source)
                    self.assertEqual(render.call_count,1)
                self.assertTrue(result['can_open'])
                self.assertTrue(all(c['os_sandbox'] for c in result['validation']['checks']))
                self.assertEqual(sorted(p.stem for p in (project/'charts').glob('*.py')),['fig1','fig2'])
                for key in profiles:
                    self.assertEqual((project/'lib/native'/key/'code/plot.py').read_text(),program)
                    self.assertEqual((source/key/'data/values.csv').read_text(),'x,y\n1,3\n2,4\n')
                cloud.assert_not_called()


if __name__=='__main__':unittest.main()
