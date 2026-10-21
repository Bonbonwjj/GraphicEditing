import copy
import hashlib
from pathlib import Path
import tempfile
import unittest

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from paired_plot import (prepare_paired_data,draw_paired_plot,discover_contract,
                         verify_paired,scope_mismatch,resolve_optional_reference_items)
from chat_runner import _capture,render_candidate


class PairedPlotTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.project=Path(self.temp.name);(self.project/'data').mkdir();(self.project/'charts').mkdir()
        self.table=pd.DataFrame([('demo','A','s2',.3),('demo','A','s1',.2),('demo','A','s3',.4),
                                 ('demo','B','s1',.25),('demo','B','s2',.35),('demo','B','s4',.45),
                                 ('other','A','s1',70000),('other','B','s1',240000)],
                                columns=['panel_id','group_label','subject_id','value'])
        self.path=self.project/'data/values.csv';self.table.to_csv(self.path,index=False)
        self.context={'user_message':'改为配对连线半小提琴图','plot_data':[{'path':'data/values.csv','sha256':hashlib.sha256(self.path.read_bytes()).hexdigest()}]}
        self.context['paired_plot_data']=discover_contract(self.project,'demo',self.context['plot_data'])
        self.data=self.prepare(self.table)
        self.addCleanup(plt.close,'all')

    def prepare(self,table):return prepare_paired_data(table,chart='demo',groups=['A','B'])

    def report(self,mutate=None,half=True,connect=True):
        fig,ax=plt.subplots(figsize=(5.4,4.8));ax.set_ylabel('Rate')
        ax.set_xticks([0,1],['A','B']);ax.text(.5,.5,'P = 0.04')
        fig.canvas.draw();before=_capture(fig,fig.canvas.get_renderer())
        record=draw_paired_plot(ax,self.data,half_violin=half,connect=connect)
        if mutate:mutate(ax,record)
        fig.canvas.draw();after=_capture(fig,fig.canvas.get_renderer())
        return {'paired_plots':after['paired_plots'],'candidate_artists':after['artists'],
                'layout_signature':after['layout_signature'],'baseline_layout_signature':before['layout_signature']}

    def verify(self,report,proposal=None):return verify_paired(self.project,'demo',self.context,proposal or {},report)

    def test_scope_unique_pair_alignment_and_unmatched_samples(self):
        self.assertEqual([len(g) for g in self.data['samples']],[3,3])
        self.assertEqual(self.data['paired_ids'],['s1','s2'])
        self.assertEqual(self.data['paired_values'],[[.2,.25],[.3,.35]])
        self.assertEqual(self.data['unpaired_counts'],[1,1])
        self.assertEqual(self.context['paired_plot_data']['expected']['pair_count'],2)

    def test_duplicates_rejected_after_filtering_not_in_other_metrics(self):
        self.prepare(self.table)  # same ID in another metric is valid
        with self.assertRaisesRegex(ValueError,'不唯一'):
            self.prepare(pd.concat([self.table,self.table.iloc[[0]]]))

    def test_missing_id_nonfinite_and_missing_metric_rejected(self):
        for col,value in [('subject_id',None),('value',float('nan')),('value',float('inf'))]:
            changed=self.table.copy();changed.loc[0,col]=value
            with self.subTest(col=col,value=value),self.assertRaises(ValueError):self.prepare(changed)
        with self.assertRaisesRegex(ValueError,'没有逐条样本'):
            prepare_paired_data(self.table,chart='missing',groups=['A','B'])

    def test_visible_half_violins_and_exact_pairs_pass(self):
        report=self.report();result=self.verify(report)
        self.assertEqual(result['status'],'pass',result)
        self.assertTrue(report['paired_plots'][0]['density_visible'])
        self.assertEqual(result['matches'][0]['pair_count'],2)
        self.assertTrue(result['warnings'])

    def test_shuffled_rows_keep_pair_identity(self):
        from paired_plot import signature
        shuffled=self.prepare(self.table.sample(frac=1,random_state=42))
        self.assertEqual(signature(shuffled),signature(self.data))

    def test_mutated_points_lines_hidden_density_and_extra_artists_block(self):
        cases=[lambda ax,r:r['lines'][0].set_ydata([.1,.9]),
               lambda ax,r:r['points'][0].set_offsets([[0,.8]]),
               lambda ax,r:r['bodies'][0].set_visible(False),
               lambda ax,r:ax.set_ylim(0,250000),
               lambda ax,r:ax.scatter([.5],[.8])]
        for mutate in cases:
            with self.subTest(mutate=mutate):self.assertNotEqual(self.verify(self.report(mutate))['status'],'pass')

    def test_source_pair_identity_unit_and_stat_annotation_changes_block(self):
        original=self.report()
        for field in ('pairs_sha256','pair_count'):
            report=copy.deepcopy(original);report['paired_plots'][0]['signature'][field]='wrong'
            self.assertEqual(self.verify(report)['status'],'fail')
        self.assertEqual(self.verify(self.report(lambda ax,r:ax.set_ylabel('Other unit')))['status'],'fail')
        self.assertEqual(self.verify(self.report(lambda ax,r:ax.text(.5,.8,'P < 0.001')))['status'],'fail')
        self.path.write_text('changed')
        self.assertEqual(self.verify(original)['status'],'fail')

    def test_paired_scatter_uses_same_pipeline(self):
        self.assertEqual(self.verify(self.report(half=False))['status'],'pass')

    def test_horizontal_spacing_is_allowed_when_values_and_pair_endpoints_remain(self):
        def shift(ax,record):
            for group,point in enumerate(record['points']):
                offsets=point.get_offsets().copy();offsets[:,0]+=[-.06,.06][group];point.set_offsets(offsets)
            for line in record['lines']:line.set_xdata(np.asarray(line.get_xdata())+[-.06,.06])
        report=self.report(shift)
        self.assertFalse(report['paired_plots'][0]['geometry_unchanged'])
        self.assertTrue(report['paired_plots'][0]['values_unchanged'])
        self.assertEqual(self.verify(report)['status'],'pass')

    def test_moving_dots_without_their_paired_endpoints_still_fails(self):
        def shift(ax,record):
            offsets=record['points'][0].get_offsets().copy();offsets[:,0]-=.06;record['points'][0].set_offsets(offsets)
        result=self.verify(self.report(shift))
        self.assertEqual(result['status'],'fail');self.assertIn('端点',result['reason'])

    def test_explicit_independent_groups_cannot_gain_paired_lines(self):
        self.context['user_message']='两组独立，没有配对关系，参照图修改样式'
        self.assertEqual(self.verify(self.report())['status'],'fail')

    def test_reference_density_appearance_is_advisory_but_pairs_are_checked(self):
        self.context['reference_images']=[{'reference_id':'r'}]
        report=self.report(lambda ax,r:ax.set_ylim(0,250000))
        result=self.verify(report)
        self.assertEqual(result['status'],'pass',result)
        self.assertTrue(result['warnings'])
        self.assertEqual(self.verify(self.report(lambda ax,r:r['lines'][0].set_ydata([0,9])))['status'],'fail')

    def test_reference_label_and_annotation_differences_can_continue(self):
        self.context['reference_images']=[{'reference_id':'r'}]
        result=self.verify(self.report(lambda ax,r:(ax.set_xticks([]),ax.text(.5,.8,'P = 0.04'))))
        self.assertEqual(result['status'],'presentation_review')
        self.assertTrue(result['data_integrity_verified'])
        from chat_harness import ChatHarness
        draft={'image_path':'candidate.png','code':{'chart.py':'draw()'},'status':'needs_clarification',
               'review_blocker':'paired_presentation','chart_transform':result,
               'data_report':{'status':'review_required','changed':[{'key':'line'}]}}
        self.assertTrue(ChatHarness.can_continue_draft(draft))
        self.assertTrue(ChatHarness.can_apply_after_reference_review(draft))
        draft['reference_features']={'features':[{'feature_id':'f1'}]}
        draft['reference_comparison']={'status':'unverified'}
        self.assertTrue(ChatHarness.can_apply_after_reference_review(draft))
        draft['data_report']['status']='fail'
        self.assertTrue(ChatHarness.can_continue_draft(draft))
        self.assertTrue(ChatHarness.can_apply_after_reference_review(draft))

    def test_no_id_overlap_can_show_distributions_but_not_connections(self):
        self.table.loc[self.table.group_label.eq('B'),'subject_id']=['u1','u2','u3','u4']
        self.data=self.prepare(self.table)
        fig,ax=plt.subplots()
        with self.assertRaisesRegex(ValueError,'没有可一一对应'):draw_paired_plot(ax,self.data)
        draw_paired_plot(ax,self.data,connect=False)

    def test_cross_metric_counts_have_specific_diagnostic(self):
        report={'candidate_artists':[{'kind':'scatter','data':{'offsets':{'shape':[1425,2]}}}]*2}
        result=scope_mismatch(self.context,report)
        self.assertEqual(result['code'],'source_scope_mismatch');self.assertIn('[3, 3]',result['reason'])
        from chat_diagnostics import explain_draft
        self.assertEqual(explain_draft({'status':'validation_failed','chart_transform':result,'reason':result['reason']})[0]['code'],'source_scope_mismatch')

    def test_only_structured_executed_optional_omission_is_resolved(self):
        ctx={**self.context,'user_message':'参照这个图修改','reference_images':[{'reference_id':'ref'}]}
        base={'intent_check':{'status':'consistent','unresolved_items':[{'resolution':'omit_optional_reference_connection','reason':'无配对依据'}]},
              'proposed_files':[{'content':'from paired_plot import draw_paired_plot\ndraw_paired_plot(ax,data,connect=False)'}]}
        response=copy.deepcopy(base);resolve_optional_reference_items(ctx,response)
        self.assertEqual(response['intent_check']['unresolved_items'],[])
        self.assertTrue(response['_reference_connection_omitted'])
        for changed in ('text','connect','explicit'):
            response=copy.deepcopy(base);local=copy.deepcopy(ctx)
            if changed=='text':response['intent_check']['unresolved_items']=['missing pairing']
            if changed=='connect':response['proposed_files'][0]['content']=response['proposed_files'][0]['content'].replace('False','True')
            if changed=='explicit':local['user_message']='请添加配对连线'
            resolve_optional_reference_items(local,response)
            self.assertTrue(response['intent_check']['unresolved_items'])
        self.assertEqual(self.verify(self.report(),{'_reference_connection_omitted':True})['status'],'fail')

    def test_reference_half_violin_inference_recognizes_real_request(self):
        from chat_reference_images import inferred_distribution
        ctx={'user_message':'参照这个图修改我选中的图','reference_images':[{'reference_id':'r'}],'image_order':['r']}
        proposal={'interpreted_request':{'operations':[{'property':'chart_type','desired_change':'convert to split half-violin plot with paired points'}]}}
        self.assertEqual(inferred_distribution(ctx,proposal),'violinplot')

    def test_isolated_render_exports_helper_evidence(self):
        base="""import os
from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt
from studio_style import finish_figure
p=Path(os.environ['CHART_PROJECT_DIR'])
t=pd.read_csv(p/'data/values.csv');t=t[t.panel_id.eq('demo')]
fig,ax=plt.subplots();ax.set_ylabel('Rate');ax.set_xticks([0,1],['A','B'])
for i,g in enumerate(['A','B']):ax.scatter([i]*3,t[t.group_label.eq(g)].value)
finish_figure(fig,os.environ['CHART_OUTPUT'])
"""
        candidate="""import os
from pathlib import Path
import matplotlib.pyplot as plt
from studio_style import finish_figure
from paired_plot import load_paired_data,draw_paired_plot
p=Path(os.environ['CHART_PROJECT_DIR'])
data=load_paired_data(p/'data/values.csv',chart='demo',groups=['A','B'])
fig,ax=plt.subplots();ax.set_ylabel('Rate')
draw_paired_plot(ax,data)
finish_figure(fig,os.environ['CHART_OUTPUT'])
"""
        (self.project/'charts/demo.py').write_text(base)
        report=render_candidate(self.project,'charts/demo.py',{'charts/demo.py':candidate},self.project/'out',baseline_files={'charts/demo.py':base})
        self.assertEqual(len(report['paired_plots']),1)
        self.assertEqual(self.verify(report)['status'],'pass',self.verify(report))
        from chat_harness import ChatHarness
        from types import SimpleNamespace
        host=SimpleNamespace(project_path=lambda project:self.project)
        harness=ChatHarness(host,renderer=lambda *a,**kw:report)
        session={'project':'p','id':'ses_00000000-0000-0000-0000-000000000001'}
        context={**self.context,'base_revision':'sha256:base','parent_draft_id':None,
                 'allowed_write_paths':['charts/demo.py'],
                 'source_files':[{'path':'charts/demo.py','content':base,'writable':True}]}
        response={'status':'candidate','summary':'配对半小提琴','warnings':[],
                  'proposed_files':[{'path':'charts/demo.py','content':candidate}],
                  'interpreted_request':{'operations':[]}}
        draft=harness.build_draft(session,{'chart':'demo','chart_id':'test'}, {'id':'trn_test'}, None,context,response)
        self.assertEqual(draft['status'],'preview_ready',draft.get('reason'))
        self.assertTrue(draft['paired_runtime_sha256'])
