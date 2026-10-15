"""Focused checks for page configuration without storing a real credential."""
import io
import http.client
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import model_config
import chat_agent


class FakeKeyring:
    def __init__(self):
        self.values = {}

    def get_password(self, service, account):
        return self.values.get((service, account))

    def set_password(self, service, account, value):
        self.values[(service, account)] = value

    def delete_password(self, service, account):
        self.values.pop((service, account), None)


class FakeResponse:
    def __init__(self, value):
        self.data = io.BytesIO(json.dumps(value).encode())

    def __enter__(self):
        return self.data

    def __exit__(self, *args):
        self.data.close()


class FakeStream:
    def __init__(self, text):
        events = [
            {'choices': [{'delta': {'role': 'assistant'}, 'finish_reason': None}]},
            {'choices': [{'delta': {'reasoning': 'private reasoning'}, 'finish_reason': None}]},
            {'choices': [{'delta': {'content': text[:len(text)//2]}, 'finish_reason': None}]},
            {'choices': [{'delta': {'content': text[len(text)//2:]}, 'finish_reason': 'stop'}]},
            {'choices': [], 'usage': {'total_tokens': 1}},
        ]
        self.data = io.BytesIO(b''.join(b'data: ' + json.dumps(event).encode() + b'\n\n' for event in events) + b'data: [DONE]\n\n')

    def __enter__(self):
        return self.data

    def __exit__(self, *args):
        self.data.close()


class ModelConfigTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.keyring = FakeKeyring()
        self.config = patch.object(model_config, 'CONFIG_PATH', Path(self.folder.name) / 'settings.json')
        self.backend = patch.object(model_config, 'keyring', self.keyring)
        self.environment = patch.dict('os.environ', {'OPENAI_API_KEY': '', 'LLM_API_URL': '', 'LLM_MODEL': ''})
        self.config.start(); self.backend.start(); self.environment.start()

    def tearDown(self):
        self.environment.stop(); self.backend.stop(); self.config.stop(); self.folder.cleanup()

    def values(self, key='private-test-token'):
        return {'api_url': 'https://example.test/v1/chat/completions', 'model': 'test-model', 'api_key': key}

    def test_save_is_private_and_read_never_returns_key(self):
        shown = model_config.save(self.values())
        self.assertTrue(shown['key_configured'])
        self.assertEqual(shown['key_source'], 'keychain')
        self.assertNotIn('private-test-token', json.dumps(shown))
        self.assertNotIn('private-test-token', model_config.CONFIG_PATH.read_text())
        self.assertEqual(model_config.CONFIG_PATH.stat().st_mode & 0o777, 0o600)
        self.assertEqual(model_config.effective()['api_key'], 'private-test-token')

    def test_blank_key_keeps_existing_and_clear_removes_it(self):
        model_config.save(self.values())
        model_config.save(self.values(''))
        self.assertEqual(model_config.effective()['api_key'], 'private-test-token')
        self.assertFalse(model_config.clear()['key_configured'])
        self.assertFalse(model_config.CONFIG_PATH.exists())

    def test_bad_url_and_first_blank_key_do_not_save(self):
        for url in ('http://example.test/v1/chat/completions', 'https://user:pass@example.test/', 'ftp://example.test'):
            with self.assertRaises(ValueError): model_config.save({**self.values(), 'api_url': url})
        with self.assertRaisesRegex(ValueError, '首次保存'):
            model_config.save(self.values(''))
        self.assertFalse(model_config.CONFIG_PATH.exists())

    def test_connection_sends_only_constant_probe(self):
        model_config.save(self.values())
        captured = []
        def fake_open(req, timeout):
            captured.append(req)
            return FakeResponse({'choices': [{'message': {'content': 'OK'}}]})
        with patch.object(model_config.request, 'urlopen', side_effect=fake_open):
            self.assertTrue(model_config.test_connection()['connected'])
        self.assertEqual(captured[0].get_header('Authorization'), 'Bearer private-test-token')
        body = json.loads(captured[0].data)
        self.assertNotIn('CSV', json.dumps(body))
        self.assertEqual(body['messages'][0]['content'], 'Reply OK.')

    def test_chat_agent_removes_auth_before_model_prompt(self):
        model_config.save(self.values())
        context = {name: None for name in chat_agent.ECHO_FIELDS}
        context.update({'chart_id': 'cht_test', 'user_message': 'Change the line',
                        'allowed_write_paths': [], 'source_files': [], 'plot_data': [],
                        '_model_auth': model_config.effective()})
        response = {name: context[name] for name in chat_agent.ECHO_FIELDS}
        response.update({'status': 'needs_clarification', 'interpreted_request': {}, 'intent_check': {},
                         'proposed_files': [], 'reason': 'Need a target'})
        requests = []
        def fake_open(req, timeout):
            requests.append(req)
            return FakeStream(json.dumps(response))
        with patch.object(chat_agent.urllib.request, 'urlopen', side_effect=fake_open):
            self.assertEqual(chat_agent.propose(context)['status'], 'needs_clarification')
        payload = json.loads(requests[0].data)
        self.assertEqual(requests[0].get_header('Authorization'), 'Bearer private-test-token')
        self.assertNotIn('private-test-token', json.dumps(payload))
        self.assertTrue(payload['stream'])

    def test_stream_rejects_truncated_output(self):
        event = {'choices': [{'delta': {'content': '{"incomplete":'}, 'finish_reason': 'length'}]}
        stream = io.BytesIO(b'data: ' + json.dumps(event).encode() + b'\n\ndata: [DONE]\n\n')
        with self.assertRaisesRegex(ValueError, '输出被截断'):
            chat_agent.read_model_response(stream, requested_max_tokens=1024)

    def test_chat_agent_reports_provider_disconnect(self):
        context={name:None for name in chat_agent.ECHO_FIELDS}
        context.update({'chart_id':'cht_test', 'user_message':'Change the line', 'allowed_write_paths':[],
                        'source_files':[], 'plot_data':[],
                        '_model_auth':{'api_key':'private-test-token','api_url':'https://example.test/v1/chat/completions','model':'test-model'}})
        with patch.object(chat_agent.urllib.request,'urlopen',side_effect=http.client.RemoteDisconnected('closed')):
            with self.assertRaisesRegex(ValueError,'提前断开连接'):
                chat_agent.propose(context)


if __name__ == '__main__':
    unittest.main()
