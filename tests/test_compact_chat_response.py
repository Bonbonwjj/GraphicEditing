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

    def test_missing_unique_anchor_and_bad_column_can_repair_within_same_budget(self):
        for kind in ('anchor','column'):
            context=copy.deepcopy(self.context)
            context['_model_auth']={'api_key':'test-key','api_url':'https://example.test/v1/chat/completions','model':'test-model'}
            context['_model_attempt_budget']={'used':0}
            bad=copy.deepcopy(self.response)
            if kind=='anchor':bad['proposed_files'][0]['replacements'][0]['old']='not in the current source'
            else:bad['read_data_refs'][0]['columns'][0]['name']='not_a_real_column'
            with self.subTest(kind=kind),patch.object(chat_agent.urllib.request,'urlopen',side_effect=[
                    FakeStream(json.dumps(bad)),FakeStream(json.dumps(self.response))]) as request:
                result=chat_agent.propose(context)
                self.assertEqual(result['status'],'candidate')
                self.assertEqual(request.call_count,2)
                self.assertEqual(context['_model_attempt_budget']['used'],2)

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
