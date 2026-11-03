import unittest
import tempfile
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from interactive_style import apply_interactive_style, upsert_style, read_style
from drawing_items import validate_items
from chat_runner import _one_render


class DrawingItemsTests(unittest.TestCase):
    def test_add_multiline_text_and_dashed_line_hide_and_restore(self):
        fig,axis=plt.subplots()
        self.addCleanup(plt.close,fig)
        base,=axis.plot([0,1],[1,2])
        items={'11111111':{'kind':'text','axis':0,'text':'First\nSecond','x':.5,'y':.7},
               '22222222':{'kind':'line','axis':0,'x':.2,'y':.4,'x2':.8,'y2':.4}}
        apply_interactive_style(fig,{'added_items':items,'component_styles':{'axes_0.line_1':{'linestyle':'dashed','color':'#ff0000'}}})
        self.assertEqual(axis.texts[0].get_text(),'First\nSecond')
        self.assertEqual(axis.lines[1].get_linestyle(),'--')
        self.assertEqual(base.get_ydata().tolist(),[1,2])
        apply_interactive_style(fig,{'added_items':items,'component_styles':{'axes_0.line_1':{'hidden':True},'axes_0.annotation_0':{'hidden':True}}})
        self.assertEqual(len(axis.lines),2)
        self.assertFalse(axis.lines[1].get_visible())
        self.assertFalse(axis.texts[0].get_visible())
        apply_interactive_style(fig,{'component_styles':{'axes_0.line_1':{'hidden':False}}})
        self.assertTrue(axis.lines[1].get_visible())

    def test_added_items_survive_source_and_isolated_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);project=root/'project';(project/'charts').mkdir(parents=True)
            source='import os\nimport matplotlib.pyplot as plt\nfig,ax=plt.subplots()\nax.plot([0,1],[1,2])\nfig.savefig(os.environ["CHART_OUTPUT"])\n'
            style={'added_items':{'aaaaaaaa':{'kind':'text','axis':0,'text':'Added\ntext','x':.5,'y':.8},'bbbbbbbb':{'kind':'line','axis':0,'x':.2,'y':.4,'x2':.7,'y2':.4}},'component_styles':{'axes_0.line_1':{'linestyle':'dotted'}}}
            source=upsert_style(source,style)
            self.assertEqual(read_style(source)['added_items'],style['added_items'])
            (project/'charts/one.py').write_text(source,encoding='utf-8')
            result=_one_render(project,'charts/one.py',{},root/'render')
            self.assertTrue(result['image_bytes'].startswith(b'\x89PNG'))
            self.assertTrue(any(t.get('added_id')=='aaaaaaaa' for t in result['layout_signature']['texts']))
            self.assertTrue(any(a.get('added_id')=='bbbbbbbb' for a in result['artists']))

    def test_reject_invalid_item_definitions(self):
        for spec in ({'kind':'code','axis':0},{'kind':'text','axis':-1},{'kind':'line','axis':0,'x':float('nan')}):
            with self.assertRaises(ValueError):validate_items({'aaaaaaaa':spec})
