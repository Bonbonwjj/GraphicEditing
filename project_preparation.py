"""Durable, local-only project preparation using the supplied extraction Skill."""
import ast
import hashlib
import io
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
import threading
import time
import uuid
import zipfile

ROOT = Path(__file__).resolve().parent
SKILL = ROOT / 'skills' / 'plot-code-extraction'
DATA_SUFFIXES = {'.csv', '.tsv', '.json', '.npz', '.npy', '.parquet', '.png', '.jpg', '.jpeg', '.webp',
                 '.svg', '.ttf', '.otf', '.pptx'}
SKIP_DIRS = {'.git', '.venv', 'venv', 'node_modules', '__pycache__', 'dist', 'build', '.aws', '.ssh', '.codex', '.agents'}
LOCK = threading.RLock()
RUNNING = set()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix='.save-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
        Path(name).replace(path)
    finally:
        Path(name).unlink(missing_ok=True)


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def relative_path(value):
    if not isinstance(value, str) or not value or '\\' in value or ':' in value:
        raise ValueError('不支持的相对路径')
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ('..', '.') for part in value.split('/')) or path.as_posix() != value:
        raise ValueError('路径必须在工程内且不能包含 ..')
    return path


def inventory(source):
    if not isinstance(source, (str, Path)) or not str(source).strip():
        raise ValueError('请填写具体工程文件夹地址。')
    source = Path(os.path.expandvars(str(source).strip().strip('"').strip("'"))).expanduser()
    if source.is_symlink():
        raise ValueError('请选择真实工程目录，不接受符号链接')
    source = source.resolve(strict=True)
    if not source.is_dir() or source == Path(source.anchor) or source == Path.home():
        raise ValueError('请选择具体的工程文件夹，不能选择磁盘根目录或用户主目录')
    files, skipped, size = [], [], 0
    for directory, dirs, names in os.walk(source, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith('.') and not (Path(directory)/d).is_symlink())
        for name in sorted(names):
            path = Path(directory) / name
            rel = path.relative_to(source).as_posix()
            if path.is_symlink() or name.startswith('.') or path.suffix.lower() not in DATA_SUFFIXES | {'.py', '.md', '.txt'}:
                continue
            if re.search(r'(?i)(credential|secret|token|password|id_rsa|api[-_]key)', name):
                skipped.append(rel)
                continue
            relative_path(rel)
            count = path.stat().st_size
            size += count
            if size > 2 * 1024**3 or len(files) >= 10000:
                raise ValueError('工程超过 2 GiB 或 10000 个文件；请选择更小的绘图子工程。')
            files.append({'path': rel, 'bytes': count, 'kind': 'code' if path.suffix == '.py' else 'data'})
    if not any(item['kind'] == 'code' for item in files):
        raise ValueError('未找到 Python 源码，请选择代码工程目录。')
    return source, files, skipped


def project_layout(root):
    if (root/'code/project.json').is_file() and (root/'code/charts').is_dir():
        return root/'code', root/'code/project.json'
    if (root/'project.json').is_file():
        if (root/'charts').is_dir():
            return root, root/'project.json'
        if (root/'code/charts').is_dir():
            return root/'code', root/'project.json'  # Older standardizer layout.
    return None


def inspect(source):
    root, files, skipped = inventory(source)
    prepared = project_layout(root) is not None
    return {'name': root.name, 'files': files, 'skipped': skipped, 'bytes': sum(f['bytes'] for f in files),
            'mode': 'prepared' if prepared else 'inspect',
            'message': '可直接恢复已准备工程，无需重新提取。' if prepared else '先备份到本机，再由 Skill 检查绘图依赖；不会运行原始分析。'}


def mark_private(projects, name):
    registry = projects.parent / '.private-projects.json'
    with LOCK:
        names = json.loads(registry.read_text()) if registry.exists() else []
        if name not in names:
            write_json(registry, [*names, name])
        ignore = projects.parent / '.gitignore'
        pattern = '/projects/' + name + '/'
        existing = ignore.read_text(encoding='utf-8') if ignore.exists() else ''
        if pattern not in existing.splitlines():
            ignore.write_text(existing.rstrip('\n') + '\n' + pattern + '\n', encoding='utf-8')


def project_path(projects, name):
    if not isinstance(name, str) or not re.fullmatch(r'[\w-]+', name, re.UNICODE):
        raise ValueError('无效的项目名称')
    p = Path(projects) / name
    if p.is_symlink() or not (p/'project.json').is_file():
        raise ValueError('项目不存在')
    return p


def read_state(project):
    path = project / '.preparation/state.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {'status': 'ready', 'reason': '已有绘图工程'}


def save_state(project, value):
    write_json(project/'.preparation/state.json', value)


