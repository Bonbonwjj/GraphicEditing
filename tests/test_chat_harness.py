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

    def test_model_failure_preserves_successful_parent(self):
        a=self.turn({'user_message':'first'});self.model_failure=True
        b=self.turn({'user_message':'second'})
        self.assertEqual(a['active_drafts'],b['active_drafts'])
        self.assertEqual(b['turns'][-1]['results'][0]['status'],'cannot_complete')

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
        self.assertEqual(d['status'],'needs_clarification');self.assertFalse(a['active_drafts'])
        b=self.turn({'user_message':'accept overlap','layout_exception':{'warning_ids':['w1'],'authorization_quote':'accept overlap'}})
        self.assertEqual(b['drafts'][-1]['status'],'preview_ready')
        self.assertEqual(b['drafts'][-1]['layout']['status'],'accepted_exception')

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
