"""Exercise real headless preview export without a model or Docker."""
from pathlib import Path
import tempfile
import unittest
import server


class PreviewRuntimeTests(unittest.TestCase):
    def test_show_after_close_keeps_successful_export(self):
        source = """import os
import matplotlib.pyplot as plt
from studio_style import finish_figure
fig, ax = plt.subplots()
ax.plot([0, 1], [1, 2])
ax.set(xlabel='Time', ylabel='Value')
finish_figure(fig, os.environ['CHART_OUTPUT'])
fig.show()
"""
        with tempfile.TemporaryDirectory() as directory:
            image = server.render(Path(directory), source)
        self.assertTrue(image.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertEqual(image.naming['display_name'], 'Time_Value')
