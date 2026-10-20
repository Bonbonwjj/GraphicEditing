import hashlib
from pathlib import Path
import tempfile
import unittest

from chart_source_evidence import inspect_source_samples
from chart_transform import verify_distribution
from chat_diagnostics import explain_draft


class SourceEvidenceTests(unittest.TestCase):
    def evidence(self,raw,message='改为小提琴图'):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.project=Path(self.temp.name).resolve();(self.project/'data').mkdir()
        (self.project/'data/source.csv').write_bytes(raw)
        self.context={'user_message':message,'plot_data':[{'path':'data/source.csv','sha256':hashlib.sha256(raw).hexdigest()}]}
        return inspect_source_samples(self.project,'demo',self.context)

    def test_missing_render_capture_does_not_claim_source_is_missing(self):
        source=self.evidence(b'group,value\nA,1\nA,2\nB,3\nB,4\n')
        self.assertEqual(source['status'],'available')
        report=verify_distribution(self.project,'demo',self.context,{}, {'distribution_inputs':[]})
        self.assertIn('原分组数据已找到',report['reason'])
        self.assertEqual(report['source_evidence']['sources'][0]['groups'][0]['count'],2)
        diagnosis=explain_draft({'status':'validation_failed','chart_transform':report,'reason':report['reason']})[0]
        self.assertIn('原数据已找到',diagnosis['title'])
        self.assertIn('无需重复上传',diagnosis['next_action'])

    def test_summary_only_reports_the_actual_missing_observations(self):
        source=self.evidence(b'group,mean,sem\nA,1,.1\nB,2,.2\n')
        self.assertEqual(source['status'],'summary_only')
        result=verify_distribution(self.project,'demo',self.context,{}, {})
        self.assertIn('不能据此还原',result['reason'])
        self.assertEqual(result['status'],'unverified')

    def test_single_observation_per_group_reports_sample_quantity(self):
        self.evidence(b'group,value\nA,1\nB,2\n')
        result=verify_distribution(self.project,'demo',self.context,{}, {})
        self.assertEqual(result['source_evidence']['status'],'insufficient_samples')
        self.assertIn('不足两条',result['reason'])

    def test_unknown_source_does_not_assert_that_project_has_no_data(self):
        source=self.evidence(b'unknown,description\na,hello\nb,world\n')
        self.assertEqual(source['status'],'unresolved')
        self.assertIn('不代表项目没有数据',source['reason'])

    def test_changed_source_is_not_accepted(self):
        self.evidence(b'group,value\nA,1\nA,2\n')
        (self.project/'data/source.csv').write_text('changed')
        self.assertEqual(inspect_source_samples(self.project,'demo',self.context)['status'],'changed')
