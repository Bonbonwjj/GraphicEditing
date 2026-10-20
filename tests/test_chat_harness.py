"""Deterministic workflow tests. Model and render doubles are explicit."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server
from chat_harness import ChatHarness, digest, scoped_plot_data
from chat_agent import validate_response

ROOT=Path(__file__).resolve().parents[1]
BASE=(ROOT/'docs/chat-acceptance/inputs/01.json')


class HarnessTests(unittest.TestCase):
    def test_prompt_csv_scope_keeps_only_selected_panel_rows(self):
        files={
            'charts/target.py':{'path':'charts/target.py','content':"read_csv('data/panels.csv')\npanel_id = 'target'",'sha256':'source'},
            'data/panels.csv':{'path':'data/panels.csv','content':'panel_id,value\ntarget,1\nother,2\n','sha256':'complete-file-hash'},
            'data/unrelated.csv':{'path':'data/unrelated.csv','content':'panel_id,value\nother,3\n','sha256':'unrelated-file-hash'},
        }
        data=scoped_plot_data(files,'target')
        selected=next(item for item in data if item['path']=='data/panels.csv')
        unrelated=next(item for item in data if item['path']=='data/unrelated.csv')
        self.assertEqual(selected['content_scope'],'matching_chart_rows')
        self.assertEqual(selected['content'],'panel_id,value\ntarget,1\n')
        self.assertEqual(selected['sha256'],'complete-file-hash')
        self.assertEqual(unrelated['content_scope'],'schema_only')
        self.assertEqual(unrelated['content'],'panel_id,value\n')

    def setUp(self):
        # The renderer double returns marker bytes, not a PNG. Personal vision
        # settings must not cause deterministic workflow tests to decode them.
        self.model_settings = patch('chat_harness.effective_model_config', return_value={
            'vision_enabled': False, 'api_url': 'https://example.test/v1/chat/completions',
            'model': 'test-model', 'api_key': '', 'max_output_tokens': 16384})
        self.model_settings.start(); self.addCleanup(self.model_settings.stop)
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.project=self.root/'test';(self.project/'charts').mkdir(parents=True);(self.project/'data').mkdir()
        (self.project/'project.json').write_text('{"name":"Test"}', encoding="utf-8", newline="\n")
        raw=json.loads(BASE.read_text(encoding="utf-8"));self.source=raw['source_files'][0]['content']
        for f in raw['source_files']+raw['plot_data']:
            out=self.project/f['path'];out.parent.mkdir(parents=True,exist_ok=True);out.write_text(f['content'], encoding="utf-8", newline="\n")
        (self.project/'charts/c.py').write_text(self.source, encoding="utf-8", newline="\n")
        from local_execution import approve
        approve(self.project)
        self.patch=patch.object(server,'PROJECTS',self.root);self.patch.start()
        self.font_patch=patch("chat_runner.inspect_chart_fonts", return_value={"fonts": [], "platform_font": "test"})
        self.font_patch.start();self.addCleanup(self.font_patch.stop)
        self.contexts=[];self.model_failure=False;self.layout_issues=[];self.changed_data=False
        self.layout_signature={'canvas':[600,400]};self.axes_changes=[]
        self.added=[]
        self.h=ChatHarness(server,agent=self.agent,renderer=self.render)
        self.session=self.h.create('test',['b'])

    def tearDown(self):
        self.patch.stop();self.temp.cleanup()

    def agent(self,q):
        self.contexts.append(copy.deepcopy(q))
        if self.model_failure:raise ValueError('model unavailable')
        response=json.loads((ROOT/'docs/chat-acceptance/responses/01.json').read_text(encoding="utf-8"))
        for key in ('request_id','edit_session_id','turn_id','parent_draft_id','chart_id','base_revision','user_message'):response[key]=q[key]
        source=next(f for f in q['source_files'] if f['writable'])
        response['proposed_files']=[{'path':source['path'],'base_sha256':source['sha256'],'content':source['content']+'\n# '+q['user_message']+'\n'}]
        response['affected_chart_ids']=[q['chart_id']]
        response['interpreted_request']['operations']=[{'operation_id':'requested','target_chart_id':q['chart_id'],
            'target_element':'Obs line','property':'linewidth','current_value':1.5,'desired_change':2.5,
            'source_quotes':[q['user_message']],'disposition':'planned'}]
        response['read_data_refs']=[{'path':f['path'],'sha256':f['sha256'],'columns':[{'name':c,'role':'plotting'} for c in ('group','x','mean')]} for f in q['plot_data']]
        return response

    def render(self,p,entry,files,output,baseline_files=None):
        output.mkdir(parents=True,exist_ok=True);image=output/'candidate.png';image.write_bytes(b'fixture-image')
        return {'image_path':str(image),'layout':{'status':'conflict' if self.layout_issues else 'pass','issues':copy.deepcopy(self.layout_issues)},
                'data_report':{'status':'changed' if self.changed_data else 'unchanged','axes_changes':self.axes_changes,'added':self.added},
                'layout_signature':copy.deepcopy(self.layout_signature),'naming':{'display_name':'Obs&Control_Score','status':'ready'}}

    def turn(self,body):return self.h.turn('test',self.session['id'],body)

    def test_candidate_does_not_apply_and_next_turn_uses_active_parent(self):
        a=self.turn({'user_message':'first'});draft=a['drafts'][0]
        self.assertEqual((self.project/'charts/b.py').read_text(encoding="utf-8"),self.source)
        b=self.turn({'user_message':'second'})
        self.assertEqual(self.contexts[-1]['parent_draft_id'],draft['id'])
        self.assertIn('# first',next(f for f in self.contexts[-1]['source_files'] if f['writable'])['content'])
        self.assertEqual(len(b['drafts']),2)

    def test_new_unused_parameter_helper_does_not_invalidate_legacy_session(self):
        session=self.h.load('test',self.session['id'])
        session['base_platform_hashes'].pop('@platform/chart_overrides.py')
        session['base_revisions'][session['chart_ids'][0]]='legacy-revision-without-new-helper'
        self.h.save(session)
        result=self.turn({'user_message':'first'})
        self.assertEqual(result['drafts'][-1]['status'],'preview_ready')

    def test_model_failure_preserves_successful_parent(self):
        a=self.turn({'user_message':'first'});self.model_failure=True
        b=self.turn({'user_message':'second'})
        self.assertEqual(a['active_drafts'],b['active_drafts'])
        self.assertEqual(b['turns'][-1]['results'][0]['status'],'cannot_complete')

    def test_render_repairs_share_three_attempt_limit(self):
        self.layout_issues=[{'id':'w1','kind':'text_overlap','elements':['xlabel','tick']}]
        original=self.agent
        def counted(context):
            context['_model_attempt_budget']['used']+=1
            return original(context)
        self.h.agent=counted
        result=self.turn({'user_message':'first'})
        self.assertEqual(len(self.contexts),3)
        self.assertEqual(result['turns'][-1]['results'][0]['model_attempts'],3)

    def test_format_attempts_reduce_remaining_render_repairs(self):
        self.layout_issues=[{'id':'w1','kind':'text_overlap','elements':['xlabel','tick']}]
        original=self.agent
        def counted(context):
            context['_model_attempt_budget']['used']+=2 if not self.contexts else 1
            return original(context)
        self.h.agent=counted
        result=self.turn({'user_message':'first'})
        self.assertEqual(len(self.contexts),2)
        self.assertEqual(result['turns'][-1]['results'][0]['model_attempts'],3)

    def test_session_persists_across_harness_instances(self):
        self.turn({'user_message':'first'})
        restored=ChatHarness(server).load('test',self.session['id'])
        self.assertEqual(restored['turns'][0]['user_message'],'first')
        self.assertEqual(restored['drafts'][0]['status'],'preview_ready')

    def test_apply_persists_image_and_source_then_new_turn_starts_from_formal(self):
        a=self.turn({'user_message':'first'});draft=a['drafts'][0]
        with patch.object(server,'snapshot_image',return_value='.png'):
            b=self.h.draft_action('test',a['id'],draft['id'],'apply')
        self.assertEqual(b['drafts'][0]['status'],'applied')
        self.assertIn('# first',(self.project/'charts/b.py').read_text(encoding="utf-8"))
        self.assertEqual((self.project/'previews/b.png').read_bytes(),b'fixture-image')
        self.turn({'user_message':'second'})
        self.assertIsNone(self.contexts[-1]['parent_draft_id'])
        self.assertIn('# first',next(f for f in self.contexts[-1]['source_files'] if f['writable'])['content'])

    def test_dependency_change_rejects_apply(self):
        a=self.turn({'user_message':'first'});(self.project/'shared_draw.py').write_text('# changed', encoding="utf-8", newline="\n")
        with self.assertRaisesRegex(ValueError,'revision_conflict'):
            self.h.draft_action('test',a['id'],a['drafts'][0]['id'],'apply')
        self.assertEqual((self.project/'charts/b.py').read_text(encoding="utf-8"),self.source)

    def test_foreign_draft_and_missing_warning_rejected(self):
        a=self.turn({'user_message':'first'})
        with self.assertRaises(ValueError):self.h.draft_action('test',a['id'],'dft_bad','apply')
        b=self.turn({'user_message':'override','layout_exception':{'warning_ids':['made-up'],'authorization_quote':'override'}})
        self.assertEqual(b['turns'][-1]['results'][0]['status'],'cannot_complete')

    def test_scope_and_raw_quote_validation(self):
        self.turn({'user_message':'first'});q=self.contexts[-1];r=self.agent(q)
        r['proposed_files'][0]['path']='shared_draw.py'
        with self.assertRaises(ValueError):validate_response(q,r)
        r=self.agent(q);r['user_message']='different'
        with self.assertRaises(ValueError):validate_response(q,r)

    def test_missing_data_columns_rejected(self):
        self.turn({'user_message':'first'});q=self.contexts[-1];r=self.agent(q)
        r['read_data_refs'][0]['columns']=[]
        with self.assertRaises(ValueError):validate_response(q,r)

    def test_layout_conflict_is_diagnostic_until_explicit_override(self):
        self.layout_issues=[{'id':'w1','kind':'text_overlap','elements':['xlabel','tick'],'message':'overlap'}]
        a=self.turn({'user_message':'first'});d=a['drafts'][0]
        self.assertEqual(d['status'],'needs_clarification')
        self.assertEqual(a['active_drafts'][d['chart_id']],d['id'])
        self.assertTrue(d['can_continue'])
        with self.assertRaises(ValueError):self.h.draft_action('test',a['id'],d['id'],'apply')
        b=self.turn({'user_message':'accept overlap','layout_exception':{'warning_ids':['w1'],'authorization_quote':'accept overlap'}})
        self.assertEqual(b['drafts'][-1]['status'],'preview_ready')
        self.assertEqual(b['drafts'][-1]['layout']['status'],'accepted_exception')

    def test_layout_conflict_followup_uses_candidate_without_accepting_overlap(self):
        self.layout_issues=[{'id':'w1','kind':'text_overlap','elements':['xlabel','tick'],'message':'overlap'}]
        first=self.turn({'user_message':'first'})
        draft=first['drafts'][-1]
        self.layout_issues=[]
        second=self.turn({'user_message':'基于这个版本把重叠解决'})
        context=self.contexts[-1]
        self.assertEqual(context['parent_draft_id'],draft['id'])
        self.assertIn('# first',next(f for f in context['source_files'] if f['writable'])['content'])
        self.assertEqual(context['harness_layout_feedback']['layout']['issues'][0]['id'],'w1')
        self.assertFalse(context['layout_exception'])
        self.assertEqual(second['drafts'][-1]['status'],'preview_ready')
        self.assertEqual((self.project/'charts/b.py').read_text(encoding='utf-8'),self.source)

    def test_layout_continuation_still_rejects_changed_or_removed_data(self):
        draft={'image_path':'candidate.png','code':{'charts/b.py':'pass'},
               'status':'needs_clarification','review_blocker':'layout_conflict'}
        for report in ({'changed':[{'key':'line'}]}, {'removed':[{'key':'line'}]}, {'status':'fail'}):
            with self.subTest(report=report):
                self.assertFalse(self.h.can_continue_draft({**draft,'data_report':report}))

    def test_accepting_layout_allows_identical_image_only_for_explicit_acceptance(self):
        self.layout_issues=[{'id':'w1','kind':'text_overlap','elements':['xlabel','tick']}]
        def identical(*args,**kwargs):
            report=self.render(*args,**kwargs)
            report['visual_change']={'status':'identical'}
            return report
        self.h.renderer=identical
        self.turn({'user_message':'first'})
        accepted=self.turn({'user_message':'accept overlap','layout_exception':{
            'warning_ids':['w1'],'authorization_quote':'accept overlap'}})
        self.assertEqual(accepted['drafts'][-1]['status'],'preview_ready')
        later=self.turn({'user_message':'make the line wider'})
        self.assertEqual(later['drafts'][-1]['status'],'no_visible_change')

    def test_batch_override_only_runs_affected_chart(self):
        self.session=self.h.create('test',['b','c']);self.layout_issues=[{'id':'w1','kind':'text_overlap','elements':['xlabel','tick']}]
        a=self.turn({'user_message':'first'});cid=a['charts'][0]['chart_id'];count=len(self.contexts)
        b=self.turn({'user_message':'accept B','layout_exception':{'chart_id':cid,'warning_ids':['w1'],'authorization_quote':'accept B'}})
        self.assertEqual(len(self.contexts)-count,1)
        self.assertEqual(len(b['turns'][-1]['results']),1)

    def test_data_change_cannot_apply(self):
        self.changed_data=True;a=self.turn({'user_message':'first'})
        self.assertEqual(a['drafts'][0]['status'],'validation_failed')
        with self.assertRaises(ValueError):self.h.draft_action('test',a['id'],a['drafts'][0]['id'],'apply')

    def test_verified_chart_conversion_allows_expected_geometry_changes(self):
        def converted(*args,**kwargs):
            report=self.render(*args,**kwargs)
            report['data_report'].update(status='review_required',changed=[{'key':'line_0'}],removed=[{'key':'errorbar'}])
            return report
        self.h.renderer=converted
        with patch('chart_transform.verify_distribution',return_value={'status':'pass','reason':'Complete source groups matched'}):
            result=self.turn({'user_message':'改为箱线图'})
        draft=result['drafts'][-1]
        self.assertEqual(draft['status'],'preview_ready')
        self.assertTrue(draft['can_continue'])

    def test_unsupported_model_completion_is_not_reported_as_verified(self):
        from chat_agent import expand_compact_response
        with patch.object(self.h,'agent',side_effect=lambda context:expand_compact_response(context,{'status':'already_compliant','reason':'looks done','warnings':[],'interpreted_request':{'operations':[]},'intent_check':{'status':'consistent','unresolved_items':[]},'proposed_files':[]})):
            result=self.turn({'user_message':'让整张图具有更好的视觉平衡'})
        item=result['turns'][-1]['results'][0]
        self.assertEqual(item['status'],'manual_review',item)
        self.assertIn('人工审阅',item['summary'])

    def test_repeated_conversion_reuses_verified_candidate_without_model_question(self):
        with patch('chart_transform.verify_distribution',return_value={'status':'pass','kind':'boxplot'}):
            first=self.turn({'user_message':'把这2个图改为箱线图'})
            count=len(self.contexts)
            second=self.turn({'user_message':'把这2个图改为箱型图'})
            result=second['turns'][-1]['results'][0]
            self.assertEqual(result['status'],'already_compliant')
            self.assertEqual(result['draft_id'],first['drafts'][-1]['id'])
            self.assertEqual(result['model_attempts'],0)
            self.assertEqual(len(self.contexts),count)
            self.assertEqual(len(second['drafts']),len(first['drafts']))
            self.assertIn('可直接应用',result['reason'])
            self.turn({'user_message':'改为箱型图，颜色改成蓝色'})
            self.assertGreater(len(self.contexts),count)

    def test_conversion_does_not_override_explicit_data_failure(self):
        self.changed_data=True
        with patch('chart_transform.verify_distribution',return_value={'status':'pass'}):
            result=self.turn({'user_message':'改为箱线图'})
        self.assertEqual(result['drafts'][-1]['status'],'validation_failed')
        self.assertFalse(result['drafts'][-1]['can_continue'])

    def test_missing_target_distribution_can_be_repaired_but_wrong_data_cannot(self):
        with patch('chart_transform.verify_distribution',side_effect=[
                {'status':'unverified','reason':'Target violin was not rendered'},
                {'status':'pass','kind':'violinplot'}]):
            result=self.turn({'user_message':'改为小提琴图'})
        self.assertEqual(result['drafts'][-1]['status'],'preview_ready')
        self.assertEqual(len(self.contexts),2)
        self.assertEqual(self.contexts[-1]['harness_layout_feedback']['chart_transform']['status'],'unverified')
        calls=len(self.contexts)
        with patch('chart_transform.verify_distribution',return_value={'status':'fail','reason':'Missing raw samples'}):
            failed=self.turn({'user_message':'改为箱型图'})
        self.assertEqual(failed['drafts'][-1]['status'],'validation_failed')
        self.assertEqual(len(self.contexts),calls+1)

    def test_recheck_renders_saved_candidate_without_calling_model(self):
        self.changed_data=True;first=self.turn({'user_message':'first'})
        calls=len(self.contexts)
        self.changed_data=False
        checked=self.h.draft_action('test',first['id'],first['drafts'][-1]['id'],'recheck')
        self.assertEqual(len(self.contexts),calls)
        self.assertEqual(checked['drafts'][-1]['status'],'preview_ready')
        self.assertEqual(checked['drafts'][-1]['rechecked_from'],first['drafts'][-1]['id'])
        self.assertEqual(checked['active_drafts'][checked['drafts'][-1]['chart_id']],checked['drafts'][-1]['id'])

    def test_recheck_rejects_stale_source(self):
        first=self.turn({'user_message':'first'})
        (self.project/'charts/b.py').write_text(self.source+'\n# external edit\n')
        with self.assertRaisesRegex(ValueError,'revision_conflict'):
            self.h.draft_action('test',first['id'],first['drafts'][-1]['id'],'recheck')

    def test_reference_versions_pinned_across_turns(self):
        self.session=self.h.create('test',['b'],['c']);first=self.session['references'][0]['revision_id']
        (self.project/'charts/c.py').write_text(self.source+'\n# new reference', encoding="utf-8", newline="\n")
        a=self.turn({'user_message':'use reference','reference_charts':['c']})
        self.assertEqual(a['references'][0]['revision_id'],first)
        self.assertFalse(self.contexts[-1]['reference_charts'][0]['source_files'][0]['writable'])

    def test_failed_commit_rolls_back_source(self):
        a=self.turn({'user_message':'first'})
        with patch.object(server,'snapshot_image',return_value='.png'),patch.object(server,'save_preview',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):self.h.draft_action('test',a['id'],a['drafts'][0]['id'],'apply')
        self.assertEqual((self.project/'charts/b.py').read_text(encoding="utf-8"),self.source)

    def test_layout_exception_expires_when_geometry_changes(self):
        self.layout_issues=[{'id':'w1','kind':'text_overlap','elements':['xlabel','tick']}]
        self.turn({'user_message':'first'})
        self.layout_signature={'canvas':[300,200]}
        a=self.turn({'user_message':'accept','layout_exception':{'warning_ids':['w1'],'authorization_quote':'accept'}})
        self.assertEqual(a['drafts'][-1]['status'],'needs_clarification')

    def test_unrequested_view_change_does_not_become_applicable(self):
        self.axes_changes=[{'axis':'x','before':[0,10],'after':[0,1]}]
        a=self.turn({'user_message':'line width only'})
        self.assertEqual(a['drafts'][-1]['status'],'needs_clarification')
        self.assertFalse(a['drafts'][-1]['can_continue'])
        with self.assertRaises(ValueError):
            self.h.draft_action('test',a['id'],a['drafts'][-1]['id'],'activate')

    def test_reference_image_is_immutable_and_target_image_is_in_context(self):
        import io
        from PIL import Image
        image = io.BytesIO()
        Image.new('RGB', (2, 2), (255, 0, 0)).save(image, format='PNG')
        original = image.getvalue()
        server.save_preview(self.project,'c',self.source,original)
        server.save_preview(self.project,'b',self.source,original)
        self.session=self.h.create('test',['b'],['c'])
        (self.project/'previews/c.png').write_bytes(b'replaced')
        with patch('chat_harness.effective_model_config', return_value={'vision_enabled': True}):
            self.turn({'user_message':'use reference'})
        ctx=self.contexts[-1]
        import base64
        self.assertEqual(Image.open(io.BytesIO(base64.b64decode(ctx['_images'][1].split(',')[1]))).getpixel((0,0)), (255, 0, 0))
        self.assertTrue(ctx['target_image_available'])
        self.assertEqual(ctx['image_order'][0],'current_target')

    def test_finalize_removes_only_target_drafts_and_closes_session(self):
        self.session=self.h.create('test',['b','c'])
        a=self.turn({'user_message':'first'})
        before=(self.project/'charts/b.py').read_bytes()
        self.h.finalize('test','b');session=self.h.load('test',a['id'])
        self.assertEqual(session['status'],'closed')
        self.assertEqual([d['chart'] for d in session['drafts']],['c'])
        self.assertEqual((self.project/'charts/b.py').read_bytes(),before)
        self.assertFalse(Path(a['drafts'][0]['image_url']).is_file())
        self.assertFalse((self.h.path('test',a['id']).parent/'drafts'/a['drafts'][0]['id']).exists())
        with self.assertRaises(ValueError):self.h.draft_action('test',a['id'],a['drafts'][1]['id'],'apply')

    def test_orphan_running_session_recovers_after_restart(self):
        a=self.h.load('test',self.session['id']);a['status']='running';self.h.save(a)
        self.assertEqual(self.h.get('test',a['id'])['status'],'interrupted')

    def test_empty_operations_rejected(self):
        self.turn({'user_message':'first'});ctx=self.contexts[-1];r=self.agent(ctx)
        r['interpreted_request']['operations']=[]
        with self.assertRaises(ValueError):validate_response(ctx,r)

    def test_csv_reader_cannot_omit_data_references(self):
        self.turn({'user_message':'first'});ctx=self.contexts[-1];r=self.agent(ctx);r['read_data_refs']=[]
        with self.assertRaises(ValueError):validate_response(ctx,r)

    def test_preview_cache_rejects_changed_root_helper(self):
        server.save_preview(self.project,'c',self.source,b'original')
        (self.project/'shared_draw.py').write_text('# dependency changed', encoding="utf-8", newline="\n")
        files,revision=self.h.snapshot('test','c')
        self.assertIsNone(self.h.cached_image('test','c',self.source,revision))

    def test_old_preview_request_cannot_replace_current_image(self):
        newer=self.source+'\n# new formal';(self.project/'charts/b.py').write_text(newer, encoding="utf-8", newline="\n")
        server.save_preview(self.project,'b',newer,b'newer')
        with patch.object(server,'render',return_value=b'old-render'):
            image,_=server.preview_asset(self.project,'b',self.source)
        self.assertEqual(image,b'old-render')
        self.assertEqual((self.project/'previews/b.png').read_bytes(),b'newer')

    def test_unrequested_extra_series_requires_clarification(self):
        self.added=[{'kind':'line','semantic_role':'data_series','data':[100,200]}]
        a=self.turn({'user_message':'line width only'})
        self.assertEqual(a['drafts'][-1]['status'],'needs_clarification')

    def test_old_branch_history_is_not_an_active_constraint(self):
        a=self.turn({'user_message':'first'});d1=a['drafts'][0]['id']
        b=self.turn({'user_message':'second'});d2=b['drafts'][-1]['id']
        self.h.draft_action('test',a['id'],d1,'activate')
        self.turn({'user_message':'third'})
        context=self.contexts[-1]['conversation_context']
        self.assertEqual(context['active_parent_lineage'],[d1])
        branch=next(t for t in context['recent_turns'] if t['draft_id']==d2)
        self.assertFalse(branch['in_active_lineage'])

if __name__=='__main__':unittest.main()