def source_root(project):
    """Batch children share the parent's read-only backup, never arbitrary paths."""
    project = Path(project)
    if project.parent.name == 'batches' and project.parent.parent.name == '.preparation':
        parent = project.parent.parent.parent
        if not (parent/'project.json').is_file() or not (project/'batch-child.json').is_file():
            raise ValueError('无效的整工程批次')
        return parent/'.preparation/source'
    return project/'.preparation/source'


def status(project):
    value = read_state(project)
    if value.get('status') == 'working' and str(project) not in RUNNING:
        value = {**value, 'status': 'interrupted', 'reason': '准备任务被中断，可重新发起；原工程已备份。'}
    result = {k: v for k, v in value.items() if k not in ('generated_files',)}
    result['project'] = project.name
    result['display_name'] = json.loads((project/'project.json').read_text(encoding='utf-8')).get('name', project.name)
    result['local_path'] = str(project)
    result['generated_files'] = [{'path': f['path'], 'role': f['role']} for f in value.get('generated_files', [])]
    if value.get('mode') == 'batch':
        from project_batch import public_status
        result['batch'] = public_status(project)
    if value.get('mode')=='native' and value.get('import_completed'):
        checks=value.get('validation',{}).get('checks',[])
        result['native_progress']={'completed':len(checks),'total':len(value.get('figures',[])),'passed':sum(c.get('render')=='passed' for c in checks),'failed':sum(c.get('render')=='failed' for c in checks),'diagnostics':sum(c.get('render')=='warning' for c in checks)}
    result['can_open'] = can_open(project)
    source = value.get('source_path')
    if source and not result['can_open']:
        from native_project import discover
        result['native_available'] = discover(Path(source)) is not None
    else:
        result['native_available'] = False
    return result


def can_open(project):
    """Only advertise prepared projects with persisted validation evidence."""
    value = read_state(project)
    if value.get('status') != 'ready' or not any((project/'charts').glob('*.py')):
        return False
    if value.get('mode')=='native' and value.get('import_completed') is True:
        marker=project/'validation/native.json'
        if (project/'native-project.json').is_file() and marker.is_file():
            try:return json.loads(marker.read_text(encoding='utf-8')).get('import_completed') is True
            except (OSError,ValueError):return False
    if value.get('mode') == 'batch':
        from project_batch import read
        batch = read(project)
        return bool(batch.get('installed') and batch.get('jobs') and
                    all(j.get('status') == 'ready' for j in batch['jobs']))
    if (value.get('validation') or {}).get('state') == 'passed':
        return True
    if value.get('restored_standard') is True:
        return True
    for name in ('direct.json', 'extraction.json', 'batch.json', 'native.json'):
        path = project/'validation'/name
        if path.is_file():
            try:
                if json.loads(path.read_text()).get('state') == 'passed':
                    return True
            except (ValueError, OSError):
                pass
    # Legacy projects predate .preparation. An actual charts directory is the
    # old split format; absence of a newer validation file does not make it an
    # unfinished import. An explicit pending/failed state above still blocks.
    return not (project/'.preparation/state.json').exists()


def rename_project(project, name):
    """Display name only: IDs and persisted draft/source paths stay stable."""
    from chat_harness import lock
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 100 or any(ord(c) < 32 for c in name):
        raise ValueError('工程名称须为 1–100 个字符，不能含控制字符')
    with LOCK, lock(project):
        if str(project) in RUNNING:
            raise ValueError('工程正在准备，请完成后重命名')
        metadata = project/'project.json'
        if metadata.is_symlink() or not metadata.is_file():
            raise ValueError('工程元数据路径不安全或已不存在')
        value = json.loads(metadata.read_text(encoding='utf-8'))
        write_json(metadata, {**value, 'name': name.strip()})
        return status(project)


