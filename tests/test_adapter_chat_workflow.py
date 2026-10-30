"""Adapter presentation routing and exact data-reference identity."""
import copy
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import chat_agent
from tests.test_model_config import FakeStream


ADAPTER = '''from universal_plot_runtime import render_original
UNIVERSAL_FIGURE = 'example'
UNIVERSAL_SOURCE_EDITS = {}
def customize(figure):
    pass
render_original(UNIVERSAL_FIGURE, customize, UNIVERSAL_SOURCE_EDITS)
'''
CUSTOMIZED = ADAPTER.replace('    pass', '''    for ax in figure.axes:
        for spine in ax.spines.values():
            spine.set_linewidth(2)
        ax.tick_params(width=2)''')


class AdapterChatWorkflowTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1]
        self.context = json.loads((root/'docs/chat-acceptance/inputs/01.json').read_text())
        self.context['user_message'] = '将图的轴加粗'
        path = self.context['allowed_write_paths'][0]
        self.context['source_files'] = [
            {'path':path,'content':ADAPTER,'sha256':'sha256:'+hashlib.sha256(ADAPTER.encode()).hexdigest(),'writable':True},
            {'path':'universal-project.json','content':json.dumps({'schema':'plot-forge-universal/1',
                'source_root':'lib/universal/source'}),'sha256':'registry','writable':False},
            {'path':'lib/universal/source/analysis.py','content':'# analysis\n'*30000,'sha256':'analysis','writable':False}]
        self.context['plot_data'] = [{'path':'lib/universal/source/group a/values.csv','sha256':'data-hash',
            'columns':['x','y'],'content':'x,y\n1,2\n','format':'csv'}]
        self.response = {'output_format':'compact_v1','status':'candidate','summary':'轴线与刻度线加粗至 2。',
            'interpreted_request':{'operations':[{'target_element':'axes','property':'linewidth',
                'current_value':None,'desired_change':2,'source_quotes':['将图的轴加粗']}]},
            'intent_check':{'status':'consistent','unresolved_items':[]},
            'proposed_files':[{'path':path,'replacements':[{'old':'    pass','new':CUSTOMIZED.split('def customize(figure):\n')[1].split('\nrender_original')[0]}]}],
            'data_access':'preserve_existing','read_data_refs':[]}

    def expanded(self, response=None):
        value = chat_agent.expand_compact_response(self.context, copy.deepcopy(response or self.response))
        return chat_agent.expand_compact_edits(self.context, value)

    def test_axes_bold_adapter_does_not_require_inherited_csv_references(self):
        response = chat_agent.validate_response(self.context, self.expanded())
        self.assertEqual(response['status'], 'candidate')
        self.assertEqual(response['read_data_refs'], [])
        self.assertTrue(chat_agent.customize_only(self.context, response['proposed_files']))

    def test_cosmetic_model_request_omits_analysis_and_all_numeric_data(self):
        context = copy.deepcopy(self.context)
        context['_model_auth'] = {'api_key':'test','api_url':'https://example.test/v1/chat/completions'}
        with patch.object(chat_agent.urllib.request, 'urlopen', return_value=FakeStream(json.dumps(self.response))) as request:
            result = chat_agent.propose(context)
        self.assertEqual(result['model_attempts_used'], 1)
        payload = json.loads(request.call_args.args[0].data)
        supplied = json.loads(payload['messages'][-1]['content'])
        self.assertEqual(supplied['plot_data'], [])
        self.assertTrue(all(item['writable'] for item in supplied['source_files']))
        self.assertEqual(supplied['data_access_policy']['mode'], 'preserve_existing')
        self.assertLess(len(json.dumps(supplied)), 15000)

    def test_scientific_mixed_requests_do_not_take_style_route(self):
        for message in ('轴加粗并过滤异常值','轴加粗并改成箱线图','轴加粗并重新计算均值','坐标范围改为0到2，刻度加粗'):
            self.assertFalse(chat_agent.adapter_style_context({**self.context,'user_message':message}))

    def test_preserve_existing_cannot_change_adapter_wiring_or_add_readers(self):
        response = self.expanded()
        for source in (CUSTOMIZED.replace("'example'", "'other'"),
                       CUSTOMIZED.replace('UNIVERSAL_SOURCE_EDITS = {}', "UNIVERSAL_SOURCE_EDITS = {'analysis.py': []}"),
                       CUSTOMIZED.replace('    for ax', "    data = open('other.csv').read()\n    for ax"),
                       CUSTOMIZED.replace('    for ax', '    import pandas\n    for ax')):
            with self.subTest(source=source):
                bad = copy.deepcopy(response);bad['proposed_files'][0]['content'] = source
                with self.assertRaises(chat_agent.OperationSchemaMismatch):
                    chat_agent.validate_response(self.context, bad)

    def test_registry_relative_alias_is_canonicalized_without_guessing(self):
        response = copy.deepcopy(self.response)
        response.pop('data_access')
        response['read_data_refs'] = [{'path':'group a/values.csv','columns':[{'name':'x','role':'x coordinate'}]}]
        result = self.expanded(response)
        ref = result['read_data_refs'][0]
        self.assertEqual(ref['path'], self.context['plot_data'][0]['path'])
        self.assertEqual(ref['sha256'], 'data-hash')
        chat_agent.validate_response(self.context, result)
        for path in ('values.csv','../group a/values.csv','/tmp/runtime/group a/values.csv','group b/values.csv'):
            self.assertIsNone(chat_agent.canonical_data_path(self.context, path))

    def test_incorrect_hash_and_unknown_column_remain_rejected(self):
        for fields in ({'sha256':'stale','columns':[{'name':'x','role':'x'}]},
                       {'columns':[{'name':'guessed','role':'x'}]}):
            response = copy.deepcopy(self.response);response.pop('data_access')
            response['read_data_refs'] = [{'path':'group a/values.csv',**fields}]
            with self.assertRaises(chat_agent.OperationSchemaMismatch):
                chat_agent.validate_response(self.context, self.expanded(response))

    def test_host_root_metadata_works_without_registry_source_in_prompt(self):
        self.context['source_files'] = [s for s in self.context['source_files'] if s['path'].endswith('.py')]
        self.context['data_reference_roots'] = ['lib/universal/source']
        self.assertEqual(chat_agent.canonical_data_path(self.context, 'group a/values.csv'),
                         'lib/universal/source/group a/values.csv')
        self.context['data_reference_roots'].append('data')
        self.context['plot_data'].append({'path':'data/group a/values.csv'})
        self.assertIsNone(chat_agent.canonical_data_path(self.context, 'group a/values.csv'))

    def test_existing_hook_imports_are_preserved_but_cannot_be_changed(self):
        source = self.context['source_files'][0]
        source['content'] = ADAPTER.replace('    pass', '    from native_plot_runtime import panel_axes\n    pass')
        source['sha256'] = 'updated'
        response = self.expanded()
        self.assertTrue(chat_agent.customize_only(self.context, response['proposed_files']))
        response['proposed_files'][0]['content'] = response['proposed_files'][0]['content'].replace('import panel_axes','import prepare_native')
        self.assertFalse(chat_agent.customize_only(self.context, response['proposed_files']))

    def test_invalid_data_reference_gets_bounded_model_repair(self):
        context = copy.deepcopy(self.context)
        context['_model_auth'] = {'api_key':'test','api_url':'https://example.test/v1/chat/completions'}
        bad = copy.deepcopy(self.response);bad.pop('data_access')
        bad['read_data_refs'] = [{'path':'/tmp/guessed.csv','columns':[{'name':'x','role':'x'}]}]
        with patch.object(chat_agent.urllib.request, 'urlopen', side_effect=[
                FakeStream(json.dumps(bad)), FakeStream(json.dumps(self.response))]) as request:
            result = chat_agent.propose(context)
        self.assertEqual(request.call_count, 2)
        self.assertEqual(result['status'], 'candidate')
        self.assertEqual(result['model_attempts_used'], 2)


if __name__ == '__main__':
    unittest.main()
