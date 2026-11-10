import unittest
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from component_editor import apply_components
from component_groups import install_group_tracking, artist_key, artist_points
from point_components import targets
from chat_runner import _capture


class PointMovementLinkTests(unittest.TestCase):
    def setUp(self):
        install_group_tracking()
        self.fig,self.ax=plt.subplots(dpi=100)
        self.addCleanup(plt.close,self.fig)

    def example(self,marked=False,horizontal=False):
        values=[[1,2,3,4,20],[2,3,4,5,22]]
        self.ax.boxplot(values,positions=[1,2],patch_artist=True,orientation='horizontal' if horizontal else 'vertical')
        if not marked:
            for x,ys in zip([.99,2.01],values):
                self.ax.scatter(ys if horizontal else [x]*len(ys),[x]*len(ys) if horizontal else ys)
        lines=[self.ax.plot([a,b] if horizontal else [1,2],[1,2] if horizontal else [a,b],color='gray',marker='o' if marked else None)[0] for a,b in zip(*values)]
        self.fig.canvas.draw();return lines

    def test_point_moves_same_category_samples_outliers_and_only_connected_endpoints(self):
        for horizontal in (False,True):
            with self.subTest(horizontal=horizontal):
                if horizontal:
                    self.fig,self.ax=plt.subplots(dpi=100);self.addCleanup(plt.close,self.fig)
                lines=self.example(horizontal=horizontal)
                points=targets(self.fig,[]);selected=next(p for p in points if p['point_role']=='regular' and p['point_group']=='axes_0.category_0')
                original={p['key']:np.array(p['hit_path_px'])/100 for p in points}
                before=[artist_points(line,self.fig.canvas.get_renderer())/100 for line in lines]
                raw=[line.get_xydata().copy() for line in lines]
                box=self.ax.patches[0].get_transform().transform(self.ax.patches[0].get_path().vertices)/100
                apply_components(self.fig,{selected['key']:{'dx':18,'dy':9}})
                for dpi in (100,200,72):
                    self.fig.set_dpi(dpi);self.fig.canvas.draw()
                    for point in targets(self.fig,[]):
                        shift=np.array([18,9])/72 if point['point_group']=='axes_0.category_0' and point['point_role'] in ('regular','outliers') else 0
                        np.testing.assert_allclose(np.array(point['hit_path_px'])/dpi,original[point['key']]+shift)
                    for line,p,data in zip(lines,before,raw):
                        np.testing.assert_allclose(artist_points(line,self.fig.canvas.get_renderer())/dpi,p+np.array([[18,9],[0,0]])/72)
                        np.testing.assert_array_equal(line.get_xydata(),data)
                np.testing.assert_allclose(self.ax.patches[0].get_transform().transform(self.ax.patches[0].get_path().vertices)/self.fig.dpi,box)

    def test_connector_moves_family_and_both_clouds_exactly_once(self):
        for marked in (False,True):
            with self.subTest(marked=marked):
                if marked:
                    self.fig,self.ax=plt.subplots(dpi=100);self.addCleanup(plt.close,self.fig)
                lines=self.example(marked=marked)
                before=[artist_points(line,self.fig.canvas.get_renderer())/100 for line in lines]
                points={p['key']:np.array(p['hit_path_px'])/100 for p in targets(self.fig,[])}
                apply_components(self.fig,{artist_key(self.fig,lines[0]):{'dx':12,'dy':-6}})
                for dpi in (100,200,72):
                    self.fig.set_dpi(dpi);self.fig.canvas.draw()
                    for line,p in zip(lines,before):np.testing.assert_allclose(artist_points(line,self.fig.canvas.get_renderer())/dpi,p+np.array([12,-6])/72)
                    for point in targets(self.fig,[]):
                        # Boxplot fliers share the category and follow too.
                        np.testing.assert_allclose(np.array(point['hit_path_px'])/dpi,points[point['key']]+np.array([12,-6])/72)

    def test_marked_rows_without_distributions_move_their_common_cohort(self):
        lines=[self.ax.plot([1,2],[y,y+1],marker='o',color='gray')[0] for y in (1,3,5)]
        self.fig.canvas.draw();before=[artist_points(line,self.fig.canvas.get_renderer()).copy() for line in lines]
        selected=targets(self.fig,[])[0]
        apply_components(self.fig,{selected['key']:{'dx':9}});self.fig.canvas.draw()
        for line,p in zip(lines,before):np.testing.assert_allclose(artist_points(line,self.fig.canvas.get_renderer()),p+[12.5,0])

    def test_report_has_same_members_and_per_vertex_links_for_preview(self):
        lines=self.example();report=_capture(self.fig,self.fig.canvas.get_renderer())
        point=next(p for p in report['point_targets'] if p['point_role']=='regular' and p['point_group']=='axes_0.category_0')
        self.assertGreater(len(point['point_move_members']),1)
        line=next(r for r in report['artists'] if r['key']==artist_key(self.fig,lines[0]))
        self.assertIn(point['key'],line['point_move_vertices'][0]);self.assertNotIn(point['key'],line['point_move_vertices'][1])
        self.assertEqual(line['move_connection_members'],[artist_key(self.fig,l) for l in lines])

    def test_large_point_move_keeps_constrained_subplot_frames_fixed(self):
        self.fig,self.ax=plt.subplots(1,2,layout='constrained',dpi=100);self.addCleanup(plt.close,self.fig)
        axes=self.ax;self.ax=axes[0];self.example()
        axes[1].plot([0,1],[0,1]);self.fig.canvas.draw()
        before=[a.bbox.extents.copy() for a in axes]
        point=next(p for p in targets(self.fig,[]) if p['point_role']=='regular')
        apply_components(self.fig,{point['key']:{'dx':-100,'dy':50}});self.fig.canvas.draw()
        for axis,box in zip(axes,before):np.testing.assert_allclose(axis.bbox.extents,box,atol=.01)

    def test_saved_chart_source_replays_group_and_endpoint_movement_in_isolated_renderer(self):
        import tempfile
        from pathlib import Path
        from chat_runner import _one_render
        from interactive_style import upsert_style
        source="""import os
import matplotlib.pyplot as plt
fig,ax=plt.subplots(figsize=(4,3),dpi=100)
ax.boxplot([[1,2,3,4,20],[2,3,4,5,22]],patch_artist=True)
ax.scatter([1]*5+[2]*5,[1,2,3,4,20,2,3,4,5,22])
for a,b in zip([1,2,3,4,20],[2,3,4,5,22]):ax.plot([1,2],[a,b],color='gray')
fig.savefig(os.environ['CHART_OUTPUT'])
"""
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);project=root/'project';(project/'charts').mkdir(parents=True)
            (project/'charts/plot.py').write_text(source,encoding='utf-8')
            before=_one_render(project,'charts/plot.py',{},root/'before')
            point=next(p for p in before['point_targets'] if p['point_role']=='regular' and p['point_group']=='axes_0.category_0')
            changed=upsert_style(source,{'component_styles':{point['key']:{'dx':12,'dy':6}}})
            after=_one_render(project,'charts/plot.py',{'charts/plot.py':changed},root/'after')
            later={a['key']:a for a in after['artists']}
            count=0
            for artist in before['artists']:
                links=artist.get('point_move_vertices')
                if not links:continue
                expected=np.array([[12,6] if point['key'] in keys else [0,0] for keys in links])*100/72
                np.testing.assert_allclose(np.array(later[artist['key']]['hit_path_px'])-artist['hit_path_px'],expected,atol=1e-5);count+=1
            self.assertEqual(count,5)
            self.assertEqual([(a['key'],a['data_hash']) for a in before['artists']],[(a['key'],a['data_hash']) for a in after['artists']])


if __name__=='__main__':unittest.main()
