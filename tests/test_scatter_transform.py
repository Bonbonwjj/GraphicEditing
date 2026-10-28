"""Full-coordinate conversions, not sample-only or artist-index exceptions."""
import copy
import unittest

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from chart_transform import requested_scatter, verify_scatter, requested_line, verify_line
from chat_runner import _capture, compare_reports


class ScatterTransformTests(unittest.TestCase):
    def test_scatter_to_line_passes_without_data_review_false_positive(self):
        report=self.report()
        report['baseline_artists'],report['candidate_artists']=report['candidate_artists'],report['baseline_artists']
        result=verify_line({'user_message':'更改为折线图，横纵坐标加粗'},report)
        self.assertEqual(result['status'],'pass',result)
        self.assertEqual(result['kind'],'line')
        self.assertEqual([m['label'] for m in result['matches']],['Target','Hand'])
        changed=copy.deepcopy(report)
        changed['candidate_artists'][0]['point_signature']['sha256']='changed-point'
        self.assertEqual(verify_line({'user_message':'改为折线图'},changed)['status'],'fail')
        for message in ('不要改为折线图','折线图是什么','do not convert to line plot'):
            self.assertFalse(requested_line(message))
        self.assertIsNone(verify_line({'user_message':'加粗坐标轴'},report))

    def tearDown(self):
        plt.close('all')

    def report(self, change=None):
        captures=[]
        for candidate in (False, True):
            fig, ax=plt.subplots()
            x=np.arange(7, dtype=float)
            for i,label in enumerate(('Target','Hand')):
                y=x*(i+1)+1
                if candidate:
                    artist=ax.scatter(x,y,label=label,s=24)
                    if change:change(artist,i,ax)
                else:ax.plot(x,y,label=label)
            ax.set(xlabel='Time (s)',ylabel='Position',xlim=(-1,8),ylim=(0,15))
            ax.legend();fig.canvas.draw()
            captures.append(_capture(fig,fig.canvas.get_renderer()))
        before,after=captures
        return {'baseline_artists':before['artists'],'candidate_artists':after['artists'],
                'data_report':compare_reports(before,after),
                'unsupported_artists':before['unsupported_artists']+after['unsupported_artists'],
                'baseline_layout_signature':before['layout_signature'],'layout_signature':after['layout_signature']}

    def verify(self, report):
        return verify_scatter({'user_message':'将图变成scatter图'},report)

    def test_all_points_pass_and_candidate_can_continue(self):
        report=self.report();result=self.verify(report)
        self.assertEqual(result['status'],'pass',result)
        self.assertEqual([m['count'] for m in result['matches']],[7,7])
        from chat_harness import ChatHarness
        draft={'status':'preview_ready','image_path':'candidate.png','code':{'charts/a.py':'pass'},
               'data_report':report['data_report'],'chart_transform':result}
        self.assertTrue(ChatHarness.can_continue_draft(draft))
        draft['data_report']['status']='fail'
        self.assertFalse(ChatHarness.can_continue_draft(draft))

    def test_modified_unsampled_point_missing_point_and_reordering_fail(self):
        def alter(a,i,ax):
            points=a.get_offsets().copy();points[-1,1]+=1;a.set_offsets(points)
        def drop(a,i,ax):a.set_offsets(a.get_offsets()[:-1])
        def reorder(a,i,ax):a.set_offsets(a.get_offsets()[::-1])
        for fn in (alter,drop,reorder):
            with self.subTest(fn=fn.__name__):self.assertEqual(self.verify(self.report(fn))['status'],'fail')

    def test_swapped_groups_extra_and_hidden_points_rejected(self):
        def swap(a,i,ax):a.set_label(('Hand','Target')[i])
        def extra(a,i,ax):ax.scatter([1],[9],label='extra'+str(i))
        def hidden(a,i,ax):a.set_sizes([24]*6+[0])
        def transparent(a,i,ax):a.set_facecolor((1,0,0,0));a.set_edgecolor((1,0,0,0))
        def invisible_edge(a,i,ax):a.set_facecolor('none');a.set_linewidth(0)
        def empty_marker(a,i,ax):
            from matplotlib.path import Path
            a.set_paths([Path(np.empty((0,2)))])
        def transformed(a,i,ax):a.set_offset_transform(ax.transAxes)
        def masked(a,i,ax):
            points=a.get_offsets().copy();points[-1,1]=np.nan;a.set_offsets(points)
        for fn in (swap,extra,hidden,transparent,invisible_edge,empty_marker,transformed,masked):
            with self.subTest(fn=fn.__name__):self.assertNotEqual(self.verify(self.report(fn))['status'],'pass')

    def test_axes_annotations_unsupported_and_legacy_records_fail_closed(self):
        original=self.report()
        for key in ('axes','annotation','unsupported','legacy'):
            report=copy.deepcopy(original)
            if key=='axes':report['data_report']['axes_changes']=[{'changed':True}]
            if key=='annotation':report['layout_signature']['texts'][0]['text']='wrong units'
            if key=='unsupported':report['unsupported_artists']=['custom artist']
            if key=='legacy':report['baseline_artists'][0].pop('point_signature')
            with self.subTest(key=key):self.assertNotEqual(self.verify(report)['status'],'pass')

    def test_explicit_request_only(self):
        for message in ('将突变成scatter图','把折线改为散点图','Convert this chart to a scatter plot.'):
            self.assertTrue(requested_scatter(message),message)
        for message in ('不要把折线改成scatter图','散点图是什么','Make scatter points red',"Don't convert this to scatter"):
            self.assertFalse(requested_scatter(message),message)
        self.assertIsNone(verify_scatter({'user_message':'把线变粗'},self.report()))


if __name__=='__main__':unittest.main()
