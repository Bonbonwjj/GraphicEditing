import json
from pathlib import Path
import tempfile
import unittest
from collaboration_sync import CollaborationSync,SyncConflict


class SharedFolderSyncTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.shared=self.root/'shared';self.shared.mkdir()
        self.alice=self.member('Alice');self.bob=self.member('Bob')

    def member(self,name):
        root=self.root/name;(root/'projects').mkdir(parents=True)
        (root/'team_collaboration.json').write_text(json.dumps({'mode':'folder','path':str(self.shared),'projects':['research']}))
        sync=CollaborationSync(root);sync.configure({'name':name,'shared_projects':['research']});return sync

    def seed(self):
        project=self.alice.root/'projects/research';(project/'charts').mkdir(parents=True)
        (project/'project.json').write_text('{"name":"Research"}')
        (project/'charts/a.py').write_text('original')
        (project/'data').mkdir();(project/'data/input.csv').write_text('x,y\n1,2\n')
        (project/'history').mkdir();(project/'history/initial.py').write_text('initial code')
        (project/'.chat').mkdir();(project/'.chat/private.json').write_text('local candidate')
        (self.alice.root/'.private-projects.json').write_text('["research"]')
        self.alice.sync(True,'Initial upload');self.bob.sync()

    def test_explicit_private_project_selection_shares_code_data_history_but_not_credentials_or_candidates(self):
        self.seed();folder=self.shared/'projects/research'
        self.assertEqual((folder/'code/charts/a.py').read_text(),'original')
        self.assertTrue((folder/'data/input.csv').is_file());self.assertTrue((folder/'code/history/initial.py').is_file())
        self.assertFalse((folder/'code/.chat').exists())
        self.assertEqual((self.bob.root/'projects/research/charts/a.py').read_text(),'original')
        self.assertFalse(CollaborationSync.files(self.alice.root/'projects')) # Git publication still excludes it.

    def test_disjoint_changes_merge_and_same_file_conflicts_preserve_every_copy(self):
        self.seed();a=self.alice.root/'projects/research/charts/a.py';b=self.bob.root/'projects/research/charts/a.py'
        a.write_text('Alice');(b.parent/'b.py').write_text('Bob new chart')
        self.alice.sync(True,'Alice edits');self.bob.sync(True,'Bob adds chart')
        self.assertEqual(b.read_text(),'Alice');self.alice.sync()
        self.assertEqual((a.parent/'b.py').read_text(),'Bob new chart')
        a.write_text('Alice again');b.write_text('Bob conflict');self.alice.sync(True,'New Alice edit')
        with self.assertRaises(SyncConflict):self.bob.sync(True,'Conflict')
        self.assertEqual(b.read_text(),'Bob conflict');self.assertEqual((self.shared/'projects/research/code/charts/a.py').read_text(),'Alice again')
        self.assertFalse((self.shared/'.plot-forge-sync.lock').exists())

    def test_lock_and_offline_share_do_not_change_local_project(self):
        self.seed();lock=self.shared/'.plot-forge-sync.lock';lock.mkdir()
        with self.assertRaisesRegex(ValueError,'其他成员'):self.alice.sync()
        lock.rmdir();self.alice.team_target=lambda:{'mode':'folder','path':str(self.root/'missing'),'projects':['research']}
        self.assertFalse(self.alice.status()['available'])
        with self.assertRaisesRegex(ValueError,'不可访问'):self.alice.sync()
        self.assertFalse((self.root/'missing').exists())

    def test_deletion_merges_without_touching_unselected_projects(self):
        self.seed();other=self.shared/'projects/other/code';other.mkdir(parents=True);(other/'project.json').write_text('{}')
        (self.alice.root/'projects/research/charts/a.py').unlink();self.alice.sync(True,'Remove obsolete chart');self.bob.sync()
        self.assertFalse((self.bob.root/'projects/research/charts/a.py').exists());self.assertTrue((other/'project.json').is_file())

    def test_frozen_code_and_input_bytes_keep_their_line_endings(self):
        self.seed();path=self.alice.root/'projects/research/data/frozen.json'
        path.write_bytes(b'{"fixed":true}\r\n');self.alice.sync(True,'Add frozen input');self.bob.sync()
        self.assertEqual((self.shared/'projects/research/data/frozen.json').read_bytes(),path.read_bytes())
        self.assertEqual((self.bob.root/'projects/research/data/frozen.json').read_bytes(),path.read_bytes())


if __name__=='__main__':unittest.main()
