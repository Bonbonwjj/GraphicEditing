import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from import_jobs import ImportJobs
from upload_importer import copy_local_sources


class ImportProgressTests(unittest.TestCase):
    def test_worker_returns_immediately_and_reports_current_file(self):
        jobs=ImportJobs();entered=threading.Event();release=threading.Event()
        def work(update):
            update(stage='splitting',total=3,completed=1,current_file='second.py')
            entered.set();release.wait(3)
            return {'charts':['a','b']}
        try:
            result=jobs.start('demo',work)
            self.assertTrue(entered.wait(1))
            status=jobs.get(result['id'])
            self.assertEqual(status['status'],'working')
            self.assertEqual(status['completed'],1)
            self.assertEqual(status['current_file'],'second.py')
            with self.assertRaises(ValueError):jobs.start('demo',work)
        finally:release.set()

    def test_worker_failure_is_visible(self):
        jobs=ImportJobs();done=threading.Event()
        def work(update):
            done.set();raise ValueError('缺少数据列')
        result=jobs.start('bad',work)
        done.wait(1)
        for _ in range(100):
            result=jobs.get(result['id'])
            if result['status']=='failed':break
            time.sleep(.005)
        self.assertEqual(result['status'],'failed')
        self.assertEqual(result['message'],'缺少数据列')

    def test_local_paths_preserve_layout_and_ignore_hidden_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'中文工程';source.mkdir();(source/'charts').mkdir();(source/'lib').mkdir()
            (source/'charts/a.py').write_text('# source',encoding='utf-8')
            (source/'lib/helper.py').write_text('# helper',encoding='utf-8')
            (source/'.hidden.py').write_text('private',encoding='utf-8')
            data=root/'values.csv';data.write_bytes(b'x,y\n1,2\n')
            total,counts=copy_local_sources(root/'upload',{'code':'"'+str(source)+'"','data':str(data)})
            self.assertEqual(counts,{'code':2,'data':1,'image':0})
            self.assertEqual((root/'upload/code/lib/helper.py').read_text(),'# helper')
            self.assertFalse((root/'upload/code/.hidden.py').exists())
            self.assertEqual((root/'upload/csv/values.csv').read_bytes(),data.read_bytes())

    def test_bad_or_oversize_path_fails_before_import(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'a.py';source.write_text('1234')
            with patch('upload_importer.MAX_UPLOAD_BYTES',3),self.assertRaises(ValueError):
                copy_local_sources(root/'output',{'code':str(source)})
            with self.assertRaises(ValueError):
                copy_local_sources(root/'output',{'code':str(root/'missing')})

    def test_windows_picker_is_topmost_and_preserves_unicode(self):
        import folder_picker
        with patch.object(folder_picker.sys,'platform','win32'),patch.object(folder_picker.subprocess,'run') as run:
            run.return_value.returncode=0;run.return_value.stdout='C:\\研究\\工程\n'
            self.assertEqual(folder_picker.choose_folder(),'C:\\研究\\工程')
            command=run.call_args.args[0]
            self.assertIn('-STA',command)
            self.assertIn('$owner.TopMost = $true',command[-1])
            self.assertEqual(run.call_args.kwargs['encoding'],'utf-8')

    def test_server_port_cannot_be_shared_with_another_backend(self):
        import server
        first=server.LocalHTTPServer(('127.0.0.1',0),server.Handler)
        try:
            with self.assertRaises(OSError):
                second=server.LocalHTTPServer(('127.0.0.1',first.server_port),server.Handler)
                second.server_close()
        finally:first.server_close()


class ImportHttpProgressTests(unittest.TestCase):
    from tests.test_collaboration_api import CollaborationApiTests as Fixtures
    setUp=Fixtures.setUp
    post=Fixtures.post

    def get(self,path):
        from urllib.request import urlopen
        with urlopen(f'http://127.0.0.1:{self.port}/api/'+path,timeout=1) as response:
            return json.load(response)

    def test_status_is_readable_while_worker_holds_sync_lock(self):
        import import_jobs
        import server
        entered=threading.Event();release=threading.Event()
        def split(root,upload,project_id,name,progress=None):
            progress(stage='splitting',completed=0,total=1,current_file='a.py',message='等待模型返回')
            entered.set();release.wait(3)
            return {'project':project_id,'charts':[],'files':1}
        try:
            with patch.object(server,'ROOT',self.project.parent.parent),patch.object(import_jobs,'JOBS',ImportJobs()),patch.object(server,'import_generic',side_effect=split),patch.object(server,'warm_project_previews'):
                with self.post('uploads/import',{'project_id':'demo','name':'Demo','existing':True,'async':True,
                    'files':[{'name':'a.py','kind':'code','content':'# safe'},{'name':'a.csv','kind':'data','content':'x\n1\n'}]}) as response:
                    self.assertEqual(response.status,202);job=json.load(response)
                self.assertTrue(entered.wait(1))
                status=self.get('uploads/jobs/'+job['id'])
                self.assertEqual(status['status'],'working')
                self.assertEqual(status['current_file'],'a.py')
                release.set()
                for _ in range(100):
                    status=self.get('uploads/jobs/'+job['id'])
                    if status['status']!='working':break
                    time.sleep(.005)
                self.assertEqual(status['status'],'completed')
        finally:release.set()

    def test_pasted_paths_import_through_multipart_and_report_completion(self):
        import import_jobs
        import server
        from urllib.request import Request,urlopen
        root=self.project.parent.parent
        source=root/'中文源码';source.mkdir();(source/'a.py').write_text('x = [1, 2]\n',encoding='utf-8')
        data=root/'values.csv';data.write_bytes(b'x\n1\n')
        fields={'project_id':'demo','name':'Demo','existing':'true','async':'true',
                'code_path':'"'+str(source)+'"','data_path':str(data)}
        boundary='plot-upload-test-boundary'
        body=''.join('--'+boundary+'\r\nContent-Disposition: form-data; name="'+key+'"\r\n\r\n'+value+'\r\n' for key,value in fields.items())+'--'+boundary+'--\r\n'
        with patch.object(server,'ROOT',root),patch.object(import_jobs,'JOBS',ImportJobs()),patch('llm_client.is_configured',return_value=False),patch.object(server,'warm_project_previews'):
            req=Request(f'http://127.0.0.1:{self.port}/api/uploads/import',data=body.encode('utf-8'),
                        headers={'Content-Type':'multipart/form-data; boundary='+boundary,'Origin':f'http://127.0.0.1:{self.port}'})
            with urlopen(req,timeout=3) as response:job=json.load(response)
            for _ in range(100):
                status=self.get('uploads/jobs/'+job['id'])
                if status['status']!='working':break
                time.sleep(.01)
            self.assertEqual(status['status'],'completed',status)
            self.assertEqual(status['completed'],1)
            self.assertEqual(status['total'],1)
            self.assertTrue((self.project/'charts/a.py').is_file())
            self.assertEqual((self.project/'data/values.csv').read_bytes(),data.read_bytes())

    def test_folder_picker_route_accepts_cancellation_and_unicode(self):
        with patch('folder_picker.choose_folder',return_value='C:\\研究\\绘图'):
            with self.post('workspace/pick-folder',{}) as response:
                self.assertEqual(json.load(response)['path'],'C:\\研究\\绘图')
        with patch('folder_picker.choose_folder',return_value=''):
            with self.post('workspace/pick-folder',{}) as response:
                self.assertEqual(json.load(response)['path'],'')

    def test_progress_script_is_served_to_browser(self):
        from urllib.request import urlopen
        with urlopen(f'http://127.0.0.1:{self.port}/static/upload_progress.js',timeout=2) as response:
            self.assertEqual(response.status,200)
            self.assertIn('importProgressText',response.read().decode('utf-8'))
