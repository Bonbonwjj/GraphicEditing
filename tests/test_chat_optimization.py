"""Chart-only adapters, explicit shared handoff, and observed token accounting."""
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import server
from chat_agent import expand_compact_response, read_model_response, validate_response
from chat_harness import ChatHarness
from chat_module_route import module_handoff
from chat_parameters import propose_parameters
from chart_overrides import apply_chart_parameters
from tests.test_chat_parameters import context


SHARED = '''import matplotlib.pyplot as plt
def draw():
    fig, ax = plt.subplots(figsize=(6,4))
    ax.plot([0,1,2],[1,2,1], color='blue')
    ax.set_xlabel('Time'); ax.set_ylabel('Value')
    fig.subplots_adjust(bottom=.2,left=.2)
    return fig
'''
ENTRY = '''import os
from lib.draw import draw
def main():
    fig = draw()
    fig.savefig(os.environ['CHART_OUTPUT'], dpi=100)
if __name__ == '__main__':
    main()
'''


class LocalAdapterTests(unittest.TestCase):
    def test_function_entry_and_repeated_changes_consolidate_only_local_settings(self):
        q=context(ENTRY,'X轴标题字号改为14')
        first=propose_parameters(q)['proposed_files'][0]['content']
        second=propose_parameters(context(first,'Y轴标签字号改为16'))['proposed_files'][0]['content']
        self.assertEqual(second.count('from chart_overrides import'),1)
        self.assertIn("'xlabel_fontsize': 14.0",second)
        self.assertIn("'ylabel_fontsize': 16.0",second)
        self.assertIn('from lib.draw import draw',second)

    def test_multiple_axes_and_data_lines_are_not_guessed_at_runtime(self):
        import matplotlib.pyplot as plt
        fig,axes=plt.subplots(1,2)
        with self.assertRaisesRegex(ValueError,'唯一'):
            apply_chart_parameters(fig,{'xlabel_fontsize':14})
        plt.close(fig)
        fig,ax=plt.subplots();ax.plot([0,1],[1,2]);ax.plot([0,1],[2,3])
        with self.assertRaisesRegex(ValueError,'多个'):
            apply_chart_parameters(fig,{'line_color':'red'})
        plt.close(fig)

    def test_range_override_updates_explicit_spine_endpoints(self):
        import matplotlib.pyplot as plt
        fig,ax=plt.subplots();ax.spines['bottom'].set_bounds(0,1)
        apply_chart_parameters(fig,{'xlim':(0,4)})
        self.assertEqual(ax.get_xlim(),(0,4))
        self.assertEqual(ax.spines['bottom'].get_bounds(),(0,4))
        plt.close(fig)

    def test_shared_drawing_function_keeps_other_chart_and_module_unchanged(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary).resolve();project=root/'p'
            for directory in ('charts','lib'):(project/directory).mkdir(parents=True)
            (project/'project.json').write_text('{"name":"p"}')
            module=project/'lib/draw.py';module.write_text(SHARED)
            for chart in ('a','b'):(project/f'charts/{chart}.py').write_text(ENTRY)
            from local_execution import approve
            approve(project)
            with patch.object(server,'PROJECTS',root),patch('chat_harness.effective_model_config',return_value={'vision_enabled':False}), \
                 patch('chat_runner.inspect_chart_fonts',return_value={'fonts':[]}), \
                 patch('chat_harness.ChatHarness.call_agent',side_effect=AssertionError('No model needed')):
                harness=ChatHarness(server);session=harness.create('p',['a'])
                result=harness.turn('p',session['id'],{'user_message':'X轴标题字号改为14'})
                draft=result['drafts'][-1]
                self.assertEqual(draft['status'],'preview_ready',draft.get('reason'))
                self.assertEqual(result['turns'][-1]['results'][0]['model_attempts'],0)
                self.assertEqual(draft['data_report']['changed'],[])
                harness.draft_action('p',session['id'],draft['id'],'apply')
                self.assertEqual(module.read_text(),SHARED)
                self.assertEqual((project/'charts/b.py').read_text(),ENTRY)
                self.assertIn('_plot_forge_apply_parameters',(project/'charts/a.py').read_text())


