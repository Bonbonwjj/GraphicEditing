"""Local-first discovery and verified adaptation of ordinary plotting projects."""
from __future__ import annotations

import ast
import hashlib
import importlib.metadata
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
import threading
import time
import sys

import project_preparation as prep


SCHEMA = 'plot-forge-universal/1'
MAX_PROJECT_BYTES = 100 * 1024 * 1024
MAX_ENTRY_CANDIDATES = 50
MAX_OUTPUTS_PER_ENTRY = 20
PLOT_METHODS = {
    'plot', 'scatter', 'bar', 'barh', 'boxplot', 'violinplot', 'hist', 'hist2d',
    'imshow', 'pcolormesh', 'contour', 'contourf', 'errorbar', 'fill_between',
    'heatmap', 'lineplot', 'scatterplot', 'catplot', 'relplot', 'displot',
    'savefig', 'show',
}
OUTPUT_METHODS = {'savefig', 'show'}


def _call_name(node):
    if not isinstance(node, ast.Call):
        return ''
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return ''


def _main_guard(node):
    if not isinstance(node, ast.If):
        return False
    try:
        text = ast.unparse(node.test)
    except Exception:
        return False
    return '__name__' in text and '__main__' in text


def _literal_output(node):
    if not isinstance(node, ast.Call) or not node.args:
        return None
    value = node.args[0]
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return value.value
    if isinstance(value, ast.BinOp) and isinstance(value.op, ast.Div) and isinstance(value.right, ast.Constant) and isinstance(value.right.value, str):
        return value.right.value
    return None


