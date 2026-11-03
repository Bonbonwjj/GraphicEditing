import tempfile
import unittest
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from component_groups import (install_group_tracking, component_groups, artist_points,
                              artist_key, group_report, CollectionSegment, register_component_group)
from component_editor import apply_components, resolve_component


class GenericComponentGroupTests(unittest.TestCase):
    def setUp(self):
        install_group_tracking()
        self.fig, self.axis = plt.subplots()
        self.addCleanup(plt.close, self.fig)

    def test_isolated_worker_registers_boxes_and_violins_without_project_setup(self):
        from chat_runner import _one_render
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); project=root/'project'; (project/'charts').mkdir(parents=True)
            source="""import os
import matplotlib.pyplot as plt
from interactive_style import apply_interactive_style
fig,(a,b)=plt.subplots(1,2)
a.boxplot([[1,2,3,4,5],[2,3,4,5,6]],patch_artist=True)
b.violinplot([[1,2,3,4,5],[2,3,4,5,6]],showmeans=True,showmedians=True)
apply_interactive_style(fig,{'component_styles':{'axes_0.box_0':{'edge_color':'#ff0000'},'axes_1.violin_0':{'edge_color':'#00aa55'}}})
fig.savefig(os.environ['CHART_OUTPUT'])
"""
            (project/'charts/plot.py').write_text(source,encoding='utf-8')
            report=_one_render(project,'charts/plot.py',{},root/'render')
            groups={g['key']:g for g in report['component_groups']}
            self.assertEqual(set(groups),{'axes_0.box_0','axes_0.box_1','axes_1.violin_0','axes_1.violin_1'})
            box=groups['axes_0.box_0']; records={r['key']:r for r in report['artists']}
            for key in box['members']:
                obj=records[key]
                if obj['kind']=='patch': np.testing.assert_allclose(obj['style']['edgecolor'],[1,0,0,1])
                else: self.assertEqual(obj['style']['color'],'#ff0000')
            violin=groups['axes_1.violin_0']
            self.assertTrue(any('.segment_' in part['key'] for part in violin['part_targets']))
            self.assertFalse(any(r.get('distribution_mutated') for r in report['artists']))

    def test_violin_parts_colors_width_opacity_and_motion_do_not_leak_to_neighbor(self):
        result=self.axis.violinplot([[1,2,3,4,5],[2,3,4,5,6]],showmeans=True,showmedians=True,
                                    quantiles=[[.25,.75],[.5]])
        self.fig.canvas.draw()
        groups=component_groups(self.fig); first=groups['axes_0.violin_0']; second=groups['axes_0.violin_1']
        before=[artist_points(obj,self.fig.canvas.get_renderer()).copy() for obj in first]
        neighbor=[artist_points(obj,self.fig.canvas.get_renderer()).copy() for obj in second]
        neighbor_colors=[np.asarray(obj.get_edgecolor()).copy() for obj in second]
        segments={key:[p.copy() for p in collection.get_segments()] for key,collection in result.items() if key!='bodies'}
        apply_components(self.fig,{'axes_0.violin_0':{'edge_color':'#ff0000','edge_alpha':.7,'linewidth':4,'dx':12,'width_scale':1.4}})
        self.fig.canvas.draw()
        old=np.concatenate(before); center=(old.min(axis=0)+old.max(axis=0))/2
        for obj,points in zip(first,before):
            expected=(points-center)*[1.4,1]+center+[12*self.fig.dpi/72,0]
            np.testing.assert_allclose(artist_points(obj,self.fig.canvas.get_renderer()),expected,atol=1e-7)
            np.testing.assert_allclose(np.asarray(obj.get_edgecolor()).reshape(-1,4)[0],[1,0,0,.7])
        for obj,points,color in zip(second,neighbor,neighbor_colors):
            np.testing.assert_allclose(artist_points(obj,self.fig.canvas.get_renderer()),points,atol=1e-7)
            np.testing.assert_allclose(obj.get_edgecolor(),color)
        for key,original in segments.items():
            for a,b in zip(result[key].get_segments(),original): np.testing.assert_array_equal(a,b)

    def test_horizontal_violin_width_and_single_summary_segment(self):
        result=self.axis.violinplot([[1,2,3,4,5],[2,3,4,5,6]],orientation='horizontal',showmedians=True)
        self.fig.canvas.draw(); body=result['bodies'][0]
        before=artist_points(body,self.fig.canvas.get_renderer())
        apply_components(self.fig,{'axes_0.violin_0':{'width_scale':2}})
        after=artist_points(body,self.fig.canvas.get_renderer())
        np.testing.assert_allclose(after[:,0],before[:,0])
        self.assertAlmostEqual(np.ptp(after[:,1]),2*np.ptp(before[:,1]))
        segment=CollectionSegment(result['cmedians'],0); key=artist_key(self.fig,segment)
        other=CollectionSegment(result['cmedians'],1).get_color()
        apply_components(self.fig,{key:{'color':'#0066ff','linewidth':5}})
        self.assertIsInstance(resolve_component(self.fig,key),CollectionSegment)
        np.testing.assert_allclose(segment.get_color(),[0,.4,1,1])
        np.testing.assert_allclose(CollectionSegment(result['cmedians'],1).get_color(),other)

    def test_group_properties_are_inherited_independent_of_style_order(self):
        for reverse in (False,True):
            fig,axis=plt.subplots();self.addCleanup(plt.close,fig)
            result=axis.violinplot([[1,2,3,4,5],[2,3,4,5,6]],showmedians=True)
            segment=CollectionSegment(result['cmedians'],0);key=artist_key(fig,segment)
            pairs=[('axes_0.violin_0',{'edge_color':'#00aa55','linewidth':4}),
                   (key,{'color':'#0066ff'})]
            apply_components(fig,dict(reversed(pairs) if reverse else pairs))
            np.testing.assert_allclose(segment.get_color(),[0,2/3,1/3,1])
            self.assertEqual(segment.get_linewidth(),4)

    def test_bars_stems_and_explicit_custom_groups(self):
        bars=self.axis.bar([1,2],[3,4],yerr=.2,capsize=4)
        stem=self.axis.stem([3,4],[2,3])
        groups=component_groups(self.fig)
        self.assertTrue(all(patch in groups['axes_0.bars_0'] for patch in bars.patches))
        self.assertIn(bars.errorbar.lines[2][0],groups['axes_0.bars_0'])
        self.assertIn(stem.markerline,groups['axes_0.stem_0'])
        line,=self.axis.plot([5,6],[1,2]); text=self.axis.scatter([5],[1])
        key=register_component_group(self.axis,[line,text],'自定义组合')
        self.fig.canvas.draw(); report=group_report(self.fig,[])
        self.assertEqual(next(g for g in report if g['key']==key)['label'],'自定义组合')
        apply_components(self.fig,{key:{'color':'#ff0000'}})
        self.assertEqual(line.get_color(),'#ff0000')
        np.testing.assert_allclose(text.get_facecolor()[0],[1,0,0,1])


if __name__=='__main__': unittest.main()
