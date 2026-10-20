"""Actual Harness + OS-isolated renderer integration using synthetic projects.

The Chat Agent and normalization provider JSON are deterministic doubles; this
suite does not establish deployed-model behavior. All project writes stay inside
TemporaryDirectory. Run in ordinary Terminal (nested Seatbelt may be unavailable):
/opt/anaconda3/bin/python -m unittest discover -s tests -p test_chat_integration.py -v
"""
import copy
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import server
from chat_agent import ECHO_FIELDS
from chat_harness import ChatHarness
from chat_runner import CandidateRenderError, render_candidate

SOURCE = '''import os
from pathlib import Path
import csv
import matplotlib.pyplot as plt
project = Path(os.environ['CHART_PROJECT_DIR'])
with (project / 'data/values.csv').open() as handle:
    rows = list(csv.DictReader(handle))
x = [float(row['x']) for row in rows]
y = [float(row['mean']) for row in rows]
fig, ax = plt.subplots(figsize=(6, 4))
ax.plot(x, y, color='blue', linewidth=1.5, label='sample')
ax.set(xlabel='Time (s)', ylabel='Score', xlim=(-.2, 3.2), ylim=(.5, 2.5))
fig.subplots_adjust(left=.18, bottom=.2, right=.94, top=.9)
fig.savefig(os.environ['CHART_OUTPUT'], dpi=120)
plt.close(fig)
'''
NORMALIZED = SOURCE.replace('import matplotlib.pyplot as plt', 'import matplotlib.pyplot as plt\nfrom studio_style import apply_normalization_style, finish_normalized_figure\napply_normalization_style()').replace(
    "ax.plot(x, y, color='blue', linewidth=1.5, label='sample')",
    "ax.errorbar(x, y, yerr=[float(row['sem']) for row in rows], color='blue', linewidth=3.2, capsize=8, elinewidth=3.2, label='sample')").replace(
    "fig.savefig(os.environ['CHART_OUTPUT'], dpi=120)", "finish_normalized_figure(fig, os.environ['CHART_OUTPUT'], chart_type='line')")


