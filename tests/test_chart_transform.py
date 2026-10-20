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
                'distribution_overlays':after['distribution_overlays'],
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

    def test_horizontal_conversion_keeps_group_and_unit_meaning(self):
        result=self.report()
        fig,ax=plt.subplots();ax.boxplot([[1,2,5],[2,3,7]],orientation='horizontal',patch_artist=True)
        ax.set_yticks([1,2],['A','B']);ax.set_xlabel('Score');fig.canvas.draw()
        after=_capture(fig,fig.canvas.get_renderer())
        result.update(distribution_inputs=after['distribution_inputs'],candidate_artists=after['artists'],layout_signature=after['layout_signature'])
        self.assertEqual(self.verify(result)['status'],'pass')

    def test_scatter_overlay_uses_all_the_same_samples(self):
        for last,expected in ((7,'pass'),(99,'fail')):
            result=self.report()
            fig,ax=plt.subplots();ax.boxplot([[1,2,5],[2,3,7]],patch_artist=True)
            ax.scatter([.9,1,1.1,1.9,2,2.1],[1,2,5,2,3,last])
            ax.set_xticks([1,2],['A','B']);ax.set_ylabel('Score');fig.canvas.draw()
            after=_capture(fig,fig.canvas.get_renderer())
            result.update(distribution_inputs=after['distribution_inputs'],candidate_artists=after['artists'],
                          layout_signature=after['layout_signature'],distribution_overlays=after['distribution_overlays'])
            self.assertEqual(self.verify(result)['status'],expected)

    def test_unsupported_source_is_unverified_instead_of_claiming_data_changed(self):
        self.proposal['read_data_refs']=[]
        self.assertEqual(self.verify(self.report())['status'],'unverified')

    def test_ambiguous_scatter_grouping_reports_unknown_instead_of_wrong_values(self):
        report=self.report();report['distribution_overlays']=[{'valid':False,'groups':[]}]
        result=self.verify(report)
        self.assertEqual(result['status'],'unverified')
        self.assertIn('无法唯一归组',result['reason'])

    def test_multi_panel_samples_are_anchored_to_each_original_panel(self):
        raw=b'panel_id,group,value,other\ndemo,A,1,10\ndemo,A,2,20\ndemo,A,5,50\ndemo,B,2,20\ndemo,B,3,30\ndemo,B,7,70\n'
        (self.project/'data/values.csv').write_bytes(raw)
        self.context['plot_data'][0]['sha256']='sha256:'+hashlib.sha256(raw).hexdigest()
        self.proposal['read_data_refs'][0]['columns'].append({'name':'other','role':'observation'})
        def captured(kind,swap=False):
            fig,axes=plt.subplots(1,2,figsize=(10,4))
            groups=[[[1,2,5],[2,3,7]],[[10,20,50],[20,30,70]]]
            if swap:groups.reverse()
            for ax,group in zip(axes,groups):
                getattr(ax,kind)(group);ax.set_xticks([1,2],['A','B']);ax.set_ylabel('Score')
            fig.canvas.draw();return _capture(fig,fig.canvas.get_renderer())
        before=captured('boxplot');self.context['user_message']='改为小提琴图'
        for swap,expected in ((False,'pass'),(True,'fail')):
            after=captured('violinplot',swap)
            report={'baseline_distribution_inputs':before['distribution_inputs'],'distribution_inputs':after['distribution_inputs'],
                    'candidate_artists':after['artists'],'baseline_layout_signature':before['layout_signature'],
                    'layout_signature':after['layout_signature']}
            self.assertEqual(self.verify(report)['status'],expected)
        report['baseline_distribution_inputs']=[]
        self.assertEqual(self.verify(report)['status'],'unverified')


    def test_violin_iqr_connectors_checked_against_complete_source_groups(self):
        import numpy as np
        self.context['user_message']='改为小提琴图'
        for horizontal,collection,wrong,hidden in ((False,False,False,False),(True,False,False,False),
                                                   (False,True,False,False),(False,False,True,False),
                                                   (False,False,False,True)):
            with self.subTest(horizontal=horizontal,collection=collection,wrong=wrong,hidden=hidden):
                report=self.report()
                fig,ax=plt.subplots();groups=[[1,2,5],[2,3,7]]
                if horizontal:
                    ax.violinplot(groups,orientation='horizontal',showmedians=True,quantiles=[[.25,.75]]*2)
                    ax.set_yticks([1,2],['A','B']);ax.set_xlabel('Score')
                else:
                    ax.violinplot(groups,showmedians=True,quantiles=[[.25,.75]]*2)
                    ax.set_xticks([1,2],['A','B']);ax.set_ylabel('Score')
                for i,g in enumerate(groups,1):
                    q1,q3=np.percentile(g,[25,75]);q3+=1 if wrong else 0
                    if collection:artist=ax.vlines(i,q1,q3)
                    elif horizontal:artist,=ax.plot([q1,q3],[i,i])
                    else:artist,=ax.plot([i,i],[q1,q3])
                    if hidden:artist.set_alpha(0)
                fig.canvas.draw();after=_capture(fig,fig.canvas.get_renderer())
                report.update(distribution_inputs=after['distribution_inputs'],candidate_artists=after['artists'],
                              layout_signature=after['layout_signature'])
                checked=self.verify(report)
                self.assertEqual(checked['status'],'unverified' if wrong or hidden else 'pass',checked)
                if wrong:self.assertIn('端点应为 Q1=',checked['reason'])
                if not wrong and not hidden:self.assertEqual(len(checked['statistic_overlays']),2)


if __name__=='__main__':unittest.main()
