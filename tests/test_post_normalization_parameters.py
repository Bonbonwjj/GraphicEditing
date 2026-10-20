import ast
import unittest
from unittest.mock import patch
import matplotlib.pyplot as plt
from chart_type_defaults import finish_converted_figure
from chat_parameters import parse_request,propose_parameters
from tests.test_chat_parameters import context

SOURCE="""from chart_type_defaults import finish_converted_figure as final
import os
import matplotlib.pyplot as plt
fig,ax=plt.subplots()
ax.plot([0,1],[1,2])
final(fig,os.environ['CHART_OUTPUT'])
"""
MESSAGE='我现在希望把这2个图的xy轴粗细调整一下，都细一些，粗细是现在的一半'


class PostNormalizationParametersTests(unittest.TestCase):
    def tearDown(self):plt.close('all')

    def test_batch_wording_and_compound_requests(self):
        self.assertEqual(parse_request(MESSAGE)['value'],.5)
        self.assertIsNone(parse_request(MESSAGE+'，删除第二组数据'))
        self.assertIsNone(parse_request('不要把XY轴线宽减半'))

    def test_repeated_edits_are_finalizer_parameters_not_pre_export_calls(self):
        first=propose_parameters(context(SOURCE,MESSAGE))
        self.assertIn("parameters={'spine_scale': 0.5}",first['proposed_files'][0]['content'])
        self.assertNotIn('_plot_forge_apply_parameters',first['proposed_files'][0]['content'])
        second=propose_parameters(context(first['proposed_files'][0]['content'],MESSAGE))
        self.assertIn("parameters={'spine_scale': 0.25}",second['proposed_files'][0]['content'])
        self.assertEqual(first['parameter_intent']['value'],.5)
        ast.parse(second['proposed_files'][0]['content'])

    def test_actual_override_runs_after_normalization_and_before_save(self):
        fig,ax=plt.subplots();line,=ax.plot([0,1],[1,2],lw=3.2)
        ax.spines['top'].set_visible(False);ax.spines['right'].set_visible(False)
        observed=[]
        def normalize(fig,template):
            for name in ('left','bottom'):ax.spines[name].set_linewidth(3.4)
            return {'warnings':[]}
        def save(*args,**kwargs):observed.append([ax.spines[name].get_linewidth() for name in ('left','bottom')])
        with patch('studio_style.normalize_figure_geometry',side_effect=normalize),patch.object(fig,'savefig',side_effect=save):
            finish_converted_figure(fig,'unused.png',parameters={'spine_scale':.5})
        self.assertEqual(observed,[[1.7,1.7]])
        self.assertEqual(line.get_linewidth(),3.2)
        self.assertFalse(ax.spines['top'].get_visible())

    def test_explicit_range_keeps_lower_tick_and_spine_after_normalization(self):
        intent=parse_request('这个图的y轴范围改为0.1～0.8')
        self.assertEqual(intent['value'],(.1,.8))
        result=propose_parameters(context(SOURCE,'这个图的y轴范围改为0.1～0.8'))
        self.assertIn("parameters={'ylim': (0.1, 0.8)}",result['proposed_files'][0]['content'])
        fig,ax=plt.subplots();ax.set_ylim(.1,.8);ax.set_yticks([.2,.4,.6,.8])
        def normalize(fig,template):
            ax.spines['left'].set_bounds(.2,.8)
            return {'warnings':[]}
        observed=[]
        def save(*args,**kwargs):observed.append((ax.get_ylim(),ax.get_yticks().tolist(),ax.spines['left'].get_bounds()))
        with patch('studio_style.normalize_figure_geometry',side_effect=normalize),patch.object(fig,'savefig',side_effect=save):
            finish_converted_figure(fig,'unused.png',parameters={'ylim':(.1,.8)})
        limits,ticks,bounds=observed[0]
        self.assertEqual(limits,(.1,.8));self.assertEqual(bounds,(.1,.8))
        self.assertEqual(len(ticks),5)
        for i,value in enumerate(ticks):self.assertAlmostEqual(value,.1+i*.175)

    def test_ranges_rebuild_equal_ticks_on_both_axes_and_keep_endpoints(self):
        from chart_type_defaults import _apply_final_parameters
        for key,limits in (('ylim',(.1,.8)),('xlim',(-.3,1.1)),('ylim',(0,1))):
            with self.subTest(key=key,limits=limits):
                fig,ax=plt.subplots();ax.plot([0,1],[0,1]);fig.canvas.draw()
                _apply_final_parameters(fig,{key:limits})
                ticks=getattr(ax,'get_'+key[0]+'ticks')()
                self.assertAlmostEqual(ticks[0],limits[0]);self.assertAlmostEqual(ticks[-1],limits[1])
                gaps=[b-a for a,b in zip(ticks,ticks[1:])]
                for gap in gaps:self.assertAlmostEqual(gap,gaps[0])

    def test_wrong_axis_width_is_reported_even_if_other_pixels_changed(self):
        from chat_harness import ChatHarness
        report={'visual_change':{'status':'changed'},
                'baseline_layout_signature':{'axes':[{'spine_linewidths':{'left':3.4,'bottom':3.4}}]},
                'layout_signature':{'axes':[{'spine_linewidths':{'left':3.4,'bottom':3.4}}]}}
        response={'parameter_intent':parse_request(MESSAGE)}
        issue=ChatHarness(None).visual_effect_issue({'user_message':MESSAGE},response,report)
        self.assertIn('目标 1.7 pt',issue)