class ChatIntegrationTests(unittest.TestCase):
    def setUp(self):
        from chat_runner import isolation_backend
        import subprocess
        try:
            backend = isolation_backend()
            if backend == "docker":
                check = subprocess.run(["docker", "image", "inspect", os.environ.get("PLOT_FORGE_RENDER_IMAGE", "plot-forge-renderer:local")], capture_output=True, timeout=15)
                if check.returncode:
                    self.skipTest("Docker engine/image unavailable: " + check.stderr.decode("utf-8", errors="replace"))
        except (CandidateRenderError, OSError, subprocess.TimeoutExpired) as exc:
            self.skipTest(str(exc))
        self.temp = tempfile.TemporaryDirectory(prefix='chart-integration-')
        self.root = Path(self.temp.name).resolve()
        self.project = self.root / 'synthetic'
        from local_execution import approve
        approve(self.project)
        (self.project / 'charts').mkdir(parents=True)
        (self.project / 'data').mkdir()
        (self.project / 'project.json').write_text('{"name":"Synthetic integration"}', encoding="utf-8", newline="\n")
        self.csv = b'x,mean,sem\n0,1,.1\n1,1.3,.12\n2,1.6,.14\n3,2,.15\n'
        (self.project / 'data/values.csv').write_bytes(self.csv)
        for name in ('a', 'b'):
            (self.project / f'charts/{name}.py').write_text(SOURCE, encoding="utf-8", newline="\n")
        self.project_patch = patch.object(server, 'PROJECTS', self.root)
        self.project_patch.start()
        self.env_patch = patch.dict(os.environ, {'CHAT_MODEL_VISION': '0'})
        self.env_patch.start()
        self.contexts = []
        self.fail_chart = None
        self.harness = ChatHarness(server, agent=self.agent)

    def tearDown(self):
        self.env_patch.stop()
        self.project_patch.stop()
        self.temp.cleanup()

    def agent(self, context):
        self.contexts.append(copy.deepcopy(context))
        source = next(item for item in context['source_files'] if item['writable'])
        if source['path'] == self.fail_chart:
            raise ValueError('Synthetic provider failure for this chart only')
        desired = source['content']
        operation = 'color'
        if context['user_message'] == 'Make the line red; keep everything else.':
            desired = desired.replace("color='blue'", "color='red'")
        elif context['user_message'] == 'Now make this line width 3; keep the red color.':
            desired = desired.replace('linewidth=1.5', 'linewidth=3')
            operation = 'linewidth'
        else:
            desired += '\n# confirmed no-op candidate\n'
        return {
            **{key: context[key] for key in ECHO_FIELDS}, 'status': 'candidate',
            'interpreted_request': {'operations': [{'operation_id': 'requested_style', 'target_chart_id': context['chart_id'],
                'source_quotes': [context['user_message']], 'target_element': 'sample line', 'category': 'visual styling',
                'property': operation, 'current_value': 'from supplied candidate', 'desired_change': context['user_message'],
                'evidence': [{'path': source['path'], 'sha256': source['sha256'], 'fact': 'The entry has one sample line.'}],
                'disposition': 'planned'}], 'preserve': ['CSV', 'all plotted x/y coordinates', 'all unrelated styles']},
            'intent_check': {'status': 'consistent', 'unresolved_items': [], 'implementation_choices': ['Set existing line style only.']},
            'proposed_files': [{'path': source['path'], 'base_sha256': source['sha256'], 'content': desired}],
            'read_data_refs': [{'path': item['path'], 'sha256': item['sha256'],
                'columns': [{'name': name, 'role': role} for name, role in [('x', 'x coordinate'), ('mean', 'plotted mean')]]}
                for item in context['plot_data']],
            'reference_usage': [], 'affected_chart_ids': [context['chart_id']],
            'expected_effects': [{'operation_id': 'requested_style', 'observable_change': context['user_message'],
                                  'preservation_checks': ['Same x/y values'], 'verification_status': 'unverified'}],
            'layout_policy': {'mode': 'avoid_overlap', 'checks_requested': ['whole figure']},
            'summary': context['user_message'], 'warnings': []}

    def ready(self, result, expected=1):
        outcomes = result['turns'][-1]['results']
        self.assertEqual(len(outcomes), expected)
        for outcome in outcomes:
            if 'sandbox' in str(outcome.get('reason', '')).lower() and 'unavailable' in str(outcome.get('reason', '')).lower():
                self.skipTest('Outer environment prohibits nested Seatbelt; run from ordinary Terminal: ' + outcome['reason'])
            self.assertEqual(outcome['status'], 'preview_ready', json.dumps(outcomes, ensure_ascii=False))
        return result['drafts'][-expected:]

    def turn(self, session, message):
        return self.harness.turn('synthetic', session['id'], {'user_message': message})

    def test_real_candidate_multiturn_apply_and_resume(self):
        session = self.harness.create('synthetic', ['a'])
        first = self.turn(session, 'Make the line red; keep everything else.')
        draft1 = self.ready(first)[0]
        self.assertEqual((self.project / 'charts/a.py').read_text(encoding="utf-8"), SOURCE)
        private1 = self.harness.load('synthetic', session['id'])['drafts'][-1]
        self.assertEqual(Path(private1['image_path']).read_bytes()[:8], b'\x89PNG\r\n\x1a\n')
        self.assertFalse((self.project / 'previews/a.png').exists())
        second = self.turn(session, 'Now make this line width 3; keep the red color.')
        draft2 = self.ready(second)[0]
        self.assertEqual(draft2['parent_draft_id'], draft1['id'])
        self.assertIn("color='red'", self.contexts[-1]['source_files'][0]['content'])
        self.assertIn('linewidth=3', draft2['code']['charts/a.py'])
        self.assertEqual((self.project / 'charts/a.py').read_text(encoding="utf-8"), SOURCE)
        private2 = self.harness.load('synthetic', session['id'])['drafts'][-1]
        candidate_bytes = Path(private2['image_path']).read_bytes()
        applied = self.harness.draft_action('synthetic', session['id'], draft2['id'], 'apply')
        self.assertEqual(applied['drafts'][-1]['status'], 'applied')
        self.assertEqual((self.project / 'charts/a.py').read_text(encoding="utf-8"), draft2['code']['charts/a.py'])
        self.assertEqual((self.project / 'previews/a.png').read_bytes(), candidate_bytes)
        self.assertEqual((self.project / 'data/values.csv').read_bytes(), self.csv)
        self.assertEqual((self.project / 'charts/b.py').read_text(encoding="utf-8"), SOURCE)
        self.assertEqual(len(server.read_history(self.project, 'a')), 2)
        initial_revision=server.read_history(self.project,'a')[0]['id']
        self.assertEqual((self.project/'history'/(initial_revision+'.png')).read_bytes(),
                         Path(private1['baseline_image_path']).read_bytes())
        next_turn = self.turn(session, 'Keep this version.')
        self.assertEqual(next_turn['turns'][-1]['results'][0]['status'], 'no_visible_change')
        self.assertIsNone(self.contexts[-1]['parent_draft_id'])
        self.assertIn('linewidth=3', next(item for item in self.contexts[-1]['source_files'] if item['writable'])['content'])

    def test_real_candidate_dependency_conflict_does_not_apply(self):
        session = self.harness.create('synthetic', ['a'])
        result = self.turn(session, 'Make the line red; keep everything else.')
        draft = self.ready(result)[0]
        (self.project / 'data/values.csv').write_bytes(self.csv + b'4,2.2,.2\n')
        with self.assertRaisesRegex(ValueError, 'revision_conflict'):
            self.harness.draft_action('synthetic', session['id'], draft['id'], 'apply')
        self.assertEqual((self.project / 'charts/a.py').read_text(encoding="utf-8"), SOURCE)
        self.assertFalse((self.project / 'previews/a.png').exists())

    def test_real_batch_candidates_apply_independently(self):
        session = self.harness.create('synthetic', ['a', 'b'])
        result = self.turn(session, 'Make the line red; keep everything else.')
        drafts = self.ready(result, 2)
        self.assertNotEqual(drafts[0]['chart_id'], drafts[1]['chart_id'])
        for draft in drafts:
            self.harness.draft_action('synthetic', session['id'], draft['id'], 'apply')
        for name in ('a', 'b'):
            self.assertIn("color='red'", (self.project / f'charts/{name}.py').read_text(encoding="utf-8"))
            self.assertTrue((self.project / f'previews/{name}.png').is_file())
        self.assertEqual((self.project / 'data/values.csv').read_bytes(), self.csv)

    def test_real_batch_partial_provider_failure_keeps_other_candidate(self):
        self.fail_chart = 'charts/b.py'
        session = self.harness.create('synthetic', ['a', 'b'])
        result = self.turn(session, 'Make the line red; keep everything else.')
        statuses = {item['chart']: item['status'] for item in result['turns'][-1]['results']}
        if statuses.get('a') != 'preview_ready':
            self.ready({**result, 'turns': [{**result['turns'][-1], 'results': result['turns'][-1]['results'][:1]}]})
        self.assertEqual(statuses, {'a': 'preview_ready', 'b': 'cannot_complete'})
        self.assertEqual(len(result['drafts']), 1)
        for name in ('a', 'b'):
            self.assertEqual((self.project / f'charts/{name}.py').read_text(encoding="utf-8"), SOURCE)

    def test_real_changed_plot_values_cannot_apply(self):
        original_agent = self.harness.agent
        def wrong_data(context):
            result = original_agent(context)
            result['proposed_files'][0]['content'] = result['proposed_files'][0]['content'].replace(
                "float(row['mean'])", "float(row['mean']) + .25")
            return result
        self.harness.agent = wrong_data
        session = self.harness.create('synthetic', ['a'])
        result = self.turn(session, 'Make the line red; keep everything else.')
        outcome = result['turns'][-1]['results'][0]
        if outcome['status'] == 'render_failed':
            self.ready(result)
        self.assertEqual(outcome['status'], 'validation_failed')
        self.assertTrue(result['drafts'][-1]['data_report']['changed'])
        with self.assertRaises(ValueError):
            self.harness.draft_action('synthetic', session['id'], result['drafts'][-1]['id'], 'apply')
        self.assertEqual((self.project / 'charts/a.py').read_text(encoding="utf-8"), SOURCE)
        self.assertEqual((self.project / 'data/values.csv').read_bytes(), self.csv)

    def test_real_layout_conflict_then_explicit_exception(self):
        original_agent = self.harness.agent
        def overlapping(context):
            result = original_agent(context)
            source = next(item for item in context['source_files'] if item['writable'])['content']
            annotations = ("ax.text(.5, .6, 'Overlap A', transform=ax.transAxes)\n"
                           "ax.text(.5, .6, 'Overlap B', transform=ax.transAxes)\n")
            result['proposed_files'][0]['content'] = (source if 'Overlap A' in source else
                source.replace("fig.savefig(", annotations + "fig.savefig("))
            operation = result['interpreted_request']['operations'][0]
            operation.update(property='annotation_position', target_element='two requested labels')
            if context.get('layout_exception'):
                result['layout_policy']['mode'] = 'allow_disclosed_overlap'
            return result
        self.harness.agent = overlapping
        session = self.harness.create('synthetic', ['a'])
        first = self.turn(session, 'Place both labels here.')
        if first['turns'][-1]['results'][0]['status'] == 'render_failed':
            self.ready(first)
        draft = first['drafts'][-1]
        self.assertEqual(draft['status'], 'needs_clarification')
        self.assertEqual(draft['layout']['status'], 'conflict')
        self.assertEqual(first['active_drafts'][draft['chart_id']],draft['id'])
        self.assertTrue(draft['can_continue'])
        self.assertEqual((self.project / 'charts/a.py').read_text(encoding="utf-8"), SOURCE)
        message = 'I understand the disclosed overlap; keep these labels exactly there.'
        second = self.harness.turn('synthetic', session['id'], {'user_message': message,
            'layout_exception': {'warning_ids': [issue['id'] for issue in draft['layout']['issues']],
                                 'authorization_quote': message}})
        accepted = self.ready(second)[0]
        self.assertEqual(accepted['layout']['status'], 'accepted_exception')
        self.assertTrue(any('保留' in item for item in accepted['warnings']))
        self.assertEqual((self.project / 'charts/a.py').read_text(encoding="utf-8"), SOURCE)

    def test_real_layout_conflict_can_be_repaired_by_followup(self):
        original_agent = self.harness.agent
        def edit_labels(context):
            result = original_agent(context)
            source = next(item for item in context['source_files'] if item['writable'])['content']
            if 'Overlap A' not in source:
                annotations = ("ax.text(.2, .8, 'Overlap A', transform=ax.transAxes)\n"
                               "ax.text(.2, .8, 'Overlap B', transform=ax.transAxes)\n")
                source = source.replace('fig.savefig(', annotations + 'fig.savefig(')
            if context['user_message'] == 'Move the second annotation down on this version.':
                source = source.replace("ax.text(.2, .8, 'Overlap B'", "ax.text(.2, .6, 'Overlap B'")
            result['proposed_files'][0]['content'] = source
            result['interpreted_request']['operations'][0].update(
                property='annotation_position', target_element='two requested labels')
            return result
        self.harness.agent = edit_labels
        session = self.harness.create('synthetic', ['a'])
        first = self.turn(session, 'Add two annotations here.')
        draft = first['drafts'][-1]
        self.assertEqual(draft['review_blocker'], 'layout_conflict')
        with self.assertRaises(ValueError):
            self.harness.draft_action('synthetic', session['id'], draft['id'], 'apply')
        second = self.turn(session, 'Move the second annotation down on this version.')
        repaired = self.ready(second)[0]
        self.assertEqual(repaired['parent_draft_id'], draft['id'])
        self.assertEqual(repaired['layout']['status'], 'pass')
        self.assertFalse(self.contexts[-1]['layout_exception'])
        self.assertTrue(self.contexts[-1]['harness_layout_feedback']['layout']['issues'])
        self.assertEqual((self.project / 'charts/a.py').read_text(encoding='utf-8'), SOURCE)

    def test_real_requested_boxplot_can_continue_and_apply(self):
        (self.project/'data/groups.csv').write_text('group,value\nA,1\nA,2\nA,5\nB,2\nB,3\nB,7\n')
        prefix="""import os, csv
from pathlib import Path
import matplotlib.pyplot as plt
rows=list(csv.DictReader((Path(os.environ['CHART_PROJECT_DIR'])/'data/groups.csv').open()))
groups=[[float(row['value']) for row in rows if row['group']==label] for label in ['A','B']]
fig,ax=plt.subplots(figsize=(6,4))
"""
        suffix="""ax.set_xticks([1,2],['A','B'])
ax.set_ylabel('Score')
fig.subplots_adjust(left=.2,bottom=.2)
fig.savefig(os.environ['CHART_OUTPUT'],dpi=120)
plt.close(fig)
"""
        original=prefix+"ax.errorbar([1,2],[8/3,4],yerr=[.2,.3],fmt='o')\n"+suffix
        candidate=prefix+"ax.boxplot(groups,showfliers=False)\n"+suffix
        (self.project/'charts/a.py').write_text(original)
        def convert(context):
            result=self.agent(context)
            result['proposed_files'][0]['content']=candidate
            result['interpreted_request']['operations'][0].update(property='chart type',desired_change='boxplot')
            result.pop('expected_effects')
            result.pop('warnings')
            result['read_data_refs']=[{'path':d['path'],'sha256':d['sha256'],
                'columns':[{'name':'group','role':'group'},{'name':'value','role':'observation'}]}
                for d in context['plot_data'] if d['path']=='data/groups.csv']
            return result
        self.harness.agent=convert
        session=self.harness.create('synthetic',['a'])
        result=self.turn(session,'将这个图改为箱型图')
        draft=self.ready(result)[0]
        self.assertEqual(draft['chart_transform']['status'],'pass')
        self.assertTrue(draft['can_continue'])
        self.assertTrue(draft['data_report']['changed'] or draft['data_report']['removed'])
        self.assertTrue(any('离群点' in w for w in draft['warnings']))
        calls=len(self.contexts)
        repeated=self.turn(session,'将这个图改为箱线图')
        self.assertEqual(repeated['turns'][-1]['results'][0]['status'],'already_compliant')
        self.assertEqual(repeated['turns'][-1]['results'][0]['model_attempts'],0)
        self.assertEqual(len(self.contexts),calls)
        applied=self.harness.draft_action('synthetic',session['id'],draft['id'],'apply')
        self.assertEqual(applied['drafts'][-1]['status'],'applied')
        self.assertEqual((self.project/'charts/a.py').read_text(),candidate)

    def test_real_normalizer_pipeline_preview_uses_mock_provider_json(self):
        session = self.harness.create('synthetic', ['a'])
        provider_result = {'status': 'proposed', 'message': 'Fixed style with explicit stored SEM; candidate only.',
                           'changes': ['Apply fixed line style', 'Use supplied sem column without recalculating statistics'],
                           'warnings': [], 'unsupported': [], 'normalized_source': NORMALIZED}
        provider_body = {'choices': [{'message': {'content': json.dumps(provider_result)}}]}
        captured = []
        def provider(request, **kwargs):
            captured.append(json.loads(request.data))
            return io.BytesIO(json.dumps(provider_body).encode())
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'synthetic-test-token'}), patch('normalizer_agent.urllib.request.urlopen', side_effect=provider):
            result = self.harness.turn('synthetic', session['id'], {'skill_id': 'chart-normalization'}, normalize=True)
        draft = self.ready(result)[0]
        self.assertEqual(len(captured), 1)
        self.assertIn('Never apply automatically', captured[0]['messages'][0]['content'])
        self.assertIn('prepared plotting data', captured[0]['messages'][0]['content'])
        self.assertEqual(draft['code']['charts/a.py'], NORMALIZED)
        self.assertEqual((self.project / 'charts/a.py').read_text(encoding="utf-8"), SOURCE)
        self.assertFalse((self.project / 'previews/a.png').exists())
        private = self.harness.load('synthetic', session['id'])['drafts'][-1]
        from PIL import Image
        with Image.open(private['image_path']) as image:
            self.assertEqual(image.size, (2160, 1440))
        self.assertEqual((self.project / 'data/values.csv').read_bytes(), self.csv)


if __name__ == '__main__':
    unittest.main()
