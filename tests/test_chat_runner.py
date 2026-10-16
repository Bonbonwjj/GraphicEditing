"""Synthetic runner tests; no official project is executed or changed.

Run: /opt/anaconda3/bin/python -m unittest discover -s tests -p test_chat_runner.py -v
OS integration cases fail closed (or skip with the explicit OS reason) if nested
Seatbelt is unavailable. Run from an ordinary Terminal for full integration.
"""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from chat_runner import CandidateRenderError, _capture, _install_stat_capture, _snapshot, _validate_sources, compare_reports, render_candidate

SOURCE = """import os
from pathlib import Path
import matplotlib.pyplot as plt
import pandas as pd
from studio_style import finish_figure
frame = pd.read_csv(Path(os.environ['CHART_PROJECT_DIR'])/'data'/'values.csv')
fig, ax = plt.subplots(figsize=(5, 4))
ax.plot(frame.x, frame.y, label='sample', color='blue', linewidth=1.5)
ax.set_xlabel('Time (s)')
ax.set_ylabel('Score')
ax.legend(loc='upper left')
finish_figure(fig, os.environ['CHART_OUTPUT'])
"""


class RunnerUnitTests(unittest.TestCase):
    def test_scope_and_process_rejections(self):
        for path, source in (("../secret.py", "pass"), ("lib/helper.py", "pass"),
                             ("charts/b.py", "pass"), ("charts/a.py", "import socket"),
                             ("charts/a.py", "import os; os.system('touch anything')")):
            with self.subTest(path=path, source=source), self.assertRaises(CandidateRenderError):
                _validate_sources("charts/a.py", {path: source})

    def test_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "project"
            (project / "data").mkdir(parents=True)
            try:
                (project / "data" / "secret.csv").symlink_to("/etc/passwd")
            except OSError as exc:
                self.skipTest("Symlink creation unavailable: " + str(exc))
            with self.assertRaises(CandidateRenderError):
                _snapshot(project, root / "snapshot", {})

    def test_no_isolation_fails_closed(self):
        with patch("chat_runner.sys.platform", "unsupported"):
            with self.assertRaises(CandidateRenderError) as error:
                render_candidate(".", "charts/a.py", {}, "/tmp/unused")
        self.assertEqual(error.exception.code, "sandbox_unavailable")

    def test_style_not_counted_as_data_change(self):
        a = {"artists": [{"key": "line_0", "kind": "line", "data_hash": "abc", "visibility": {"alpha": 1}, "style": {"color": "blue"}}]}
        b = {"artists": [{"key": "line_0", "kind": "line", "data_hash": "abc", "visibility": {"alpha": 1}, "style": {"color": "red"}}]}
        result = compare_reports(a, b)
        self.assertEqual(result["status"], "unchanged")
        self.assertEqual(len(result["style_changes"]), 1)
        b["artists"][0]["data_hash"] = "changed"
        self.assertEqual(compare_reports(a, b)["status"], "review_required")

    def test_layout_overlap_and_clip(self):
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(5, 4))
        ax.text(.5, .5, 'Overlap A', transform=ax.transAxes)
        ax.text(.5, .5, 'Overlap B', transform=ax.transAxes)
        fig.text(-.2, .5, 'Outside')
        fig.canvas.draw()
        captured = _capture(fig, fig.canvas.get_renderer())
        plt.close(fig)
        kinds = {issue['kind'] for issue in captured['layout']['issues']}
        self.assertIn('text_overlap', kinds)
        self.assertIn('text_clipped', kinds)
        self.assertEqual(captured['layout']['status'], 'conflict')

    def test_heatmap_cell_labels_are_not_collisions(self):
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(5, 4))
        ax.imshow([[1, 2], [3, 4]])
        ax.text(0, 0, '*', ha='center', va='center')
        fig.canvas.draw()
        result = _capture(fig, fig.canvas.get_renderer())
        plt.close(fig)
        self.assertFalse(result['layout']['issues'])

    def test_distribution_width_preserves_numeric_statistics(self):
        import matplotlib.pyplot as plt
        from matplotlib.axes import Axes
        originals = Axes.bxp, Axes.violin
        _install_stat_capture(Axes)
        try:
            for kind in ('box', 'violin'):
                captures = []
                for width in (.4, .8):
                    fig, ax = plt.subplots(figsize=(5, 4))
                    data = [[1, 2, 3, 4, 5], [2, 3, 4, 5, 7]]
                    if kind == 'box':
                        ax.boxplot(data, widths=width)
                    else:
                        ax.violinplot(data, widths=width, showmedians=True)
                    ax.set_xlim(.2, 2.8)
                    ax.set_ylim(0, 8)
                    fig.canvas.draw()
                    captures.append(_capture(fig, fig.canvas.get_renderer()))
                    plt.close(fig)
                with self.subTest(kind=kind):
                    diff = compare_reports(*captures)
                    self.assertFalse(diff['changed'])
                    self.assertEqual(diff['status'], 'unchanged')
                    self.assertTrue(diff['style_changes'])
        finally:
            Axes.bxp, Axes.violin = originals

    def test_distribution_post_creation_data_mutation_detected(self):
        import matplotlib.pyplot as plt
        from matplotlib.axes import Axes
        originals = Axes.bxp, Axes.violin
        _install_stat_capture(Axes)
        try:
            fig, ax = plt.subplots()
            artists = ax.boxplot([[1, 2, 3, 4, 5]])
            fig.canvas.draw()
            before = _capture(fig, fig.canvas.get_renderer())
            artists['medians'][0].set_ydata([4, 4])
            fig.canvas.draw()
            after = _capture(fig, fig.canvas.get_renderer())
            self.assertTrue(compare_reports(before, after)['changed'])
            plt.close(fig)
        finally:
            Axes.bxp, Axes.violin = originals

    def test_hidden_axes_and_per_point_alpha_are_captured(self):
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots()
        ax.scatter([1, 2], [2, 3], alpha=[.5, 1.])
        ax.set_xlabel('Hidden axis text')
        ax.set_axis_off()
        fig.canvas.draw()
        result = _capture(fig, fig.canvas.get_renderer())
        plt.close(fig)
        json.dumps(result, allow_nan=False)
        self.assertFalse(result['layout']['issues'])
        self.assertEqual(result['artists'][0]['visibility']['alpha'], [.5, 1.])

    def test_actual_errorbar_children_are_classified(self):
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots()
        ax.plot([0, 1], [1, 2], label='ordinary')
        ax.errorbar([0, 1], [2, 3], yerr=[.1, .2], capsize=5, label='uncertainty')
        fig.canvas.draw()
        records = _capture(fig, fig.canvas.get_renderer())['artists']
        plt.close(fig)
        ordinary = next(item for item in records if item['label'] == 'ordinary')
        self.assertEqual(ordinary['semantic_role'], 'data_artist')
        primary = [item for item in records if item['errorbar_component'] == 'data_line']
        self.assertEqual(len(primary), 1)
        self.assertEqual(primary[0]['semantic_role'], 'data_series')
        uncertainty = [item for item in records if item['semantic_role'] == 'errorbar']
        self.assertEqual(len(uncertainty), 3)
        self.assertEqual({item['errorbar_component'] for item in uncertainty}, {'cap', 'range'})
        self.assertTrue(all(item['role_evidence'] == 'matplotlib.container.ErrorbarContainer' for item in uncertainty))

    def test_distribution_and_quartile_roles(self):
        import matplotlib.pyplot as plt
        from matplotlib.axes import Axes
        originals = Axes.bxp, Axes.violin
        _install_stat_capture(Axes)
        try:
            fig, ax = plt.subplots()
            ax.violinplot([[1, 2, 3, 4]], showmedians=True)
            quartile, = ax.plot([.9, 1.1], [2, 2])
            quartile._normalization_role = 'violin_quartiles'
            fig.canvas.draw()
            records = _capture(fig, fig.canvas.get_renderer())['artists']
            plt.close(fig)
            self.assertEqual(len([item for item in records if item['semantic_role'] == 'violin_quartiles']), 1)
            semantic = [item for item in records if item['signature_basis'] == 'supplied_statistics']
            self.assertTrue(semantic)
            self.assertTrue(all(item['semantic_role'] == 'distribution_statistics' for item in semantic))
        finally:
            Axes.bxp, Axes.violin = originals


class RunnerIsolationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='chat-runner-test-')
        self.root = Path(self.temporary.name).resolve()
        self.project = self.root / 'synthetic'
        from local_execution import approve
        approve(self.project)
        (self.project / 'charts').mkdir(parents=True)
        (self.project / 'data').mkdir()
        (self.project / 'charts/a.py').write_text(SOURCE, encoding="utf-8", newline="\n")
        (self.project / 'data/values.csv').write_text('x,y\n0,2\n1,3\n2,4\n', encoding="utf-8", newline="\n")
        self.original = (self.project / 'data/values.csv').read_bytes()

    def tearDown(self):
        self.temporary.cleanup()

    def render(self, source, output='result', baseline=None):
        try:
            return render_candidate(self.project, 'charts/a.py', {'charts/a.py': source}, self.root / output,
                                    baseline_files=baseline)
        except CandidateRenderError as exc:
            if exc.code == 'sandbox_unavailable':
                self.skipTest(str(exc))
            raise

    def test_simple_style_and_export_size(self):
        result = self.render(SOURCE.replace("color='blue'", "color='red'"))
        self.assertEqual(result['data_report']['status'], 'unchanged')
        self.assertEqual(result['layout']['status'], 'pass', result['layout'])
        self.assertEqual(result['naming']['display_name'], 'Time (s)_Score')
        from PIL import Image
        with Image.open(result['image_path']) as image:
            self.assertTrue(all(abs(a - b) <= 1 for a, b in zip(image.size, result['render_size_px'])))
        self.assertEqual((self.project / 'data/values.csv').read_bytes(), self.original)

    def test_candidate_uses_parent_basis(self):
        parent = SOURCE.replace('linewidth=1.5', 'linewidth=3')
        result = self.render(parent.replace("color='blue'", "color='red'"), baseline={'charts/a.py': parent})
        self.assertEqual(result['data_report']['status'], 'unchanged')
        style = result['data_report']['style_changes'][0]
        self.assertEqual(style['before']['linewidth'], style['after']['linewidth'])

    def test_csv_write_denied(self):
        attack = "\n(Path(os.environ['CHART_PROJECT_DIR'])/'data/values.csv').write_text('corrupt')\n"
        with self.assertRaises(CandidateRenderError):
            self.render(SOURCE + attack)
        self.assertEqual((self.project / 'data/values.csv').read_bytes(), self.original)

    def test_dynamic_network_denied(self):
        attack = "\n__import__('socket').create_connection(('127.0.0.1', 8765), timeout=1)\n"
        with self.assertRaises(CandidateRenderError):
            self.render(SOURCE + attack)

    def test_external_read_denied(self):
        from chat_runner import isolation_backend
        if isolation_backend() == "local-python":
            self.skipTest("Local Python explicitly has no OS filesystem sandbox")
        secret = self.root / 'synthetic-secret.txt'
        secret.write_text('must not be readable', encoding="utf-8", newline="\n")
        attack = '\nPath(' + repr(str(secret)) + ').read_text(encoding="utf-8")\n'
        with self.assertRaises(CandidateRenderError):
            self.render(SOURCE + attack)

    def test_uninherited_environment(self):
        with patch.dict(os.environ, {'CHAT_RUNNER_TEST_SECRET': 'must-not-inherit'}):
            result = self.render(SOURCE + "\nassert 'CHAT_RUNNER_TEST_SECRET' not in os.environ\n")
        self.assertIn(result['isolation']['network'], ('denied', 'python-audit-hook'))

    def test_geometry_changes_reported(self):
        result = self.render(SOURCE.replace('frame.x, frame.y', 'frame.x, frame.y * 2'))
        self.assertEqual(result['data_report']['status'], 'review_required')
        self.assertTrue(result['data_report']['changed'])

    def test_root_helper_import_works(self):
        (self.project / 'shared_draw.py').write_text("def identity(value):\n    return value\n", encoding="utf-8", newline="\n")
        result = self.render('from shared_draw import identity\n' + SOURCE.replace('frame.y, label=', 'identity(frame.y), label='))
        self.assertEqual(result['data_report']['status'], 'unchanged')

    def test_sibling_chart_cannot_be_hidden_dependency(self):
        (self.project / 'charts' / 'other.py').write_text('value=3\n', encoding="utf-8", newline="\n")
        with self.assertRaises(CandidateRenderError) as error:
            self.render('import other\n' + SOURCE)
        self.assertIn('ModuleNotFoundError', str(error.exception))

    def test_external_write_denied(self):
        from chat_runner import isolation_backend
        if isolation_backend() == "local-python":
            self.skipTest("Local Python explicitly has no OS filesystem sandbox")
        protected = self.root / 'protected.txt'
        protected.write_text('original', encoding="utf-8", newline="\n")
        with self.assertRaises(CandidateRenderError):
            self.render(SOURCE + '\nPath(' + repr(str(protected)) + ').write_text("modified")\n')
        self.assertEqual(protected.read_text(encoding="utf-8"), 'original')

    def test_scientific_dependency_imports(self):
        result = self.render('from scipy.stats import linregress\n' + SOURCE)
        self.assertEqual(result['data_report']['status'], 'unchanged')


if __name__ == '__main__':
    unittest.main()
