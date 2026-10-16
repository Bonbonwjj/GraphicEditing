"""Focused checks for page configuration without storing a real credential."""
import io
import http.client
import json
import os
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
        self.session = patch.object(model_config, '_session_secret', None)
        self.session.start()

    def tearDown(self):
        self.session.stop()
        self.environment.stop(); self.backend.stop(); self.config.stop(); self.folder.cleanup()

    def values(self, key='private-test-token'):
        return {'api_url': 'https://example.test/v1/chat/completions', 'model': 'test-model', 'api_key': key}

    def test_default_model_and_address_with_saved_settings_preserved(self):
        shown = model_config.public()
        self.assertEqual(shown['api_url'], 'http://10.254.1.138:8080/api/v1/chat/completions')
        self.assertEqual(shown['model'], 'glm-5.3')
        with patch.object(model_config, 'INTRANET_URL', ''), patch.object(model_config, 'INTRANET_MODEL', ''):
            self.assertEqual(model_config.public()['intranet_preset'], {
                'api_url': shown['api_url'], 'model': shown['model']})
        model_config.save(self.values())
        self.assertEqual(model_config.public()['api_url'], self.values()['api_url'])
        self.assertEqual(model_config.public()['model'], self.values()['model'])

    def test_save_is_private_and_read_never_returns_key(self):
        shown = model_config.save(self.values())
        self.assertTrue(shown['key_configured'])
        self.assertEqual(shown['key_source'], 'keychain')
        self.assertNotIn('private-test-token', json.dumps(shown))
        self.assertNotIn('private-test-token', model_config.CONFIG_PATH.read_text(encoding="utf-8"))
        if os.name != "nt":
            self.assertEqual(model_config.CONFIG_PATH.stat().st_mode & 0o777, 0o600)
        self.assertEqual(model_config.effective()['api_key'], 'private-test-token')

    def test_blank_key_keeps_existing_and_clear_removes_it(self):
        model_config.save(self.values())
        model_config.save(self.values(''))
        self.assertEqual(model_config.effective()['api_key'], 'private-test-token')
        self.assertFalse(model_config.clear()['key_configured'])
        self.assertFalse(model_config.CONFIG_PATH.exists())

    @unittest.skipUnless(os.name == 'nt', 'Windows DPAPI integration')
    def test_windows_session_error_falls_back_to_encryption_and_can_clear(self):
        # Reproduce a backend exception outside the KeyringError hierarchy.
        from win32ctypes.pywin32.pywintypes import error
        failure = error(1312, 'CredWrite', 'logon session unavailable')
        with patch('windows_secret.transform', side_effect=lambda data, decrypt=False: data[4:][::-1] if decrypt else b'enc:' + data[::-1]), \
             patch.object(self.keyring, 'set_password', side_effect=failure), \
             patch.object(self.keyring, 'get_password', side_effect=failure):
            shown = model_config.save(self.values())
            self.assertEqual(shown['key_source'], 'windows_encrypted')
            self.assertNotIn('private-test-token', json.dumps(shown))
            self.assertNotIn(b'private-test-token', model_config._encrypted_path().read_bytes())
            self.assertEqual(model_config.effective()['api_key'], 'private-test-token')
            model_config.save(self.values(''))
            self.assertEqual(model_config.effective()['api_key'], 'private-test-token')
            self.assertFalse(model_config.clear()['key_configured'])
        # The old key must stay ignored even if Credential Manager recovers later.
        self.keyring.set_password(model_config.KEYRING_SERVICE, model_config.KEYRING_ACCOUNT, 'stale')
        self.assertFalse(model_config.public()['key_configured'])

    def test_bad_url_and_first_blank_key_do_not_save(self):
        for url in ('http://example.test/v1/chat/completions', 'https://user:pass@example.test/', 'ftp://example.test'):
            with self.assertRaises(ValueError): model_config.save({**self.values(), 'api_url': url})
        with self.assertRaisesRegex(ValueError, '首次保存'):
            model_config.save(self.values(''))
        self.assertFalse(model_config.CONFIG_PATH.exists())

    @unittest.skipUnless(os.name == 'nt', 'Windows fallback')
    def test_unavailable_vault_and_dpapi_use_memory_only(self):
        with patch.object(self.keyring, 'set_password', side_effect=RuntimeError('1312')), \
             patch.object(self.keyring, 'get_password', side_effect=RuntimeError('1312')), \
             patch('windows_secret.transform', side_effect=OSError('DPAPI unavailable')):
            shown = model_config.save(self.values())
            self.assertEqual(shown['key_source'], 'session')
            self.assertTrue(shown['key_configured'])
            self.assertNotIn('private-test-token', json.dumps(shown))
            self.assertFalse(model_config._encrypted_path().exists())
            model_config.save(self.values(''))
            self.assertEqual(model_config.effective()['api_key'], 'private-test-token')
            self.assertFalse(model_config.clear()['key_configured'])

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

    def test_404_reports_model_error_and_visible_models_without_key(self):
        from urllib.error import HTTPError
        model_config.save(self.values())
        failure = HTTPError(self.values()['api_url'], 404, 'Not Found', {},
                            io.BytesIO(b'{"error":{"message":"model unavailable private-test-token"}}'))
        with patch.object(model_config.request, 'urlopen', side_effect=[failure,
                FakeResponse({'data': [{'id': 'available-model'}]})]) as call:
            with self.assertRaises(ValueError) as caught:
                model_config.test_connection()
        self.assertIn('model unavailable', str(caught.exception))
        self.assertIn('available-model', str(caught.exception))
        self.assertNotIn('private-test-token', str(caught.exception))
        self.assertEqual(call.call_args_list[1].args[0].full_url, 'https://example.test/v1/models')

    def test_private_http_endpoints_can_be_saved_without_environment_preset(self):
        urls = ('http://10.254.1.138:8080/api/v1/chat/completions',
                'http://172.16.0.20:8000/v1/chat/completions',
                'http://192.168.1.20:8000/v1/chat/completions',
                'http://127.0.0.1:8000/v1/chat/completions',
                'http://[::1]:8000/v1/chat/completions',
                'http://[fd00::10]:8000/v1/chat/completions')
        with patch.object(model_config, 'INTRANET_URL', ''):
            for url in urls:
                with self.subTest(url=url):
                    shown = model_config.save({**self.values(), 'api_url': url})
                    self.assertEqual(shown['api_url'], url)

    def test_public_http_cannot_bypass_validation_via_saved_preferences(self):
        url = 'http://8.8.8.8/v1/chat/completions'
        model_config._write_preferences(url, 'test-model', False, 16384)
        with self.assertRaises(ValueError):
            model_config.validate_url(url)

    def test_invalid_port_whitespace_and_embedded_credentials_are_rejected(self):
        for url in ('http://10.0.0.1:99999/v1/chat/completions',
                    'http://10.0.0.1:abc/v1/chat/completions',
                    'http://10.0.0.1/line\nbreak',
                    'http://user:secret@10.0.0.1/v1/chat/completions'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                model_config.validate_url(url)

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