def open_project(projects, source, name='', allow_local_execution=False):
    projects = Path(projects)
    root, files, skipped = inventory(source)
    name = (name or root.name).strip()
    ident = re.sub(r'[^\w-]', '_', name, flags=re.UNICODE).strip('_')
    if not ident or len(ident) > 100:
        raise ValueError('工程名称无效或过长')
    target = projects / ident
    if target.exists():
        # Reopening is read-only; never overwrite changed charts with source files.
        p = project_path(projects, ident)
        origin = read_state(p).get('source_path')
        if root == target.resolve() or origin == str(root):
            return {**status(p), 'reopened': True}
        raise ValueError('已存在同名工程但来源不同，请使用其他工程名称；未覆盖任何文件。')
    prepared_source = project_layout(root) is not None
    if prepared_source and not allow_local_execution:
        raise ValueError('标准工程含可执行 Python。请先确认已审阅代码并允许本机渲染。')
    if projects.resolve().is_relative_to(root):
        raise ValueError('源目录包含 Plot Forge 工作区，请选择具体绘图工程。')
    projects.mkdir(parents=True, exist_ok=True)
    mark_private(projects, ident)
    with tempfile.TemporaryDirectory(prefix='.prepare-', dir=projects) as folder:
        staged = Path(folder)/ident
        source_copy = staged/'.preparation/source'
        source_copy.mkdir(parents=True)
        for item in files:
            origin = root/item['path']
            if origin.is_symlink() or not origin.resolve().is_relative_to(root):
                raise ValueError('源文件在扫描后发生变化，请重新检查')
            destination = source_copy/item['path']
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(origin, destination)
            item['sha256'] = sha(destination)
        for directory in ('charts', 'lib', 'data', 'previews', 'history', 'validation'):
            (staged/directory).mkdir()
        layout = project_layout(source_copy)
        prepared = layout is not None
        metadata = {'name': name, 'description': '本地绘图工程', 'plot_forge_format': 1}
        if prepared:
            code_root, metadata_file = layout
            old = json.loads(metadata_file.read_text(encoding='utf-8'))
            metadata.update({k:v for k,v in old.items() if k not in ('id','source_root')})
            for directory in ('charts', 'lib', 'previews', 'history', 'validation', 'images'):
                if (code_root/directory).is_dir():
                    shutil.copytree(code_root/directory, staged/directory, dirs_exist_ok=True)
                elif directory in ('previews','history','validation','images') and (source_copy/directory).is_dir():
                    shutil.copytree(source_copy/directory, staged/directory, dirs_exist_ok=True)
            if (source_copy/'data').is_dir():
                shutil.copytree(source_copy/'data', staged/'data', dirs_exist_ok=True)
            for f in code_root.glob('*.py'):
                shutil.copy2(f, staged/f.name)
            for f in code_root.glob('*.json'):
                if f.name != 'project.json':
                    shutil.copy2(f, staged/f.name)
        value = {'status': 'ready' if prepared else 'needs_analysis', 'mode': 'direct' if prepared else None,
                 'restored_standard': prepared,
                 'source_path': str(root),
                 'reason': '已恢复标准工程，可直接选择图表修改。' if prepared else '本地备份完成，尚未运行分析或发送代码。',
                 'files': files, 'skipped': skipped, 'figures': [], 'generated_files': []}
        write_json(staged/'project.json', metadata)
        save_state(staged, value)
        staged.rename(target)
    return status(target)


def validate_renderer(source):
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef)):
            continue
        expression = node.value if isinstance(node, (ast.Assign, ast.AnnAssign, ast.Expr)) else None
        if expression is None or any(isinstance(n, (ast.Call, ast.Await, ast.Yield, ast.NamedExpr)) for n in ast.walk(expression)):
            raise ValueError('绘图模块顶层只能包含导入、常量、函数和注册表；不能执行 I/O 或调用。')
    allowed = {'numpy', 'pandas', 'matplotlib', 'json', 'pathlib', 'hashlib', 'math', 'collections', 'PIL', 'csv', 'typing'}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [x.name for x in node.names] if isinstance(node, ast.Import) else [node.module or '']
            if any(name.split('.')[0] not in allowed for name in names):
                raise ValueError('独立绘图代码包含未允许的依赖，请补全数据导出而非依赖原始分析。')
        if isinstance(node, ast.Call):
            func = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else ''
            if func in {'exec','eval','compile','__import__','globals','locals','getattr','setattr','system','show','read_pickle','load_pickle'}:
                raise ValueError('绘图代码含动态执行、交互或不安全读取')
            if func == 'load' and not any(k.arg == 'allow_pickle' and isinstance(k.value, ast.Constant) and k.value.value is False for k in node.keywords):
                # json.load is safe; numpy.load must explicitly reject pickle.
                if not isinstance(node.func, ast.Attribute) or not isinstance(node.func.value, ast.Name) or node.func.value.id != 'json':
                    raise ValueError('数组读取必须显式设置 allow_pickle=False')
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and (node.value.startswith(('/home/', '/data/', 'C:\\', '/Users/'))):
            raise ValueError('绘图代码仍引用原始绝对路径')
    names = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    if not {'render','list_figures'} <= names:
        raise ValueError('绘图代码必须实现 render 和 list_figures')


def validate_exporter(source):
    tree = ast.parse(source)
    banned = {'requests','urllib','http','socket','subprocess','keyring','ctypes','pickle','dill','joblib'}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [n.name for n in node.names] if isinstance(node, ast.Import) else [node.module or '']
            if any(n.split('.')[0] in banned for n in names):
                raise ValueError('导出程序包含网络、凭据或不安全序列化依赖，请先处理这些依赖。')
        if isinstance(node, ast.Call):
            name = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else ''
            if any(k.arg=='allow_pickle' and not (isinstance(k.value,ast.Constant) and k.value.value is False) for k in node.keywords):
                raise ValueError('不允许启用 pickle 数组读取。')
            if name in {'exec','eval','compile','__import__','system','popen','get_password','read_pickle'}:
                raise ValueError('导出程序包含不允许的动态执行或凭据读取。')


