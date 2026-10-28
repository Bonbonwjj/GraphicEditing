import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import panel_index
import chat_agent
from native_plot_runtime import _apply_source_edits, panel_axes
from tests.test_model_config import FakeStream


class PanelIndexTests(unittest.TestCase):
    def test_explicit_visible_mapping_keeps_compound_panels(self):
        text = 'PUBLIC_PANEL_MEMBERS={"a":["a","b"],"b":["c"],"c":["d"]}\n'
        index=panel_index.build_from_sources({'lib/native/fig4/code/render.py': text}, 'fig4')
        self.assertEqual([(p['id'],p['axis_labels']) for p in index['panels']], [('a',['a','b']),('b',['c']),('c',['d'])])
        self.assertEqual(index['panels'][0]['status'],'confirmed')
        unresolved=panel_index.build_from_sources({'charts/a.py':'ax.set_label("internal")\n'}, 'a')
        self.assertFalse(unresolved['panels'])
        self.assertTrue(unresolved['warning'])
        self.assertEqual(unresolved['axis_label_candidates'],['internal'])

    def test_conflicting_mappings_are_unresolved(self):
        index=panel_index.build_from_sources({'a.py':'PUBLIC_PANEL_MEMBERS={"a":["x"]}',
                                             'b.py':'PUBLIC_PANEL_MEMBERS={"a":["y"]}'},'figure')
        self.assertFalse(index['panels'])

    def test_large_source_excerpts_and_range_reads_preserve_full_local_source(self):
        source='PUBLIC_PANEL_MEMBERS={"a":["x"]}\n'+''.join(f'v{i}="'+('z'*160)+'"\n' for i in range(400))
        context={'source_files':[{'path':'charts/a.py','content':'pass\n','writable':True},
                    {'path':'lib/render.py','content':source,'writable':False}], 'plot_data':[]}
        context['panel_index']=panel_index.build_from_sources({'lib/render.py':source},'a')
        context['selected_panel']=context['panel_index']['panels'][0]
        compact=chat_agent.compact_model_context(context)
        self.assertTrue(compact['source_excerpts'])
        self.assertLessEqual(sum(len(e['content']) for e in compact['source_excerpts']),22000)
        self.assertEqual(context['source_files'][1]['content'],source)
        self.assertEqual(panel_index.read_range({'lib/render.py':source},{'path':'lib/render.py','start_line':399,'end_line':401}), ''.join(source.splitlines(keepends=True)[398:401]))
        for request in ({'path':'../../secret'}, {'path':'lib/render.py','start_line':1,'end_line':401}):
            with self.assertRaises(ValueError):panel_index.read_range({'lib/render.py':source},request)

    def test_local_edits_preserve_original_and_continue_from_effective_source(self):
        entry='"""entry"""\nfrom native_plot_runtime import prepare_native\nNATIVE_FIGURE="fig4"\ndef produce():\n    root=prepare_native(NATIVE_FIGURE)\n'
        first=panel_index.local_edit(entry,'code/render.py','color="blue"','color="red"')
        second=panel_index.local_edit(first,'code/render.py','color="red"','color="green"')
        original='color="blue"\n'
        sources={'charts/fig4.py':second,'lib/native/fig4/code/render.py':original}
        self.assertEqual(panel_index.effective_sources(sources)['lib/native/fig4/code/render.py'],'color="green"\n')
        self.assertEqual(sources['lib/native/fig4/code/render.py'], original)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'code').mkdir();target=root/'code/render.py';target.write_text(original)
            _apply_source_edits(root,{'code/render.py':[{'old':'color="blue"','new':'color="green"'}]})
            self.assertEqual(target.read_text(),'color="green"\n')
            for path in ('../outside.py','code/../../outside.py'):
                with self.assertRaises(ValueError):_apply_source_edits(root,{path:[]})
            with self.assertRaises(ValueError):_apply_source_edits(root,{'code/render.py':[{'old':'absent','new':'pass'}]})

    def test_panel_axes_resolves_labels_not_positions(self):
        from matplotlib.figure import Figure
        figure=Figure();c=figure.add_axes((.1,.1,.2,.2),label='c');a=figure.add_axes((.5,.5,.2,.2),label='a')
        self.assertEqual(panel_axes(figure,'b',{'b':['c']}),[c])
        self.assertEqual(panel_axes(figure,'a',{'a':['a','c']}),[c,a])
        with self.assertRaises(ValueError):panel_axes(figure,'x',{'x':['missing']})

    def test_model_requests_source_then_continues_in_same_turn(self):
        sources={'charts/a.py':'pass\n','lib/render.py':'def draw_panel():\n    return "real implementation"\n'}
        context={'user_message':'解释图a的代码','source_files':[{'path':p,'content':c,'writable':p.startswith('charts/')} for p,c in sources.items()],
                 'plot_data':[], 'allowed_write_paths':['charts/a.py'],
                 'panel_index':panel_index.build_from_sources(sources,'a'),
                 '_model_auth':{'api_key':'fake','api_url':'https://example.test/v1/chat/completions'}}
        response={'status':'needs_context','reason':'Need implementation','source_requests':[{'path':'render.py','start_line':'1','end_line':'999'}]}
        captured=[]
        def send(request,timeout):
            captured.append(json.loads(request.data))
            result=response if len(captured)==1 else {'status':'answer','message':'已读取实现','proposed_files':[]}
            return FakeStream(json.dumps(result))
        with patch.object(chat_agent.urllib.request,'urlopen',side_effect=send):
            result=chat_agent.propose(context)
        self.assertEqual(result['status'],'answer');self.assertEqual(len(captured),2)
        request=json.loads(captured[1]['messages'][-1]['content'])
        self.assertIn('real implementation',request['requested_source'][0]['content'])
        self.assertEqual(request['requested_source'][0]['end_line'],2)
        self.assertTrue(request['source_read_feedback'])

    def test_large_model_reads_page_and_bad_ranges_return_feedback(self):
        source=''.join(f'line_{i} = {i}\n' for i in range(700))
        reads,feedback,remaining=panel_index.model_source_reads({'lib/plot.py':source},[
            {'path':'plot.py','start_line':'1','end_line':'700'}])
        self.assertEqual([(r['start_line'],r['end_line']) for r in reads],[(1,240),(241,480),(481,700)])
        self.assertEqual(''.join(r['content'] for r in reads),source)
        self.assertFalse(remaining)
        for request in ({'path':'lib/plot.py','start_line':900,'end_line':1000},
                        {'path':'lib/plot.py','start_line':'wrong'}, {'path':'../../secret'}):
            reads,feedback,remaining=panel_index.model_source_reads({'lib/plot.py':source},[request])
            self.assertFalse(reads);self.assertTrue(feedback)
        reads,feedback,remaining=panel_index.model_source_reads({'lib/plot.py':source},[
            {'path':'lib/plot.py','start_line':1,'end_line':700}],budget=100)
        self.assertTrue(reads);self.assertTrue(remaining)
        self.assertLessEqual(sum(len(r['content']) for r in reads),100)

    def test_invalid_source_request_is_recoverable_within_model_budget(self):
        sources={'charts/a.py':'pass\n','lib/render.py':'def draw_panel():\n    return "real implementation"\n'}
        context={'user_message':'解释代码','source_files':[{'path':p,'content':c,'writable':p.startswith('charts/')} for p,c in sources.items()],
                 'plot_data':[], 'allowed_write_paths':['charts/a.py'],
                 'panel_index':panel_index.build_from_sources(sources,'a'),
                 '_model_auth':{'api_key':'fake','api_url':'https://example.test/v1/chat/completions'}}
        responses=[{'status':'needs_context','source_requests':[{'path':'lib/render.py','start_line':900,'end_line':1000}]},
                   {'status':'needs_context','source_requests':[{'path':'lib/render.py','symbol':'draw_panel'}]},
                   {'status':'answer','message':'已读取实现','proposed_files':[]}]
        captured=[]
        def send(request,timeout):
            captured.append(json.loads(request.data))
            return FakeStream(json.dumps(responses[len(captured)-1]))
        with patch.object(chat_agent.urllib.request,'urlopen',side_effect=send):
            result=chat_agent.propose(context)
        self.assertEqual(result['status'],'answer');self.assertEqual(result['model_attempts_used'],3)
        self.assertTrue(json.loads(captured[1]['messages'][-1]['content'])['source_read_feedback'])
        self.assertIn('real implementation',json.loads(captured[2]['messages'][-1]['content'])['requested_source'][0]['content'])

    def test_scope_check_warns_about_changes_outside_selected_panel(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);before=root/'before.png';after=root/'after.png'
            image=Image.new('RGB',(100,100),'white');image.save(before)
            image.putpixel((20,75),(255,0,0));image.save(after)
            signature={'axes':[{'axis_label':'d','bbox_px':[10,10,40,40]}]}
            report={'baseline_layout_signature':signature,'layout_signature':signature,
                    'baseline_image_path':str(before),'image_path':str(after)}
            self.assertEqual(panel_index.check_panel_scope(report,{'axis_labels':['d']})['status'],'pass')
            image.putpixel((80,20),(0,0,0));image.save(after)
            result=panel_index.check_panel_scope(report,{'axis_labels':['d']})
            self.assertEqual(result['status'],'review_required');self.assertIn('warning',result)
            self.assertEqual(panel_index.check_panel_scope(report,{'axis_labels':['missing']})['status'],'unverified')


if __name__=='__main__':unittest.main()