def discover(project):
    """Find runnable Python entries using syntax only; never import user code."""
    root = prep.source_root(Path(project))
    state = prep.read_state(Path(project))
    run_config=Path(project)/'run-config.json'
    if run_config.is_file():
        configured=json.loads(run_config.read_text(encoding='utf-8'))
        if configured.get('schema')!='plot-forge-run/1' or not isinstance(configured.get('entries'),list):
            raise ValueError('工程运行配置格式无效')
        candidates=[]
        for item in configured['entries']:
            entry=str(prep.relative_path(item.get('path')))
            if not entry.endswith('.py') or not (root/entry).is_file():
                raise ValueError('配置的绘图入口不存在：'+entry)
            if not isinstance(item.get('kwargs',{}),dict):
                raise ValueError('入口 kwargs 必须是参数对象')
            for field in ('symbol','method'):
                value=item.get(field)
                if value is not None and (not isinstance(value,str) or not value.isidentifier() or value.startswith('_')):
                    raise ValueError('入口函数或方法名称无效')
            candidates.append({'entry_path':entry,'entry_symbol':item.get('symbol'),
                'entry_method':item.get('method'),'entry_kwargs':item.get('kwargs',{}),
                'status':'candidate','runnable_evidence':'project_run_configuration',
                'confidence':1,'capture_open_figures':True,'capture_return':True,
                'output_sites':[],'plot_call_count':0})
        return {'schema':SCHEMA,'candidates':candidates[:MAX_ENTRY_CANDIDATES],
                'diagnostics':[],'truncated':len(candidates)>MAX_ENTRY_CANDIDATES}
    records = []
    for item in state.get('files', []):
        if item.get('kind') != 'code' or not item.get('path', '').endswith('.py'):
            continue
        path = root / item['path']
        try:
            source = path.read_text(encoding='utf-8-sig')
            tree = ast.parse(source, filename=item['path'])
        except (OSError, UnicodeError, SyntaxError) as error:
            records.append({'entry_path': item['path'], 'status': 'syntax_error', 'reason': str(error)})
            continue
        parent = {}
        for owner in ast.walk(tree):
            for child in ast.iter_child_nodes(owner):
                parent[child] = owner
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and _call_name(node) in PLOT_METHODS]
        outputs = [node for node in calls if _call_name(node) in OUTPUT_METHODS]
        if not calls:
            continue
        top_level = []
        top_level_calls = []
        for node in calls:
            owner = node
            while owner in parent and not isinstance(parent[owner], (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                owner = parent[owner]
            if not isinstance(parent.get(owner), (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                top_level_calls.append(node)
                if node in outputs:
                    top_level.append(node)
        guarded = any(_main_guard(node) for node in tree.body)
        output_sites = [{'line': node.lineno, 'kind': _call_name(node), 'literal_output': _literal_output(node)} for node in outputs]
        if top_level_calls or guarded:
            records.append({'entry_path': item['path'], 'entry_symbol': None, 'status': 'candidate',
                            'runnable_evidence': 'top_level_output' if top_level else 'top_level_plot' if top_level_calls else 'main_guard',
                            'confidence': 0.95 if top_level else 0.9,
                            'capture_open_figures':not bool(outputs),
                            'output_sites': output_sites, 'plot_call_count': len(calls)})
        for function in (node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))):
            function_calls=[node for node in ast.walk(function) if isinstance(node, ast.Call) and _call_name(node) in PLOT_METHODS]
            function_outputs=[node for node in function_calls if _call_name(node) in OUTPUT_METHODS]
            positional=[*function.args.posonlyargs,*function.args.args]
            required=len(positional)-len(function.args.defaults)
            required+=sum(default is None for default in function.args.kw_defaults)
            if not function_calls or required or isinstance(function,ast.AsyncFunctionDef):
                continue
            records.append({'entry_path':item['path'],'entry_symbol':function.name,'status':'candidate',
                            'runnable_evidence':'zero_argument_plot_function','confidence':0.86,
                            'capture_return':not bool(function_outputs),
                            'output_sites':[{'line':node.lineno,'kind':_call_name(node),
                                             'literal_output':_literal_output(node)} for node in function_outputs],
                            'plot_call_count':len(function_calls)})
        if outputs and not any(record.get('entry_path')==item['path'] for record in records):
            records.append({'entry_path':item['path'],'entry_symbol':None,'status':'candidate',
                            'runnable_evidence':'unresolved_function_output','confidence':0.45,
                            'output_sites':output_sites,'plot_call_count':len(calls)})
    candidates = [record for record in records if record.get('status') == 'candidate']
    # Orchestration scripts often import draw(data) from another file and have
    # no plotting API call themselves. Resolve their local dependency closure.
    plotting_paths={item['entry_path'] for item in candidates}
    from analysis_scope import build
    for item in state.get('files', []):
        entry=item.get('path','')
        if item.get('kind')!='code' or entry in plotting_paths:
            continue
        try:
            tree=ast.parse((root/entry).read_text(encoding='utf-8-sig'))
            if not any(_main_guard(node) for node in tree.body):
                continue
            dependencies=build(project,targets=[entry])['files']
            if not plotting_paths.intersection(dependencies):
                continue
        except (OSError,UnicodeError,SyntaxError,ValueError):
            continue
        candidates.append({'entry_path':entry,'entry_symbol':None,'status':'candidate',
                           'runnable_evidence':'main_guard_with_plot_dependency',
                           'confidence':0.96,'capture_open_figures':True,
                           'output_sites':[],'plot_call_count':0})
    candidates.sort(key=lambda item: (-item['confidence'], item['entry_path'], item.get('entry_symbol') or ''))
    return {'schema': SCHEMA, 'candidates': candidates[:MAX_ENTRY_CANDIDATES],
            'diagnostics': [record for record in records if record.get('status') != 'candidate'],
            'truncated': len(candidates) > MAX_ENTRY_CANDIDATES}


def available(project):
    try:
        return bool(discover(project)['candidates'])
    except (OSError, ValueError):
        return False


def selection(project, entry, overrides=None):
    """Return the registered figure for a chart adapter without executing it."""
    project = Path(project)
    registry_path = project / 'universal-project.json'
    if not registry_path.is_file():
        return None
    registry = json.loads(registry_path.read_text(encoding='utf-8'))
    if registry.get('schema') != SCHEMA or registry.get('source_root') != 'lib/universal/source':
        raise ValueError('Unsupported universal registry')
    text = (overrides or {}).get(entry)
    if text is None:
        path = project / entry
        if not path.is_file():
            return None
        text = path.read_text(encoding='utf-8')
    tree = ast.parse(text)
    values = [node.value.value for node in tree.body if isinstance(node, ast.Assign)
              and any(isinstance(target, ast.Name) and target.id == 'UNIVERSAL_FIGURE' for target in node.targets)
              and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)]
    if len(values) != 1 or values[0] not in registry.get('figures', {}):
        raise ValueError('Universal chart must declare exactly one registered UNIVERSAL_FIGURE')
    record=registry['figures'][values[0]]
    prep.relative_path(record.get('entry_path'))
    for path in [*record.get('source_files',[]),*record.get('input_files',[])]:
        prep.relative_path(path)
    if type(record.get('output_index')) is not int or not 1<=record['output_index']<=MAX_OUTPUTS_PER_ENTRY:
        raise ValueError('Universal output index is invalid')
    return values[0]


def adapter_source(figure_id, drawing_code='', source_ref='', direct_inputs=()):
    return f'''"""Verified adapter for an original plotting output.

The original project snapshot is read-only.  Presentation edits belong in
customize(); exact source replacements apply only to a disposable runtime copy.
"""
from universal_plot_runtime import render_original
from interactive_style import apply_interactive_style

UNIVERSAL_FIGURE = {figure_id!r}
UNIVERSAL_SOURCE_EDITS = {{}}
FIGURE_SOURCE_REF = {source_ref!r}
FIGURE_DIRECT_INPUTS = {tuple(direct_inputs)!r}
FIGURE_DRAWING_CODE = {drawing_code!r}

# --- PLOT_FORGE_INTERACTIVE_STYLE_START ---
INTERACTIVE_STYLE = {{'border_width': 1.0, 'border_color': '#333333',
                     'legend_location': 'best', 'legend_names': {{}}}}
# --- PLOT_FORGE_INTERACTIVE_STYLE_END ---


def customize(figure):
    apply_interactive_style(figure, INTERACTIVE_STYLE)


render_original(UNIVERSAL_FIGURE, customize, UNIVERSAL_SOURCE_EDITS)
'''


def _drawing_code(staged, provenance):
    """Expose the exact figure-local source section without copying its analysis."""
    relative=provenance.get('source_path')
    line=provenance.get('line')
    path=staged/'lib/universal/source'/str(relative or '')
    if not relative or not isinstance(line,int) or not path.is_file():
        return '', str(relative or '')
    text=path.read_text(encoding='utf-8-sig')
    try:
        tree=ast.parse(text)
        nodes=[node for node in ast.walk(tree) if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef))
               and node.lineno<=line<=getattr(node,'end_lineno',node.lineno)]
        node=min(nodes,key=lambda item:getattr(item,'end_lineno',item.lineno)-item.lineno) if nodes else None
        snippet=ast.get_source_segment(text,node) if node else None
    except SyntaxError:
        snippet=None
    if not snippet:
        lines=text.splitlines();snippet='\n'.join(lines[max(0,line-31):min(len(lines),line+30)])
    return snippet[:20000], f'{relative}:{line}'