def analyze(project, consent=False, plan=None):
    if not consent:
        raise ValueError('请先确认允许将列出的 Python 源码发送给所选模型；原始数据不会随此分析发送。')
    value = read_state(project)
    if value.get('status') == 'ready':
        return status(project)
    from analysis_scope import build, public, require_limit
    plan = plan if plan is not None else build(project, value.get('analysis_scope', ''))
    require_limit(plan)
    sources = plan['sources']
    value = {**value, 'analysis_scope': plan['scope'], 'analysis_summary': public(plan)}
    from model_transport import guard_secrets
    guard_secrets(sources)
    from llm_client import chat
    instruction = (SKILL/'SKILL.md').read_text() + '\n' + (SKILL/'references/extraction-contract.md').read_text()
    instruction += '''
Host integration requirements:
There is no completed execution evidence. Never return ready. Direct mode may identify
existing Plot Forge-ready scripts in figures[].entry_path and figures[].data_paths,
with figures[].helper_paths listing every required Python helper. Direct entries must
already use CHART_PROJECT_DIR and CHART_OUTPUT, with data paths below data/ and helpers
at the project root or under lib/. Their scientific processing must already be separate.
Otherwise use extraction, or needs_context with missing paths and evidence. Do not guess.
For extraction return the two complete generated source files and pending_local_run.
Export input reads must stay inside the copied source folder. Accept --output DIRECTORY
for a new plot-data package. Keep raw inputs read-only. All data processing stays local.
Use JSON, CSV or NPZ for numeric plot values. Reference validation/plot-inputs.json must
be a declared JSON artifact: {"figures": {figure_id: {"inputs": [
{"artifact":"arrays/values.npz","key":"x","original":[1,2]}]}}}.
Capture original values at the original plot boundary (never fabricate reference data).
For JSON, key is a slash-separated key path; for CSV, key is a column name. Every figure
needs at least one input comparison, and ALL its scientific plotting inputs must be included.
numeric_atol and numeric_rtol default to zero; nonzero tolerances need tolerance_reason.
Renderer imports only numpy, pandas, matplotlib, json, pathlib, hashlib, math,
collections, PIL, csv, typing. It must have no top-level I/O and no CLI/main block.
Keep render_plot.py under 90000 characters so it remains editable by the host.
It must save exactly one PNG per render call and close figures. Unknown data dependencies
must produce needs_context. Never replace unresolved inputs with demo data.
'''
    response = chat([{'role':'system','content':instruction}, {'role':'user','content':json.dumps({
        'sources': sources, 'data_catalog': plan['data_catalog'],
        'requested_scope': (plan.get('target_files') if value.get('batch_child') else plan['scope'] or 'whole project'), 'source_catalog': plan['source_catalog'],
        'batch_instruction': ('This is one batch of an entire project. Each source may include identical_paths: those paths have EXACTLY the same COMPLETE decoded text as content, not summaries or omissions. Resolve their imports relative to each original path, not only the representative path. Use extraction mode, not direct mode, so the host can safely namespace and combine verified packages. If the requested target files ONLY provide helpers, style, verification or orchestration and contain no independently generated figures, return status=needs_context and explain that this batch needs a human non-figure review. Do not invent figures or silently exclude plotting branches.' if value.get('batch_child') else ''),
        'scope_contract': 'Prepare ONLY figures in requested_scope. Other sources are dependency context, not additional target figures. Omitted file names are not their contents. Static imports are best-effort, not proof of a complete dependency closure. Inspect dynamic imports, file reads and missing inputs; return needs_context with exact paths if required source is not provided. Never fabricate or omit figures within the requested scope. Paths remain relative to the ORIGINAL project root, not the selected subdirectory.',
        'dependency_warnings': plan['warnings'],
        'validation_evidence': None}, ensure_ascii=False)}])
    from llm_workflows import _json_object
    result = _json_object(response)
    result = {k:v for k,v in result.items() if k in ('mode','status','reason','figures','generated_files','required_local_inputs','validation')}
    if value.get('batch_child') and result.get('mode') == 'direct':
        raise ValueError('整工程批次必须生成独立提取方案，不能直接合并未隔离的绘图入口')
    if result.get('mode') == 'direct':
        try:
            validate_direct(project, result.get('figures', []))
            result['status'] = 'pending_local_run'
            result['reason'] = '发现已有独立绘图入口。无需重写科学计算；请审阅并允许验证原始绘图代码。'
        except ValueError as exc:
            result['status'] = 'needs_context'
            result['reason'] = str(exc)
        result['generated_files'] = []
    generated = result.get('generated_files') or []
    if result.get('mode') == 'extract' and result.get('status') == 'pending_local_run':
        if len(generated) != 2 or {f.get('role') for f in generated} != {'export_program','renderer'}:
            raise ValueError('提取结果必须包含一个完整导出程序和一个独立绘图程序')
        paths = set()
        for f in generated:
            path = relative_path(f['path'])
            if len(path.parts) != 1 or path.suffix != '.py' or str(path) in paths:
                raise ValueError('生成文件必须是两个不同的顶层 Python 文件')
            paths.add(str(path))
            if not isinstance(f.get('content'), str) or len(f['content']) > 400000:
                raise ValueError('生成代码过大或缺失')
            ast.parse(f['content'])
            if f['role'] == 'renderer':
                if len(f['content']) > 90000:
                    raise ValueError('独立绘图代码超过 9 万字符，请拆分图组，以便后续对话修改。')
                if str(path) != 'render_plot.py':
                    raise ValueError('绘图程序须命名为 render_plot.py')
                validate_renderer(f['content'])
            else:
                validate_exporter(f['content'])
                if not str(path).endswith('_export.py') or 'manifest.json' not in f['content']:
                    raise ValueError('导出程序缺少命名或 manifest 写入契约')
        folder = project/'.preparation/generated'
        folder.mkdir(exist_ok=True)
        for f in generated:
            (folder/f['path']).write_text(f['content'], encoding='utf-8')
    elif result.get('mode') == 'direct' and result.get('status') == 'pending_local_run':
        pass
    elif result.get('status') not in ('needs_context', 'unsupported'):
        raise ValueError('尚无本地执行证据，不能把模型输出标记为可用工程')
    else:
        generated = []
        result['generated_files'] = []
    save_state(project, {**value, **result, 'files': value['files'],
                        'validation': {'state':'pending_local_run' if result.get('status')=='pending_local_run' else 'unverified'},
                        'updated_at': time.time()})
    return status(project)


