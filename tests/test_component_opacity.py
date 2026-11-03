import unittest
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from interactive_style import apply_interactive_style, upsert_style, read_style
from component_editor import validate_components


class ComponentOpacityTests(unittest.TestCase):
    def test_errorbar_marker_and_caps_support_separate_opacity(self):
        fig,axis=plt.subplots();self.addCleanup(plt.close,fig)
        error=axis.errorbar([1],[2],yerr=.3,fmt='o',capsize=8,color='#ff0000')
        apply_interactive_style(fig,{'component_styles':{'axes_0.mean_error_0':{'fill_alpha':.2,'edge_alpha':.7}}})
        self.assertAlmostEqual(error.lines[0].get_markerfacecolor()[3],.2)
        for cap in error.lines[1]:self.assertAlmostEqual(cap.get_markeredgecolor()[3],.7)
        self.assertAlmostEqual(error.lines[2][0].get_edgecolor()[0,3],.7)

    def test_line_text_and_fill_edge_alpha_are_independent(self):
        fig,axis=plt.subplots();self.addCleanup(plt.close,fig)
        line,=axis.plot([0,1],[1,2]);other,=axis.plot([0,1],[2,1]);axis.set_ylabel('Y')
        patch=Rectangle((.2,.2),.2,.2,facecolor='red',edgecolor='blue');axis.add_patch(patch)
        dots=axis.scatter([.5],[.5],facecolor='green',edgecolor='black',alpha=.8)
        style={'component_styles':{'axes_0.line_0':{'alpha':.4},'axes_0.ylabel':{'alpha':.6},
            'axes_0.patch_0':{'fill_alpha':.2,'edge_alpha':.9},'axes_0.collection_0':{'fill_alpha':.3}}}
        apply_interactive_style(fig,style)
        self.assertEqual(line.get_alpha(),.4);self.assertIsNone(other.get_alpha())
        self.assertEqual(axis.yaxis.label.get_alpha(),.6)
        self.assertAlmostEqual(patch.get_facecolor()[3],.2);self.assertAlmostEqual(patch.get_edgecolor()[3],.9)
        self.assertAlmostEqual(dots.get_facecolors()[0,3],.3);self.assertAlmostEqual(dots.get_edgecolors()[0,3],.8)
        source='import matplotlib.pyplot as plt\nfig,ax=plt.subplots()\nfig.savefig("out.png")\n'
        self.assertEqual(read_style(upsert_style(source,style))['component_styles'],style['component_styles'])

    def test_transparency_does_not_change_rgb_and_rejects_invalid_alpha(self):
        fig,axis=plt.subplots();self.addCleanup(plt.close,fig)
        patch=Rectangle((0,0),1,1,facecolor='#ff0080',edgecolor='#0066ff');axis.add_patch(patch)
        rgb=patch.get_facecolor()[:3]
        apply_interactive_style(fig,{'component_styles':{'axes_0.patch_0':{'fill_alpha':0}}})
        self.assertEqual(patch.get_facecolor()[:3],rgb);self.assertEqual(patch.get_facecolor()[3],0)
        for value in (-.1,1.1,True,float('nan')):
            with self.assertRaises(ValueError): validate_components({'axes_0.line_0':{'alpha':value}})
