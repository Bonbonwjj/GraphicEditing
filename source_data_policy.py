"""Conservative source-input checks, independent of rendered artist geometry.

This checks ordinary literal arrays and explicit file readers, not arbitrary
Python semantics. Unknown input construction stays unverified.
"""
import ast
from collections import Counter

READERS = {
    'pandas': {'read_csv', 'read_table', 'read_json', 'read_excel', 'read_parquet',
               'read_feather', 'read_hdf', 'read_pickle', 'read_sql', 'read_sql_query',
               'read_sql_table', 'read_fwf', 'read_stata', 'read_sas', 'read_spss',
               'read_orc', 'read_xml', 'read_html', 'ExcelFile'},
    'numpy': {'load', 'loadtxt', 'genfromtxt', 'fromfile', 'frombuffer', 'fromstring', 'memmap'},
    'csv': {'DictReader', 'reader'},
    'json': {'load', 'loads'},
    'pickle': {'load', 'loads'},
    'yaml': {'load', 'safe_load', 'full_load', 'load_all', 'safe_load_all'},
    'scipy.io': {'loadmat', 'mmread', 'readsav', 'netcdf_file'},
    'h5py': {'File'},
    'tables': {'open_file'},
    'pyarrow.parquet': {'read_table', 'read_pandas', 'ParquetFile'},
    'pyarrow.feather': {'read_table', 'read_feather'},
    'pyarrow.csv': {'read_csv', 'open_csv'},
    'xarray': {'open_dataset', 'open_dataarray', 'open_mfdataset', 'load_dataset', 'load_dataarray'},
    'polars': {'read_csv', 'read_excel', 'read_json', 'read_ndjson', 'read_parquet',
               'read_ipc', 'read_database', 'scan_csv', 'scan_parquet', 'scan_ipc', 'scan_ndjson'},
    'joblib': {'load'},
    'torch': {'load'},
}
ALIASES = {'pd': 'pandas', 'np': 'numpy', 'pq': 'pyarrow.parquet'}
DISPLAY = {'figsize', 'color', 'colors', 'c', 'facecolor', 'edgecolor', 'palette',
           'xlim', 'ylim', 'xticks', 'yticks', 'ticks', 'bbox_to_anchor', 'position'}


def _inputs(source):
    tree = ast.parse(source)
    anchors = Counter()
    aliases = dict(ALIASES)
    definitions = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for name in node.names:
                aliases[name.asname or name.name.split('.')[0]] = name.name if name.asname else name.name.split('.')[0]
        elif isinstance(node, ast.ImportFrom):
            for name in node.names:
                aliases[name.asname or name.name] = (node.module or '') + '.' + name.name
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and node.value is not None:
                    definitions.setdefault(target.id, []).append(node.value)
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                if isinstance(item.optional_vars, ast.Name):
                    definitions.setdefault(item.optional_vars.id, []).append(item.context_expr)

    def qualified(node):
        if isinstance(node, ast.Name):
            return aliases.get(node.id, node.id)
        if isinstance(node, ast.Attribute):
            return qualified(node.value) + '.' + node.attr
        return ''

    def reader(node):
        name = qualified(node.func)
        module, _, method = name.rpartition('.')
        if method in READERS.get(module, set()):
            if name in {'h5py.File', 'tables.open_file', 'numpy.memmap'}:
                index = 2 if name=='numpy.memmap' else 1
                mode = next((k.value for k in node.keywords if k.arg=='mode'), None)
                if mode is None:
                    mode = node.args[index] if len(node.args)>index else ast.Constant(value='r')
                if not isinstance(mode, ast.Constant) or not isinstance(mode.value, str) or any(c in mode.value for c in 'wax+'):
                    return False
            return True
        # File/Path readers, including compressed streams. Write-only opens
        # must never provide evidence that original data was checked.
        short = method or name
        if short in {'read_text', 'read_bytes'}:
            return True
        if short == 'open' and (name in {'open', 'builtins.open', 'io.open', 'gzip.open', 'bz2.open', 'lzma.open'} or isinstance(node.func, ast.Attribute)):
            mode = next((k.value for k in node.keywords if k.arg=='mode'), None)
            if mode is None:
                index = 0 if isinstance(node.func, ast.Attribute) and module not in {'builtins','io','gzip','bz2','lzma'} else 1
                mode = node.args[index] if len(node.args)>index else ast.Constant(value='r')
            return isinstance(mode, ast.Constant) and isinstance(mode.value, str) and not any(c in mode.value for c in 'wax+')
        return False

    def dependencies(node, seen=None):
        seen = set() if seen is None else seen
        for name in {n.id for n in ast.walk(node) if isinstance(n, ast.Name)} - seen:
            seen.add(name)
            for value in definitions.get(name, []):
                binding = ast.dump(ast.Name(id=name, ctx=ast.Store()), include_attributes=False)
                anchors[('dependency', binding, ast.dump(value, include_attributes=False))] += 1
                dependencies(value, seen)

    def visit(node, binding='inline'):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            binding = '|'.join(ast.dump(t, include_attributes=False) for t in targets)
            if node.value is not None:
                visit(node.value, binding)
            return
        if isinstance(node, ast.Call):
            name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, 'id', '')
            if reader(node):
                anchors[('reader', binding, qualified(node.func) + ':' + ast.dump(node, include_attributes=False))] += 1
                dependencies(node)
                return
            if name.startswith(('set_', 'subplots', 'figure', 'legend', 'text', 'annotate')):
                return
            for arg in node.args:
                visit(arg, binding)
            for kw in node.keywords:
                if kw.arg not in DISPLAY:
                    visit(kw.value, binding)
            # Readers may be the receiver of a chained call, e.g.
            # pd.ExcelFile(path).parse(sheet) or Path(path).read_text().split().
            if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Call):
                visit(node.func.value, binding)
            return
        if isinstance(node, (ast.List, ast.Tuple, ast.Dict)):
            try:
                value = ast.literal_eval(node)
            except (ValueError, TypeError):
                value = None
            if value is not None and any(isinstance(n, ast.Constant) and
                    isinstance(n.value, (int, float, complex)) and not isinstance(n.value, bool)
                    for n in ast.walk(node)):
                anchors[('literal', binding, ast.dump(node, include_attributes=False))] += 1
                return
        for child in ast.iter_child_nodes(node):
            visit(child, binding)

    visit(tree)
    return anchors


