import unittest
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from component_editor import apply_components
from component_groups import install_group_tracking, artist_points, artist_key
from point_components import targets
from chat_runner import _capture


class ComponentLinkTests(unittest.TestCase):
    def setUp(self):
        install_group_tracking()
        self.fig, self.ax = plt.subplots(dpi=100)
        self.addCleanup(plt.close, self.fig)

    def example(self, horizontal=False, marked=False):
        values = [np.array([1., 2, 5]), np.array([2., 4, 8])]
        boxes = self.ax.boxplot(values, positions=[1, 2], patch_artist=True,
                               orientation='horizontal' if horizontal else 'vertical')
        scatter = None
        if not marked:
            x = np.repeat([.98, 2.02], 3); y = np.concatenate(values)
            scatter = self.ax.scatter(y if horizontal else x, x if horizontal else y, color='purple', alpha=.4)
        lines = []
        for a, b in zip(*values):
            lines.extend(self.ax.plot([a, b] if horizontal else [1, 2], [1, 2] if horizontal else [a, b],
                                      marker='o' if marked else None, color='gray'))
        self.fig.canvas.draw()
        return boxes, scatter, lines

    def test_group_moves_cloud_and_only_its_connector_endpoints_without_changing_data(self):
        for horizontal in (False, True):
            with self.subTest(horizontal=horizontal):
                if horizontal:
                    self.fig, self.ax = plt.subplots(dpi=100)
                    self.addCleanup(plt.close, self.fig)
                boxes, cloud, lines = self.example(horizontal)
                box_before = artist_points(boxes['boxes'][0], self.fig.canvas.get_renderer()).copy()/self.fig.dpi
                line_before = [artist_points(line, self.fig.canvas.get_renderer()).copy()/self.fig.dpi for line in lines]
                raw_cloud = cloud.get_offsets().copy()
                raw_lines = [line.get_xydata().copy() for line in lines]
                point_before = {p['key']: np.array(p['hit_path_px'])/self.fig.dpi for p in targets(self.fig, []) if p['owner_key']==artist_key(self.fig, cloud)}
                apply_components(self.fig, {'axes_0.box_0': {'dx': 18, 'dy': -9}})
                for dpi in (100, 200, 72):
                    self.fig.set_dpi(dpi); self.fig.canvas.draw()
                    shift = np.array([18, -9])/72
                    np.testing.assert_allclose(artist_points(boxes['boxes'][0], self.fig.canvas.get_renderer())/dpi, box_before+shift)
                    for line, original, raw in zip(lines, line_before, raw_lines):
                        np.testing.assert_array_equal(line.get_xydata(), raw)
                        np.testing.assert_allclose(artist_points(line, self.fig.canvas.get_renderer())/dpi, original+np.array([shift,[0,0]]))
                    np.testing.assert_array_equal(cloud.get_offsets(), raw_cloud)
                    for p in targets(self.fig, []):
                        if p['key'] in point_before:
                            expected = point_before[p['key']] + (shift if p['point_group'].endswith('category_0') else 0)
                            np.testing.assert_allclose(np.array(p['hit_path_px'])/dpi, expected)

    def test_marked_paired_rows_follow_once_and_report_common_style_family(self):
        _, _, lines = self.example(marked=True)
        before = [artist_points(line, self.fig.canvas.get_renderer()).copy() for line in lines]
        apply_components(self.fig, {'axes_0.box_0': {'dx': 12}})
        self.fig.canvas.draw()
        for line, original in zip(lines, before):
            np.testing.assert_allclose(artist_points(line, self.fig.canvas.get_renderer()), original+np.array([[12*self.fig.dpi/72,0],[0,0]]))
        report = _capture(self.fig, self.fig.canvas.get_renderer())
        expected = [artist_key(self.fig, line) for line in lines]
        for record in report['artists']:
            if record['key'] in expected: self.assertEqual(record['connection_members'], expected)

    def test_unrelated_annotation_and_neighbor_box_do_not_move(self):
        boxes, cloud, lines = self.example()
        bracket, = self.ax.plot([1,1,2,2], [7,8,8,7], color='black')
        self.ax.text(1.5, 8, 'unrelated note')
        self.fig.canvas.draw()
        before = [artist_points(obj, self.fig.canvas.get_renderer()).copy() for obj in [boxes['boxes'][1], bracket]]
        report = _capture(self.fig, self.fig.canvas.get_renderer())
        group = next(g for g in report['component_groups'] if g['key']=='axes_0.box_0')
        self.assertTrue(group['move_members'])
        apply_components(self.fig, {'axes_0.box_0': {'dx': 18, 'dy': 5}})
        for obj, original in zip([boxes['boxes'][1], bracket], before):
            np.testing.assert_allclose(artist_points(obj, self.fig.canvas.get_renderer()), original)

    def test_point_specific_motion_is_additive_and_preserves_custom_style(self):
        _, cloud, _ = self.example()
        owner = artist_key(self.fig, cloud)
        layer = next(p for p in targets(self.fig, []) if p['owner_key']==owner and p['point_group'].endswith('category_0'))
        before = np.array(layer['hit_path_px'])
        apply_components(self.fig, {'axes_0.box_0': {'dx': 12}, layer['key']: {'dx': 3, 'fill_color': '#ff0000'}})
        after = next(p for p in targets(self.fig, []) if p['key']==layer['key'])
        np.testing.assert_allclose(after['hit_path_px'], before+[15*self.fig.dpi/72,0])
        np.testing.assert_allclose(after['style']['fill_color'][:3], [1,0,0])

    def test_category_tick_strokes_labels_and_grid_follow_group_on_axis_only(self):
        for horizontal in (False, True):
            with self.subTest(horizontal=horizontal):
                if horizontal:
                    self.fig, self.ax = plt.subplots(dpi=100)
                    self.addCleanup(plt.close, self.fig)
                self.example(horizontal)
                axis = self.ax.yaxis if horizontal else self.ax.xaxis
                (self.ax.set_yticks if horizontal else self.ax.set_xticks)([1,2], ['Before', 'After'])
                self.ax.grid(axis='y' if horizontal else 'x')
                self.fig.canvas.draw()
                ticks = axis.get_major_ticks()
                artists = lambda tick: (tick.tick1line, tick.tick2line, tick.label1, tick.label2, tick.gridline)
                point = lambda obj: obj.get_transform().transform(obj.get_position()) if hasattr(obj,'get_position') else obj.get_transform().transform(obj.get_path().vertices)
                before = [[np.asarray(point(obj)).copy()/self.fig.dpi for obj in artists(tick)] for tick in ticks]
                bbox = self.ax.bbox.bounds
                limits = (self.ax.get_xlim(), self.ax.get_ylim())
                apply_components(self.fig, {'axes_0.box_0': {'dx':18, 'dy':9}})
                for dpi in (100,200,72):
                    self.fig.set_dpi(dpi); self.fig.canvas.draw()
                    for i,tick in enumerate(ticks):
                        shift = np.array([0,9] if horizontal else [18,0])/72 if i==0 else np.array([0,0])
                        for obj,original in zip(artists(tick),before[i]):
                            np.testing.assert_allclose(np.asarray(point(obj))/dpi, original+shift, atol=1e-9)
                self.assertEqual([tick.label1.get_text() for tick in ticks], ['Before','After'])
                self.assertEqual((self.ax.get_xlim(), self.ax.get_ylim()), limits)
                self.fig.set_dpi(100); self.fig.canvas.draw()
                np.testing.assert_allclose(self.ax.bbox.bounds, bbox)

    def test_standalone_marked_rows_link_without_scatter_collections(self):
        rows = [self.ax.plot([1,2], [a,a+1], marker='o', color='gray')[0] for a in (1,3,5)]
        self.fig.canvas.draw()
        report = _capture(self.fig, self.fig.canvas.get_renderer())
        expected = [artist_key(self.fig, row) for row in rows]
        self.assertTrue(all(r.get('connection_members')==expected for r in report['artists'] if r['key'] in expected))

    def test_moving_category_labels_does_not_resize_constrained_layout(self):
        fig, axes = plt.subplots(1, 2, layout='constrained')
        self.addCleanup(plt.close, fig)
        axes[0].boxplot([[1,2,3],[2,3,5]], patch_artist=True)
        axes[0].set_xticks([1,2], ['Group A', 'Group B'])
        fig.canvas.draw()
        frames = [a.bbox.bounds for a in axes]
        apply_components(fig, {'axes_0.box_0': {'dx': -60}})
        fig.canvas.draw()
        for axis, frame in zip(axes, frames):
            np.testing.assert_allclose(axis.bbox.bounds, frame, atol=.01)

    def test_category_spine_ends_and_title_follow_outer_groups_across_export_dpi(self):
        for horizontal, inverted, group, delta in ((False,False,0,-18), (False,False,2,-18),
                (False,False,1,12), (False,True,2,24), (True,False,2,18), (True,True,0,-18)):
            with self.subTest(horizontal=horizontal,inverted=inverted,group=group):
                fig, ax = plt.subplots(dpi=100)
                self.addCleanup(plt.close, fig)
                ax.boxplot([[1,2,3],[2,3,4],[3,4,5]],positions=[1,2,3],patch_artist=True,
                           orientation='horizontal' if horizontal else 'vertical')
                ax.set(xlabel='X title', ylabel='Y title')
                d = 1 if horizontal else 0
                if inverted: (ax.invert_yaxis if horizontal else ax.invert_xaxis)()
                spine = ax.spines['left' if horizontal else 'bottom']
                spine.set_bounds(.8,3.2)  # Authored margins survive extension and contraction.
                numerical = ax.spines['bottom' if horizontal else 'left']
                fig.canvas.draw()
                points = np.tile([ax.get_xlim()[0],ax.get_ylim()[0]],(3,1));points[:,d]=[1,2,3]
                before = ax.transData.transform(points)[:,d]/fig.dpi
                moved = before.copy();moved[group]+=delta/72
                expected_shift=np.array([moved.min()-before.min(),moved.max()-before.max()])
                original=artist_points(spine,fig.canvas.get_renderer()).copy()/fig.dpi
                original_numerical=artist_points(numerical,fig.canvas.get_renderer()).copy()/fig.dpi
                title=(ax.yaxis if horizontal else ax.xaxis).label
                title_before=title.get_transform().transform(title.get_position())/fig.dpi
                frame=np.array(ax.bbox.bounds)/fig.dpi
                apply_components(fig,{f'axes_0.box_{group}':{'dy' if horizontal else 'dx':delta}})
                for dpi in (100,200,72):
                    fig.set_dpi(dpi);fig.canvas.draw()
                    after=artist_points(spine,fig.canvas.get_renderer())/dpi
                    np.testing.assert_allclose(np.sort(after[:,d]),np.sort(original[:,d])+expected_shift)
                    np.testing.assert_allclose(after[:,1-d],original[:,1-d])
                    np.testing.assert_allclose(artist_points(numerical,fig.canvas.get_renderer())/dpi,original_numerical)
                    title_after=title.get_transform().transform(title.get_position())/dpi
                    self.assertAlmostEqual(title_after[d],title_before[d]+expected_shift.mean())
                    np.testing.assert_allclose(np.array(ax.bbox.bounds)/dpi,frame)

    def test_full_and_seeded_worker_keep_linked_moves_and_raw_signatures(self):
        import tempfile
        from pathlib import Path
        from tests.test_fast_interactive_preview import fixture
        from chat_runner import _one_render
        from interactive_style import upsert_style
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); project, source = fixture(root)
            code = project/'lib/native/fig1/code/plot.py'
            code.write_text(code.read_text(encoding='utf-8')
                .replace('ax.boxplot([values],patch_artist=True)', 'ax.boxplot([values, np.array(values)+1],patch_artist=True)')
                .replace('ax.plot([0,1],[1,3])', "ax.scatter([1]*5+[2]*5, values+list(np.array(values)+1),color='purple')\n    for a in values: ax.plot([1,2],[a,a+1],color='gray')"), encoding='utf-8')
            baseline = _one_render(project, 'charts/fig1.py', {}, root/'baseline', capture_interactive_seed=True)
            candidate = upsert_style(source, {'component_styles': {'axes_0.box_0': {'dx': 10, 'dy': -4}}})
            fast = _one_render(project, 'charts/fig1.py', {'charts/fig1.py': candidate}, root/'fast', interactive_seed=baseline['interactive_seed_bytes'])
            full = _one_render(project, 'charts/fig1.py', {'charts/fig1.py': candidate}, root/'full')
            self.assertEqual(fast['image_bytes'], full['image_bytes'])
            self.assertEqual([(r['key'],r['data_hash']) for r in baseline['artists']], [(r['key'],r['data_hash']) for r in full['artists']])
            self.assertTrue(any(r.get('connection_members') for r in full['artists']))
