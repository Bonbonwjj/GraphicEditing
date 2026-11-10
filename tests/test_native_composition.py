import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from PIL import Image
from native_plot_runtime import _compose_native_results


class NativeCompositionTests(unittest.TestCase):
    def test_crop_and_raster_scale_with_preview_dpi(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); native = root/'native-work/fig1'
            native.mkdir(parents=True)
            Image.new('RGB', (400, 200), 'white').save(native/'top.png')
            for dpi, width_inches in ((100, 4), (50, 4), (25, 4), (100, 4.009), (50, 4.009)):
                with self.subTest(dpi=dpi):
                    fig = plt.figure(figsize=(width_inches, 6), dpi=dpi)
                    try:
                        axis = fig.add_axes([.1, .05, .8, .2]); axis.plot([0,1],[0,1])
                        before = axis.get_position().height*fig.get_figheight()
                        with patch.dict(os.environ, {'CHART_OUTPUT': str(root/'figure.png')}):
                            _compose_native_results(fig, {'approved_top':'top.png', 'cut_px':400, 'source_dpi':100})
                        self.assertAlmostEqual(fig.get_figheight(), 4)
                        self.assertAlmostEqual(axis.get_position().height*fig.get_figheight(), before)
                        self.assertEqual(fig.images[0].get_array().shape[:2], (2*dpi, 4*dpi))
                    finally:
                        plt.close(fig)
