"""Compact model responses keep the existing local validation boundaries."""
import copy
import csv
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import chat_agent
from tests.test_model_config import FakeStream


class CompactResponseTests(unittest.TestCase):
    def test_skill_references_are_loaded_only_for_relevant_context(self):
        context={'user_message':'修改颜色','source_files':[{'writable':True,'content':'UNIVERSAL_FIGURE="x"'}],
                 'plot_data':[{'content_scope':'truncated_sample','source_row_count':None}]}
        instruction,references=chat_agent.skill_guidance(context)
        self.assertEqual(references,['adapters.md','large-data.md'])
        self.assertIn('UNIVERSAL_SOURCE_EDITS',instruction)
        self.assertIn('sample length is never the full sample size',instruction)
        self.assertNotIn('multiply by 1.2',instruction)
        instruction,references=chat_agent.skill_guidance({**context,'user_message':'字体大一些'})
        self.assertIn('appearance.md',references)
        self.assertIn('scatter area s by 1.44',instruction)

    def test_presentation_only_edit_sends_schema_without_numeric_rows(self):
        context=copy.deepcopy(self.context)
        context['user_message']='将配色改为深紫到浅粉'
        context['_model_auth']={'api_key':'test-key','api_url':'https://example.test/v1/chat/completions','model':'test-model'}
        response=copy.deepcopy(self.response)
        response['interpreted_request']['operations'][0]['source_quotes']=[context['user_message']]
        with patch.object(chat_agent.urllib.request,'urlopen',return_value=FakeStream(json.dumps(response))) as request:
            chat_agent.propose(context)
        supplied=json.loads(json.loads(request.call_args.args[0].data)['messages'][-1]['content'])
        self.assertTrue(supplied['plot_data'])
        self.assertTrue(all(item['content_scope']=='schema_only' for item in supplied['plot_data']))
        self.assertEqual([item['content'].splitlines() for item in supplied['plot_data']],
                         [[original['content'].splitlines()[0]] for original in context['plot_data']])
        self.assertTrue(any(item['content'] for item in context['plot_data']))

    def test_numeric_palette_choice_inherits_presentation_intent(self):
        context=copy.deepcopy(self.context)
        context['user_message']='2'
        context['conversation_context']={'recent_turns':[{'user_message':'更换图a的色谱',
            'message':'请选择 1、2 或 3 种配色'}]}
        self.assertTrue(chat_agent.presentation_only_edit(context))

    def test_simple_edit_shortens_prompt_without_removing_target_or_data(self):
        context=copy.deepcopy(self.context)
        context['user_message']='更改为折线图，横纵坐标加粗'
        context['reference_charts']=[]
        context['_model_auth']={'api_key':'test-key','api_url':'https://example.test/v1/chat/completions','model':'test-model'}
        response=copy.deepcopy(self.response)
        response['interpreted_request']['operations'][0]['source_quotes']=[context['user_message']]
        captured=[]
        def send(request,timeout):
            captured.append(json.loads(request.data))
            return FakeStream(json.dumps(response))
        with patch.object(chat_agent.urllib.request,'urlopen',side_effect=send):
            chat_agent.propose(context)
        fast=captured[0]
        with patch.object(chat_agent,'simple_edit',return_value=False),patch.object(chat_agent.urllib.request,'urlopen',side_effect=send):
            chat_agent.propose(context)
        full=captured[1]
        self.assertLess(len(json.dumps(fast)),len(json.dumps(full))*.7)
        self.assertEqual(fast['model'],full['model'])
        fast_context=json.loads(fast['messages'][-1]['content'])
        full_context=json.loads(full['messages'][-1]['content'])
        self.assertEqual([f['content'] for f in fast_context['source_files']],
                         [f['content'] for f in full_context['source_files']])
        self.assertEqual([(d['path'],d.get('columns')) for d in fast_context['plot_data']],
                         [(d['path'],d.get('columns')) for d in full_context['plot_data']])
        self.assertTrue(all(d['content']=='' and d['content_scope']=='schema_only' for d in fast_context['plot_data']))
        self.assertTrue(any(d['content'] for d in context['plot_data']))
        self.assertLess(len(json.dumps(fast)),5000)

    def test_fast_edit_rejects_unmatched_clauses_and_complex_context(self):
        message='更改为折线图，横纵坐标加粗'
        self.assertTrue(chat_agent.simple_edit(message,{}))
        for extra in ('，数据乘以2','，并删除异常值','，只改图c','，参考图A的颜色','，不要修改'):
            self.assertFalse(chat_agent.simple_edit(message+extra,{}))
        for field in ('reference_charts','layout_exception','harness_layout_feedback'):
            self.assertFalse(chat_agent.simple_edit(message,{field:[{'id':'present'}]}))

    def test_answer_passes_model_transport_in_one_call_with_configured_identity(self):
        context=copy.deepcopy(self.context);context['user_message']='你是什么模型？'
        context['_model_auth']={'api_key':'test-key','api_url':'https://example.test/v1/chat/completions','model':'configured-test-model'}
        answer={'status':'answer','message':'应用配置的模型是 configured-test-model，无法独立核实后端实现。','proposed_files':[]}
        with patch.object(chat_agent.urllib.request,'urlopen',return_value=FakeStream(json.dumps(answer))) as request:
            response=chat_agent.propose(context)
        self.assertEqual(response['status'],'answer');self.assertEqual(request.call_count,1)
        payload=json.loads(request.call_args.args[0].data)
        supplied=json.loads(payload['messages'][-1]['content'])
        self.assertEqual(supplied['model_connection']['configured_model'],'configured-test-model')
        self.assertEqual(supplied['model_connection']['endpoint_host'],'example.test')
        self.assertNotIn('test-key',json.dumps(payload))
        self.assertLess(len(json.dumps(payload)),2000)
        self.assertNotIn('source_files',supplied)
        self.assertNotIn('plot_data',supplied)

    def test_mixed_and_ambiguous_requests_never_take_lightweight_route(self):
        for message in ('你是什么模型，顺便把图c改成散点','你好，线宽改成2',
                        '能把图c改成散点吗？','再往左一点','散点图是什么？'):
            with self.subTest(message=message):
                self.assertFalse(chat_agent.lightweight_question(message))

    def test_plain_answer_needs_no_edit_schema_but_cannot_modify_files(self):
        answer={'status':'answer','message':'这是普通问答，图表未改变。','proposed_files':[]}
        expanded=chat_agent.expand_compact_response(self.context,answer)
        self.assertEqual(chat_agent.validate_response(self.context,expanded)['status'],'answer')
        for bad in ('', ' '*3, 'x'*12001, None):
            with self.subTest(message=repr(bad)[:20]),self.assertRaises(ValueError):
                chat_agent.validate_response(self.context,{**expanded,'message':bad})
        with self.assertRaises(ValueError):
            chat_agent.validate_response(self.context,{**expanded,'proposed_files':[{'path':'charts/b.py','content':'pass'}]})
        with self.assertRaises(ValueError):
            chat_agent.validate_response(self.context,{**expanded,'chart_id':'another-chart'})

    def setUp(self):
        root=Path(__file__).resolve().parents[1]
        self.context=json.loads((root/'docs/chat-acceptance/inputs/01.json').read_text())
        for data in self.context['plot_data']:
            data['columns']=next(csv.reader(io.StringIO(data['content'])))
        path=self.context['allowed_write_paths'][0]
        source=next(s for s in self.context['source_files'] if s['path']==path)
        self.response={'output_format':'compact_v1','status':'candidate',
            'interpreted_request':{'operations':[{'target_element':'Obs line','property':'linewidth',
                'current_value':None,'desired_change':2.5,'source_quotes':['线宽改成 2.5']}]},
            'intent_check':{'status':'consistent','unresolved_items':[]},
            'proposed_files':[{'path':path,'replacements':[{'old':source['content'],'new':source['content']+'\n# change\n'}]}],
            'read_data_refs':[{'path':d['path'],'columns':[{'name':name,'role':'plotting'} for name in d['columns']]}
                              for d in self.context['plot_data']]}

    def expanded(self,response=None):
        result=chat_agent.expand_compact_response(self.context,copy.deepcopy(response or self.response))
        return chat_agent.expand_compact_edits(self.context,result)

    def test_compact_response_passes_original_validator(self):
        result=self.expanded()
        self.assertEqual(chat_agent.validate_response(self.context,result)['status'],'candidate')
        self.assertEqual(result['user_message'],self.context['user_message'])
        self.assertEqual(result['expected_effects'][0]['verification_status'],'unverified')
        self.assertLess(len(json.dumps(self.response)),len(json.dumps(result)))

    def test_supplied_incorrect_scope_or_hash_is_not_overwritten(self):
        for kind in ('target','hash','quote','intent'):
            with self.subTest(kind=kind):
                response=copy.deepcopy(self.response)
                if kind=='target':response['interpreted_request']['operations'][0]['target_chart_id']='other'
                if kind=='hash':response['proposed_files'][0]['base_sha256']='wrong'
                if kind=='quote':response['interpreted_request']['operations'][0]['source_quotes']=['invented user quote']
                if kind=='intent':response['intent_check']['unresolved_items']=['Which line?']
                with self.assertRaises(ValueError):
                    chat_agent.validate_response(self.context,self.expanded(response))

    def test_data_columns_and_unresolved_intent_still_required(self):
        for key in ('read_data_refs','intent_check'):
            response=copy.deepcopy(self.response);response.pop(key)
            with self.subTest(key=key),self.assertRaises(ValueError):
                chat_agent.validate_response(self.context,self.expanded(response))

    def test_legacy_response_restores_only_request_metadata(self):
        response=copy.deepcopy(self.response);response.pop('output_format')
        response.pop('intent_check');response.pop('read_data_refs')
        expanded=chat_agent.expand_compact_response(self.context,response)
        self.assertEqual(expanded['base_revision'],self.context['base_revision'])
        self.assertNotIn('intent_check',expanded)
        self.assertNotIn('read_data_refs',expanded)

    def test_missing_or_empty_display_fields_do_not_block_valid_legacy_edit(self):
        for missing in (True,False):
            response=self.expanded();response.pop('output_format')
            if missing:
                response.pop('expected_effects');response.pop('warnings')
            else:
                response['expected_effects']=[];response['warnings']='实际提示必须保留'
            checked=chat_agent.validate_response(self.context,response)
            self.assertEqual(checked['status'],'candidate')
            self.assertTrue(checked['expected_effects'])
            self.assertEqual(checked['expected_effects'][0]['verification_status'],'unverified')
            if not missing:self.assertIn('实际提示必须保留',checked['warnings'])

    def test_malformed_json_and_missing_schema_share_three_attempts(self):
        context=copy.deepcopy(self.context)
        context['_model_auth']={'api_key':'test-key','api_url':'https://example.test/v1/chat/completions','model':'test-model'}
        context['_model_attempt_budget']={'used':0}
        bad=copy.deepcopy(self.response);bad.pop('intent_check')
        with patch.object(chat_agent.urllib.request,'urlopen',side_effect=[
                FakeStream('{bad json'),FakeStream(json.dumps(bad)),FakeStream(json.dumps(self.response))]) as request:
            checked=chat_agent.propose(context)
        self.assertEqual(checked['status'],'candidate')
        self.assertEqual(request.call_count,3)
        self.assertEqual(checked['model_attempts_used'],3)

    def test_redundant_parent_code_omitted_but_repair_candidate_kept(self):
        context=copy.deepcopy(self.context)
        sources={s['path']:s['content'] for s in context['source_files'] if s.get('writable')}
        context['harness_layout_feedback']={'candidate_code':sources,'layout':{'issues':['overlap']}}
        compact=chat_agent.compact_model_context(context)
        self.assertNotIn('candidate_code',compact['harness_layout_feedback'])
        self.assertEqual(context['harness_layout_feedback']['candidate_code'],sources)
        context['harness_layout_feedback']['candidate_code']={'charts/b.py':'different repair candidate'}
        self.assertIn('candidate_code',chat_agent.compact_model_context(context)['harness_layout_feedback'])

    def test_actual_model_path_expands_compact_response(self):
        context=copy.deepcopy(self.context)
        context['_model_auth']={'api_key':'test-key','api_url':'https://example.test/v1/chat/completions',
                                'model':'test-model','max_output_tokens':16384}
        with patch.object(chat_agent.urllib.request,'urlopen',return_value=FakeStream(json.dumps(self.response))) as request:
            result=chat_agent.propose(context)
        self.assertEqual(result['status'],'candidate')
        payload=json.loads(request.call_args.args[0].data)
        self.assertEqual(payload['max_tokens'],16384)
        self.assertIn('compact_v1',payload['messages'][0]['content'])
        self.assertIn('Do NOT ask the user to choose a second chart',payload['messages'][0]['content'])

    def test_schema_corrections_stop_at_three_total_requests(self):
        context=copy.deepcopy(self.context)
        context['_model_auth']={'api_key':'test-key','api_url':'https://example.test/v1/chat/completions','model':'test-model'}
        context['_model_attempt_budget']={'used':0}
        bad=copy.deepcopy(self.response);bad['interpreted_request']['operations'][0]['target_chart_id']='wrong'
        with patch.object(chat_agent.urllib.request,'urlopen',side_effect=[
                FakeStream(json.dumps(bad)),FakeStream(json.dumps(bad)),FakeStream(json.dumps(self.response))]) as request:
            self.assertEqual(chat_agent.propose(context)['model_attempts_used'],3)
            with self.assertRaisesRegex(ValueError,'3 次上限'):chat_agent.propose(context)
            self.assertEqual(request.call_count,3)

    def test_schema_retries_share_budget_with_followup_repair(self):
        context=copy.deepcopy(self.context)
        context['_model_auth']={'api_key':'test-key','api_url':'https://example.test/v1/chat/completions','model':'test-model'}
        context['_model_attempt_budget']={'used':0}
        bad=copy.deepcopy(self.response);bad['interpreted_request']['operations'][0]['target_chart_id']='wrong'
        with patch.object(chat_agent.urllib.request,'urlopen',side_effect=[
                FakeStream(json.dumps(bad)),FakeStream(json.dumps(self.response)),FakeStream(json.dumps(bad))]) as request:
            self.assertEqual(chat_agent.propose(context)['model_attempts_used'],2)
            with self.assertRaises(chat_agent.TargetMismatch):chat_agent.propose(context)
            self.assertEqual(context['_model_attempt_budget']['used'],3)
            self.assertEqual(request.call_count,3)


if __name__=='__main__':unittest.main()
