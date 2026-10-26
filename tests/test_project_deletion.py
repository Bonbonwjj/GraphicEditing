"""Destructive regression tests operate exclusively on disposable copies."""
from contextlib import contextmanager
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import project_preparation as prep
from chat_harness import lock
from project_deletion import deletion_info, delete_project


@contextmanager
def held_elsewhere(guard):
    ready, finish = threading.Event(), threading.Event()
    def hold():
        with guard:
            ready.set()
            finish.wait(10)
    worker = threading.Thread(target=hold)
    worker.start()
    try:
        assert ready.wait(5)
        yield
    finally:
        finish.set()
        worker.join(5)


class ProjectDeletionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='plot-delete-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.projects = self.root / 'app/projects'
        self.source = self.root / 'original'
        self.source.mkdir()
        (self.source / 'plot.py').write_text('# original code\n')
        (self.source / 'values.csv').write_bytes(b'x,y\n1,2\n')
        prep.open_project(self.projects, self.source, 'copy')
        self.project = self.projects / 'copy'

    def remove(self, **kwargs):
        info = deletion_info(self.projects, 'copy')
        return delete_project(self.projects, 'copy', 'copy', info['confirmation_token'], **kwargs)

    def test_delete_only_workspace_copy_preserves_sources_other_projects_and_privacy(self):
        before = {p.name: p.read_bytes() for p in self.source.iterdir()}
        prep.open_project(self.projects, self.source, 'other')
        (self.root / 'downloaded-backup.zip').write_bytes(b'backup')
        with patch('llm_client.chat') as cloud:
            result = self.remove()
            cloud.assert_not_called()
        self.assertTrue(result['originals_preserved'])
        self.assertFalse(self.project.exists())
        self.assertTrue((self.projects / 'other/project.json').is_file())
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.source.iterdir()})
        self.assertEqual((self.root / 'downloaded-backup.zip').read_bytes(), b'backup')
        self.assertIn('copy', json.loads((self.projects.parent / '.private-projects.json').read_text()))
        self.assertIn('/projects/copy/', (self.projects.parent / '.gitignore').read_text())
        self.assertEqual(prep.open_project(self.projects, self.source, 'copy')['status'], 'needs_analysis')

    def test_requires_exact_confirmation_and_fresh_preview(self):
        info = deletion_info(self.projects, 'copy')
        for name, token in [('', info['confirmation_token']), ('other', info['confirmation_token']), ('copy', ''), ('copy', 'stale')]:
            with self.assertRaises(ValueError):
                delete_project(self.projects, 'copy', name, token)
        self.project.rename(self.projects / 'old')
        prep.open_project(self.projects, self.source, 'copy')
        with self.assertRaisesRegex(ValueError, '已变化'):
            delete_project(self.projects, 'copy', 'copy', info['confirmation_token'])
        self.assertTrue(self.project.exists())

    def test_rejects_invalid_paths_symlinks_and_mounts(self):
        for name in ('..', '../original', '/tmp', 'copy/sub', ''):
            with self.assertRaises(ValueError):
                deletion_info(self.projects, name)
        (self.projects / 'alias').symlink_to(self.source, target_is_directory=True)
        with self.assertRaises(ValueError):deletion_info(self.projects, 'alias')
        linked = self.project / 'data/external'
        linked.symlink_to(self.source, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, '符号链接'):self.remove()
        linked.unlink()
        with patch.object(Path, 'is_mount', return_value=True):
            with self.assertRaisesRegex(ValueError, '挂载'):self.remove()
        alias = self.root / 'linked-projects'
        alias.symlink_to(self.projects, target_is_directory=True)
        with self.assertRaises(ValueError):deletion_info(alias, 'copy')

    def test_rejects_source_overlap_including_other_project_origins(self):
        original = prep.read_state(self.project)
        for source in (self.project, self.project / 'data', self.projects):
            prep.save_state(self.project, {**original, 'source_path': str(source)})
            with self.assertRaisesRegex(ValueError, '重叠'):self.remove()
        prep.save_state(self.project, original)
        prep.open_project(self.projects, self.source, 'other')
        other = self.projects / 'other'
        prep.save_state(other, {**prep.read_state(other), 'source_path': str(self.project / 'data')})
        with self.assertRaisesRegex(ValueError, '重叠'):self.remove()

    def test_blocks_active_preparation_chat_and_render(self):
        prep.RUNNING.add(str(self.project))
        try:
            with self.assertRaisesRegex(ValueError, '准备'):self.remove()
        finally:prep.RUNNING.discard(str(self.project))
        session = self.project / '.chat/sessions/ses_test/session.json'
        session.parent.mkdir(parents=True)
        session.write_text('{}')
        (self.project / 'charts/line.py').write_text('# line')
        for guard in (lock(session), lock(self.project), lock('fake-preview')):
            with held_elsewhere(guard):
                with self.assertRaisesRegex(ValueError, '改图或渲染'):
                    self.remove(preview_lock=lambda p, c: lock('fake-preview'))
        self.assertTrue(self.project.exists())


if __name__ == '__main__':unittest.main()