def compare_source_inputs(baseline, candidate):
    missing = []
    count = 0
    for path, source in baseline.items():
        try:
            old = _inputs(source)
            proposed = candidate.get(path, source)
            new = _inputs(proposed)
        except (SyntaxError, ValueError, TypeError):
            return {'status': 'unverified', 'reason': '无法解析原始数据来源。'}
        count += sum(old.values())
        missing.extend({'path': path, 'kind': key[0], 'binding': key[1]}
                       for key in (old - new).elements())
        protected = {key[1] for key in old if key[1] != 'inline'}
        missing.extend({'path': path, 'kind': 'replacement_input', 'binding': key[1]}
                       for key in (new - old).elements() if key[1] in protected)
        # Literal initialization must not merely be retained as dead evidence
        # followed by a direct overwrite of the same input or one of its cells.
        def writes(text):
            found = Counter()
            tree = ast.parse(text)
            roots = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and
                     any(ast.dump(n, include_attributes=False) in binding for binding in protected)}
            def root(node):
                while isinstance(node, (ast.Subscript, ast.Attribute)):
                    node = node.value
                return node.id if isinstance(node, ast.Name) else None
            # Track ordinary aliases too; derived copies have independent names.
            previous = None
            while previous != roots:
                previous = set(roots)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Assign) and isinstance(node.value, ast.Name) and node.value.id in roots:
                        roots.update(t.id for t in node.targets if isinstance(t, ast.Name))
            for node in ast.walk(tree):
                if isinstance(node, (ast.Assign, ast.Delete)):
                    targets = node.targets
                elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
                    targets = [node.target]
                else:
                    targets = []
                if any(root(t) in roots for t in targets):
                    found[ast.dump(node, include_attributes=False)] += 1
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and root(node.func.value) in roots:
                    if node.func.attr in {'append','extend','insert','pop','remove','clear','sort','reverse','update','fill','resize','put','itemset','__setitem__'} or any(k.arg=='inplace' and isinstance(k.value, ast.Constant) and k.value.value is True for k in node.keywords):
                        found[ast.dump(node, include_attributes=False)] += 1
            return found
        if writes(proposed) - writes(source):
            missing.append({'path': path, 'kind': 'input_overwrite', 'binding': 'original input'})
    if missing:
        return {'status': 'fail', 'changed_inputs': missing,
                'reason': '候选修改或删除了原始数值输入或数据读取定义；请保留原输入，另行计算派生值。'}
    return {'status': 'pass' if count else 'unverified', 'checked_inputs': count,
            'reason': '原始数值输入和读取定义保持不变；允许派生计算和绘图映射变化。' if count else
                      '未识别到可自动核对的原始数值输入或文件读取定义。',
            'limitations': ['静态来源检查不能证明任意 Python 的科学语义；请审阅派生计算。']}
