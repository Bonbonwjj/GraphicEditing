import json
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib import request, error

import tests.test_collaboration_api as api_tests


class WorkspaceApiTests(unittest.TestCase):
    setUp = api_tests.CollaborationApiTests.setUp
    post = api_tests.CollaborationApiTests.post

    def test_chat_save_delete_http_routes_preserve_formal_code(self):
        source=self.project/'charts/example.py';source.write_text('# do not run\n')
        from local_execution import approve
        approve(self.project)
        with self.post('projects/demo/chat/sessions',{'charts':['example']}) as response:
            sid=json.load(response)['id']
        route='projects/demo/chat/sessions/'+sid
        with self.post(route+'/save',{'title':'测试对话'}) as response:
            self.assertEqual(json.load(response)['title'],'测试对话')
        with self.assertRaises(error.HTTPError):self.post(route+'/delete',{})
        with self.assertRaises(error.HTTPError):
            self.post(route+'/delete',{'confirm_session_id':sid},origin='https://untrusted.test')
        with self.post(route+'/delete',{'confirm_session_id':sid}) as response:
            self.assertTrue(json.load(response)['deleted'])
        self.assertEqual(self.get('projects/demo/chat/sessions')['sessions'],[])
        self.assertEqual(source.read_text(),'# do not run\n')

    def test_chat_stop_does_not_wait_for_running_turn_global_lock(self):
        import server
        import threading
        held=threading.Event();release=threading.Event()
        def ongoing_turn():
            with server.SYNC.lock:
                held.set();release.wait(5)
        worker=threading.Thread(target=ongoing_turn);worker.start()
        try:
            self.assertTrue(held.wait(1))
            with patch.object(server.CHAT,'stop',return_value={'stopping':True}) as stop:
                req=request.Request(f'http://127.0.0.1:{self.port}/api/projects/demo/chat/sessions/test-session/stop',
                    data=b'{}',headers={'Content-Type':'application/json'})
                with request.urlopen(req,timeout=1) as response:
                    self.assertTrue(json.load(response)['stopping'])
                stop.assert_called_once_with('demo','test-session')
                with self.assertRaises(error.HTTPError):
                    self.post('projects/demo/chat/sessions/test-session/stop',{},origin='https://untrusted.test')
                self.assertEqual(stop.call_count,1)
        finally:
            release.set();worker.join(2)

    def get(self, path):
        with request.urlopen(f'http://127.0.0.1:{self.port}/api/'+path) as response:
            return json.load(response)

    def test_open_inspect_resume_routes_do_not_execute_or_call_model(self):
        root=self.project.parent.parent
        source=root/'source';source.mkdir();(source/'analysis.py').write_text('raise RuntimeError("must not execute")')
        with patch('llm_client.chat') as cloud:
            with self.post('workspace/inspect',{'source':str(source)}) as response:
                self.assertEqual(json.load(response)['mode'],'inspect')
            with self.post('workspace/open',{'source':str(source),'name':'private'}) as response:
                self.assertEqual(json.load(response)['status'],'needs_analysis')
            self.assertEqual(self.get('workspace/projects/private/status')['status'],'needs_analysis')
            with self.post('workspace/open',{'source':str(source),'name':'private'}) as response:
                self.assertTrue(json.load(response)['reopened'])
            cloud.assert_not_called()
        entries=self.get('workspace/projects')['projects']
        self.assertTrue(next(p for p in entries if p['project']=='private')['private'])

    def test_workspace_and_login_reject_cross_origin_and_non_json(self):
        for path in ('workspace/open','chatgpt/connect'):
            with self.assertRaises(error.HTTPError) as cm:
                self.post(path,{},origin='https://untrusted.test')
            self.assertEqual(cm.exception.code,400)
            req=request.Request(f'http://127.0.0.1:{self.port}/api/'+path,data=b'{}',headers={'Content-Type':'text/plain'})
            with self.assertRaises(error.HTTPError):request.urlopen(req)

    def test_auth_status_returns_masked_identity_no_tokens(self):
        with patch('chatgpt_auth.read_record',return_value={'access_token':'SECRET_ACCESS','id_token':'SECRET_ID','sub':'private-sub','email':'person@example.test','scope':'chatgpt.tokens.use.direct'}):
            shown=self.get('chatgpt/status')
        self.assertTrue(shown['sharing'])
        self.assertNotIn('SECRET',json.dumps(shown));self.assertNotIn('person@example.test',json.dumps(shown))
        with self.assertRaises(error.HTTPError):self.get('chatgpt/connect')

    def test_pending_cannot_download_ready_backup(self):
        root=self.project.parent.parent;source=root/'source';source.mkdir();(source/'analysis.py').write_text('pass')
        with self.post('workspace/open',{'source':str(source),'name':'private'}):pass
        with self.assertRaises(error.HTTPError):self.get('workspace/projects/private/backup.zip')

    def test_delete_requires_local_confirmation_and_preserves_original(self):
        root=self.project.parent.parent;source=root/'source';source.mkdir()
        original=source/'analysis.py';original.write_bytes(b'# keep original\n')
        with self.post('workspace/open',{'source':str(source),'name':'private'}):pass
        route='workspace/projects/private/'
        info=self.get(route+'delete-preview')
        self.assertEqual(info['source_paths'],[str(source)])
        body={'confirm_name':'private','confirmation_token':info['confirmation_token']}
        for invalid in ({}, {**body,'confirm_name':'demo'}, {**body,'confirmation_token':'old'}):
            with self.assertRaises(error.HTTPError):self.post(route+'delete',invalid)
        with self.assertRaises(error.HTTPError):self.post(route+'delete',body,origin='https://untrusted.test')
        with self.assertRaises(error.HTTPError):self.get(route+'delete')
        with self.post(route+'delete',body) as response:
            self.assertTrue(json.load(response)['deleted'])
        self.assertEqual(original.read_bytes(),b'# keep original\n')
        self.assertEqual([p['project'] for p in self.get('workspace/projects')['projects']],['demo'])
        self.assertTrue(self.project.is_dir())

    def test_delete_does_not_queue_behind_active_request(self):
        import server
        from tests.test_project_deletion import held_elsewhere
        info=self.get('workspace/projects/demo/delete-preview')
        with held_elsewhere(server.SYNC.lock):
            with self.assertRaises(error.HTTPError) as exc:
                self.post('workspace/projects/demo/delete',{'confirm_name':'demo','confirmation_token':info['confirmation_token']})
            self.assertEqual(exc.exception.code,409)
        self.assertTrue(self.project.is_dir())

    def test_rename_and_analysis_preview_are_local_and_scoped(self):
        root=self.project.parent.parent;source=root/'source';(source/'small').mkdir(parents=True)
        (source/'small/render.py').write_text('raise RuntimeError("not executed")')
        (source/'large.py').write_text('#'+'x'*190000)
        with self.post('workspace/open',{'source':str(source),'name':'private'}):pass
        route='workspace/projects/private/'
        with patch('llm_client.chat') as cloud:
            with self.post(route+'rename',{'name':'New Display'}) as response:
                value=json.load(response)
                self.assertEqual(value['display_name'],'New Display');self.assertEqual(value['project'],'private')
            self.assertTrue(self.get(route+'analysis-options')['options'])
            with self.post(route+'analysis-preview',{'scope':'small'}) as response:
                preview=json.load(response)
            self.assertTrue(preview['within_limit']);self.assertNotIn('sources',preview)
            for body in ({'consent':True,'scope':'small'}, {'consent':True,'scope':''}):
                with self.assertRaises(error.HTTPError):self.post(route+'analyze',body)
            with self.assertRaises(error.HTTPError):self.post(route+'rename',{'name':'bad'},origin='https://untrusted.test')
            cloud.assert_not_called()

    def test_whole_project_plan_requires_separate_consent(self):
        root=self.project.parent.parent;source=root/'batch-source';source.mkdir()
        (source/'a.py').write_text('# a\n'+'#x\n'*35000)
        (source/'b.py').write_text('# b\n'+'#y\n'*35000)
        with self.post('workspace/open',{'source':str(source),'name':'batch_test'}):pass
        route='workspace/projects/batch_test/'
        with patch('llm_client.chat') as cloud:
            with self.post(route+'batch-preview',{}) as response:plan=json.load(response)
            self.assertEqual(plan['source_files'],2)
            self.assertEqual(len(plan['jobs']),2)
            self.assertNotIn('sources',plan['jobs'][0])
            for body in ({'consent':False,'confirmation_token':plan['confirmation_token']},
                         {'consent':True,'confirmation_token':'stale'}):
                with self.assertRaises(error.HTTPError):self.post(route+'batch-analyze',body)
            with self.assertRaises(error.HTTPError):self.post(route+'batch-preview',{},origin='https://untrusted.test')
            cloud.assert_not_called()


if __name__=='__main__':unittest.main()
