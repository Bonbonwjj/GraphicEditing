import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib import error
import shared_workspace
from shared_workspace import SharedFileLock,projects_path
from collaboration_sync import CollaborationSync


class DirectSharedWorkspaceTests(unittest.TestCase):
    def test_direct_path_never_falls_back_to_local_when_unmounted(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);local=root/'app';(local/'projects').mkdir(parents=True)
            target={'mode':'direct','path':str(root/'offline'),'projects':['research']}
            (local/'team_collaboration.json').write_text(json.dumps(target))
            self.assertEqual(projects_path(local,target),root/'offline/projects')
            status=CollaborationSync(local).status()
            self.assertEqual(status['mode'],'direct');self.assertFalse(status['available']);self.assertFalse(status['auto_pull'])
            with self.assertRaisesRegex(ValueError,'无需'):CollaborationSync(local).sync(True,'save')

    def test_two_processes_cannot_hold_shared_file_lock_simultaneously(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'write.lock'
            script="from pathlib import Path\nimport sys\nfrom shared_workspace import SharedFileLock\nwith SharedFileLock(Path(sys.argv[1])):\n print('READY',flush=True)\n sys.stdin.readline()\n"
            process=subprocess.Popen([sys.executable,'-c',script,str(path)],cwd=Path(__file__).resolve().parents[1],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            try:
                self.assertEqual(process.stdout.readline().strip(),'READY')
                lock=SharedFileLock(path);self.assertFalse(lock.acquire(blocking=False))
                process.communicate('\n',timeout=10);self.assertEqual(process.returncode,0)
                self.assertTrue(lock.acquire(blocking=False));self.assertTrue(lock.acquire(blocking=False));lock.release();lock.release()
            finally:
                if process.poll() is None:process.kill();process.communicate()

    def test_shared_lock_names_are_based_on_relative_project_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'projects'
            with patch.object(shared_workspace,'SHARED_ROOT',root):
                self.assertIsNotNone(shared_workspace.shared_lock_path(root/'research'))
                self.assertIsNone(shared_workspace.shared_lock_path(root.parent/'local'))


class DirectSharedApiTests(unittest.TestCase):
    from tests.test_collaboration_api import CollaborationApiTests as _base
    setUp=_base.setUp
    post=_base.post

    def test_stale_and_missing_versions_cannot_overwrite_shared_chart(self):
        import server
        source=self.project/'charts/a.py';source.write_text('# initial\n')
        with patch.object(shared_workspace,'SHARED_ROOT',self.project.parent),patch.object(server,'render',return_value=b'png') as render,patch.object(server,'save_preview'),patch.object(server,'snapshot_image'):
            for body in ({'code':'# stale\n','base_revision':'old'},{'code':'# no revision\n'}):
                with self.assertRaises(error.HTTPError):self.post('projects/demo/charts/a/apply',body)
                self.assertEqual(source.read_text(),'# initial\n')
            render.assert_not_called()
            revision=server.source_revision(source.read_text())
            with self.post('projects/demo/charts/a/apply',{'code':'# Alice\n','base_revision':revision}) as response:self.assertEqual(response.status,200)
            with self.assertRaises(error.HTTPError):self.post('projects/demo/charts/a/apply',{'code':'# Bob\n','base_revision':revision})
            self.assertEqual(source.read_text(),'# Alice\n')
            self.assertTrue((self.project/'history/a.json').is_file())


if __name__=='__main__':unittest.main()