def validate_direct(project, figures):
    ids=[f.get('figure_id') for f in figures]
    if not ids or len(ids)>100 or len(set(ids))!=len(ids) or any(not isinstance(i,str) or not re.fullmatch(r'[A-Za-z0-9_]+',i) for i in ids):
        raise ValueError('直接模式缺少唯一、稳定的图表 ID。')
    catalog={f['path']:f for f in read_state(project).get('files',[])}
    source=source_root(project)
    for f in figures:
        entry=str(relative_path(f.get('entry_path')))
        if entry not in catalog or not entry.endswith('.py'):
            raise ValueError('直接模式的绘图入口不存在：'+entry)
        content=(source/entry).read_text(encoding='utf-8-sig')
        validate_exporter(content)
        if 'CHART_PROJECT_DIR' not in content or 'CHART_OUTPUT' not in content or '__file__' in content:
            raise ValueError('已有入口尚不兼容 CHART_PROJECT_DIR / CHART_OUTPUT；请提供独立入口或采用提取模式。')
        for rel in f.get('data_paths',[]):
            path=relative_path(rel)
            if rel not in catalog or not rel.startswith('data/') or path.suffix.lower() not in DATA_SUFFIXES:
                raise ValueError('直接模式数据须位于工程内 data/：'+rel)
        for rel in f.get('helper_paths',[]):
            path=relative_path(rel)
            if rel not in catalog or path.suffix!='.py' or (len(path.parts)>1 and path.parts[0]!='lib'):
                raise ValueError('直接模式辅助模块须位于工程根目录或 lib/：'+rel)
            validate_exporter((source/rel).read_text(encoding='utf-8-sig'))


def finalize_direct(project, value):
    validate_direct(project,value['figures'])
    from chat_runner import _one_render, isolation_backend
    with tempfile.TemporaryDirectory(prefix='plot-direct-') as folder:
        staged=Path(folder)/'project'
        for name in ('charts','data','lib','previews'):(staged/name).mkdir(parents=True)
        write_json(staged/'project.json',{'name':project.name})
        source=source_root(project)
        checks=[]
        for f in value['figures']:
            for rel in [*f.get('data_paths',[]),*f.get('helper_paths',[])]:
                target=staged/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source/rel,target)
            shutil.copy2(source/f['entry_path'],staged/'charts'/(f['figure_id']+'.py'))
        for f in value['figures']:
            ident=f['figure_id']
            report=_one_render(staged,'charts/'+ident+'.py',{},Path(folder)/('render_'+ident), strict_io=True)
            if report['output_count']!=1:raise ValueError('独立入口必须只输出选中的一张图：'+ident)
            (staged/'previews'/(ident+'.png')).write_bytes(report['image_bytes'])
            checks.append({'figure_id':ident,'render':'passed','source':'unchanged','inputs':'byte-identical snapshot','backend':isolation_backend()})
        install_verified(project,staged,('charts','data','lib','previews'),Path(folder)/'rollback')
        write_json(project/'validation/direct.json',{'state':'passed','checks':checks,'basis':'Original independent code and inputs, unchanged; no claim of scientific equivalence.'})
        save_state(project,{**value,'status':'ready','reason':'独立绘图入口验证通过；源码与输入保持不变。','validation':{'state':'passed','checks':checks}})
    return status(project)


