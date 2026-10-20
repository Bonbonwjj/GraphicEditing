import copy
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from chat_parameters import propose_parameters,prepare_axis_range_proposal
from tests.test_chat_parameters import context,SOURCE


class ChatRangeDefaultsTests(unittest.TestCase):
    def test_plain_savefig_range_uses_equal_tick_adapter(self):
        response=propose_parameters(context(message='Y轴范围改为0.1～0.8'))
        self.assertIn('from axis_range_policy import',response['proposed_files'][0]['content'])
        self.assertIn("'ylim': (0.1, 0.8)",response['proposed_files'][0]['content'])

    def test_model_candidate_gets_range_policy_persisted_and_idempotent(self):
        ctx=context(message='Y轴范围改为0.1～0.8')
        proposal=propose_parameters(ctx)
        proposal['proposed_files'][0]['content']=SOURCE.replace('ax.set_ylim(0, 3)','ax.set_ylim(.1, .8)\nax.set_yticks([.1,.2,.4,.6,.8])')
        requirement=[{'axis':'y','lower':.1,'upper':.8}]
        fixed=prepare_axis_range_proposal(ctx,proposal,requirement)
        code=fixed['proposed_files'][0]['content']
        self.assertIn('from axis_range_policy import',code)
        again=prepare_axis_range_proposal(ctx,fixed,requirement)
        self.assertEqual(code,again['proposed_files'][0]['content'])
        self.assertEqual(fixed['proposed_files'][0]['base_sha256'],proposal['proposed_files'][0]['base_sha256'])

    def test_non_numeric_and_log_axes_keep_their_locators(self):
        import datetime
        import matplotlib.pyplot as plt
        from axis_range_policy import apply_chart_parameters
        for kind in ('category','date','log'):
            with self.subTest(kind=kind):
                fig,ax=plt.subplots()
                if kind=='category':ax.plot(['A','B','C'],[1,2,3])
                elif kind=='date':ax.plot([datetime.datetime(2026,1,1),datetime.datetime(2026,2,1)],[1,2])
                else:ax.plot([1,10,100],[1,2,3]);ax.set_xscale('log')
                locator=ax.xaxis.get_major_locator();limits=ax.get_xlim()
                apply_chart_parameters(fig,{'xlim':limits})
                self.assertIs(ax.xaxis.get_major_locator(),locator)
                plt.close(fig)

    def test_real_chat_local_and_model_paths_and_applied_replay(self):
        import server
        from chat_harness import ChatHarness
        from local_execution import approve
        with tempfile.TemporaryDirectory(prefix='chat-range-default-') as temp:
            root=Path(temp).resolve();project=root/'p';(project/'charts').mkdir(parents=True)
            (project/'project.json').write_text('{"name":"range"}')
            (project/'charts/a.py').write_text(SOURCE);approve(project)
            with patch.object(server,'PROJECTS',root),patch('chat_harness.effective_model_config',return_value={'vision_enabled':False}):
                h=ChatHarness(server);s=h.create('p',['a'])
                with patch.object(h,'agent',side_effect=AssertionError('local path must not call model')):
                    result=h.turn('p',s['id'],{'user_message':'Y轴范围改为0.1～0.8'})
                draft=result['drafts'][-1];self.assertEqual(draft['status'],'preview_ready',draft.get('reason'))
                self.assertTrue(draft['edit_contract']['requirements'][0]['tick_spacing']['equal'])
                def model(ctx):
                    canonical={**ctx,'user_message':'Y轴范围改为0.1～0.8'}
                    response=propose_parameters(canonical)
                    response['user_message']=ctx['user_message'];response['generation_path']='model'
                    for operation in response['interpreted_request']['operations']:operation['source_quotes']=[ctx['user_message']]
                    response['proposed_files'][0]['content']=SOURCE.replace('ax.set_ylim(0, 3)','ax.set_ylim(.1,.8)\nax.set_yticks([.1,.2,.4,.6,.8])')
                    return response
                s=h.create('p',['a'])
                with patch.object(h,'agent',side_effect=model):
                    result=h.turn('p',s['id'],{'user_message':'请将Y轴范围调整到0.1～0.8，保持其他内容'})
                draft=result['drafts'][-1]
                self.assertEqual(draft['status'],'preview_ready',draft.get('reason'))
                self.assertEqual(draft['proposal']['axis_range_policy'],'equal_numeric_linear_ticks')
                ticks=draft['axis_details'][0]['major_yticks']
                self.assertEqual(len(ticks),5)
                self.assertTrue(all(math.isclose(b-a,.175) for a,b in zip(ticks,ticks[1:])))
                h.draft_action('p',s['id'],draft['id'],'apply')
                self.assertIn('axis_range_policy',(project/'charts/a.py').read_text())
                s=h.create('p',['a'])
                with patch.object(h,'agent',side_effect=AssertionError('no model on replay')):
                    replay=h.turn('p',s['id'],{'user_message':'Y轴范围改为0.1～0.8'})
                self.assertEqual(replay['drafts'][-1]['status'],'already_compliant',replay['drafts'][-1].get('reason'))
                self.assertTrue(replay['drafts'][-1]['edit_contract']['requirements'][0]['tick_spacing']['equal'])
