import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from edit_contract import verify_requirements,finish_summary
from chat_parameters import propose_parameters,parse_requests
from tests.test_chat_parameters import context,SOURCE


def report():
    axis={'labels':['Time','Value'],'label_fontsizes':[10,10],'tick_fontsizes':[[10,10],[10,10]],
          'spine_linewidths':{'left':3.4,'bottom':3.4},'line_colors':['#0000ffff'],
          'legend':{'labels':['sample'],'loc':1,'fontsizes':[10]}}
    signature={'axes':[axis],'texts':[{'key':'xlabel','text':'Time','fontsize':10}]}
    return {'baseline_layout_signature':copy.deepcopy(signature),'layout_signature':copy.deepcopy(signature)}


class EditContractTests(unittest.TestCase):
    def test_changed_pixels_cannot_hide_unmet_width(self):
        r=report();r['visual_change']={'status':'changed'}
        result=verify_requirements('XY轴线宽减半',r)
        self.assertEqual(result['status'],'fail');self.assertTrue(result['blocking'])
        self.assertEqual(result['requirements'][0]['expected'],{'bottom':1.7,'left':1.7})

    def test_compound_width_and_range_do_not_assign_y_range_to_x(self):
        from chat_harness import ChatHarness
        message='XY轴线宽减半，同时Y轴范围改为0.1～0.8，其他不变'
        self.assertEqual(ChatHarness(None).axis_requirement(message),[{'axis':'y','lower':.1,'upper':.8,'ticks':False}])

    def test_font_color_and_legend_use_measured_values(self):
        for message in ('X轴标题字号改为12','刻度字号改为12','图例字号改为12','图例位置改为左上角','折线颜色改为红色','字大一点'):
            with self.subTest(message=message):
                result=verify_requirements(message,report())
                self.assertEqual(result['status'],'fail');self.assertTrue(result['blocking'])
        r=report();r['layout_signature']['axes'][0]['line_colors']=['#ff0000ff']
        self.assertEqual(verify_requirements('折线颜色改为红色',r)['status'],'pass')

    def test_unknown_intent_remains_reviewable_but_not_verified(self):
        result=verify_requirements('把图调整得更清楚，删除第二组',report())
        self.assertEqual(result['status'],'unverified');self.assertFalse(result['blocking'])
        r=report();r.pop('layout_signature')
        self.assertTrue(verify_requirements('X轴标题字号改为12',r)['blocking'])

    def test_compound_edits_are_atomic_and_do_not_drop_unsupported_clauses(self):
        message='X轴标题字号改为12，同时折线颜色改为红色'
        response=propose_parameters(context(message=message))
        code=response['proposed_files'][0]['content']
        self.assertIn("fontsize=12",code);self.assertIn("color='red'",code)
        self.assertEqual(len(response['interpreted_request']['operations']),2)
        self.assertEqual(response['proposed_files'][0]['base_sha256'],context()['source_files'][0]['sha256'])
        for text in ('X轴标题字号改为12，删除第二组','X轴标题字号改为12，同时X轴标题字号改为14','字大一点，刻度字号改为12'):
            self.assertIsNone(parse_requests(text))

    def test_preservation_request_catches_unrequested_style_change(self):
        r=report();r['layout_signature']['axes'][0]['label_fontsizes'][0]=12
        r['layout_signature']['axes'][0]['line_colors']=['#ff0000ff']
        result=verify_requirements('X轴标题字号改为12，其他不变',r)
        self.assertEqual(result['status'],'fail')
        self.assertEqual(result['requirements'][0]['status'],'pass')
        self.assertIn('line_colors',result['requirements'][-1]['actual'])

    def test_irregular_endpoint_tick_insertion_fails_final_export_checks(self):
        from chat_harness import ChatHarness
        r=report();axis={'xlim':[0,1],'ylim':[.1,.8],'yscale':'linear','numeric_yticks':True,
            'left_spine_bounds':[.1,.8],'left_spine_continuous':True,'left_spine_visible':True,
            'major_yticks':[.1,.2,.4,.6,.8]}
        r['axis_details']=[axis]
        result=verify_requirements('Y轴范围改为0.1～0.8',r)
        self.assertEqual(result['status'],'fail')
        self.assertIn('不均匀',ChatHarness(None).axis_requirement_issue({'user_message':'Y轴范围改为0.1～0.8'},r))
        axis['major_yticks']=[.1,.275,.45,.625,.8]
        self.assertEqual(verify_requirements('Y轴范围改为0.1～0.8',r)['status'],'pass')
        self.assertIsNone(ChatHarness(None).axis_requirement_issue({'user_message':'Y轴范围改为0.1～0.8'},r))
        self.assertEqual(verify_requirements('Y轴范围改为0.1～0.8',r)['requirements'][0]['tick_spacing']['intervals'],[.175]*4)

    def test_false_completion_is_replaced_by_measured_summary(self):
        draft={'status':'intent_unmet','summary':'已成功全部改好','reason':'字号没有变','edit_contract':{'status':'fail'}}
        finish_summary(draft)
        self.assertNotIn('成功',draft['summary']);self.assertEqual(draft['proposal_summary'],'已成功全部改好')

    def test_final_export_checks_and_history_without_model(self):
        import server
        from chat_harness import ChatHarness
        from local_execution import approve
        with tempfile.TemporaryDirectory(prefix='plot-contract-') as temp:
            root=Path(temp).resolve();project=root/'p';(project/'charts').mkdir(parents=True)
            (project/'project.json').write_text('{"name":"contract"}')
            (project/'charts/a.py').write_text(SOURCE);approve(project)
            with patch.object(server,'PROJECTS',root),patch('chat_harness.effective_model_config',return_value={'vision_enabled':False}),patch('chat_harness.ChatHarness.call_agent',side_effect=AssertionError('must not call model')):
                h=ChatHarness(server);s=h.create('p',['a'])
                result=h.turn('p',s['id'],{'user_message':'X轴标题字号改为12，同时折线颜色改为红色'})
                draft=result['drafts'][-1]
                self.assertEqual(draft['status'],'preview_ready',draft.get('reason'))
                self.assertEqual(draft['edit_contract']['status'],'pass')
                self.assertEqual(result['turns'][-1]['results'][0]['model_attempts'],0)
                self.assertEqual(h.history('p')[0]['drafts'][-1]['edit_contract'],draft['edit_contract'])
                h.draft_action('p',s['id'],draft['id'],'apply')
                self.assertIn("color='red'",(project/'charts/a.py').read_text())
