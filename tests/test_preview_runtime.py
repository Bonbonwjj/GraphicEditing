"""Exercise real headless preview export without a model or Docker."""
from pathlib import Path
import os
import tempfile
import time
import unittest
from unittest.mock import patch
import server


class PreviewRuntimeTests(unittest.TestCase):
    def test_repeated_preview_signatures_reuse_data_hash_and_detect_changes(self):
        import project_preparation as prep
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'data').mkdir()
            data=root/'data/values.csv';data.write_text('x,y\n1,2\n')
            server._cached_preview_digest.cache_clear()
            with patch.object(prep,'sha',wraps=prep.sha) as digest:
                first=server.preview_signature(root,'pass')
                self.assertEqual(first,server.preview_signature(root,'pass'))
                self.assertEqual(sum(call.args[0]==data for call in digest.call_args_list),1)
                stat=data.stat()
                # Some filesystems coalesce timestamp updates within one tick.
                time.sleep(0.02)
                data.write_text('x,y\n1,9\n')
                os.utime(data,ns=(stat.st_atime_ns,stat.st_mtime_ns))
                self.assertNotEqual(first,server.preview_signature(root,'pass'))
                self.assertEqual(sum(call.args[0]==data for call in digest.call_args_list),2)

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
