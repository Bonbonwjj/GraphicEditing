"""Local HTTP consent and conflict responses with a disposable project."""
from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

import server
from collaboration_sync import CollaborationSync, SyncConflict
from local_execution import trusted, revoke_all


class CollaborationApiTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.project = root / 'projects/demo'
        (self.project / 'charts').mkdir(parents=True)
        (self.project / 'data').mkdir()
        (self.project / 'project.json').write_text('{"name":"demo"}', encoding='utf-8')
        self.stack.enter_context(patch.object(server, 'PROJECTS', root / 'projects'))
        self.stack.enter_context(patch.object(server, 'SYNC', CollaborationSync(root)))
        self.stack.enter_context(patch.object(server.Handler, 'log_message', lambda *args: None))
        self.http = server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        self.port = self.http.server_port
        import os
        self.stack.enter_context(patch.dict(os.environ, {'CHART_STUDIO_PORT': str(self.port)}))
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.http.server_close)
        self.addCleanup(self.http.shutdown)
        self.addCleanup(revoke_all)

    def post(self, path, body, origin=None):
        request = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/' + path,
            data=json.dumps(body).encode(), headers={'Content-Type': 'application/json',
                'Origin': origin or f'http://127.0.0.1:{self.port}'})
        return urllib.request.urlopen(request, timeout=30)

    def test_project_runs_without_separate_approval(self):
        from local_execution import require_trust
        require_trust(self.project)
        self.assertTrue(trusted(self.project))
        revoke_all()
        self.assertTrue(trusted(self.project))

    def test_third_party_page_cannot_publish(self):
        with patch.object(server.SYNC, 'sync') as sync:
            # Windows can reset a rejected connection while its POST body is
            # unread. Either transport outcome must leave sync uncalled.
            with self.assertRaises((urllib.error.HTTPError, ConnectionAbortedError)):
                self.post('collaboration/publish', {'message': 'edit'}, 'https://example.test')
            sync.assert_not_called()

    def test_sync_conflicts_return_paths_and_http_409(self):
        with patch.object(server.SYNC, 'sync', side_effect=SyncConflict(['demo/charts/a.py'])):
            with self.assertRaises(urllib.error.HTTPError) as error:
                self.post('collaboration/publish', {'message': 'edit'})
        self.assertEqual(error.exception.code, 409)
        self.assertEqual(json.load(error.exception)['conflicts'], ['demo/charts/a.py'])

    def test_shared_module_candidate_requires_manual_apply_after_success(self):
        from local_execution import approve
        from shared_modules import encode_module_id
        library=self.project/'lib';library.mkdir()
        module=library/'theme.py';module.write_text("COLOR='blue'\n",encoding='utf-8')
        source="import os\nimport matplotlib.pyplot as plt\nfrom theme import COLOR\nfig,ax=plt.subplots()\nax.plot([0,1],[1,2],color=COLOR)\nfig.savefig(os.environ['CHART_OUTPUT'])\n"
        (self.project/'charts/a.py').write_text(source,encoding='utf-8')
        approve(self.project)
        base='projects/demo/modules/'+encode_module_id('theme.py')
        with self.post(base+'/preview',{'source':"COLOR='red'\n",'chart':'a'}) as response:
            draft=json.load(response)
        self.assertEqual(module.read_text(),"COLOR='blue'\n")
        with self.assertRaises(urllib.error.HTTPError):
            self.post(base+'/apply',{'draft_id':draft['id'],'acknowledge':False})
        self.assertEqual(module.read_text(),"COLOR='blue'\n")
        with self.post(base+'/apply',{'draft_id':draft['id'],'acknowledge':True}) as response:
            self.assertTrue(json.load(response)['applied'])
        self.assertEqual(module.read_text(),"COLOR='red'\n")
