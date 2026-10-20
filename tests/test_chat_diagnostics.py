import unittest

from chat_diagnostics import explain_draft


class DiagnosticTests(unittest.TestCase):
    def test_unsupported_check_is_distinct_from_observed_mismatch(self):
        for status, category in (('unverified','unverified'),('fail','mismatch')):
            draft={'status':'validation_failed','reason':'specific sample reason',
                   'chart_transform':{'status':status}}
            diagnostic=explain_draft(draft)[0]
            self.assertEqual(diagnostic['category'],category)
            self.assertEqual(diagnostic['reason'],'specific sample reason')
            self.assertTrue(diagnostic['next_action'])

    def test_data_differences_include_actual_object_keys(self):
        result=explain_draft({'status':'validation_failed','data_report':{
            'changed':[{'key':'axes_0.line_0'}],'removed':[{'key':'axes_0.bar_1'}]}})[0]
        self.assertEqual(result['code'],'data_mapping_difference')
        self.assertEqual(result['evidence'][0]['objects'],['axes_0.line_0'])
        self.assertEqual(result['evidence'][1]['count'],1)

    def test_success_does_not_keep_old_failure_label(self):
        self.assertEqual(explain_draft({'status':'applied','review_blocker':'layout_conflict'}),[])
        self.assertEqual(explain_draft({'status':'preview_ready','chart_transform':{'status':'pass'}}),[])

    def test_layout_does_not_claim_data_changed(self):
        result=explain_draft({'status':'needs_clarification','review_blocker':'layout_conflict'})[0]
        self.assertEqual(result['category'],'presentation')
        self.assertEqual(result['evidence'],[])

    def test_legacy_missing_capture_is_not_labeled_as_changed_data(self):
        result=explain_draft({'status':'validation_failed','reason':'无法捕获目标图型的原始样本；需要使用可检查的接口。'})[0]
        self.assertEqual(result['code'],'transform_unverified')
