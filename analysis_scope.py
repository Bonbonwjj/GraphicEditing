"""Local, non-executing source scope previews. No truncation or cloud calls."""
import ast
import hashlib
import json
from pathlib import PurePosixPath

LIMIT = 180000


def static_search_paths(text, caller, before_line=None, tree=None):
    """Resolve only literal top-level sys.path edits; never eval source code."""
    values = {'__file__': PurePosixPath(caller)}
    paths = []
    def value(node):
        if isinstance(node, ast.Name):return values.get(node.id)
        if isinstance(node, ast.Constant) and isinstance(node.value, (str, int)):return node.value
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            left, right = value(node.left), value(node.right)
            if isinstance(left, PurePosixPath) and isinstance(right, str) and not right.startswith('/') and '..' not in right.split('/'):
                return left/right
        if isinstance(node, ast.Attribute) and node.attr == 'parent':
            base = value(node.value)
            if isinstance(base, PurePosixPath):return base.parent
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute) and node.value.attr == 'parents':
            base, index = value(node.value.value), value(node.slice)
            if isinstance(base, PurePosixPath) and type(index) is int and 0 <= index < len(base.parents):return base.parents[index]
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in ('Path','str') and len(node.args) == 1:
                result = value(node.args[0])
                if isinstance(result, PurePosixPath):return result
                if node.func.id == 'Path' and isinstance(result, str) and not result.startswith('/') and '..' not in result.split('/'):
                    return PurePosixPath(result)
            if isinstance(node.func, ast.Attribute) and node.func.attr in ('resolve','absolute') and not node.args:
                return value(node.func.value)
        return None
    if tree is None:
        try:tree = ast.parse(text)
        except SyntaxError:return paths
    for node in tree.body:
        if before_line is not None and node.lineno >= before_line:break
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):values[target.id] = value(node.value)
        call = node.value if isinstance(node, ast.Expr) else None
        if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute):continue
        owner = call.func.value
        if not (isinstance(owner, ast.Attribute) and owner.attr == 'path' and isinstance(owner.value, ast.Name) and owner.value.id == 'sys'):continue
        item = value(call.args[-1]) if call.args else None
        if isinstance(item, PurePosixPath) and not item.is_absolute():
            if call.func.attr == 'insert' and len(call.args)==2 and value(call.args[0])==0:paths.insert(0,item)
            elif call.func.attr == 'append':paths.append(item)
    return paths


def unique_sources(ordered):
    """Represent identical complete texts once, keeping every original path."""
    packed, by_content = [], {}
    for item in ordered:
        content = item['content']
        if content in by_content:
            by_content[content].setdefault('identical_paths', []).append(item['path'])
        else:
            record = dict(item);packed.append(record);by_content[content] = record
    return packed


def sources_for(project):
    from project_preparation import read_state, relative_path, source_root
    root = source_root(project)
    owner = project.parent.parent.parent if root != project/'.preparation/source' else project
    if project.is_symlink() or root.is_symlink() or not root.resolve().is_relative_to(owner.resolve()):
        raise ValueError('源码备份目录不安全')
    sources = {}
    for item in read_state(project).get('files', []):
        if item.get('kind') != 'code':
            continue
        rel = str(relative_path(item['path']))
        path = root / rel
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError('源码备份路径不安全：' + rel)
        sources[rel] = path.read_text(encoding='utf-8-sig')
    return sources


def options(project):
    sources = sources_for(project)
    groups = {'': {'chars': 0, 'files': 0}}
    for path, text in sources.items():
        for parent in PurePosixPath(path).parents:
            key = '' if str(parent) == '.' else str(parent)
            group = groups.setdefault(key, {'chars': 0, 'files': 0})
            group['chars'] += len(text)
            group['files'] += 1
    return {'limit': LIMIT, 'options': [
        {'scope': key, 'kind': 'directory', **value} for key, value in sorted(groups.items())
    ] + [{'scope': key, 'kind': 'file', 'chars': len(value), 'files': 1} for key, value in sorted(sources.items())]}


