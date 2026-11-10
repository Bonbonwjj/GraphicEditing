import json
from pathlib import Path
import signal
import tempfile
import unittest
from unittest.mock import patch

import launch


class RuntimeLauncherTests(unittest.TestCase):
    def test_new_or_changed_module_invalidates_runtime_but_project_edits_do_not(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'server.py').write_text('pass')
            initial = launch.runtime_fingerprint(root)
            (root/'projects').mkdir()
            (root/'projects/data.csv').write_text('value\n1\n')
            self.assertEqual(initial, launch.runtime_fingerprint(root))
            module = root/'plot_modes.py'; module.write_text('def apply(): pass')
            updated = launch.runtime_fingerprint(root)
            self.assertNotEqual(initial, updated)
            module.write_text('def apply(): return True')
            self.assertNotEqual(updated, launch.runtime_fingerprint(root))

    def test_current_server_is_reused_without_starting_another_process(self):
        server = {'app': 'plot-forge', 'root': str(launch.ROOT), 'pid': 12345,
                  'runtime_fingerprint': launch.runtime_fingerprint()}
        with patch.object(launch, 'health', return_value=server), \
                patch.object(launch.webbrowser, 'open') as open_page, \
                patch.object(launch.subprocess, 'Popen') as start:
            launch.main()
            open_page.assert_called_once_with('http://127.0.0.1:8765/')
            start.assert_not_called()

    def test_legacy_backend_is_stopped_only_after_identity_recheck(self):
        server = {'app': 'plot-forge', 'root': str(launch.ROOT), 'pid': 12345}
        with patch.object(launch, 'health', side_effect=[server, None]), \
                patch.object(launch.os, 'kill') as stop:
            launch.stop_stale_server(8765, server)
            stop.assert_called_once_with(12345, signal.SIGTERM)

    def test_different_process_or_checkout_is_never_stopped(self):
        server = {'app': 'plot-forge', 'root': str(launch.ROOT), 'pid': 12345}
        for current in ({**server, 'pid': 54321}, {**server, 'root': str(launch.ROOT.parent)},
                        {**server, 'app': 'another-app'}):
            with self.subTest(current=current), patch.object(launch, 'health', return_value=current), \
                    patch.object(launch.os, 'kill') as stop:
                with self.assertRaises(RuntimeError):
                    launch.stop_stale_server(8765, server)
                stop.assert_not_called()

    def test_active_chat_task_prevents_automatic_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root/'projects/demo/.chat/sessions/one/session.json'
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({'status': 'running'}), encoding='utf-8')
            server = {'app': 'plot-forge', 'root': str(root), 'pid': 12345}
            with patch.object(launch, 'ROOT', root), patch.object(launch, 'health', return_value=server), \
                    patch.object(launch.os, 'kill') as stop:
                with self.assertRaisesRegex(RuntimeError, '正在处理'):
                    launch.stop_stale_server(8765, server)
                stop.assert_not_called()
