import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageChops

from chart_naming import RenderedImage
from chat_runner import _one_render
from interactive_style import upsert_style
from native_project import chart_source
from interactive_preview import render_preview


def fixture(root):
    project=root/'example'
    for folder in ('charts','lib/native/fig1/code','data/native/fig1/data'):(project/folder).mkdir(parents=True)
    (project/'native-project.json').write_text(json.dumps({'schema':'plot-forge-native/1','required_versions':{},
        'figures':{'fig1':{'save_file':'plot.py','save_function':'render'}}}),encoding='utf-8')
    (project/'data/native/fig1/data/values.json').write_text('[1,2,3,4,5]')
    (project/'lib/native/fig1/code/plot.py').write_text('''from pathlib import Path
import json
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.ticker import FuncFormatter
ROOT=Path(__file__).resolve().parents[1]
def render():
    values=json.loads((ROOT/'data/values.json').read_text())
    fig,ax=plt.subplots(figsize=(3,2),dpi=100)
    ax.boxplot([values],patch_artist=True)
    ax.plot([0,1],[1,3])
    ax.yaxis.set_major_formatter(FuncFormatter(lambda value,position:f'{value:.1f}'))
    ax.set(xlabel='Group',ylabel='Score')
    image=fig.add_axes([.78,.78,.1,.1]);image.imshow(np.arange(27).reshape(3,3,3)/26);image.set_axis_off()
    fig.savefig(ROOT/'output/figure.png',dpi=100)
''',encoding='utf-8')
    source=chart_source('fig1','import plot\nplot.render()')
    (project/'charts/fig1.py').write_text(source,encoding='utf-8')
    return project,source


class FastInteractiveWorkerTests(unittest.TestCase):
    def test_cached_image_hash_detects_in_place_pixel_changes(self):
        import numpy as np
        import matplotlib.pyplot as plt
        from chat_runner import _image_array_description, _number_array
        fig,axis=plt.subplots();self.addCleanup(plt.close,fig)
        image=axis.imshow(np.arange(12).reshape(3,4))
        original=_image_array_description(image,prime=True)
        self.assertEqual(original,_number_array(image.get_array()))
        image.get_array()[0,0]=99
        changed=_image_array_description(image)
        self.assertNotEqual(original['sha256'],changed['sha256'])
        self.assertEqual(changed,_number_array(image.get_array()))

    def test_replay_is_identical_to_full_render_and_does_not_accumulate_edits(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);project,source=fixture(root);entry='charts/fig1.py'
            baseline=_one_render(project,entry,{},root/'cold',capture_interactive_seed=True)
            seed=baseline['interactive_seed_bytes'];self.assertGreater(len(seed),100)
            style={'component_styles':{'axes_0':{'ylim':[-1,8]},'axes_0.box_0':{'edge_color':'#ff0000','width_scale':1.4}}}
            candidate=upsert_style(source,style)
            fast=_one_render(project,entry,{entry:candidate},root/'fast',interactive_seed=seed)
            full=_one_render(project,entry,{entry:candidate},root/'full')
            self.assertTrue(fast['interactive_seed_reused']);self.assertFalse(full['interactive_seed_reused'])
            for a,b in ((fast,full),(_one_render(project,entry,{},root/'reset',interactive_seed=seed),baseline)):
                aa=Image.open(io.BytesIO(a['image_bytes'])).convert('RGB');bb=Image.open(io.BytesIO(b['image_bytes'])).convert('RGB')
                self.assertEqual(aa.size,bb.size);self.assertIsNone(ImageChops.difference(aa,bb).getbbox())
                self.assertEqual([(r['key'],r['data_hash']) for r in a['artists']],[(r['key'],r['data_hash']) for r in b['artists']])
            (project/'data/native/fig1/data/values.json').write_text('[2,3,4,5,6]')
            with self.assertRaisesRegex(ValueError,'缓存与当前数据不一致'):
                _one_render(project,entry,{},root/'stale',interactive_seed=seed)


class FastInteractiveCacheTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.project,self.source=fixture(Path(self.temporary.name))
        self.calls=[]
        self.environment=patch('render_environment.describe',return_value={'fingerprint':'environment-1'})
        self.environment.start();self.addCleanup(self.environment.stop)

    def signature(self,project,source):
        data=(project/'data/native/fig1/data/values.json').read_text()
        return hashlib.sha256((data+source).encode()).hexdigest()

    def renderer(self,project,source,**options):
        self.calls.append(options)
        image=RenderedImage(b'png');image.render_report={'interactive_seed_reused':bool(options.get('interactive_seed'))}
        if options.get('capture_interactive_seed'): image.interactive_seed=b'opaque-worker-only-cache'
        return image

    def preview(self,style):
        return render_preview(self.project,'fig1',self.source,style,self.renderer,self.signature)

    def test_style_changes_reuse_cache_but_data_and_code_changes_rebuild(self):
        self.preview({'component_styles':{'axes_0':{'ylim':[0,4]}}})
        self.preview({'component_styles':{'axes_0':{'ylim':[0,8]}}})
        self.assertEqual(self.calls[0],{'capture_interactive_seed':True})
        self.assertEqual(self.calls[1],{'interactive_seed':b'opaque-worker-only-cache'})
        (self.project/'data/native/fig1/data/values.json').write_text('[2,3,4,5,6]')
        self.preview({});self.assertEqual(self.calls[-1],{'capture_interactive_seed':True})
        self.source=self.source.replace('def customize(figure):','def customize(figure):\n    figure.axes[0].set_title("new")')
        (self.project/'charts/fig1.py').write_text(self.source,encoding='utf-8')
        self.preview({});self.assertEqual(self.calls[-1],{'capture_interactive_seed':True})

    def test_cache_failure_falls_back_to_full_render(self):
        self.preview({})
        original=self.renderer
        def fail(project,source,**options):
            if options.get('interactive_seed'): raise ValueError('incompatible cached figure')
            return original(project,source,**options)
        result=render_preview(self.project,'fig1',self.source,{},fail,self.signature)
        self.assertFalse(result.render_report['interactive_seed_reused'])
        self.assertEqual(self.calls[-1],{'capture_interactive_seed':True})

    def test_data_change_during_preview_is_rejected(self):
        def change(project,source,**options):
            image=self.renderer(project,source,**options)
            (project/'data/native/fig1/data/values.json').write_text('[7,8,9]')
            return image
        with self.assertRaisesRegex(ValueError,'数据在预览期间发生变化'):
            render_preview(self.project,'fig1',self.source,{},change,self.signature)

    def test_regular_projects_keep_original_render_path(self):
        (self.project/'native-project.json').unlink()
        self.preview({});self.assertEqual(self.calls,[{}])


if __name__=='__main__':unittest.main()
