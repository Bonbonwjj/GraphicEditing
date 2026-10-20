import unittest
from unittest.mock import patch
import model_connection as module

SETTINGS={'api_url':'https://example.test/v1/chat/completions','model':'test','api_key':'private-key'}


class ConnectionTests(unittest.TestCase):
    def setUp(self):
        self.now=1000.;self.monitor=module.ConnectionMonitor(clock=lambda:self.now)
        self.thread=patch.object(module.threading,'Thread').start();self.addCleanup(patch.stopall)
        self.transport=patch.object(module,'_transport',return_value=(True,'')).start()
        self.functional=patch('model_config.test_connection',side_effect=lambda:self.monitor.report(SETTINGS,True)).start()

    def check(self):
        self.monitor.status(SETTINGS)
        token=self.monitor.token
        self.monitor._check(SETTINGS,self.monitor.key,token,self.now)
        return self.monitor.status(SETTINGS)

    def test_unconfigured_never_starts_network_work(self):
        result=self.monitor.status(dict(SETTINGS,api_key=''))
        self.assertEqual(result['status'],'unconfigured');self.thread.assert_not_called()

    def test_initial_functional_probe_then_shared_cached_token_free_heartbeat(self):
        self.assertEqual(self.check()['status'],'connected')
        self.functional.assert_called_once()
        for _ in range(10):self.monitor.status(SETTINGS)
        self.thread.assert_called_once()
        self.now+=21
        self.assertEqual(self.check()['status'],'connected')
        self.assertEqual(self.functional.call_count,1)

    def test_disconnect_and_recovery_change_status_and_revalidate(self):
        self.check();self.now+=21;self.transport.return_value=(False,'network unavailable')
        self.assertEqual(self.check()['status'],'error')
        self.now+=21;self.transport.return_value=(True,'')
        self.assertEqual(self.check()['status'],'connected')
        self.assertEqual(self.functional.call_count,2)

    def test_actual_api_failure_is_not_cleared_by_head_success_or_retried_each_poll(self):
        self.check();self.monitor.report(SETTINGS,False,'HTTP 429');self.now+=21
        self.assertEqual(self.check()['status'],'error')
        self.assertEqual(self.functional.call_count,1)

    def test_expired_functional_result_is_only_reported_as_reachable(self):
        self.check();self.now+=121
        self.assertEqual(self.check()['status'],'reachable')
        self.assertEqual(self.functional.call_count,1)

    def test_old_worker_does_not_overwrite_new_configuration(self):
        self.monitor.status(SETTINGS);token,key=self.monitor.token,self.monitor.key
        self.monitor.status(dict(SETTINGS,model='new-model'))
        self.monitor._check(SETTINGS,key,token,self.now)
        self.assertEqual(self.monitor.value['status'],'unknown');self.functional.assert_not_called()

    def test_late_head_failure_does_not_overwrite_a_successful_real_request(self):
        self.check();self.now+=21
        def concurrent_success(settings):
            self.monitor.report(settings,True)
            return False,'old HEAD failure'
        self.transport.side_effect=concurrent_success
        self.assertEqual(self.check()['status'],'connected')

    def test_late_real_result_for_previous_credentials_is_ignored(self):
        with patch('model_config.effective',return_value=dict(SETTINGS,model='new')),patch.object(module,'_monitor') as monitor:
            module.report_result(SETTINGS,False,'old failure');monitor.report.assert_not_called()


class TransportTests(unittest.TestCase):
    def test_head_probe_has_no_model_payload_and_supports_head_unsupported_routes(self):
        from urllib.error import HTTPError
        import io
        failure=HTTPError(SETTINGS['api_url'],405,'Method Not Allowed',{},io.BytesIO())
        with patch.object(module.request,'urlopen',side_effect=failure) as opening:
            self.assertEqual(module._transport(SETTINGS),(True,''))
        req=opening.call_args.args[0]
        self.assertEqual(req.get_method(),'HEAD');self.assertIsNone(req.data)
        self.assertEqual(opening.call_args.kwargs['timeout'],5)

    def test_authentication_failure_is_reported_without_credentials(self):
        from urllib.error import HTTPError
        import io
        failure=HTTPError(SETTINGS['api_url'],401,'Unauthorized',{},io.BytesIO())
        with patch.object(module.request,'urlopen',side_effect=failure):
            connected,message=module._transport(SETTINGS)
        self.assertFalse(connected);self.assertIn('401',message);self.assertNotIn(SETTINGS['api_key'],message)
