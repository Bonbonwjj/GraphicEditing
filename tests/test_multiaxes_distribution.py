import copy
import unittest
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.axes import Axes
import numpy as np

from chat_runner import _capture,_install_stat_capture,compare_reports
from chart_transform import verify_distribution


class MultiAxesDistributionTests(unittest.TestCase):
    def setUp(self):
        originals={name:getattr(Axes,name) for name in ('boxplot','violinplot','bxp','violin')}
        self.addCleanup(lambda:[setattr(Axes,name,fn) for name,fn in originals.items()])
        self.addCleanup(plt.close,'all');_install_stat_capture(Axes)
        from component_groups import install_group_tracking
        install_group_tracking()

    def draw(self,kind,changed=False,paired_changed=False,annotation='***',other_changed=False,separate=False):
        fig,(left,right)=plt.subplots(1,2);left.set_label('paired');right.set_label('unrelated')
        values=[np.array([1,2,3,4,5.]),np.array([2,3,4,5,6.])]
        original=copy.deepcopy(values)
        if changed:values[0]=values[0][:-1]
        for i,(a,b) in enumerate(zip(*original)):
            left.plot([0,1],[a,b+(1 if paired_changed and i==0 else 0)],color='grey',alpha=.2)
        for i,value in enumerate(original):left.scatter(np.full(len(value),i),value)
        if kind=='boxplot':left.boxplot(values,positions=[0,1],patch_artist=True,showfliers=False)
        elif separate:
            for i,value in enumerate(values):left.violinplot([value],positions=[i],showmedians=True)
        else:left.violinplot(values,positions=[0,1],showmedians=True)
        left.plot([0,0,1,1],[6.5,7,7,6.5]);left.text(.5,7.2,annotation)
        left.set(xlim=(-.5,1.5),ylim=(0,8),ylabel='Score');left.set_xticks([0,1],['DIS','Others'])
        right.plot([0,1],[2,4 if other_changed else 3]);right.set(xlabel='Time',ylabel='Unrelated')
        fig.canvas.draw();return _capture(fig,fig.canvas.get_renderer())

    def report(self,**options):
        before=self.draw('boxplot');after=self.draw('violinplot',**options)
        return {'distribution_inputs':after['distribution_inputs'],'baseline_distribution_inputs':before['distribution_inputs'],
            'baseline_artists':before['artists'],'candidate_artists':after['artists'],
            'baseline_layout_signature':before['layout_signature'],'layout_signature':after['layout_signature'],
            'baseline_axis_details':before['axis_details'],'axis_details':after['axis_details'],
            'data_report':compare_reports(before,after)}

    def verify(self,report):return verify_distribution(Path('.'),'figure',{'user_message':'把箱型图改为小提琴图'}, {},report)

    def test_multiplot_conversion_keeps_full_samples_pairs_annotations_and_other_plot(self):
        result=self.verify(self.report());self.assertEqual(result['status'],'pass',result)
        self.assertEqual([group['count'] for group in result['matches']],[5,5])

    def test_separate_per_group_calls_match_same_original_arrays(self):
        result=self.verify(self.report(separate=True));self.assertEqual(result['status'],'pass',result)

    def test_native_finalize_hook_can_replace_marks_after_original_drawing(self):
        before=self.draw('boxplot');fig=plt.gcf();axis=fig.axes[0]
        for obj in list(axis.lines)+list(axis.patches):
            if getattr(obj,'_chat_semantic_data',{}).get('type')=='box_statistics':obj.remove()
        axis.violinplot([[1,2,3,4,5],[2,3,4,5,6]],positions=[0,1],showmedians=True)
        fig.canvas.draw();after=_capture(fig,fig.canvas.get_renderer())
        report={'distribution_inputs':after['distribution_inputs'],'baseline_distribution_inputs':before['distribution_inputs'],
            'baseline_artists':before['artists'],'candidate_artists':after['artists'],
            'baseline_layout_signature':before['layout_signature'],'layout_signature':after['layout_signature']}
        result=self.verify(report);self.assertEqual(result['status'],'pass',result)
        self.assertFalse(any('.box_' in group['key'] for group in after['component_groups']))

    def test_dropped_samples_broken_pairs_annotations_or_other_data_are_rejected(self):
        for options in ({'changed':True},{'paired_changed':True},{'annotation':'ns'},{'other_changed':True}):
            with self.subTest(options=options):
                result=self.verify(self.report(**options));self.assertEqual(result['status'],'fail',result)


if __name__=='__main__':unittest.main()
