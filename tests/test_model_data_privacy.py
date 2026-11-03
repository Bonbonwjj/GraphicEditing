import json
import unittest
from unittest.mock import patch

import chat_agent
import llm_workflows
import normalizer_agent


class ModelDataPrivacyTests(unittest.TestCase):
    def test_chat_context_never_contains_original_rows(self):
        item = {'path':'data/private.csv','columns':['subject','score'],
                'source_row_count':2,'content':'subject,score\nalice,99\nbob,42\n'}
        safe, used = chat_agent._csv_excerpt(item, 100000)
        self.assertEqual(used, len('subject,score'))
        self.assertEqual(safe['content'], 'subject,score')
        self.assertEqual(safe['content_scope'], 'schema_only')
        self.assertNotIn('alice', json.dumps(safe))

    def test_normalizer_never_contains_original_rows(self):
        safe = normalizer_agent.compact_model_data([
            {'path':'data/private.csv','columns':['x'],'content':'x\nSECRET_VALUE\n'}])
        self.assertEqual(safe[0]['content'], 'x')
        self.assertNotIn('SECRET_VALUE', json.dumps(safe))

    @patch('llm_workflows.llm_client.chat')
    def test_legacy_edit_sends_schema_but_not_values(self, model):
        model.return_value = '''import os
from pathlib import Path
import matplotlib.pyplot as plt
project=Path(os.environ["CHART_PROJECT_DIR"])
plt.plot([1])
plt.savefig(os.environ["CHART_OUTPUT"])
'''
        llm_workflows.edit_chart('red line', model.return_value,
            [{'path':'data/private.csv','columns':['x'],'content':'x\nSECRET_VALUE\n'}])
        request_text = model.call_args.args[0][1]['content']
        self.assertIn('private.csv', request_text)
        self.assertIn('columns', request_text)
        self.assertNotIn('SECRET_VALUE', request_text)


if __name__ == '__main__':
    unittest.main()
