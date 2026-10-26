"""Offline OAuth/Responses regressions: no real account or provider calls."""
import base64
import hashlib
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse, urlencode
from urllib.request import Request

import chatgpt_auth as auth
import model_config
import model_transport as transport
from tests.test_model_config import FakeKeyring


def events(*items):
    return io.BytesIO(b''.join(b'data: '+json.dumps(item).encode()+b'\n\n' for item in items))


class ChatGPTConnectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = Path(self.temp.name)/'.model-api.json'
        self.vault = FakeKeyring()
        for item in (patch.object(model_config,'CONFIG_PATH',self.config),
                     patch.object(auth,'keyring',self.vault), patch.object(auth,'_record',None),
                     patch.object(auth,'_vault',return_value=self.vault),
                     patch.object(auth,'_storage','session'), patch.object(auth,'_pending',None),
                     patch.object(auth,'_retry_registration',None),
                     patch.object(auth,'_status','')):
            item.start(); self.addCleanup(item.stop)

    def record(self):
        return {'client_id':'client-test','access_token':'private-access','refresh_token':'private-refresh',
                'id_token':'private-identity','sub':'subject-test','email':'research@example.test',
                'scope':auth.SCOPE,'expires_at':time.time()+3600}

    def test_credentials_never_in_preferences_or_public_state(self):
        auth.save_record(self.record())
        shown=model_config.save({'provider':'chatgpt','model':'test','allow_code_upload':False})
        output=json.dumps(shown)+self.config.read_text()
        for secret in ('private-access','private-refresh','private-identity','subject-test','research@example.test'):
            self.assertNotIn(secret,output)
        self.assertTrue(shown['key_configured'])
        self.assertFalse(shown['allow_code_upload'])
        self.assertEqual(model_config.effective()['api_key'],'')

    def test_vault_unavailable_uses_memory_and_blocks_stale_restart(self):
        auth.save_record(self.record())
        with patch.object(self.vault,'set_password',side_effect=RuntimeError('locked')):
            auth.save_record({})
        self.assertEqual(auth.public()['storage'],'session')
        auth._record=None
        self.assertFalse(auth.public()['connected'])
        for path in Path(self.temp.name).iterdir():
            self.assertNotIn('private-',path.read_text())

    def test_pkce_state_nonce_loopback_and_official_origin(self):
        server=MagicMock(server_port=43123)
        with patch.object(auth,'ThreadingHTTPServer',return_value=server), patch.object(auth.threading,'Thread'), patch.object(auth.threading,'Timer'):
            result=auth.begin()
            url=urlparse(result['url']); query=parse_qs(url.query)
            self.assertEqual(url.netloc,'auth.openai.com')
            self.assertEqual(query['client_id'],['dynamic_agent_client'])
            self.assertEqual(query['redirect_uri'],['http://127.0.0.1:43123/auth/callback'])
            self.assertEqual(query['resource'],[auth.RESOURCE])
            challenge=base64.urlsafe_b64encode(hashlib.sha256(auth._pending['verifier'].encode()).digest()).rstrip(b'=').decode()
            self.assertEqual(query['code_challenge'],[challenge])
            self.assertNotEqual(query['state'],query['nonce'])
            self.assertNotIn('id_token_hint',query)

    def pending(self):
        auth._pending={'state':'correct-state','nonce':'correct-nonce','verifier':'private-verifier',
            'redirect_uri':'http://127.0.0.1:43123/auth/callback','expires':time.monotonic()+100,
            'client_id':None,'timer':MagicMock(),'server':MagicMock()}

    def test_wrong_state_and_duplicate_state_do_not_exchange(self):
        self.pending()
        with patch.object(auth,'_form') as exchange:
            for query in ('state=wrong&code=c','state=correct-state&state=correct-state&code=c'):
                with self.assertRaises(ValueError):auth.finish(query)
            exchange.assert_not_called()
            self.assertIsNotNone(auth._pending)

    def test_callback_scope_is_not_trusted_and_state_consumed_once(self):
        self.pending()
        response={'access_token':'private-access','id_token':'private-identity','scope':'openid'}
        with patch.object(auth,'_form',return_value=response), patch.object(auth,'verify_identity',return_value={'sub':'s'}):
            auth.finish(urlencode({'state':'correct-state','code':'c','client_id':'issued-client','scope':auth.SCOPE}))
            self.assertFalse(auth.public()['sharing'])
            with self.assertRaises(ValueError):auth.finish('state=correct-state&code=c&client_id=issued-client')

    def test_real_jwt_signature_audience_and_nonce_validation(self):
        import jwt
        from cryptography.hazmat.primitives.asymmetric import rsa
        key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        jwk=json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()));jwk['kid']='test-key'
        claims={'iss':auth.AUTH,'aud':'test-client','sub':'s','iat':int(time.time()),'exp':int(time.time())+60,'nonce':'nonce'}
        token=jwt.encode(claims,key,algorithm='RS256',headers={'kid':'test-key'})
        def response(*args,**kwargs):return io.BytesIO(json.dumps({'keys':[jwk]}).encode())
        with patch.object(auth,'secure_open',side_effect=response):
            self.assertEqual(auth.verify_identity(token,'test-client','nonce')['sub'],'s')
            with self.assertRaises(Exception):auth.verify_identity(token,'wrong-client','nonce')
            with self.assertRaises(ValueError):auth.verify_identity(token,'test-client','wrong-nonce')

    def test_refresh_rotates_without_requesting_more_scopes(self):
        record=self.record();record['expires_at']=0;auth.save_record(record)
        with patch.object(auth,'_form',return_value={'access_token':'rotated-access','refresh_token':'rotated-refresh','expires_in':300}) as exchange:
            self.assertEqual(auth.access_token(),'rotated-access')
            fields=exchange.call_args.args[1]
            self.assertNotIn('scope',fields)
            self.assertEqual(fields['client_id'],'client-test')
        self.assertEqual(auth.read_record()['refresh_token'],'rotated-refresh')

    def test_wrong_account_does_not_replace_existing_credentials(self):
        auth.save_record(self.record());self.pending();auth._pending.update(client_id='client-test',expected_sub='subject-test')
        with patch.object(auth,'_form',return_value={'id_token':'id','access_token':'replacement'}),patch.object(auth,'verify_identity',return_value={'sub':'different-sub'}):
            with self.assertRaises(ValueError):auth.finish('state=correct-state&code=c&client_id=client-test')
        self.assertEqual(auth.read_record()['access_token'],'private-access')

    def test_refresh_identity_mismatch_preserves_original_credentials(self):
        record=self.record();record['expires_at']=0;auth.save_record(record)
        with patch.object(auth,'_form',return_value={'access_token':'replacement','id_token':'new-id'}),patch.object(auth,'verify_identity',return_value={'sub':'wrong-account'}):
            with self.assertRaisesRegex(ValueError,'账户身份校验失败'):auth.access_token()
        self.assertEqual(auth.read_record()['access_token'],'private-access')

    def test_chatgpt_configuration_keeps_nonsecret_api_profile(self):
        model_config.CONFIG_PATH.write_text(json.dumps({'api_url':'https://example.test/v1/chat/completions','model':'old-model','max_output_tokens':12345}))
        auth.save_record(self.record())
        for _ in range(2):
            shown=model_config.save({'provider':'chatgpt','model':'new-model','allow_code_upload':False})
            self.assertEqual(shown['api_profile']['model'],'old-model')
            self.assertNotIn('api_key',shown['api_profile'])

    def test_failed_exchange_retains_issued_registration_for_retry(self):
        self.pending()
        with patch.object(auth,'_form',side_effect=ValueError('invalid_grant')):
            with self.assertRaises(ValueError):auth.finish('state=correct-state&code=c&client_id=issued-client')
        self.assertEqual(auth._retry_registration,'issued-client')
        self.assertFalse(auth.public()['connected'])

    def test_egress_consent_fails_before_token_or_network(self):
        req=Request(auth.RESOURCE+'/responses',data=json.dumps({'model':'test','messages':[{'role':'user','content':'source'}]}).encode())
        with patch.object(auth,'access_token') as token, patch.object(transport,'secure_open') as network:
            with self.assertRaisesRegex(ValueError,'外发尚未授权'):
                transport.open_completion(req,30,{'provider':'chatgpt'})
            token.assert_not_called();network.assert_not_called()

    def test_request_adaptation_no_paid_fallback_and_completed_gate(self):
        payload={'model':'test','messages':[{'role':'system','content':'instructions'},{'role':'user','content':'code'}],
                 'temperature':.2,'max_tokens':1000,'stream':True}
        req=Request('https://untrusted.test/proxy',data=json.dumps(payload).encode(),headers={'Authorization':'Bearer do-not-forward'})
        reply=events({'type':'response.output_text.delta','delta':'OK'},{'type':'response.completed','response':{'status':'completed'}})
        with patch.object(auth,'access_token',return_value='oauth-token'),patch.object(transport,'secure_open',return_value=reply) as network:
            result=transport.open_completion(req,30,{'provider':'chatgpt','allow_code_upload':True})
            self.assertIn(b'OK',result.read())
            sent=network.call_args.args[0]; body=json.loads(sent.data)
            self.assertEqual(sent.full_url,auth.RESOURCE+'/responses')
            self.assertFalse(body['store']);self.assertTrue(body['stream'])
            self.assertNotIn('temperature',body);self.assertNotIn('max_tokens',body)
            self.assertEqual(sent.get_header('Authorization'),'Bearer oauth-token')

    def test_truncated_failed_incomplete_streams_never_apply(self):
        for ending in (None, {'type':'response.failed','response':{'error':{'code':'limit'}}}, {'type':'response.incomplete'}):
            content=[{'type':'response.output_text.delta','delta':'partial-code'}]
            if ending:content.append(ending)
            with self.assertRaises(ValueError):transport.read_responses(events(*content))

    def test_literal_credentials_blocked_but_placeholder_allowed(self):
        for text in ['api_key = "abcdefghijklmnopqrstuvwx"', "password='abcdefghijklmnopqrstuvwx'", 'sk-'+('x'*30), '-----BEGIN PRIVATE KEY-----']:
            with self.assertRaises(ValueError):transport.guard_secrets([{'content':text}])
        transport.guard_secrets([{'content':'api_key = os.environ.get("KEY")'}])

    def test_redirect_never_forwards_authorization(self):
        req=Request(auth.RESOURCE,headers={'Authorization':'Bearer private-access'})
        with self.assertRaises(ValueError):auth.NoRedirect().redirect_request(req,None,302,'redirect',{},'https://other.test')


if __name__=='__main__':unittest.main()