def install_verified(project,staged,directories,rollback):
    # /tmp and the user's project volume may be different filesystems. Keep
    # rollback renames on the project volume; staging still uses bounded copies.
    with tempfile.TemporaryDirectory(prefix='.install-',dir=project) as folder:
        local_rollback=Path(folder);moved=[];created=[]
        try:
            for directory in directories:
                target=project/directory
                if target.is_symlink() or (staged/directory).is_symlink():
                    raise ValueError('Cannot install over a symlink')
                if target.exists():
                    target.rename(local_rollback/directory);moved.append(directory)
                created.append(directory)
                shutil.copytree(staged/directory,target)
        except BaseException:
            for directory in reversed(created):
                target=project/directory
                if target.exists():shutil.rmtree(target)
            for directory in moved:
                (local_rollback/directory).rename(project/directory)
            raise


def start_analysis(project, consent, scope=None, confirmation_token=None):
    with LOCK:
        if str(project) in RUNNING:
            raise ValueError('该工程正在准备，请等待当前任务完成')
        if not consent:
            raise ValueError('请先确认源码发送范围')
        old = read_state(project)
        if old.get('mode') == 'batch':
            raise ValueError('当前为整工程批处理，请使用批次操作，不能覆盖为单组方案')
        if old.get('status') == 'ready':
            return status(project)
        from analysis_scope import build, public, require_limit
        plan = build(project, old.get('analysis_scope', '') if scope is None else scope)
        require_limit(plan)
        if scope is not None and confirmation_token != plan['confirmation_token']:
            raise ValueError('分析范围或源码已变化，请重新预览并确认发送范围')
        old = {**old, 'task_outcome': None, 'analysis_scope': plan['scope'], 'analysis_summary': public(plan),
               'mode': None, 'figures': [], 'generated_files': [], 'validation': {'state': 'unverified'}}
        RUNNING.add(str(project))
        save_state(project, {**old,'status':'working','started_at':time.time(),'reason':'正在分析源码并生成提取方案，等待模型返回…'})
        def work():
            try:
                analyze(project, consent, plan=plan)
            except Exception as exc:
                save_state(project, {**old,'status':'needs_analysis','reason':str(exc)[:1000],'task_outcome':{'status':'failed','label':'失败：拆分方案生成失败'}})
            finally:
                with LOCK:
                    RUNNING.discard(str(project))
        threading.Thread(target=work, daemon=True).start()
        return status(project)


