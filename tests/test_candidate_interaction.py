import tempfile
import unittest
from pathlib import Path

from chat_runner import render_candidate
from server import interaction_payload


class CandidateInteractionTests(unittest.TestCase):
    def test_actual_candidate_keeps_box_groups_errorbars_and_ranges_for_application(self):
        source='''import os
import matplotlib.pyplot as plt
fig, ax = plt.subplots(figsize=(5,4))
ax.boxplot([[1,2,3,4,5]], positions=[1], patch_artist=True,
           boxprops={'facecolor':'red'})
ax.errorbar([2], [3], yerr=[1], fmt='o', capsize=5)
ax.set(xlim=(0,3), ylim=(0,6), xlabel='Group', ylabel='Score')
fig.savefig(os.environ['CHART_OUTPUT'])
'''
        with tempfile.TemporaryDirectory() as tmp:
            project=Path(tmp)/'project';(project/'charts').mkdir(parents=True)
            (project/'charts/figure.py').write_text(source,encoding='utf-8')
            report=render_candidate(project,'charts/figure.py',
                {'charts/figure.py':source.replace("'red'","'blue'")},Path(tmp)/'output',
                baseline_files={'charts/figure.py':source})
            self.assertTrue(report['component_groups'])
            payload=interaction_payload(report)
            self.assertTrue(payload['targets']);self.assertTrue(payload['axis_ranges'])
            box=next(g for g in payload['component_groups'] if '.box_' in g['key'])
            patch=next(t for t in payload['targets'] if t['kind']=='patch')
            self.assertIn(patch['key'],box['members'])
            self.assertEqual(patch['group_key'],box['key'])
            self.assertEqual(patch['style']['facecolor'][:3],[0,0,1])
            self.assertTrue(any('.mean_error_' in g['key'] for g in payload['component_groups']))
            self.assertEqual(payload['axis_ranges'][0]['ylim'],[0,6])
            self.assertTrue(payload['point_editing_ready'])
            self.assertTrue(any(t.get('point_role')=='mean' for t in payload['targets']))


if __name__=='__main__':unittest.main()