class HandoffTests(unittest.TestCase):
    def test_declared_module_route_pins_scope_and_rejects_unknown_paths(self):
        q=context();q['shared_module_catalog']=[{'id':'module_1','path':'draw.py'}]
        q['project_chart_catalog']=[{'chart':'a'},{'chart':'b'}]
        result=module_handoff(q,{'status':'needs_shared_module','shared_module_path':'lib/draw.py'})
        self.assertEqual(result['affected_charts'],['a','b'])
        self.assertTrue(result['force_all'])
        for path in ('../secret.py','not_there.py'):
            with self.assertRaises(ValueError):
                module_handoff(q,{'status':'needs_shared_module','shared_module_path':path})
        with self.assertRaises(ValueError):
            module_handoff(q,{'status':'candidate','shared_module_path':'draw.py'})

    def test_shared_handoff_requires_no_file_edits_and_an_explicit_path(self):
        q=context()
        response={'status':'needs_shared_module','shared_module_path':'draw.py','reason':'共享函数内部决定图型。',
                  'interpreted_request':{},'intent_check':{'status':'needs_review'},'proposed_files':[]}
        self.assertEqual(validate_response(q,expand_compact_response(q,response))['status'],'needs_shared_module')
        response['proposed_files']=[{'path':'lib/draw.py','content':'changed'}]
        with self.assertRaises(ValueError):validate_response(q,response)

    def test_real_harness_routes_without_writing_shared_or_chart_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary).resolve();project=root/'p'
            for directory in ('charts','lib'):(project/directory).mkdir(parents=True)
            (project/'project.json').write_text('{"name":"p"}')
            (project/'lib/draw.py').write_text(SHARED)
            for chart in ('a','b'):(project/f'charts/{chart}.py').write_text(ENTRY)
            def agent(q):
                q['_model_attempt_budget']['used']+=1
                return expand_compact_response(q,{'status':'needs_shared_module','shared_module_path':'draw.py',
                    'reason':'需要调整共享绘图结构。','interpreted_request':{},'intent_check':{},'proposed_files':[]})
            with patch.object(server,'PROJECTS',root),patch('chat_harness.effective_model_config',return_value={'vision_enabled':False}), \
                 patch('chat_runner.inspect_chart_fonts',return_value={'fonts':[]}):
                harness=ChatHarness(server,agent=agent);session=harness.create('p',['a'])
                result=harness.turn('p',session['id'],{'user_message':'修改共享绘图结构'})
                outcome=result['turns'][-1]['results'][0]
                self.assertEqual(outcome['status'],'needs_shared_module')
                self.assertEqual(outcome['module_handoff']['affected_charts'],['a','b'])
                self.assertEqual(result['drafts'],[])
                self.assertEqual((project/'lib/draw.py').read_text(),SHARED)
                self.assertEqual((project/'charts/a.py').read_text(),ENTRY)


class TokenMetricsTests(unittest.TestCase):
    def test_usage_only_event_keeps_reported_counts_without_inventing_missing_values(self):
        events=[{'choices':[{'delta':{'content':'{}'},'finish_reason':'stop'}]},
                {'choices':[],'usage':{'prompt_tokens':100,'completion_tokens':30,'total_tokens':130,
                                      'completion_tokens_details':{'reasoning_tokens':20}}}]
        stream=io.BytesIO(b''.join(b'data: '+json.dumps(e).encode()+b'\n' for e in events)+b'data: [DONE]\n')
        metrics={}
        self.assertEqual(read_model_response(stream,1024,metrics=metrics),'{}')
        self.assertEqual(metrics,{'prompt_tokens':100,'completion_tokens':30,'total_tokens':130,'reasoning_tokens':20})
        metrics={}
        read_model_response(io.BytesIO(b'data: {"choices":[{"delta":{"content":"{}"},"finish_reason":"stop"}]}\n'),1024,metrics=metrics)
        self.assertEqual(metrics,{})
