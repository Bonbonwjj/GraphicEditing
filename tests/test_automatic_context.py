import copy
import json
import unittest
from unittest.mock import patch

import chat_agent
import panel_index
from automatic_context import infer_source_requests,input_mappings
from tests.test_model_config import FakeStream


class AutomaticContextTests(unittest.TestCase):
    def test_technical_clarification_is_read_automatically_but_user_choices_remain_choices(self):
        from automatic_context import technical_context_request
        self.assertTrue(technical_context_request({'status':'needs_clarification','question':'请提供源码函数和文件路径'}))
        self.assertFalse(technical_context_request({'status':'needs_clarification','question':'你希望选择哪个子图？'}))

    def test_automatic_source_followup_can_return_valid_edit_candidate(self):
        from tests.test_compact_chat_response import CompactResponseTests
        fixture=CompactResponseTests();fixture.setUp();context=copy.deepcopy(fixture.context)
        context['_model_auth']={'api_key':'fake','api_url':'https://example.test/v1/chat/completions'}
        context['source_files'].append({'path':'lib/helper.py','content':'def finalize():\n    axis.set_ylim(0, 10)\n','writable':False})
        context['panel_index']=panel_index.build_from_sources({v['path']:v['content'] for v in context['source_files']},'b')
        values=[{'status':'needs_context','reason':'需要确认最终坐标范围'},fixture.response]
        with patch.object(chat_agent.urllib.request,'urlopen',side_effect=lambda *a,**k:FakeStream(json.dumps(values.pop(0)))):
            result=chat_agent.propose(context)
        self.assertEqual(result['status'],'candidate');self.assertTrue(result['proposed_files'])

    def context(self):
        sources={'charts/fig.py':'import render\nrender.figure()\n',
            'lib/render.py':'def figure():\n    boxplot()\n    ax.set_ylim(0, 5)\n\ndef boxplot():\n    return original_groups\n\ndef read():\n    return pd.read_csv("values.csv")\n'}
        return {'user_message':'把箱型图改成小提琴图','source_files':[{'path':p,'content':v,'writable':p.startswith('charts/')} for p,v in sources.items()],
            'plot_data':[],'allowed_write_paths':['charts/fig.py'],'panel_index':panel_index.build_from_sources(sources,'fig'),
            '_model_auth':{'api_key':'fake','api_url':'https://example.test/v1/chat/completions'}}

    def test_bare_technical_status_reads_sources_and_continues_without_user_input(self):
        context=self.context();progress=[];context['_context_progress']=progress.append
        captured=[]
        def send(request,timeout):
            captured.append(json.loads(request.data))
            value=({'status':'needs_context','reason':'还需确认最终坐标范围及原始输入读取映射','question':'请提供函数名'}
                if len(captured)==1 else {'status':'answer','message':'已根据本地源码读取完整实现','proposed_files':[]})
            return FakeStream(json.dumps(value))
        with patch.object(chat_agent.urllib.request,'urlopen',side_effect=send):result=chat_agent.propose(context)
        self.assertEqual(result['status'],'answer');self.assertEqual(len(captured),2)
        supplied=json.loads(captured[1]['messages'][-1]['content'])
        text='\n'.join(item['content'] for item in supplied['requested_source'])
        self.assertIn('set_ylim',text);self.assertIn('read_csv',text)
        self.assertEqual(progress[0]['read_round'],1)
        self.assertNotIn('_context_progress',supplied)

    def test_context_reads_can_continue_past_three_calls_and_still_have_generation_budget(self):
        context=self.context();context['_model_attempt_budget']={'used':0}
        captured=[]
        def send(request,timeout):
            captured.append(json.loads(request.data));count=len(captured)
            value=({'status':'needs_context','reason':'Need implementation','source_requests':[{'path':'lib/render.py','start_line':1,'end_line':9}]}
                   if count<=4 else {'status':'answer','message':'读取后完成','proposed_files':[]})
            return FakeStream(json.dumps(value))
        with patch.object(chat_agent.urllib.request,'urlopen',side_effect=send):result=chat_agent.propose(context)
        self.assertEqual(result['status'],'answer');self.assertEqual(result['model_attempts_used'],5)
        self.assertEqual(context['_model_attempt_budget']['context_reads'],4)
        self.assertEqual(chat_agent.model_attempt_limit(context['_model_attempt_budget']),7)

    def test_exhausted_reads_do_not_ask_user_for_function_or_path(self):
        context=self.context();value={'status':'needs_context','reason':'Need technical mapping','question':'请提供源代码函数',
            'source_requests':[{'path':'lib/render.py','start_line':1,'end_line':9}]}
        with patch.object(chat_agent.urllib.request,'urlopen',side_effect=lambda *a,**k:FakeStream(json.dumps(value))) as send:
            result=chat_agent.propose(context)
        self.assertEqual(result['status'],'cannot_complete');self.assertNotIn('question',result)
        self.assertLessEqual(send.call_count,7)

    def test_input_mappings_expose_paths_and_schema_without_observation_arrays(self):
        files={'data/fig5_input_map.json':{'sha256':'sha256:1','content':json.dumps({'data':{'paired':{
            'path':'old2/h.csv','original':'/private/source','columns':['subject','DIS','All'],'values':[100,200]}}})}}
        result=input_mappings(files)
        descriptor=result[0]['mapping']['data']['paired']
        self.assertEqual(descriptor['path'],'old2/h.csv');self.assertNotIn('original',descriptor);self.assertNotIn('values',descriptor)

    def test_auto_reads_never_use_requested_external_paths(self):
        context=self.context();requests=infer_source_requests(context,'读取 ../secret 和最终坐标范围')
        self.assertTrue(requests)
        self.assertTrue(all(item['path']=='lib/render.py' for item in requests))


if __name__=='__main__':unittest.main()
