import unittest
import tempfile
from pathlib import Path
from project_storage import from_shared, to_shared


class ProjectStorageTests(unittest.TestCase):
    def test_uploaded_code_and_data_export_to_separate_shared_folders(self):
        from upload_importer import store_upload
        from generic_importer import import_generic
        from export_shared_projects import export
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            source="import os\nfrom pathlib import Path\nimport pandas as pd\nimport matplotlib.pyplot as plt\nfrom helper import COLOR\ndf=pd.read_csv(Path(os.environ['CHART_PROJECT_DIR'])/'data/values.csv')\nfig,ax=plt.subplots()\nax.plot(df.x,df.y,color=COLOR)\nfig.savefig(os.environ['CHART_OUTPUT'])\n"
            upload=store_upload(root,'sample',[
                {'kind':'code','name':'charts/plot.py','content':source},
                {'kind':'code','name':'lib/helper.py','content':"COLOR='blue'\n"},
                {'kind':'data','name':'values.csv','content':'x,y\n0,1\n1,2\n'}])
            import_generic(root,upload,'sample','Sample')
            output=root/'shared'
            self.assertGreater(export(root,output),0)
            self.assertTrue((output/'sample/code/charts/plot.py').is_file())
            self.assertTrue((output/'sample/code/lib/helper.py').is_file())
            self.assertTrue((output/'sample/data/values.csv').is_file())
            self.assertEqual({p.name for p in (output/'sample').iterdir()},{'code','data'})
            import server
            image=server.render(root/'projects/sample',(root/'projects/sample/charts/plot.py').read_text())
            self.assertTrue(image.startswith(b'\x89PNG'))
    def test_data_and_code_round_trip_without_changing_payload_bytes(self):
        files={'demo/project.json':b'{}','demo/charts/a.py':b'print(1)',
               'demo/lib/helper.py':b'# shared','demo/data/bundle/index.json':b'{\r\n}',
               'demo/history/rev.py':b'# history'}
        shared=to_shared(files)
        self.assertEqual(shared['demo/code/charts/a.py'],b'print(1)')
        self.assertEqual(shared['demo/data/bundle/index.json'],b'{\r\n}')
        self.assertEqual({p.split('/')[1] for p in shared},{'data','code'})
        self.assertEqual(from_shared(shared),files)
        self.assertEqual(to_shared(shared),shared)

    def test_mixed_layouts_merge_identical_files_but_reject_different_files(self):
        files={'demo/code/project.json':b'{}','demo/project.json':b'{}',
               'demo/code/charts/a.py':b'new','demo/charts/a.py':b'old'}
        with self.assertRaisesRegex(ValueError,'新旧目录'):
            from_shared(files)
        files['demo/charts/a.py']=b'new'
        self.assertEqual(from_shared(files)['demo/charts/a.py'],b'new')
