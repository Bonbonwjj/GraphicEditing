"""Real Git integration with two collaborators and a disposable bare remote."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from collaboration_sync import CollaborationSync, SyncConflict


def git(cwd, *args):
    result = subprocess.run(['git', *args], cwd=cwd, capture_output=True, text=True,
                            encoding='utf-8', errors='replace', check=True)
    return result.stdout.strip()


class CollaborationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.remote = self.root / 'remote.git'
        git(self.root, 'init', '--bare', str(self.remote))
        seed = self.root / 'seed'
        seed.mkdir()
        git(seed, 'init', '-b', 'main')
        git(seed, 'config', 'user.name', 'Seed')
        git(seed, 'config', 'user.email', 'seed@example.test')
        chart = seed / 'projects/demo/charts/a.py'
        chart.parent.mkdir(parents=True)
        chart.write_text('print("baseline")\n', encoding='utf-8', newline='\n')
        (seed / 'projects/demo/project.json').write_text('{"name":"Demo"}', encoding='utf-8')
        git(seed, 'add', 'projects')
        git(seed, 'commit', '-m', 'initial project')
        git(seed, 'remote', 'add', 'origin', str(self.remote))
        git(seed, 'push', '-u', 'origin', 'main')
        self.alice = self.member('Alice')
        self.bob = self.member('Bob')

    def member(self, name):
        root = self.root / name
        root.mkdir()
        (root / 'projects').mkdir()
        sync = CollaborationSync(root)
        sync.folder.mkdir()
        git(root, '-c', 'core.autocrlf=false', 'clone', '-b', 'main', str(self.remote), str(sync.checkout))
        git(sync.checkout, 'config', 'user.name', name)
        git(sync.checkout, 'config', 'user.email', name.lower() + '@example.test')
        # Public API restricts endpoints to GitHub; fixtures use a local bare remote.
        sync.config_file.write_text(json.dumps({'remote': str(self.remote), 'branch': 'main',
                                               'name': name, 'email': name.lower() + '@example.test'}), encoding='utf-8')
        sync.sync()
        return sync

    def change(self, member, text, name='a.py'):
        path = member.root / 'projects/demo/charts' / name
        path.write_text(text, encoding='utf-8', newline='\n')
        return path

    def test_publish_pull_preserves_author_and_private_drafts(self):
        self.change(self.alice, 'print("Alice")\n')
        secret = self.alice.root / 'projects/demo/.chat/session.json'
        secret.parent.mkdir()
        secret.write_text('private draft', encoding='utf-8')
        (self.alice.root / '.model-api.json').write_text('private key', encoding='utf-8')
        self.alice.sync(True, 'Adjust chart color')
        self.bob.sync()
        self.assertEqual((self.bob.root / 'projects/demo/charts/a.py').read_text(), 'print("Alice")\n')
        tracked = git(self.alice.checkout, 'ls-files')
        self.assertIn('projects/demo/code/charts/a.py', tracked)
        self.assertIn('projects/demo/code/project.json', tracked)
        self.assertNotIn('projects/demo/charts/', tracked)
        self.assertNotIn('.chat', tracked)
        self.assertNotIn('.model-api.json', tracked)
        self.assertEqual(git(self.bob.checkout, 'log', '-1', '--format=%an'), 'Alice')

    def test_conflicting_same_file_does_not_overwrite_either_member(self):
        self.change(self.alice, 'print("Alice")\n')
        bob_path = self.change(self.bob, 'print("Bob")\n')
        self.alice.sync(True, 'Alice edit')
        with self.assertRaises(SyncConflict) as error:
            self.bob.sync(True, 'Bob edit')
        self.assertEqual(error.exception.paths, ['demo/charts/a.py'])
        self.assertEqual(bob_path.read_text(), 'print("Bob")\n')
        self.assertEqual(git(self.bob.checkout, 'show', 'HEAD:projects/demo/code/charts/a.py'), 'print("Alice")')

    def test_changes_to_different_files_merge_and_publish(self):
        self.change(self.alice, 'print("Alice")\n')
        self.change(self.bob, 'print("Bob extra")\n', 'b.py')
        self.alice.sync(True, 'Alice edit')
        self.bob.sync(True, 'Bob adds chart')
        self.alice.sync()
        self.assertTrue((self.alice.root / 'projects/demo/charts/b.py').exists())
        self.assertEqual((self.bob.root / 'projects/demo/charts/a.py').read_text(), 'print("Alice")\n')

    def test_legacy_projects_migrate_on_publish_and_new_member_can_open(self):
        data=self.alice.root/'projects/demo/data/values.csv'
        data.parent.mkdir();data.write_text('x,y\n1,2\n',encoding='utf-8')
        self.alice.sync(True,'Organize project data and code')
        tracked=git(self.alice.checkout,'ls-files').splitlines()
        self.assertEqual({path.split('/')[2] for path in tracked},{'data','code'})
        charlie=self.member('Charlie')
        self.assertEqual((charlie.root/'projects/demo/data/values.csv').read_text(),'x,y\n1,2\n')
        self.assertTrue((charlie.root/'projects/demo/project.json').is_file())
        self.assertTrue((charlie.root/'projects/demo/charts/a.py').is_file())
        charlie.sync(True,'Round trip canonical layout')
        self.assertEqual(git(charlie.checkout,'ls-files').splitlines(),tracked)

    def test_pull_preserves_unpublished_local_edit(self):
        self.change(self.bob, 'print("work in progress")\n')
        self.bob.sync()
        self.assertEqual((self.bob.root / 'projects/demo/charts/a.py').read_text(), 'print("work in progress")\n')

    def test_sync_keeps_automatic_local_execution(self):
        from local_execution import approve, trusted
        project = self.alice.root / 'projects/demo'
        approve(project)
        self.assertTrue(trusted(project))
        self.alice.sync()
        self.assertTrue(trusted(project))

    def test_connect_rejects_urls_containing_credentials(self):
        with self.assertRaises(ValueError):
            self.alice.configure({'remote': 'https://token@github.com/team/repo.git', 'branch': 'main',
                                  'name': 'Alice', 'email': 'alice@example.test'})

    def test_team_target_cannot_be_redirected_by_personal_request(self):
        target = {'remote': 'https://github.com/team/fixed.git', 'branch': 'team'}
        (self.alice.root / 'team_collaboration.json').write_text(json.dumps(target), encoding='utf-8')
        self.assertEqual(self.alice.status()['branch'], 'team')
        self.assertFalse(self.alice.status()['configured'])
        with self.assertRaisesRegex(ValueError, '不能从个人页面更改'):
            self.alice.configure({'remote': 'https://github.com/other/repo.git',
                                  'name': 'Alice', 'email': 'alice@example.test'})
        with self.assertRaisesRegex(ValueError, '平台固定'):
            self.alice.sync(True, 'must not publish to old target')

    def test_fixed_target_connect_only_requires_author_identity(self):
        from unittest.mock import patch
        target = {'remote': 'https://github.com/team/fixed.git', 'branch': 'team'}
        (self.alice.root / 'team_collaboration.json').write_text(json.dumps(target), encoding='utf-8')
        # Remove the disposable fixture's previous personal connection.
        self.alice.config_file.unlink()
        with patch.object(self.alice, 'git') as command:
            status = self.alice.configure({'name': 'Alice', 'email': 'alice@example.test'})
        self.assertTrue(status['configured'])
        self.assertEqual(self.alice.config()['remote'], target['remote'])
        self.assertEqual(self.alice.config()['branch'], 'team')

    def test_first_pull_connects_fixed_target_without_author(self):
        from unittest.mock import patch
        target = {'remote': 'https://github.com/team/fixed.git', 'branch': 'main'}
        (self.alice.root / 'team_collaboration.json').write_text(json.dumps(target), encoding='utf-8')
        self.alice.config_file.unlink()
        original_git = self.alice.git
        with patch.object(self.alice, 'git', side_effect=lambda *args, **kwargs: '' if args[0] == 'config' else original_git(*args, **kwargs)):
            result = self.alice.sync()
        self.assertFalse(result['published'])
        self.assertEqual(self.alice.config()['remote'], target['remote'])
        with self.assertRaisesRegex(ValueError, '提交修改前'):
            self.alice.sync(True, 'requires author')

    def test_ignored_data_cannot_be_reported_as_published(self):
        ignore = self.root / 'ignore-patterns'
        ignore.write_text('*.csv\n', encoding='utf-8')
        git(self.alice.checkout, 'config', 'core.excludesfile', str(ignore))
        data = self.alice.root / 'projects/demo/data/new.csv'
        data.parent.mkdir()
        data.write_text('x,y\n1,2\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'new.csv'):
            self.alice.sync(True, 'Upload data')
        self.assertTrue(data.exists())

    def test_bundle_json_hash_bytes_survive_git_synchronization(self):
        bundle=self.alice.root/'projects/demo/data/bundle'
        bundle.mkdir(parents=True)
        data=b'{\r\n  "analysis": "border"\r\n}\r\n'
        (bundle/'plot_specs.json').write_bytes(data)
        (bundle/'.gitattributes').write_text('** -text\n',encoding='utf-8')
        self.alice.sync(True,'Upload bundle index')
        self.bob.sync()
        self.assertEqual((self.bob.root/'projects/demo/data/bundle/plot_specs.json').read_bytes(),data)
