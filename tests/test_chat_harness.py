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
    def test_selected_panel_is_pinned_in_context_and_followup(self):
        (self.project/'lib').mkdir(exist_ok=True)
        (self.project/'lib/panels.py').write_text('PUBLIC_PANEL_MEMBERS={"a":["left","right"],"b":["third"]}\n')
        first=self.turn({'user_message':'first','target_panels':{'b':'a'}})
        self.assertEqual(self.contexts[-1]['selected_panel']['axis_labels'],['left','right'])
        self.assertEqual(first['drafts'][-1]['selected_panel']['id'],'a')
        first_id=first['drafts'][-1]['id']
        second=self.turn({'user_message':'second','target_panels':{'b':'a'}})
        self.assertEqual(self.contexts[-1]['parent_draft_id'],first_id)
        self.assertEqual(self.contexts[-1]['selected_panel']['id'],'a')
        self.assertIn('# first',next(s['content'] for s in self.contexts[-1]['source_files'] if s['writable']))
        self.assertEqual(second['turns'][-1]['target_panels'],{'b':'a'})

    def test_repaired_candidate_can_apply_when_original_never_rendered(self):
        original=self.render
        def repaired(*args,**kwargs):
            report=original(*args,**kwargs)
            report['baseline_render_error']='AssertionError: original layout'
            return report
        self.h.renderer=repaired
        first=self.turn({'user_message':'修复布局'})
        applied=self.h.draft_action('test',first['id'],first['drafts'][-1]['id'],'apply')
        self.assertEqual(applied['drafts'][-1]['status'],'applied')
        history=server.read_history(self.project,'b')
        self.assertTrue(history[0]['image_unavailable'])
        self.assertIn('仅保留代码',history[0]['note'])

    def test_partial_candidate_keeps_unmet_request_visible_and_does_not_apply(self):
        original=self.h.agent
        def partial(context):
            response=original(context)
            response['summary']='部分完成：已调整线宽，未更换不可用字体。'
            response['warnings']=['未完成：指定字体在本机不可用。']
            response['interpreted_request']['deferred_operations']=[{'request':'更换字体','reason':'字体不可用'}]
            return response
        self.h.agent=partial
        before=(self.project/'charts/b.py').read_bytes()
        result=self.turn({'user_message':'change line width'})
        draft=result['drafts'][-1]
        self.assertEqual(draft['status'],'preview_ready')
        self.assertTrue(draft['summary'].startswith('部分完成'))
        self.assertIn('未完成：指定字体在本机不可用。',draft['warnings'])
        self.assertEqual((self.project/'charts/b.py').read_bytes(),before)

    def test_thumbnail_cache_is_invalidated_by_image_content(self):
        from PIL import Image
        import io
        from chat_harness import chat_image_thumbnail
        chat_image_thumbnail.cache_clear()
        def image(color):
            stream=io.BytesIO();Image.new('RGB',(12,12),color).save(stream,format='PNG');return stream.getvalue()
        red=image('red');blue=image('blue')
        first=chat_image_thumbnail(red)
        self.assertEqual(first,chat_image_thumbnail(red))
        self.assertEqual(chat_image_thumbnail.cache_info().hits,1)
        self.assertNotEqual(first,chat_image_thumbnail(blue))
        chat_image_thumbnail.cache_clear()

    def test_save_and_recoverable_delete_preserve_applied_project(self):
        sid=self.session['id']
        self.turn({'user_message':'change line width'})
        original=(self.project/'charts/b.py').read_bytes()
        saved=self.h.manage('test',sid,'save',{'title':'配色方案'})
        self.assertEqual(saved['title'],'配色方案');self.assertTrue(saved['saved_at'])
        self.assertEqual(self.h.history('test')[0]['title'],'配色方案')
        with self.assertRaises(ValueError):self.h.manage('test',sid,'delete',{})
        self.assertTrue(self.h.path('test',sid).exists())
        result=self.h.manage('test',sid,'delete',{'confirm_session_id':sid})
        self.assertTrue(result['recoverable']);self.assertEqual(self.h.list('test'),[])
        self.assertEqual(self.h.history('test'),[])
        self.assertEqual((self.project/'charts/b.py').read_bytes(),original)
        recovered=list((self.project/'.chat/deleted_sessions').glob('*/session.json'))
        self.assertEqual(len(recovered),1)
        self.assertTrue(json.loads(recovered[0].read_text())['drafts'])

    def test_cannot_delete_running_session_or_other_session(self):
        import threading
        from chat_harness import lock
        sid=self.session['id'];held=threading.Event();release=threading.Event()
        def running():
            with lock(self.h.path('test',sid)):held.set();release.wait(3)
        worker=threading.Thread(target=running);worker.start();self.assertTrue(held.wait(1))
        try:
            with self.assertRaisesRegex(ValueError,'仍在运行'):
                self.h.manage('test',sid,'delete',{'confirm_session_id':sid})
        finally:release.set();worker.join(2)
        with self.assertRaises(ValueError):self.h.manage('test',sid,'delete',{'confirm_session_id':'other'})
        self.assertTrue(self.h.path('test',sid).exists())

    def test_plain_answer_preserves_active_draft_without_rendering(self):
        self.turn({'user_message':'change line width'})
        previous=self.h.load('test',self.session['id'])
        original=(self.project/'charts/b.py').read_bytes()
        def answer(context):
            return {**{k:context[k] for k in ('request_id','edit_session_id','turn_id','parent_draft_id','chart_id','base_revision','user_message')},
                    'status':'answer','message':'散点图用点表示坐标。','proposed_files':[]}
        self.h.agent=answer
        with patch.object(self.h,'renderer') as render,patch('chat_runner.inspect_chart_fonts') as fonts:
            result=self.turn({'user_message':'散点图是什么？当前字体是什么？请解释，不要修改。'})
        render.assert_not_called();fonts.assert_not_called()
        self.assertEqual(result['turns'][-1]['results'][0]['status'],'answer')
        self.assertEqual(result['turns'][-1]['results'][0]['message'],'散点图用点表示坐标。')
        current=self.h.load('test',self.session['id'])
        self.assertEqual(current['active_drafts'],previous['active_drafts'])
        self.assertEqual(current['drafts'],previous['drafts'])
        self.assertEqual((self.project/'charts/b.py').read_bytes(),original)

    def test_stop_waiting_model_preserves_applied_chart_and_ignores_late_response(self):
        import threading
        started=threading.Event();release=threading.Event();out=[]
        original=self.h.agent
        def slow_agent(context):
            started.set();release.wait(5)
            return original(context)
        self.h.agent=slow_agent
        worker=threading.Thread(target=lambda:out.append(self.turn({'user_message':'change line width'})))
        before=(self.project/'charts/b.py').read_bytes()
        worker.start()
        try:
            self.assertTrue(started.wait(2))
            self.assertTrue(self.h.stop('test',self.session['id'])['stopping'])
            worker.join(2)
            self.assertFalse(worker.is_alive())
            self.assertEqual(out[0]['turns'][-1]['results'][-1]['status'],'cancelled')
            self.assertEqual(out[0]['status'],'open')
            self.assertEqual(out[0]['drafts'],[])
            self.assertEqual((self.project/'charts/b.py').read_bytes(),before)
        finally:
            release.set();worker.join(2)
        self.assertFalse(self.h.stop('test',self.session['id'])['stopping'])
        self.assertEqual(self.h.load('test',self.session['id'])['drafts'],[])
        self.h.agent=original
        self.assertEqual(self.turn({'user_message':'change line width'})['status'],'open')

    def test_non_font_context_does_not_render_font_preflight(self):
        session=self.h.load('test',self.session['id'])
        with patch('chat_runner.inspect_chart_fonts') as inspect:
            context=self.h.context(session,session['charts'][0],
                                   {'id':'test-turn','operation':'chat_edit','user_message':'将图c更改为散点图'},None,None)
        inspect.assert_not_called()
        self.assertEqual(context['current_font_audit']['status'],'deferred_to_candidate_validation')

    def test_font_request_keeps_font_preflight(self):
        session=self.h.load('test',self.session['id'])
        with patch('chat_runner.inspect_chart_fonts',return_value={'fonts':[]}) as inspect:
            self.h.context(session,session['charts'][0],
                           {'id':'test-turn','operation':'chat_edit','user_message':'将字体改为 Arial'},None,None)
        inspect.assert_called_once()

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

    def test_dependency_change_warns_and_allows_apply(self):
        a=self.turn({'user_message':'first'});(self.project/'shared_draw.py').write_text('# changed', encoding="utf-8", newline="\n")
        with patch.object(server,'snapshot_image',return_value='.png'):
            result=self.h.draft_action('test',a['id'],a['drafts'][0]['id'],'apply')
        self.assertEqual(result['drafts'][0]['status'],'applied')
        self.assertTrue(any('依赖已变化' in w for w in result['drafts'][0]['warnings']))

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
        self.assertTrue(d['can_apply'])
        self.assertTrue(d['warnings'])
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

    def test_layout_continuation_allows_changed_or_removed_data(self):
        draft={'image_path':'candidate.png','code':{'charts/b.py':'pass'},
               'status':'needs_clarification','review_blocker':'layout_conflict'}
        for report in ({'changed':[{'key':'line'}]}, {'removed':[{'key':'line'}]}, {'status':'fail'}):
            with self.subTest(report=report):
                self.assertTrue(self.h.can_continue_draft({**draft,'data_report':report}))

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

    def test_old_diagnostic_candidates_remain_actionable_with_visible_warnings(self):
        result=self.turn({'user_message':'first'})
        saved=self.h.load('test',result['id'])
        for status in ('validation_failed','needs_clarification','font_unverified','axis_unmet',
                       'no_visible_change','already_compliant','revision_conflict'):
            with self.subTest(status=status):
                draft=saved['drafts'][0]
                draft.update(status=status,reason='测试问题原因',data_report={'status':'fail'})
                self.h.save(saved)
                public=self.h.public(saved)['drafts'][0]
                self.assertTrue(public['can_apply'])
                self.assertTrue(public['can_continue'])
                self.assertIn('测试问题原因',public['warnings'])
                self.h.draft_action('test',saved['id'],draft['id'],'activate')
        self.assertFalse(self.h.can_continue_draft({'status':'render_failed','code':{'a':'pass'}}))
        self.assertFalse(self.h.can_continue_draft({'status':'discarded','code':{'a':'pass'},'image_path':'a.png'}))

    def test_data_change_warns_but_can_apply(self):
        self.changed_data=True;a=self.turn({'user_message':'first'})
        self.assertEqual(a['drafts'][0]['status'],'validation_failed')
        self.assertTrue(a['drafts'][0]['can_apply'])
        with patch.object(server,'snapshot_image',return_value='.png'):
            result=self.h.draft_action('test',a['id'],a['drafts'][0]['id'],'apply')
        self.assertEqual(result['drafts'][0]['status'],'applied')
        self.assertTrue(result['drafts'][0]['warnings'])

    def test_failed_data_check_candidate_is_used_for_followup(self):
        self.changed_data=True
        first=self.turn({'user_message':'first'})
        draft=first['drafts'][-1]
        self.assertEqual(first['active_drafts'][draft['chart_id']],draft['id'])
        second=self.turn({'user_message':'基于此图继续修改'})
        self.assertEqual(self.contexts[-1]['parent_draft_id'],draft['id'])
        self.assertTrue(second['drafts'][-1]['can_apply'])
        self.assertTrue(second['drafts'][-1]['warnings'])

    def test_preserved_inputs_allow_mapping_and_derived_geometry_and_followup(self):
        server.save_preview(self.project,'b',self.source,b'original')
        def remapped(*args, **kwargs):
            report=self.render(*args, **kwargs)
            report['source_data_report']={'status':'pass','checked_inputs':2}
            report['data_report'].update(changed=[{'key':'line'}], removed=[{'key':'old'}],
                                         added=[{'key':'new'}], axes_changes=[{'axis':0}])
            return report
        self.h.renderer=remapped
        first=self.turn({'user_message':'将原始值求均值后交换横纵轴'})
        draft=first['drafts'][-1]
        self.assertEqual(draft['status'],'preview_ready')
        self.assertTrue(draft['can_continue'])
        second=self.turn({'user_message':'基于这个图修改线宽'})
        self.assertEqual(self.contexts[-1]['parent_draft_id'],draft['id'])
        latest=second['drafts'][-1]
        applied=self.h.draft_action('test',second['id'],latest['id'],'apply')
        self.assertEqual(applied['drafts'][-1]['status'],'applied')

    def test_modified_original_input_warns_without_blocking(self):
        def corrupted(*args, **kwargs):
            report=self.render(*args, **kwargs)
            report['source_data_report']={'status':'fail','reason':'原始输入已改动'}
            return report
        self.h.renderer=corrupted
        with patch('chart_transform.verify_distribution',return_value={'status':'pass'}):
            result=self.turn({'user_message':'改成箱线图'})
        draft=result['drafts'][-1]
        self.assertEqual(draft['status'],'validation_failed')
        self.assertTrue(draft['can_continue'])
        self.assertTrue(draft['can_apply'])
        self.assertIn('原始输入已改动',draft['warnings'])
        with patch.object(server,'snapshot_image',return_value='.png'):
            applied=self.h.draft_action('test',result['id'],draft['id'],'apply')
        self.assertEqual(applied['drafts'][-1]['status'],'applied')

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
        self.assertTrue(result['drafts'][-1]['can_continue'])

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

    def test_recheck_refreshes_stale_source_with_warning(self):
        first=self.turn({'user_message':'first'})
        (self.project/'charts/b.py').write_text(self.source+'\n# external edit\n')
        checked=self.h.draft_action('test',first['id'],first['drafts'][-1]['id'],'recheck')
        self.assertTrue(checked['drafts'][-1]['can_apply'])
        self.assertTrue(checked['drafts'][0]['warnings'])

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

    def test_unrequested_view_change_warns_but_allows_continuation(self):
        self.axes_changes=[{'axis':'x','before':[0,10],'after':[0,1]}]
        a=self.turn({'user_message':'line width only'})
        self.assertEqual(a['drafts'][-1]['status'],'needs_clarification')
        self.assertTrue(a['drafts'][-1]['can_continue'])
        self.assertTrue(a['drafts'][-1]['can_apply'])
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
