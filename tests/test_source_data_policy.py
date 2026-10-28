import unittest

from source_data_policy import compare_source_inputs


class SourceInputTests(unittest.TestCase):
    def check(self, before, after):
        return compare_source_inputs({'charts/a.py': before}, {'charts/a.py': after})['status']

    def test_computation_and_remapping_preserve_original_inputs(self):
        before = 'x = [1, 2, 3]\ny = [4, 5, 6]\nax.plot(x, y)'
        for drawing in ('ax.scatter(y, x)', 'derived = np.asarray(y) / np.mean(y)\nax.plot(x, derived)',
                        'ax.plot(x, np.log(y))', 'ax.bar(x, y)'):
            with self.subTest(drawing=drawing):
                self.assertEqual(self.check(before, before.rsplit('\n', 1)[0]+'\n'+drawing), 'pass')

    def test_original_numeric_value_cannot_change_or_disappear(self):
        before = 'y = [1, 2, 3]\nax.plot(y)'
        self.assertEqual(self.check(before, before.replace('1, 2, 3', '1, 9, 3')), 'fail')
        self.assertEqual(self.check(before, 'ax.plot([1, 2, 3])'), 'fail')

    def test_retaining_initialization_does_not_allow_overwriting_inputs(self):
        before = 'y = [1, 2, 3]\nax.plot(y)'
        for change in ('y[0] = 99', 'y = [9, 9, 9]', 'y *= 2', 'y.append(99)',
                       'alias = y\nalias[0] = 99'):
            with self.subTest(change=change):
                self.assertEqual(self.check(before, before+'\n'+change), 'fail')

    def test_file_source_preserved_while_columns_and_calculations_change(self):
        before = "df = pd.read_csv(root / 'data' / 'values.csv')\nax.plot(df.x, df.y)"
        self.assertEqual(self.check(before, before.replace('df.x, df.y', 'df.y, df.x * 100')), 'pass')
        self.assertEqual(self.check(before, before.replace('values.csv', 'other.csv')), 'fail')
        self.assertEqual(self.check(before, before+"\ndf.loc[0, 'y'] = 99"), 'fail')
        self.assertEqual(self.check(before, before+'\nderived = df.copy()\nderived.y = derived.y * 2'), 'pass')

    def test_display_changes_do_not_change_input_report(self):
        before = 'y = [1, 2]\nfig, ax = plt.subplots(figsize=(4, 3))\nax.plot(y, color=[1, 0, 0])'
        self.assertEqual(self.check(before, before.replace('(4, 3)', '(6, 5)').replace('[1, 0, 0]', '[0, 0, 1]')), 'pass')

    def test_unknown_sources_remain_unverified(self):
        self.assertEqual(self.check('draw_custom()', 'draw_custom(mode=2)'), 'unverified')

    def test_stdlib_csv_source_allows_fitting_but_protects_file_and_rows(self):
        before = ('with (project / "data" / "values.csv").open(newline="") as f:\n'
                  '    rows = list(csv.DictReader(f))\n'
                  'y = [float(r["y"]) for r in rows]\nax.plot(y)')
        after = before.replace('ax.plot(y)', 'ax.scatter(range(len(y)), y)\nfit = np.polyfit(range(len(y)), y, 1)')
        self.assertEqual(self.check(before, after), 'pass')
        self.assertEqual(self.check(before, after.replace('values.csv', 'other.csv')), 'fail')
        self.assertEqual(self.check(before, after+'\nrows[0] = {}'), 'fail')

    def test_reader_families_allow_derivation_and_reject_source_changes(self):
        readers = [
            'pd.read_fwf("values.txt")', 'pd.read_hdf("values.h5", key="series")',
            'pd.read_pickle("values.pkl")', 'pd.read_stata("values.dta")',
            'pd.read_sas("values.sas7bdat")', 'pd.read_spss("values.sav")',
            'pd.read_orc("values.orc")', 'pd.read_xml("values.xml")',
            'pd.read_html("values.html")', 'pd.read_sql_query("select y from values", conn)',
            'np.load("values.npz", allow_pickle=False)', 'np.loadtxt("values.txt")',
            'np.genfromtxt("values.txt")', 'np.fromfile("values.bin", dtype="float64")',
            'np.memmap("values.bin", mode="r")', 'Path("values.txt").read_text()',
            'Path("values.bin").read_bytes()', 'json.load(open("values.json"))',
            'json.loads(Path("values.json").read_text())', 'pickle.load(open("values.pkl", "rb"))',
            'yaml.safe_load(open("values.yaml"))', 'scipy.io.loadmat("values.mat")',
            'scipy.io.mmread("values.mtx")', 'scipy.io.readsav("values.sav")',
            'h5py.File("values.h5", "r")', 'tables.open_file("values.h5", mode="r")',
            'pq.read_table("values.parquet")', 'pyarrow.feather.read_table("values.feather")',
            'xarray.open_dataset("values.nc")', 'polars.read_csv("values.csv")',
            'joblib.load("values.pkl")', 'torch.load("values.pt")',
            'pd.ExcelFile("values.xlsx").parse("Sheet1")',
        ]
        for reader in readers:
            with self.subTest(reader=reader):
                before='raw = '+reader+'\nax.plot(raw)'
                self.assertEqual(self.check(before, before.replace('ax.plot(raw)', 'derived = process(raw)\nax.plot(derived)')), 'pass')
                self.assertEqual(self.check(before, before.replace('values', 'other')), 'fail')
                self.assertEqual(self.check(before, before+'\nraw[0] = 99'), 'fail')

    def test_import_aliases_and_compressed_file_handles(self):
        for source in (
            'from numpy import load as read_values\nraw = read_values("values.npz")',
            'import pandas as frames\nraw = frames.read_csv("values.csv")',
            'from scipy import io as sio\nraw = sio.loadmat("values.mat")',
            'from gzip import open as gzopen\nwith gzopen("values.csv.gz", "rt") as f:\n    raw = list(csv.reader(f))',
            'with bz2.open("values.csv.bz2", "rt") as f:\n    raw = list(csv.reader(f))',
        ):
            with self.subTest(source=source):
                self.assertEqual(self.check(source, source+'\nderived = process(raw)'), 'pass')
                self.assertEqual(self.check(source, source.replace('values', 'other')), 'fail')

    def test_changed_path_variables_and_handle_definitions_are_protected(self):
        before='directory = "data"\nfilename = "values.csv"\npath = Path(directory) / filename\nraw = pd.read_csv(path)'
        self.assertEqual(self.check(before, before+'\nderived = raw * 2'), 'pass')
        self.assertEqual(self.check(before, before.replace('values.csv', 'other.csv')), 'fail')
        self.assertEqual(self.check(before, before.replace('"data"', '"other"')), 'fail')
        self.assertEqual(self.check(before, before+'\npath = Path("other.csv")'), 'fail')

    def test_unknown_load_methods_and_write_only_opens_are_not_read_evidence(self):
        for source in ('raw = custom.load("values.bin")', 'out = open("values.csv", "w")',
                       'out = Path("values.csv").open("wb")', 'out = gzip.open("values.gz", "wt")',
                       'out = h5py.File("values.h5", "w")', 'out = np.memmap("values.bin", mode="w+")'):
            with self.subTest(source=source):
                self.assertEqual(self.check(source, source), 'unverified')

    def test_changing_imported_reader_provider_is_rejected(self):
        before='from numpy import load as read_data\nraw = read_data("values.bin")'
        self.assertEqual(self.check(before, before.replace('from numpy', 'from torch')), 'fail')


if __name__ == '__main__':
    unittest.main()
