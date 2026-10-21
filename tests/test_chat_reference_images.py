import base64
import copy
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer
from PIL import Image
import server
from chat_harness import ChatHarness
from chat_parameters import propose_parameters
from chat_reference_images import store,resolve,select,public,inferred_distribution
from tests.test_chat_parameters import SOURCE
from tests.test_model_config import FakeStream


def picture(color='red'):
    out=io.BytesIO();Image.new('RGB',(20,10),color).save(out,format='PNG')
    return 'data:image/png;base64,'+base64.b64encode(out.getvalue()).decode()


class ReferenceImageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir='/private/tmp');self.root=Path(self.temp.name).resolve()
        self.project=self.root/'p';(self.project/'charts').mkdir(parents=True)
        (self.project/'project.json').write_text('{"name":"reference"}');(self.project/'charts/a.py').write_text(SOURCE)
        from local_execution import approve
        approve(self.project)
        p=patch.object(server,'PROJECTS',self.root);p.start();self.addCleanup(p.stop);self.addCleanup(self.temp.cleanup)
        self.calls=[];self.visual_calls=[];self.comparison_status='match'
        self.h=ChatHarness(server,agent=self.agent,renderer=self.render,visual_agent=self.visual)
        self.directory=self.h.directory('p')
        self.image=store(self.directory,'p',{'name':'style.png','data_url':picture()})
        p=patch('chat_runner.inspect_chart_fonts',return_value={'fonts':[]});p.start();self.addCleanup(p.stop)
        p=patch('chat_harness.effective_model_config',return_value={'vision_enabled':True});p.start();self.addCleanup(p.stop)

    def agent(self,ctx):
        if ctx.get('reference_features') and ctx.get('_model_attempt_budget') is not None:
            ctx['_model_attempt_budget']['used']+=1
        self.calls.append(copy.deepcopy(ctx));response=propose_parameters({**ctx,'user_message':'折线颜色改为红色'})
        response['user_message']=ctx['user_message']
        for op in response['interpreted_request']['operations']:op['source_quotes']=[ctx['user_message']]
        response['reference_usage']=[{'reference_id':r['reference_id'],'revision_id':r['revision_id'],'borrowed_properties':['color']} for r in ctx.get('reference_images',[])]
        return response

    def visual(self,ctx):
        self.visual_calls.append(copy.deepcopy(ctx))
        ctx['_model_attempt_budget']['used']+=1
        if ctx['_reference_visual_task']=='extract':
            return {'features':[{'feature_id':'f'+str(i),'reference_id':r['reference_id'],
                    'name':'配色','expected':'红色','evidence':'参考图可见红色区域','transfer':'style'}
                    for i,r in enumerate(ctx['reference_images'])]}
        return {'items':[{'feature_id':f['feature_id'],'status':self.comparison_status,
                         'observed':'候选显示红色','reason':'根据候选与参考图片对照'} for f in ctx['reference_features']]}

    def render(self,project,entry,code,output,baseline_files=None):
        output.mkdir(parents=True,exist_ok=True);image=output/'candidate.png';Image.new('RGB',(2,2),'red').save(image)
        return {'image_path':str(image),'layout':{'status':'pass','issues':[]},'data_report':{'status':'unchanged'},'visual_change':{'status':'changed'},'baseline_layout_signature':{'axes':[{'line_colors':['#0000ffff']}]},'layout_signature':{'axes':[{'line_colors':['#ff0000ff']}]},'naming':{}}

    def test_store_normalizes_pins_and_is_scoped_to_project(self):
        ref=resolve(self.directory,self.image['reference_id'])
        self.assertEqual(ref['revision_id'],self.image['revision_id']);self.assertNotIn('_image',public([ref])[0])
        self.assertEqual(Image.open(ref['_image']).getpixel((0,0)),(255,0,0))
        with self.assertRaises(ValueError):resolve(self.root/'other',self.image['reference_id'])
        Path(ref['_image']).write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'变化'):resolve(self.directory,self.image['reference_id'])

    def test_bad_files_limits_and_path_traversal_are_rejected(self):
        for data in ('data:image/svg+xml;base64,PHN2Zz4=', 'data:image/png;base64,YmFk', 'data:image/png;base64,%%%'):
            with self.subTest(data=data),self.assertRaises(ValueError):store(self.directory,'p',{'data_url':data})
        for ident in ('../outside','refimg_../../etc/passwd',None):
            with self.assertRaises(ValueError):resolve(self.directory,ident)
        with self.assertRaises(ValueError):select(self.directory,[self.image['reference_id']]*4)
        with self.assertRaises(ValueError):select(self.directory,[self.image['reference_id']]*2)

    def test_uploaded_pixels_reach_agent_and_turn_history_persists(self):
        s=self.h.create('p',['a'])
        result=self.h.turn('p',s['id'],{'user_message':'希望改得和这个图类似','reference_image_ids':[self.image['reference_id']]})
        self.assertEqual(result['drafts'][-1]['status'],'preview_ready',result['drafts'][-1].get('reason'))
        ctx=self.calls[-1];self.assertEqual(ctx['image_order'],[self.image['reference_id']])
        pixels=base64.b64decode(ctx['_images'][0].split(',')[1]);self.assertEqual(Image.open(io.BytesIO(pixels)).getpixel((0,0)),(255,0,0))
        self.assertNotIn('_image',result['reference_images'][0]);self.assertEqual(result['turns'][-1]['reference_images'],[self.image])
        history=self.h.history('p')[0];self.assertEqual(history['turns'][-1]['reference_images'],[self.image])
        self.h.turn('p',s['id'],{'user_message':'再调整一点'})
        self.assertEqual(len(self.calls[-1]['reference_images']),1)
        self.h.turn('p',s['id'],{'user_message':'再调整一点','reference_image_ids':[]})
        self.assertEqual(self.calls[-1]['reference_images'],[])
        self.assertEqual(self.h.load('p',s['id'])['turns'][0]['reference_images'],[self.image])

    def test_visual_features_precede_code_and_comparison_is_advisory(self):
        self.comparison_status='different'
        s=self.h.create('p',['a'])
        result=self.h.turn('p',s['id'],{'user_message':'参照这个图改图','reference_image_ids':[self.image['reference_id']]})
        draft=result['drafts'][-1]
        self.assertEqual([c['_reference_visual_task'] for c in self.visual_calls],['extract','compare'])
        self.assertTrue(self.calls[-1]['reference_features']['features'])
        self.assertEqual(self.visual_calls[-1]['image_order'][0],'candidate_render')
        self.assertEqual(draft['reference_comparison']['status'],'different')
        self.assertEqual(draft['status'],'preview_ready')
        self.assertTrue(draft['can_continue'])
        self.assertEqual(result['turns'][-1]['results'][0]['model_attempts'],3)
        self.h.draft_action('p',s['id'],draft['id'],'activate')
        self.h.turn('p',s['id'],{'user_message':'再调整一下','reference_image_ids':[self.image['reference_id']]})
        self.assertEqual(sum(c['_reference_visual_task']=='extract' for c in self.visual_calls),1)
        with patch.object(self.h,'commit_draft'):
            applied=self.h.draft_action('p',s['id'],draft['id'],'apply')
        self.assertEqual(applied['drafts'][0]['status'],'applied')
        self.assertEqual(self.h.history('p')[0]['drafts'][0]['reference_comparison']['status'],'different')

    def test_visual_comparison_failure_keeps_candidate_without_claiming_match(self):
        visual=self.visual
        def broken(ctx):
            if ctx['_reference_visual_task']=='compare':raise ValueError('vision unavailable')
            return visual(ctx)
        self.h.visual_agent=broken
        s=self.h.create('p',['a'])
        result=self.h.turn('p',s['id'],{'user_message':'参照这个图改图','reference_image_ids':[self.image['reference_id']]})
        draft=result['drafts'][-1]
        self.assertEqual(draft['status'],'preview_ready')
        self.assertEqual(draft['reference_comparison']['status'],'unverified')
        self.assertTrue(draft['can_continue'])

    def test_reviewed_style_apply_does_not_waive_data_checks(self):
        s=self.h.create('p',['a'])
        result=self.h.turn('p',s['id'],{'user_message':'参照图改图','reference_image_ids':[self.image['reference_id']]})
        stored=self.h.load('p',s['id']);draft=stored['drafts'][-1]
        draft['status']='font_unverified';self.h.save(stored)
        self.assertTrue(self.h.get('p',s['id'])['drafts'][-1]['can_apply_after_reference_review'])
        with patch.object(self.h,'commit_draft'):
            applied=self.h.draft_action('p',s['id'],draft['id'],'apply')
        self.assertEqual(applied['drafts'][-1]['status'],'applied')
        self.assertEqual(applied['drafts'][-1]['application_checks_advisory']['previous_status'],'font_unverified')
        stored=self.h.load('p',s['id']);draft=stored['drafts'][-1]
        draft['status']='validation_failed';draft['data_report']={'status':'fail'};self.h.save(stored)
        with patch.object(self.h,'commit_draft') as commit:
            result=self.h.draft_action('p',s['id'],draft['id'],'apply')
        commit.assert_called_once();self.assertEqual(result['drafts'][-1]['status'],'applied')

    def test_three_real_model_payloads_extract_generate_compare(self):
        self.h=ChatHarness(server,renderer=self.render)
        features=[{'feature_id':'f1','reference_id':self.image['reference_id'],'name':'颜色',
                   'expected':'红色','evidence':'参考图可见红色','transfer':'style'}]
        payloads=[]
        def provider(request,timeout):
            payload=json.loads(request.data);payloads.append(payload)
            body=json.loads(payload['messages'][-1]['content'][0]['text'])
            if len(payloads)==1:response={'features':features}
            elif len(payloads)==2:response=self.agent(body)
            else:response={'items':[{'feature_id':'f1','status':'different','observed':'红色面积不同','reason':'实际候选与参考布局存在差异'}]}
            return FakeStream(json.dumps(response))
        config={'vision_enabled':True,'api_key':'synthetic-test-token','api_url':'https://example.test/v1/chat/completions','model':'test','max_output_tokens':1024}
        with patch('chat_harness.effective_model_config',return_value=config),patch('chat_agent.urllib.request.urlopen',side_effect=provider):
            s=self.h.create('p',['a'])
            result=self.h.turn('p',s['id'],{'user_message':'参照这个图改图','reference_image_ids':[self.image['reference_id']]})
        draft=result['drafts'][-1];calls=result['turns'][-1]['results'][0]['model_calls']
        self.assertEqual([c['stage'] for c in calls],['extract','generate','compare'])
        self.assertEqual(result['turns'][-1]['results'][0]['model_attempts'],3)
        self.assertEqual(draft['status'],'preview_ready',draft.get('reason'))
        self.assertEqual(draft['reference_comparison']['status'],'different')
        code_context=json.loads(payloads[1]['messages'][-1]['content'][0]['text'])
        self.assertEqual(code_context['reference_features']['features'],features)
        comparison_content=payloads[2]['messages'][-1]['content']
        comparison_context=json.loads(comparison_content[0]['text'])
        self.assertEqual(comparison_context['image_order'],['candidate_render',self.image['reference_id']])
        self.assertNotIn('source_files',comparison_context)
        actual=Image.open(io.BytesIO(base64.b64decode(comparison_content[1]['image_url']['url'].split(',')[1])))
        self.assertEqual(actual.getpixel((0,0)),(255,0,0))

    def test_missing_extraction_stops_generation_and_exhausted_review_is_unverified(self):
        self.h.visual_agent=lambda ctx:{'features':[]}
        s=self.h.create('p',['a'])
        result=self.h.turn('p',s['id'],{'user_message':'参照图修改','reference_image_ids':[self.image['reference_id']]})
        self.assertEqual(self.calls,[])
        self.assertEqual(result['turns'][-1]['results'][0]['status'],'cannot_complete')
        self.h.visual_agent=self.visual
        def used_budget(ctx):
            response=self.agent(ctx);ctx['_model_attempt_budget']['used']=3;return response
        self.h.agent=used_budget
        result=self.h.turn('p',s['id'],{'user_message':'参照图修改','reference_image_ids':[self.image['reference_id']]})
        draft=result['drafts'][-1]
        self.assertEqual(draft['status'],'preview_ready')
        self.assertEqual(draft['reference_comparison']['status'],'unverified')
        self.assertEqual(sum(c['_reference_visual_task']=='compare' for c in self.visual_calls),0)

    def test_uploads_require_vision_and_do_not_silently_use_local_fast_path(self):
        s=self.h.create('p',['a'])
        with patch('chat_harness.effective_model_config',return_value={'vision_enabled':False}):
            with self.assertRaisesRegex(ValueError,'图片输入'):
                self.h.turn('p',s['id'],{'user_message':'折线颜色改为红色','reference_image_ids':[self.image['reference_id']]})
        self.assertEqual(self.h.load('p',s['id'])['turns'],[])
        self.h.turn('p',s['id'],{'user_message':'折线颜色改为红色','reference_image_ids':[self.image['reference_id']]})
        self.assertEqual(len(self.calls),1)

    def test_all_three_uploads_fit_alongside_target(self):
        raw=base64.b64decode(picture('blue').split(',')[1]);server.save_preview(self.project,'a',SOURCE,raw)
        s=self.h.create('p',['a'])
        refs=[self.image]+[store(self.directory,'p',{'name':'ref.png','data_url':picture()}) for _ in range(2)]
        self.h.turn('p',s['id'],{'user_message':'希望改得和参考图类似','reference_image_ids':[r['reference_id'] for r in refs]})
        ctx=self.calls[-1];self.assertEqual(len(ctx['_images']),4);self.assertEqual(ctx['image_order'][0],'current_target')
        self.assertEqual(set(ctx['image_order'][1:]),{r['reference_id'] for r in refs})

    def test_actual_model_payload_contains_pixels_and_pinned_metadata(self):
        import chat_agent
        s=self.h.create('p',['a']);session=self.h.load('p',s['id'])
        turn={'id':'t','operation':'chat_edit','user_message':'希望和参考图类似','reference_images':[self.image]}
        ctx=self.h.context(session,session['charts'][0],turn,None,None,skip_font_audit=True)
        response=self.agent(ctx);requests=[]
        def provider(request,timeout):
            requests.append(json.loads(request.data));return FakeStream(json.dumps(response))
        ctx['_model_auth']={'api_key':'synthetic-test-token','api_url':'https://example.test/v1/chat/completions','vision_enabled':True,'model':'test','max_output_tokens':1024}
        with patch('chat_agent.urllib.request.urlopen',side_effect=provider):checked=chat_agent.propose(ctx)
        self.assertEqual(checked['status'],'candidate')
        content=requests[0]['messages'][-1]['content'];self.assertEqual(content[1]['type'],'image_url')
        self.assertTrue(content[1]['image_url']['url'].startswith('data:image/png;base64,'))
        text=json.loads(content[0]['text']);self.assertEqual(text['reference_images'][0]['reference_id'],self.image['reference_id'])
        self.assertEqual(text['image_order'],[self.image['reference_id']]);self.assertNotIn('_image',text['reference_images'][0])
        with patch('chat_agent.urllib.request.urlopen',side_effect=AssertionError('must not send text-only request')):
            ctx['_model_auth']['vision_enabled']=False
            with self.assertRaisesRegex(ValueError,'未传给模型'):chat_agent.propose(ctx)

    def test_http_upload_and_preview_endpoint(self):
        http=ThreadingHTTPServer(('127.0.0.1',0),server.Handler);thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
        self.addCleanup(http.server_close);self.addCleanup(http.shutdown)
        port=http.server_address[1];url=f'http://127.0.0.1:{port}'
        with patch.dict('os.environ',{'CHART_STUDIO_PORT':str(port)}),patch.object(server,'CHAT',self.h):
            request=urllib.request.Request(url+'/api/projects/p/chat/reference-images',data=json.dumps({'name':'style.png','data_url':picture()}).encode(),headers={'Content-Type':'application/json'})
            with urllib.request.urlopen(request) as result:meta=json.load(result)
            with urllib.request.urlopen(url+meta['image_url']) as result:
                self.assertEqual(result.headers['Content-Type'],'image/png');self.assertTrue(result.read().startswith(b'\x89PNG'))

    def test_type_inference_never_waives_data_verification_or_type_preservation(self):
        ctx={'reference_images':[self.image],'image_order':[self.image['reference_id']],'user_message':'希望画得和这个图类似'}
        proposal={'interpreted_request':{'operations':[{'property':'chart_type','desired_change':'violinplot'}]}}
        self.assertEqual(inferred_distribution(ctx,proposal),'violinplot')
        from chart_transform import verify_distribution
        checked=verify_distribution(self.project,'a',{**ctx,'plot_data':[]},proposal,{})
        self.assertEqual(checked['status'],'unverified')
        for text in ('只参考配色，图型保持不变','参考布局，图类型不变','把字大一点'):
            self.assertIsNone(inferred_distribution({**ctx,'user_message':text},proposal))
