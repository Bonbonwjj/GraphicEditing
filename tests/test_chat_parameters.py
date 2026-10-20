"""Local parameter edits use real renders and the normal candidate/apply policy."""
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import server
from chat_harness import ChatHarness
from chat_parameters import propose_parameters


SOURCE = '''import os
import matplotlib.pyplot as plt
fig, ax = plt.subplots(figsize=(6, 4))
ax.plot([0, 1, 2, 3], [1, 2, 1, 2], color='blue', label='sample')
ax.set_xlabel('Time', fontsize=10)
ax.set_ylabel('Value', fontsize=10)
ax.set_xlim(0, 3)
ax.set_ylim(0, 3)
ax.legend(loc='upper right')
fig.subplots_adjust(left=.2, bottom=.2, right=.9, top=.9)
fig.savefig(os.environ['CHART_OUTPUT'], dpi=100)
plt.close(fig)
'''


def context(source=SOURCE, message='折线颜色改为红色'):
    return {'request_id':'r', 'edit_session_id':'s', 'turn_id':'t', 'chart_id':'c',
            'parent_draft_id':None, 'base_revision':'base', 'user_message':message,
            'allowed_write_paths':['charts/a.py'], 'plot_data':[],
            'source_files':[{'path':'charts/a.py', 'content':source,
                             'sha256':'sha256:'+hashlib.sha256(source.encode()).hexdigest()}]}


class ParameterScopeTests(unittest.TestCase):
    def test_ambiguous_requests_and_shared_helpers_fall_back(self):
        for message in ('把颜色改好看一点', '折线颜色改为红色，并删除第二组', '图例位置改为图外右侧'):
            self.assertIsNone(propose_parameters(context(message=message)))
        for source in (SOURCE.replace('ax.plot(', 'other.plot('),
                       SOURCE.replace("ax.legend(loc='upper right')", "ax.legend(loc='upper right', bbox_to_anchor=(1,1))"),
                       SOURCE.replace('fig, ax = plt.subplots(figsize=(6, 4))', 'fig, ax = plt.subplots(2, 1)'),
                       SOURCE.replace("ax.plot([0, 1, 2, 3], [1, 2, 1, 2], color='blue', label='sample')",
                                      "ax.plot(x, y, x2, y2, color='blue')")):
            message = '图例位置改为左上角' if 'bbox_to_anchor' in source else '折线颜色改为红色'
            self.assertIsNone(propose_parameters(context(source, message)))

    def test_dynamic_parameter_uses_chart_adapter_but_multiple_targets_fall_back(self):
        result=propose_parameters(context(SOURCE.replace("color='blue'", 'color=palette')))
        self.assertIn('color=palette',result['proposed_files'][0]['content'])
        self.assertIn('_plot_forge_apply_parameters',result['proposed_files'][0]['content'])
        self.assertIsNone(propose_parameters(context(SOURCE.replace("ax.set_xlabel", "ax.plot([0], [1], color='blue')\nax.set_xlabel"))))

    def test_unicode_offsets_preserve_code_and_data(self):
        response=propose_parameters(context(SOURCE.replace("ax.plot(", "'中文'; ax.plot(")))
        self.assertIsNotNone(response)
        edited=response['proposed_files'][0]['content']
        self.assertEqual(edited,SOURCE.replace("ax.plot(", "'中文'; ax.plot(").replace("color='blue'", "color='red'"))


class ParameterRenderTests(unittest.TestCase):
    def test_real_candidates_no_model_and_selected_chart_only_apply(self):
        with tempfile.TemporaryDirectory(prefix='plot-parameters-') as temp:
            root=Path(temp).resolve(); project=root/'p'
            (project/'charts').mkdir(parents=True)
            (project/'project.json').write_text('{"name":"parameters"}')
            (project/'shared_draw.py').write_text('# shared module must stay unchanged\n')
            for name in ('a','b'):
                (project/f'charts/{name}.py').write_text(SOURCE)
            from local_execution import approve
            approve(project)
            with patch.object(server,'PROJECTS',root), patch('chat_harness.effective_model_config',return_value={'vision_enabled':False}), \
                 patch('chat_runner.inspect_chart_fonts',side_effect=AssertionError('Fast parameters must skip a redundant font-only render')), \
                 patch('chat_harness.ChatHarness.call_agent',side_effect=AssertionError('must not call model')) as model:
                harness=ChatHarness(server)
                for message in ('X轴标题字号改为12', '折线颜色改为红色', '图例位置改为左上角', 'X轴范围改为0到4'):
                    with self.subTest(message=message):
                        session=harness.create('p',['a'])
                        result=harness.turn('p',session['id'],{'user_message':message})
                        self.assertEqual(result['turns'][-1]['results'][0]['model_attempts'],0)
                        draft=result['drafts'][-1]
                        self.assertEqual(draft['status'],'preview_ready',draft.get('reason'))
                        self.assertEqual(draft['generation_path'],'local_parameters')
                        self.assertEqual(draft['data_report']['changed'],[])
                        self.assertEqual(draft['data_report']['removed'],[])
                        self.assertNotEqual(draft['visual_change']['status'],'identical')
                        self.assertEqual((project/'charts/a.py').read_text(),SOURCE)
                harness.draft_action('p',session['id'],draft['id'],'apply')
                self.assertNotEqual((project/'charts/a.py').read_text(),SOURCE)
                self.assertEqual((project/'charts/b.py').read_text(),SOURCE)
                self.assertEqual((project/'shared_draw.py').read_text(),'# shared module must stay unchanged\n')
                no_op=harness.create('p',['a'])
                same=harness.turn('p',no_op['id'],{'user_message':'X轴范围改为0到4'})
                self.assertEqual(same['drafts'][-1]['status'],'already_compliant')
                self.assertEqual(same['turns'][-1]['results'][0]['model_attempts'],0)
                model.assert_not_called()
