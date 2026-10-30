import unittest
from project_batch import outcome


class BatchOutcomeTests(unittest.TestCase):
    def test_mixed_failure_and_block_is_explicit(self):
        result=outcome({'jobs':[{'status':'failed','reason':'timed out'},
                               {'status':'blocked','reason':'超限'}, {'status':'blocked','reason':'依赖超限'}]})
        self.assertEqual(result['status'],'failed_blocked')
        self.assertEqual((result['succeeded'],result['failed'],result['blocked']),(0,1,2))
        self.assertEqual(len(result['reasons']),3)

    def test_generated_success_still_requires_export_and_validation(self):
        result=outcome({'jobs':[{'status':'pending_local_run'}]})
        self.assertEqual(result['status'],'success')
        self.assertIn('待本机导出',result['label'])

    def test_terminal_states_and_running_are_not_confused(self):
        for state,expected in [('failed','failed'),('blocked','blocked'),('needs_context','blocked'),
                               ('unsupported','blocked'),('interrupted','failed'),('pending','pending')]:
            with self.subTest(state=state):
                self.assertEqual(outcome({'jobs':[{'status':state}]})['status'],expected)
                self.assertEqual(outcome({'jobs':[{'status':state}]},working=True)['status'],'working')

    def test_merge_error_is_failed_and_ready_requires_install(self):
        self.assertEqual(outcome({'jobs':[{'status':'ready'}],'phase':'merge','error':'汇总失败'})['status'],'failed')
        result=outcome({'jobs':[{'status':'ready'}],'installed':True})
        self.assertEqual(result['status'],'success')
        self.assertIn('可进入改图',result['label'])

    def test_failure_reasons_are_readable_and_preserve_raw_evidence(self):
        result=outcome({'jobs':[
            {'status':'failed','reason':'LLM request failed: timed out','started_at':100,'finished_at':160},
            {'status':'blocked','reason':'超限','chars':591233,'limit':180000}]})
        self.assertIn('等待约 60 秒后超时',result['reasons'][0]['reason'])
        self.assertEqual(result['reasons'][0]['raw_reason'],'LLM request failed: timed out')
        self.assertIn('591,233',result['reasons'][1]['reason'])
        self.assertIn('180,000',result['reasons'][1]['reason'])
