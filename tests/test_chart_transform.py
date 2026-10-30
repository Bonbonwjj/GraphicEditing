"""Chart conversion checks use complete source samples, not artist identity."""
import copy
import hashlib
from pathlib import Path
import tempfile
import unittest

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from chart_transform import requested_distribution, simple_distribution_request, verify_distribution
from chat_runner import _capture, _install_stat_capture


class ChartTransformTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.project=Path(self.temp.name).resolve();(self.project/'data').mkdir()
        raw=b'panel_id,group,value\ndemo,A,1\ndemo,A,2\ndemo,A,5\ndemo,B,2\ndemo,B,3\ndemo,B,7\nother,A,999\n'
        (self.project/'data/values.csv').write_bytes(raw)
        self.context={'user_message':'把这个图改为箱线图','plot_data':[{'path':'data/values.csv',
            'sha256':'sha256:'+hashlib.sha256(raw).hexdigest()}]}
        self.proposal={'read_data_refs':[{'path':'data/values.csv','columns':[
            {'name':'group','role':'group'},{'name':'value','role':'observation'}]}]}
        original={n:getattr(Axes,n) for n in ('boxplot','violinplot','bxp','violin')}
        self.addCleanup(lambda:[setattr(Axes,n,v) for n,v in original.items()])
        _install_stat_capture(Axes)
        self.addCleanup(plt.close,'all')

    def report(self,groups=None,mutate=False,labels=None,showfliers=True,kind='boxplot'):
        fig,ax=plt.subplots();ax.errorbar([1,2],[8/3,4],yerr=[.2,.3],fmt='o')
        ax.set_xticks([1,2],['A','B']);ax.set_ylabel('Score');fig.canvas.draw()
        before=_capture(fig,fig.canvas.get_renderer())
        fig,ax=plt.subplots()
        if kind=='boxplot':
            objects=ax.boxplot(x=groups or [[1,2,5],[2,3,7]],showfliers=showfliers,patch_artist=True)
            if mutate:objects['medians'][0].set_ydata([99,99])
        else:ax.violinplot(dataset=groups or [[1,2,5],[2,3,7]])
        ax.set_xticks([1,2],labels or ['A','B']);ax.set_ylabel('Score');fig.canvas.draw()
        after=_capture(fig,fig.canvas.get_renderer())
        return {'distribution_inputs':after['distribution_inputs'],'candidate_artists':after['artists'],
                'baseline_layout_signature':before['layout_signature'],'layout_signature':after['layout_signature']}

    def verify(self,report):return verify_distribution(self.project,'demo',self.context,self.proposal,report)

    def test_boxplot_from_complete_grouped_rows_passes_and_discloses_hidden_outliers(self):
        result=self.verify(self.report(showfliers=False))
        self.assertEqual(result['status'],'pass',result)
        self.assertEqual([g['count'] for g in result['matches'][0]['groups']],[3,3])
        self.assertTrue(any('不显示离群点' in w for w in result['warnings']))

    def test_violin_from_same_samples_passes(self):
        self.context['user_message']='将此图改成小提琴图'
        result=self.verify(self.report(kind='violinplot'))
        self.assertEqual(result['status'],'pass',result)

    def test_changed_values_missing_rows_and_swapped_groups_fail(self):
        for groups in ([[1,2,6],[2,3,7]],[[1,2],[2,3,7]],[[2,3,7],[1,2,5]]):
            with self.subTest(groups=groups):self.assertEqual(self.verify(self.report(groups))['status'],'fail')

    def test_mutating_statistics_or_group_labels_fails(self):
        self.assertEqual(self.verify(self.report(mutate=True))['status'],'fail')
        self.assertEqual(self.verify(self.report(labels=['B','A']))['status'],'fail')

    def test_data_file_change_is_rejected(self):
        report=self.report();(self.project/'data/values.csv').write_text('changed')
        self.assertEqual(self.verify(report)['status'],'fail')

    def test_ordinary_style_edits_do_not_gain_conversion_exception(self):
        for message in ('把线变粗','不要改为箱线图','Make this boxplot red.'):
            self.context['user_message']=message
            with self.subTest(message=message):self.assertIsNone(self.verify(self.report()))
        self.assertEqual(requested_distribution('Convert this chart to a boxplot.'),'boxplot')

    def test_missing_observation_capture_does_not_pass(self):
        report=self.report();report['distribution_inputs']=[]
        self.assertEqual(self.verify(report)['status'],'unverified')

    def test_boxplot_synonyms_and_conversion_only_detection(self):
        for word in ('箱型图','箱形图','箱线图','盒须图'):
            self.assertEqual(requested_distribution('把这2个图改为'+word),'boxplot')
            self.assertEqual(simple_distribution_request('把这2个图改为'+word),'boxplot')
        self.assertIsNone(simple_distribution_request('改为箱型图，颜色改成蓝色'))
        self.assertIsNone(simple_distribution_request('不要改为箱型图'))


if __name__=='__main__':unittest.main()