def _safe_id(entry, output_index, used):
    stem = re.sub(r'[^A-Za-z0-9_]+', '_', PurePosixPath(entry).stem).strip('_') or 'figure'
    base = f'{stem}_{output_index}'
    value, suffix = base, 2
    while value in used:
        value = f'{base}_{suffix}'
        suffix += 1
    used.add(value)
    return value


def _dependencies(project, entry):
    try:
        from analysis_scope import build
        return build(project, targets=[entry])['files']
    except (OSError, ValueError):
        return [entry]


def _report_signature(report):
    return hashlib.sha256(json.dumps({
        'artists': [(item.get('key'), item.get('data_hash'), item.get('visibility'), item.get('style'))
                    for item in report.get('artists', [])],
        'axes': report.get('axes'), 'render_size_px': report.get('render_size_px'),
        'layout_signature': report.get('layout_signature'),
    }, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _runtime_fingerprint():
    packages={distribution.metadata['Name']:distribution.version
              for distribution in importlib.metadata.distributions() if distribution.metadata.get('Name')}
    return {'python':sys.version,'executable':sys.executable,'os':sys.platform,'packages':packages,
            'platform':{name:prep.sha(prep.ROOT/name) for name in (
                'chat_runner.py','universal_plot_runtime.py','universal_project.py',
                'interactive_style.py','font_policy.py','chart_naming.py')},
            'layout_profile':prep.sha(prep.ROOT/'skills/chart-normalization/assets/style-profile.v1.json')}


def _cached_render(cache, key):
    """Trust cached bytes only when both content checks match the record."""
    record_path=cache/(key+'.json')
    image_path=cache/(key+'.png')
    try:
        if record_path.stat().st_size>6*1024**2 or image_path.stat().st_size>30*1024**2:
            return None
        record=json.loads(record_path.read_text(encoding='utf-8'))
        report=record['report']
        image=image_path.read_bytes()
        if (record.get('key')!=key or report.get('output_count')!=1
                or hashlib.sha256(image).hexdigest()!=record['image_sha256']
                or _report_signature(report)!=record['artist_signature']):
            return None
        return {**report,'image_bytes':image}
    except (OSError,ValueError,KeyError,TypeError):
        return None


def prepare(project, progress=None, previous_state=None):
    """Discover, adapt and reproduce every reachable output before installing."""
    from chat_runner import _one_render, CandidateRenderError, isolation_backend
    project = Path(project)
    previous = previous_state if previous_state is not None else prep.read_state(project)
    source = prep.source_root(project)
    discovery = discover(project)
    candidates = discovery['candidates']
    if not candidates:
        raise ValueError('未找到 Matplotlib/Seaborn 的 savefig 或 show 绘图入口')
    files = previous.get('files', [])
    total_bytes = sum(item.get('bytes', 0) for item in files if item.get('kind')=='code')
    if total_bytes > MAX_PROJECT_BYTES:
        raise ValueError(f'通用本机拆解源码超过 {MAX_PROJECT_BYTES//1024//1024} MiB；数据文件不计入此限制')

    with tempfile.TemporaryDirectory(prefix='plot-universal-prepare-') as temporary:
        work = Path(temporary)
        staged = work / 'project'
        for folder in ('charts', 'lib/universal/source', 'data', 'previews', 'validation'):
            (staged / folder).mkdir(parents=True, exist_ok=True)
        prep.write_json(staged / 'project.json', {'name': project.name, 'data_source_type': 'universal_plot', 'plot_forge_format': 1})
        stored = []
        for item in files:
            original = source / item['path']
            if original.is_symlink() or not original.resolve().is_relative_to(source.resolve()):
                raise ValueError('源码扫描后变成了外部链接：' + item['path'])
            target = staged / 'lib/universal/source' / item['path']
            target.parent.mkdir(parents=True, exist_ok=True)
            digest = prep.copy_and_sha(original, target)
            if item.get('sha256') and digest != item['sha256']:
                raise ValueError('本机备份与已记录源码不一致：' + item['path'])
            stored.append({'path': item['path'], 'stored': target.relative_to(staged).as_posix(), 'sha256': digest})

        registry = {'schema': SCHEMA, 'source_root': 'lib/universal/source', 'figures': {}}
        prep.write_json(staged / 'universal-project.json', registry)
        checks, figures, used_ids, seen_images = [], [], set(), {}
        cache=project/'.preparation/universal-cache'
        cache.mkdir(parents=True,exist_ok=True)
        runtime_fingerprint=_runtime_fingerprint()
        cache_hits=0
        candidate_total = len(candidates)
        for candidate_index, candidate in enumerate(candidates, 1):
            entry = candidate['entry_path']
            symbol = candidate.get('entry_symbol')
            candidate_identity=(entry,symbol)
            dependencies = _dependencies(project, entry)
            reached = 0
            for output_index in range(1, MAX_OUTPUTS_PER_ENTRY + 1):
                if progress:
                    progress(candidate_index, candidate_total, entry, output_index, len(figures))
                identity_entry=entry if not symbol else str(PurePosixPath(entry).with_suffix(''))+'_'+symbol
                figure_id = _safe_id(identity_entry, output_index, used_ids)
                registry['figures'][figure_id] = {
                    'entry_path': entry, 'output_index': output_index,
                    'entry_symbol':symbol,'capture_return':bool(candidate.get('capture_return')),
                    'entry_method':candidate.get('entry_method'),
                    'entry_kwargs':candidate.get('entry_kwargs',{}),
                    'capture_open_figures':bool(candidate.get('capture_open_figures')),
                    'source_files': dependencies,
                    'output_sites': candidate['output_sites'],
                }
                prep.write_json(staged / 'universal-project.json', registry)
                chart = staged / 'charts' / (figure_id + '.py')
                chart.write_text(adapter_source(figure_id), encoding='utf-8', newline='\n')
                try:
                    cache_key=hashlib.sha256(json.dumps([
                        stored,runtime_fingerprint,registry['figures'][figure_id],
                        chart.read_text(encoding='utf-8'),isolation_backend(),200
                    ],sort_keys=True).encode()).hexdigest()
                    first=_cached_render(cache,cache_key)
                    cache_hit=first is not None
                    if cache_hit:
                        cache_hits+=1
                    else:
                        first = _one_render(staged, 'charts/' + figure_id + '.py', {}, work / ('render_' + figure_id),
                                            strict_io=True, preview_dpi=200)
                    if first.get('output_count') != 1:
                        raise CandidateRenderError('适配入口必须只提交选中的一张图')
                    observed=first.get('input_trace',[])
                    registry['figures'][figure_id]['source_files']=sorted(set(dependencies) | {
                        path for path in observed if path.endswith('.py')})
                    registry['figures'][figure_id]['input_files']=sorted(
                        path for path in observed if not path.endswith('.py'))
                    drawing_code,source_ref=_drawing_code(staged,first.get('output_provenance',{}))
                    chart.write_text(adapter_source(figure_id,drawing_code,source_ref,
                        registry['figures'][figure_id]['input_files']),encoding='utf-8',newline='\n')
                    prep.write_json(staged / 'universal-project.json', registry)
                    image_hash = hashlib.sha256(first['image_bytes']).hexdigest()
                    if not cache_hit:
                        second = _one_render(staged, 'charts/' + figure_id + '.py', {}, work / ('repeat_' + figure_id),
                                             strict_io=True, preview_dpi=200)
                        if (second.get('output_count')!=1 or image_hash != hashlib.sha256(second['image_bytes']).hexdigest()
                                or _report_signature(first) != _report_signature(second)
                                or sorted(observed)!=sorted(second.get('input_trace',[]))):
                            raise CandidateRenderError('相同输入重复运行的图片、图元或读取依赖不一致，不能标记为可靠拆解')
                        image_path=cache/(cache_key+'.png')
                        image_path.write_bytes(first['image_bytes'])
                        prep.write_json(cache/(cache_key+'.json'),{
                            'key':cache_key,'image_sha256':image_hash,'artist_signature':_report_signature(first),
                            'report':{name:value for name,value in first.items() if name!='image_bytes'}})
                except CandidateRenderError as error:
                    registry['figures'].pop(figure_id, None)
                    chart.unlink(missing_ok=True)
                    used_ids.discard(figure_id)
                    text = str(error)
                    if output_index > 1 and ('was not reached' in text or 'Selected plotting output' in text):
                        break
                    checks.append({'entry_path': entry, 'output_index': output_index, 'render': 'failed',
                                   'reason': text, 'error_code': error.code})
                    break
                finally:
                    from preparation_cleanup import release_render_workspaces
                    for cleanup_error in release_render_workspaces(work,figure_id):
                        print('Render workspace cleanup: '+cleanup_error,flush=True)
                reached += 1
                provenance=first.get('output_provenance',{})
                output_site=(provenance.get('source_path'),provenance.get('line'),provenance.get('symbol'))
                dedup_key=(image_hash,_report_signature(first),*output_site)
                # Equal pixels alone do not establish equal figure identity.
                # Deduplicate wrapper/function aliases only with the same
                # actual save site and full artist signature.
                duplicate=seen_images.get(dedup_key) if output_site[0] else None
                if duplicate and duplicate['candidate_identity'] != candidate_identity:
                    registry['figures'].pop(figure_id, None)
                    chart.unlink(missing_ok=True)
                    used_ids.discard(figure_id)
                    checks.append({'entry_path': entry, 'output_index': output_index, 'render': 'duplicate',
                                   'duplicate_of': duplicate['figure_id']})
                    continue
                if output_site[0]:
                    seen_images.setdefault(dedup_key,{'figure_id':figure_id,'candidate_identity':candidate_identity})
                (staged / 'previews' / (figure_id + '.png')).write_bytes(first['image_bytes'])
                record = {'figure_id': figure_id, 'entry_path': 'charts/' + figure_id + '.py',
                          'original_entry': entry, 'output_index': output_index}
                figures.append(record)
                checks.append({**record, 'render': 'passed', 'output_count': 1,
                               'reproducible': True, 'image_sha256': image_hash,
                               'cache_hit':cache_hit,
                               'artist_signature': _report_signature(first),
                               'input_trace': observed,
                               'output_provenance':provenance,
                               'backend': first.get('render_backend', isolation_backend()),
                               'os_sandbox': bool(first.get('os_sandbox'))})
            if reached == MAX_OUTPUTS_PER_ENTRY:
                checks.append({'entry_path': entry, 'render': 'warning',
                               'reason': f'输出达到每入口 {MAX_OUTPUTS_PER_ENTRY} 张上限，可能仍有更多动态输出'})

        diagnostics={'schema':SCHEMA,'discovery':discovery,'checks':checks,
                     'cache_hits':cache_hits,'updated_at':time.time()}
        prep.write_json(project/'.preparation/universal-diagnostics.json',diagnostics)
        if not figures:
            reasons = [item['entry_path'] + '：' + item.get('reason', '未产生可验证输出') for item in checks if item.get('render') == 'failed']
            raise ValueError('找到绘图语句，但没有入口通过隔离复现。' + ('；'.join(reasons[:5]) if reasons else ''))
        prep.write_json(staged / 'universal-project.json', registry)
        incomplete=any(item.get('render') in ('failed','warning') for item in checks) or discovery['truncated']
        prep.write_json(staged / 'validation/universal.json', {
            'state': 'partial' if incomplete else 'passed', 'mode': 'universal', 'checks': checks,
            'coverage_complete':not incomplete,
            'source_files': stored,
            'basis': 'Original source snapshot executed through save/show interception; every installed output reproduced twice with identical image and artist signatures.',
        })
        prep.install_verified(project, staged, ('charts', 'lib', 'data', 'previews'), work / 'rollback')
        prep.write_json(project / 'universal-project.json', registry)
        prep.write_json(project / 'validation/universal.json', json.loads((staged / 'validation/universal.json').read_text(encoding='utf-8')))
        from panel_index import build as build_panel_index
        for figure in figures:
            build_panel_index(project, figure['figure_id'])
        metadata = json.loads((project / 'project.json').read_text(encoding='utf-8'))
        prep.write_json(project / 'project.json', {**metadata, 'data_source_type': 'universal_plot',
                        'plot_forge_format': 1,
                        'description': f'通用本机拆解：{len(figures)} 张已验证绘图输出'})
        warnings = [item['entry_path'] + '：' + item.get('reason', '') for item in checks if item.get('render') in ('failed', 'warning')]
        prep.save_state(project, {**previous, 'status': 'ready', 'mode': 'universal',
            'reason': f'通用拆解完成：发现 {len(candidates)} 个候选入口，安装 {len(figures)} 张可重复验证的图。'
                      +(f'复用 {cache_hits} 张已验证缓存。' if cache_hits else ''),
            'task_outcome': {'status': 'success', 'label': '部分完成：已验证图可改图，未完成入口见详情' if incomplete else '成功：通用本机拆解与验证完成'},
            'figures': figures, 'generated_files': [], 'warnings': warnings,
            'universal_progress': {'completed': len(candidates), 'total': len(candidates), 'figures': len(figures),'cache_hits':cache_hits},
            'validation': {'state': 'partial' if incomplete else 'passed', 'checks': checks,
                           'coverage_complete':not incomplete}, 'updated_at': time.time()})
    return prep.status(project)


def start(project, consent):
    if not consent:
        raise ValueError('请先确认允许在隔离临时副本中运行原绘图入口')
    project = Path(project)
    with prep.LOCK:
        if str(project) in prep.RUNNING:
            raise ValueError('工程正在准备中')
        previous = prep.read_state(project)
        if prep.can_open(project):
            return prep.status(project)
        if any((project / 'charts').glob('*.py')):
            raise ValueError('工程已有绘图代码，请另建副本以避免覆盖修改')
        discovery = discover(project)
        if not discovery['candidates']:
            raise ValueError('未发现通用 Python 绘图入口；可继续使用模型分批提取后备流程')
        prep.RUNNING.add(str(project))
        started = time.time()

        def progress(index, total, entry, output_index, figures):
            prep.save_state(project, {**previous, 'status': 'working', 'mode': 'universal',
                'reason': f'通用本机拆解：入口 {index}/{total} · {entry} · 检查输出 {output_index}；已验证 {figures} 张。',
                'task_outcome': None,
                'universal_progress': {'completed': index - 1, 'total': total, 'current': entry,
                                       'output_index': output_index, 'figures': figures, 'started_at': started},
                'updated_at': time.time()})

        progress(1, len(discovery['candidates']), discovery['candidates'][0]['entry_path'], 1, 0)

        def work():
            try:
                prepare(project, progress=progress, previous_state=previous)
            except Exception as error:
                current = prep.read_state(project).get('universal_progress', {})
                diagnostics_path=project/'.preparation/universal-diagnostics.json'
                try:diagnostics=json.loads(diagnostics_path.read_text(encoding='utf-8'))
                except (OSError,ValueError):diagnostics={}
                prep.save_state(project, {**previous, 'status': 'needs_context', 'mode': 'universal',
                    'reason': '通用本机拆解未能生成可验证图：' + str(error)[:2500],
                    'universal_progress': current,
                    'validation': {'state': 'failed','checks':diagnostics.get('checks',[])},
                    'task_outcome': {'status': 'failed', 'label': '失败：通用拆解未通过验证'},
                    'updated_at': time.time()})
            finally:
                with prep.LOCK:
                    prep.RUNNING.discard(str(project))
        threading.Thread(target=work, daemon=True).start()
        return prep.status(project)