def validate_package(root):
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError('请选择真实的 plot-data 目录')
    root = root.resolve()
    manifest_path = root/'manifest.json'
    if manifest_path.is_symlink() or manifest_path.stat().st_size > 2_000_000:
        raise ValueError('无效的 manifest')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if manifest.get('schema_version') != '1.0':
        raise ValueError('plot-data schema_version 必须为 1.0')
    producer = manifest.get('producer', {})
    if not re.fullmatch('[0-9a-f]{64}', producer.get('source_sha256','')) or not producer.get('python'):
        raise ValueError('manifest 缺少导出程序校验和或 Python 版本')
    artifacts, total = {}, 0
    for item in manifest.get('artifacts', []):
        rel = str(relative_path(item['path']))
        path = root/rel
        if rel == 'manifest.json' or rel in artifacts or any(p.is_symlink() for p in [path, *path.parents]) or not path.is_file():
            raise ValueError('绘图数据含重复、缺失文件或符号链接：'+rel)
        formats = {'.json':'json','.csv':'csv','.npz':'npz','.parquet':'parquet','.png':'png','.jpg':'jpeg','.jpeg':'jpeg','.webp':'webp'}
        if formats.get(path.suffix.lower()) != item.get('format'):
            raise ValueError('不支持的绘图数据格式：'+rel)
        total += path.stat().st_size
        if total > 100*1024**2 or path.stat().st_size != item.get('bytes') or sha(path) != item.get('sha256'):
            raise ValueError('绘图数据大小或 SHA256 校验失败：'+rel)
        if item['format'] == 'npz':
            import numpy as np
            with zipfile.ZipFile(path) as archive:
                if sum(i.file_size for i in archive.infolist()) > 200*1024**2:
                    raise ValueError('NPZ 解压后过大')
            with np.load(path, allow_pickle=False) as arrays:
                for key in arrays.files:
                    if arrays[key].dtype.hasobject:
                        raise ValueError('不允许 object dtype')
        artifacts[rel] = item
    figures = manifest.get('figures', [])
    ids = [f.get('figure_id') for f in figures]
    if not ids or len(ids)>100 or len(set(ids)) != len(ids) or any(not isinstance(i,str) or not re.fullmatch(r'[A-Za-z0-9_]+',i) for i in ids):
        raise ValueError('图表 ID 必须是唯一的英文字母、数字或下划线，最多 100 张')
    for f in figures:
        if f.get('expected_outputs') != 1 or not f.get('renderer') or not f.get('artifacts') or not set(f['artifacts']) <= set(artifacts):
            raise ValueError('图表必须声明一个输出和完整的数据依赖')
    validation = manifest.get('validation', {})
    ref = validation.get('plot_input_reference')
    if ref not in artifacts or artifacts[ref]['format'] != 'json':
        raise ValueError('缺少声明并校验的原始绘图输入参照文件')
    for k in ('numeric_atol','numeric_rtol'):
        v = validation.get(k,0)
        if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or v<0:
            raise ValueError('数值容差无效')
        if v and not validation.get('tolerance_reason'):
            raise ValueError('非零容差需要注明理由')
    reference = json.loads((root/ref).read_text(encoding='utf-8')).get('figures',{})
    if set(reference) != set(ids):
        raise ValueError('参照文件中的图表集合与 manifest 不一致')
    import numpy as np
    checks=[]
    for f in figures:
        inputs=reference[f['figure_id']].get('inputs',[])
        if not inputs:
            raise ValueError('图表缺少原始绘图输入比较：'+f['figure_id'])
        for item in inputs:
            rel=item.get('artifact'); key=item.get('key','')
            if rel not in f['artifacts'] or rel==ref:
                raise ValueError('输入参照必须指向该图实际声明的数据文件')
            kind=artifacts[rel]['format']
            if kind=='npz':
                with np.load(root/rel,allow_pickle=False) as arrays:
                    actual=arrays[key]
            elif kind=='json':
                actual=json.loads((root/rel).read_text())
                for component in key.split('/') if key else []:
                    actual=actual[int(component)] if isinstance(actual,list) else actual[component]
            elif kind in ('csv','parquet'):
                import pandas as pd
                if kind=='csv':
                    spec=artifacts[rel].get('serialization')
                    if not spec or not {'encoding','delimiter','dtypes','columns','index','missing_values'}<=set(spec):
                        raise ValueError('CSV 必须声明 encoding/delimiter/dtypes/columns/index/missing_values')
                    frame=pd.read_csv(root/rel,encoding=spec['encoding'],sep=spec['delimiter'],dtype=spec['dtypes'],
                                      index_col=spec['index'],keep_default_na=False,na_values=spec['missing_values'])
                    if list(frame.columns)!=spec['columns']:
                        raise ValueError('CSV 列顺序不一致')
                else:
                    frame=pd.read_parquet(root/rel)
                actual=frame[key].to_numpy()
            else:
                raise ValueError('数值参照仅支持 JSON、CSV、Parquet 和 NPZ')
            expected=np.asarray(item['original']); actual=np.asarray(actual)
            if actual.shape!=expected.shape:
                raise ValueError('输入形状不一致：'+f['figure_id']+'/'+key)
            if actual.dtype.kind in 'fciub' and expected.dtype.kind in 'fciub':
                same=np.array_equal(actual,expected,equal_nan=True) if not (validation.get('numeric_atol') or validation.get('numeric_rtol')) else np.allclose(actual,expected,atol=validation.get('numeric_atol',0),rtol=validation.get('numeric_rtol',0),equal_nan=True)
            else:
                same=np.array_equal(actual,expected)
            if not same:
                raise ValueError('原始与导出绘图值不一致：'+f['figure_id']+'/'+key)
        checks.append({'figure_id':f['figure_id'],'values':'passed','inputs_compared':len(inputs)})
    return manifest, artifacts, checks