def build(project, scope='', targets=None, source_cache=None, tree_cache=None, deduplicate=False):
    from project_preparation import relative_path, read_state
    if not isinstance(scope, str):
        raise ValueError('请选择有效分析范围')
    if scope:
        relative_path(scope)
    sources = sources_for(project) if source_cache is None else source_cache
    selected = set(targets) if targets is not None else {p for p in sources if not scope or p == scope or p.startswith(scope + '/')}
    if not selected <= sources.keys():
        raise ValueError('批次目标必须属于已备份源码')
    if not selected:
        raise ValueError('所选范围没有 Python 源码')
    initial = set(selected)
    warnings, visited = set(), set()

    def module_paths(base):
        return {p for p in (base + '.py', base + '/__init__.py') if p in sources}

    def resolve(module, caller, level=0, line=None):
        parent = PurePosixPath(caller).parent
        suffix = module.replace('.', '/')
        if level:
            for _ in range(level - 1):
                parent = parent.parent
            base = str(parent / suffix) if suffix else str(parent)
            matches = module_paths(base)
        else:
            # Script-local imports take precedence, then enclosing package roots.
            matches = set()
            for directory in (*static_search_paths(sources[caller], caller, line, (tree_cache or {}).get(caller)), parent, *parent.parents):
                matches = module_paths(str(directory / suffix))
                if matches:
                    break
            if not matches:
                matches = {p for p in sources if p.endswith('/' + suffix + '.py') or p.endswith('/' + suffix + '/__init__.py')}
                if len(matches) > 1:
                    warnings.add(f'{caller}: {module} 有多个本地候选，均已加入；仍须核实实际导入路径')
        return matches

    while selected - visited:
        caller = sorted(selected - visited)[0]
        visited.add(caller)
        # Include package initializers, which Python executes on import.
        for parent in PurePosixPath(caller).parents:
            initializer = str(parent / '__init__.py')
            if initializer in sources:
                selected.add(initializer)
        try:
            if tree_cache is not None and caller in tree_cache:
                tree = tree_cache[caller]
            else:
                tree = ast.parse(sources[caller])
                if tree_cache is not None:
                    tree_cache[caller] = tree
        except SyntaxError:
            warnings.add(f'{caller}: 语法无法静态解析，依赖须由模型核实')
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    selected.update(resolve(alias.name, caller, line=node.lineno))
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ''
                selected.update(resolve(module, caller, node.level, node.lineno))
                for alias in node.names:
                    if alias.name != '*':
                        selected.update(resolve('.'.join(filter(None, (module, alias.name))), caller, node.level, node.lineno))
            elif isinstance(node, ast.Call):
                name = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else ''
                if name in ('import_module', '__import__') and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                    selected.update(resolve(node.args[0].value, caller, line=node.lineno))
                elif name in ('exec', 'eval', '__import__', 'import_module', 'spec_from_file_location', 'run_path', 'run_module'):
                    warnings.add(f'{caller}:{node.lineno}: {name} 动态依赖无法静态证明完整，必须核实；缺失时返回需要补充依赖')
    ordered = [{'path': path, 'content': sources[path]} for path in sorted(selected)]
    raw_chars = sum(len(item['content']) for item in ordered)
    if deduplicate:
        ordered = unique_sources(ordered)
    chars = sum(len(item['content']) for item in ordered)
    catalog = sorted(sources)
    data_catalog = sorted(f['path'] for f in read_state(project).get('files', []) if f['kind'] != 'code')
    fingerprint = hashlib.sha256(json.dumps([scope, sorted(initial), ordered, catalog, data_catalog], ensure_ascii=False).encode()).hexdigest()
    return {'scope': scope, 'chars': chars, 'raw_chars': raw_chars, 'limit': LIMIT, 'files': sorted(selected),
            'added_dependencies': sorted(selected - initial), 'omitted_files': sorted(set(sources) - selected),
            'warnings': sorted(warnings), 'within_limit': chars <= LIMIT,
            'confirmation_token': fingerprint, 'target_files': sorted(initial), 'sources': ordered, 'source_catalog': catalog, 'data_catalog': data_catalog}


def public(plan):
    return {key: value for key, value in plan.items() if key not in ('sources', 'source_catalog')}


def require_limit(plan):
    if not plan['within_limit']:
        raise ValueError(f"所选范围含 {len(plan['files'])} 个 Python 文件、{plan['chars']:,} 字符，超过单次 {LIMIT:,} 字符；请选择图组子目录或入口文件，依赖会自动补入，不截断源码。")
