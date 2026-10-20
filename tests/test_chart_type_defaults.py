import ast
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.axes import Axes
from chart_type_defaults import conversion_style,prepare_conversion_proposal,standard_violinplot,standard_boxplot
from chat_runner import _capture,_install_stat_capture
from chart_transform import verify_distribution


class ChartTypeDefaultsTests(unittest.TestCase):
    def tearDown(self):plt.close('all')

    def test_policy_uses_existing_profile_exactly_and_only_on_conversion(self):
        root=Path(__file__).resolve().parents[1]
        profile=json.loads((root/'skills/chart-normalization/assets/style-profile.v1.json').read_text())
        policy=conversion_style('改为小提琴图')
        self.assertEqual(policy['version'],profile['version'])
        self.assertEqual(policy['templates']['two_group_violin'],profile['chart_types']['two_group_violin'])
        self.assertEqual(policy['global'],profile['global'])
        for message in ('字大一点','不要改为小提琴图','不要改为散点图'):
            self.assertIsNone(conversion_style(message))
        self.assertEqual(conversion_style('改为散点图')['templates']['scatter']['marker_area_pt2'],100)
        self.assertEqual(conversion_style('换为热图')['templates']['heatmap']['colormap'],'preserve_source')

    def test_route_preserves_future_imports_unicode_and_is_repeatable(self):
        context={'user_message':'改为小提琴图'}
        code='"""中文"""\nfrom __future__ import annotations\nfig,ax=plt.subplots()\nvp=ax.violinplot(groups, positions=pos, widths=.9)\n'
        response={'status':'candidate','proposed_files':[{'path':'charts/a.py','content':code}]}
        first=prepare_conversion_proposal(context,response)
        second=prepare_conversion_proposal(context,first)
        source=second['proposed_files'][0]['content'];ast.parse(source)
        self.assertLess(source.index('from __future__'),source.index('from chart_type_defaults'))
        self.assertEqual(source.count('from chart_type_defaults'),1)
        self.assertNotIn('_pf_standard_violinplot(ax, ax',source)
        self.assertEqual(response['proposed_files'][0]['content'],code)
        explicit=prepare_conversion_proposal({'user_message':'改为小提琴图，宽度改为0.2'},first)
        self.assertIn("'width'",explicit['proposed_files'][0]['content'])

    def test_known_export_is_routed_to_normalization_without_duplicate_imports(self):
        source="from studio_style import finish_figure\nfig,ax=plt.subplots()\nvp=ax.violinplot(groups,positions=pos)\nfinish_figure(fig,os.environ['CHART_OUTPUT'])\n"
        response={'status':'candidate','proposed_files':[{'path':'charts/a.py','content':source}]}
        first=prepare_conversion_proposal({'user_message':'改为小提琴图'},response)
        second=prepare_conversion_proposal({'user_message':'改为小提琴图'},first)
        source=second['proposed_files'][0]['content'];ast.parse(source)
        self.assertEqual(source.count('import finish_converted_figure as'),1)
        self.assertIn("_pf_finish_converted_figure(fig, os.environ['CHART_OUTPUT']",source)
        self.assertEqual(second['chart_type_style']['routed_exports'],1)

    def test_violin_lines_follow_normalization_ratios_widths_and_connectors(self):
        rule=conversion_style('改为小提琴图')['templates']['two_group_violin']
        fig,ax=plt.subplots();groups=[[1,2,3,5,6],[2,3,5,7,8]]
        result=standard_violinplot(ax,groups,positions=[.82,1.18],widths=.9)
        self.assertEqual(len(ax.collections),10) # two bodies and four marks/group
        for i,g in enumerate(groups):
            marks=ax.collections[2+i*4:6+i*4];q1,med,q3=np.percentile(g,[25,50,75])
            spans=[np.ptp(mark.get_segments()[0][:,0]) for mark in marks[:3]]
            self.assertAlmostEqual(spans[1],spans[0]*2)
            self.assertAlmostEqual(spans[1],spans[2]*2)
            self.assertEqual([m.get_linewidths()[0] for m in marks],[2.4,3.1,2.4,2.4])
            np.testing.assert_allclose(marks[3].get_segments()[0][:,1],[q1,q3])
            self.assertAlmostEqual(np.ptp(result['bodies'][i].get_paths()[0].vertices[:,0]),rule['violin_width_x'])
        self.assertNotIn('cmedians',result) # no duplicate native bars

    def test_explicit_width_no_connector_and_box_statistical_choices_are_preserved(self):
        fig,ax=plt.subplots();groups=[[1,2,3,5,20],[2,3,5,7,8]]
        result=standard_violinplot(ax,groups,widths=.2,_style_overrides=['width','connector'])
        self.assertAlmostEqual(np.ptp(result['bodies'][0].get_paths()[0].vertices[:,0]),.2)
        self.assertEqual(len(ax.collections),8)
        fig,ax=plt.subplots();result=standard_boxplot(ax,groups,whis=(0,100),showfliers=False)
        self.assertEqual(result['fliers'],[])
        self.assertEqual(max(result['whiskers'][1].get_ydata()),20)

    def test_matching_two_group_marks_pass_full_sample_checks(self):
        originals={name:getattr(Axes,name) for name in ('boxplot','violinplot','bxp','violin')}
        try:
            _install_stat_capture(Axes)
            with tempfile.TemporaryDirectory() as temporary:
                project=Path(temporary);(project/'data').mkdir()
                raw=b'group,value\nA,1\nA,2\nA,5\nB,2\nB,3\nB,7\n'
                (project/'data/v.csv').write_bytes(raw)
                fig,ax=plt.subplots();ax.errorbar([.82,1.18],[2,3],yerr=[1,1]);ax.set_xticks([.82,1.18],['A','B']);fig.canvas.draw()
                before=_capture(fig,fig.canvas.get_renderer())
                fig,ax=plt.subplots();standard_violinplot(ax,[[1,2,5],[2,3,7]],positions=[.82,1.18]);ax.set_xticks([.82,1.18],['A','B']);fig.canvas.draw()
                after=_capture(fig,fig.canvas.get_renderer())
                report={'distribution_inputs':after['distribution_inputs'],'candidate_artists':after['artists'],
                        'baseline_layout_signature':before['layout_signature'],'layout_signature':after['layout_signature']}
                result=verify_distribution(project,'c',{'user_message':'改为小提琴图','plot_data':[{'path':'data/v.csv','sha256':hashlib.sha256(raw).hexdigest()}]},
                    {'read_data_refs':[{'path':'data/v.csv','columns':[{'name':'group','role':'group'},{'name':'value','role':'observation'}]}]},report)
                self.assertEqual(result['status'],'pass',result)
                self.assertEqual(len(result['statistic_overlays']),8)
        finally:
            for name,original in originals.items():setattr(Axes,name,original)
