import ast
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import matplotlib.pyplot as plt
from chart_overrides import apply_chart_parameters
from chat_parameters import parse_request,propose_parameters
from tests.test_chat_parameters import context
from tests.test_chat_parameters import SOURCE


class RelativeParameterTests(unittest.TestCase):
    def tearDown(self):plt.close('all')

    def test_plain_language_has_no_required_numeric_value(self):
        for message,key in (('把字放大一点','text_scale'),('文字小一点','text_scale'),
                            ('坐标轴粗一点','spine_scale'),('把X轴线加粗一些','xspine_scale'),
                            ('Y轴细一点','yspine_scale'),('X轴标题大一点','xlabel_scale')):
            with self.subTest(message=message):
                intent=parse_request(message)
                self.assertIsNotNone(intent)
                self.assertEqual(intent['setting'],key)
                self.assertTrue(intent['relative'])
        self.assertIsNone(parse_request('文字大一点，删除第二组数据'))

    def test_runtime_uses_actual_font_and_spine_values_without_changing_data(self):
        fig,ax=plt.subplots();line,=ax.plot([0,1],[1,2],linewidth=3)
        ax.set_xlabel('Time',fontsize=10);ax.set_ylabel('Value',fontsize=15)
        ax.spines['bottom'].set_linewidth(2);ax.spines['left'].set_linewidth(1)
        ax.spines['top'].set_visible(False)
        apply_chart_parameters(fig,{'text_scale':1.2,'spine_scale':1.2})
        self.assertAlmostEqual(ax.xaxis.label.get_fontsize(),12)
        self.assertAlmostEqual(ax.yaxis.label.get_fontsize(),18)
        self.assertAlmostEqual(ax.spines['bottom'].get_linewidth(),2.4)
        self.assertAlmostEqual(ax.spines['left'].get_linewidth(),1.2)
        self.assertFalse(ax.spines['top'].get_visible())
        self.assertEqual(line.get_linewidth(),3)
        self.assertEqual(list(line.get_ydata()),[1,2])

    def test_repeated_relative_changes_accumulate_and_keep_prior_settings(self):
        first=propose_parameters(context(message='字大一点'))
        self.assertIn('依据当前实际设置',first['summary'])
        code=first['proposed_files'][0]['content']
        second=propose_parameters(context(code,'字大一点'))
        code=second['proposed_files'][0]['content']
        calls=[n for n in ast.walk(ast.parse(code)) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='_plot_forge_apply_parameters']
        settings=ast.literal_eval(calls[0].args[1])
        self.assertAlmostEqual(settings['text_scale'],1.44)
        self.assertEqual(len(calls),1)
        third=propose_parameters(context(code,'坐标轴粗一点'))
        self.assertIn("'text_scale': 1.44",third['proposed_files'][0]['content'])
        self.assertIn("'spine_scale': 1.2",third['proposed_files'][0]['content'])

    def test_relative_font_request_also_scales_existing_absolute_override(self):
        code=propose_parameters(context(message='X轴标题字号改为14'))['proposed_files'][0]['content']
        code=propose_parameters(context(code,'字大一点'))['proposed_files'][0]['content']
        # Existing literal xlabel is 14; the runtime applies 1.2 to its actual value.
        self.assertIn('text_scale',code)
        code=propose_parameters(context(code,'X轴标题字号改为16'))['proposed_files'][0]['content']
        code=propose_parameters(context(code,'字大一点'))['proposed_files'][0]['content']
        self.assertIn("'xlabel_fontsize': 19.2",code)

    def test_real_multiturn_relative_edits_need_no_numeric_input_or_model(self):
        import server
        from chat_harness import ChatHarness
        from local_execution import approve
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary).resolve();project=root/'p';(project/'charts').mkdir(parents=True)
            (project/'project.json').write_text('{"name":"relative"}')
            source=SOURCE.replace('figsize=(6, 4)','figsize=(8, 6)').replace('ax.set_ylim(0, 3)','ax.set_ylim(0, 5)\nax.tick_params(pad=12)')
            for chart in ('a','b'):(project/f'charts/{chart}.py').write_text(source)
            approve(project)
            with patch.object(server,'PROJECTS',root),patch('chat_harness.effective_model_config',return_value={'vision_enabled':False}), \
                 patch('chat_runner.inspect_chart_fonts',side_effect=AssertionError('No redundant font render')), \
                 patch('chat_harness.ChatHarness.call_agent',side_effect=AssertionError('No model needed')):
                harness=ChatHarness(server);session=harness.create('p',['a'])
                for message,size in (('字大一点',12),('字大一点',14.4),('坐标轴粗一点',14.4)):
                    result=harness.turn('p',session['id'],{'user_message':message})
                    draft=result['drafts'][-1]
                    self.assertEqual(draft['status'],'preview_ready',str((message,draft.get('reason'),draft.get('layout'))))
                    self.assertEqual(result['turns'][-1]['results'][0]['model_attempts'],0)
                    self.assertAlmostEqual(draft['layout_signature']['axes'][0]['label_fontsizes'][0],size)
                    self.assertEqual(draft['data_report']['changed'],[])
                    self.assertEqual((project/'charts/a.py').read_text(),source)
                harness.draft_action('p',session['id'],draft['id'],'apply')
                self.assertEqual((project/'charts/b.py').read_text(),source)