def finalize(project, bundle, allow_local_execution=False, _running=False):
    with LOCK:
        if str(project) in RUNNING and not _running:
            raise ValueError('工程准备仍在进行')
    if not allow_local_execution:
        raise ValueError('请先审阅导出的绘图代码并确认本机渲染；推荐配置 Docker 隔离。')
    value=read_state(project)
    if value.get('status')=='ready':
        return status(project)
    if value.get('mode')=='direct':
        return finalize_direct(project,value)
    generated=value.get('generated_files',[])
    renderer=next((f for f in generated if f['role']=='renderer'),None)
    exporter=next((f for f in generated if f['role']=='export_program'),None)
    if not renderer or not exporter:
        raise ValueError('请先生成提取方案')
    validate_renderer(renderer['content'])
    manifest,artifacts,checks=validate_package(bundle)
    if manifest['producer']['source_sha256'] != hashlib.sha256(exporter['content'].encode()).hexdigest():
        raise ValueError('数据包不是由本轮导出程序产生，请重新运行本轮导出文件')
    if {f['figure_id'] for f in value.get('figures',[])} != {f['figure_id'] for f in manifest['figures']}:
        raise ValueError('数据包图表集合与提取方案不一致')
    from chat_runner import _one_render, isolation_backend
    with tempfile.TemporaryDirectory(prefix='plot-verify-') as temp:
        work=Path(temp); staged=work/'project'; (staged/'data/plot-data').mkdir(parents=True)
        for rel in ['manifest.json', *artifacts]:
            dest=staged/'data/plot-data'/rel; dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(Path(bundle)/rel,dest)
        validate_package(staged/'data/plot-data')
        write_json(staged/'project.json',{'name':project.name})
        (staged/'charts').mkdir(); (staged/'previews').mkdir()
        for figure,check in zip(manifest['figures'],checks):
            ident=figure['figure_id']
            adapter = renderer['content'] + '\n\nimport os as _pf_os\nfrom pathlib import Path as _PFPath\n_pf_bundle = _PFPath(_pf_os.environ["CHART_PROJECT_DIR"])/"data"/"plot-data"\n_pf_ids = list_figures(_pf_bundle)\n_pf_ids = [x["figure_id"] if isinstance(x, dict) else x for x in _pf_ids]\nassert _pf_ids == '+repr([f['figure_id'] for f in manifest['figures']])+', "Renderer figure registry differs from manifest"\nrender(_pf_bundle, '+repr(ident)+', _pf_os.environ["CHART_OUTPUT"])\n'
            (staged/'charts'/(ident+'.py')).write_text(adapter,encoding='utf-8')
            report=_one_render(staged,'charts/'+ident+'.py',{},work/('render_'+ident))
            if report.get('output_count')!=1:
                raise ValueError('每次调用必须只输出选中的一张图')
            (staged/'previews'/(ident+'.png')).write_bytes(report['image_bytes'])
            check.update(render='passed', backend=isolation_backend())
        # Install only after every figure and hash has passed. Roll back interrupted installation.
        install_verified(project,staged,('charts','data','previews'),work/'rollback')
        write_json(project/'validation/extraction.json', {'checks':checks,'state':'passed',
            'basis':'Local export capture compared with declared artifacts; all figures rendered in snapshots.',
            'os_sandbox':isolation_backend()!='local-python'})
        save_state(project,{**value,'status':'ready','reason':'绘图输入比较和全部图表渲染通过，可以对话改图。',
                            'validation':{'state':'passed','checks':checks}})
    return status(project)


def start_finalize(project, bundle, consent):
    if not consent:
        raise ValueError('请先审阅绘图代码并允许本机验证。')
    with LOCK:
        if str(project) in RUNNING:
            raise ValueError('工程正在准备中，请稍候。')
        old = read_state(project)
        if old.get('mode') == 'batch':
            raise ValueError('请使用整工程批次验证入口')
        if old.get('status') == 'ready':
            return status(project)
        RUNNING.add(str(project))
        save_state(project, {**old, 'status':'working', 'started_at':time.time(), 'reason':'正在校验数据与逐图渲染…'})
        def work():
            try:
                finalize(project, bundle, True, _running=True)
            except Exception as exc:
                save_state(project, {**old, 'status':'pending_local_run', 'reason':str(exc)[:1500], 'validation':{'state':'failed'}})
            finally:
                with LOCK:
                    RUNNING.discard(str(project))
        threading.Thread(target=work, daemon=True).start()
        return status(project)


def archive(project, preparation=False):
    output=io.BytesIO()
    total=0
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as z:
        if preparation:
            value=read_state(project)
            generated_paths = {f['path'] for f in value.get('generated_files',[])}
            for item in value.get('files',[]):
                p=source_root(project)/item['path']
                # Original analysis can be large; the export code ZIP includes source only.
                if p.suffix=='.py' and item['path'] not in generated_paths:
                    total+=p.stat().st_size
                    if total>200*1024**2:
                        raise ValueError('提取方案源文件超过 200 MiB，请先缩小工程。')
                    z.write(p,project.name+'/'+item['path'])
            for item in value.get('generated_files',[]):
                z.writestr(project.name+'/'+item['path'],item['content'])
            z.writestr(project.name+'/RUN_EXPORT.txt','先审阅生成的 *_export.py，将其放在原工程根目录。运行 python <name>_export.py --output <新的plot-data目录>。\n原始数据只在本机读取，不上传。导出后在 Plot Forge 选择 plot-data 目录完成检查。\n')
        else:
            if read_state(project).get('status')!='ready':
                raise ValueError('尚未完成准备，请先下载提取方案并完成本地验证')
            for p in sorted(project.rglob('*')):
                rel=p.relative_to(project)
                if any(part.startswith('.') or part=='__pycache__' for part in rel.parts) or p.is_symlink() or not p.is_file():
                    continue
                if re.search(r'(?i)(credential|secret|token|password|id_rsa|api[-_]key)', p.name):
                    continue
                total+=p.stat().st_size
                if total>200*1024**2:
                    raise ValueError('标准备份超过 200 MiB，请拆分工程，或在本机文件管理器中备份该工程目录。')
                if p.suffix.lower() in {'.py', '.json', '.md', '.txt'}:
                    from model_transport import guard_secrets
                    guard_secrets(p.read_text(encoding='utf-8'))
                name=rel.as_posix() if rel.parts[0]=='data' else 'code/'+rel.as_posix()
                z.write(p,project.name+'/'+name)
    return output.getvalue()
