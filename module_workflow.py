"""Validate shared-module candidates without applying them before human review."""
import ast
import difflib
import hashlib
import json
from pathlib import Path
import uuid

from shared_modules import apply_module, resolve_module, MAX_SHARED_MODULE_SOURCE


def input_revision(host, project):
    """Shared edits depend on every chart entry, not just library/data files."""
    project=Path(project)
    entries=[(path.relative_to(project).as_posix(),hashlib.sha256(path.read_bytes()).hexdigest())
             for path in sorted((project/'charts').rglob('*.py')) if '__pycache__' not in path.parts]
    metadata=hashlib.sha256((project/'project.json').read_bytes()).hexdigest()
    return hashlib.sha256(json.dumps([host.preview_signature(project,'shared-module-inputs'),entries,metadata],sort_keys=True).encode()).hexdigest()


def changed_locations(original, source):
    edits = [op for op in difflib.SequenceMatcher(None, original.splitlines(), source.splitlines()).get_opcodes() if op[0] != 'equal']
    locations = set()
    try:
        trees = [ast.parse(original), ast.parse(source)]
    except SyntaxError:
        return len(edits)
    for index, tree in enumerate(trees):
        regions = []
        def collect(nodes, prefix=()):
            for node in nodes:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    regions.append((node.lineno, node.end_lineno, ('definition', prefix+(node.name,))))
                elif isinstance(node, ast.ClassDef):
                    regions.append((node.lineno, node.lineno, ('class', prefix+(node.name,))))
                    collect(node.body, prefix+(node.name,))
                else:
                    names=tuple(sorted(item.id for item in ast.walk(node) if isinstance(item,ast.Name) and isinstance(item.ctx,ast.Store)))
                    regions.append((node.lineno,node.end_lineno,('module',prefix,names or (type(node).__name__,))))
        collect(tree.body)
        for op in edits:
            start, end = op[1:3] if index == 0 else op[3:5]
            matches=[key for first,last,key in regions if first <= end and last >= start+1]
            locations.update(matches)
            if end > start and not matches:
                locations.add(('text',start))
    return len(locations) or len(edits)


def draft_path(project, module_id, draft_id):
    resolve_module(project, module_id)
    if len(draft_id) != 32 or any(c not in '0123456789abcdef' for c in draft_id):
        raise ValueError('候选 ID 无效')
    return Path(project) / '.module-drafts' / module_id / draft_id


def preview(host, project_id, module_id, source, chart, force_all=False):
    import shutil
    from chat_runner import render_candidate
    project, entry = host.chart_path(project_id, chart)
    module = resolve_module(project, module_id)
    if not isinstance(source, str) or len(source) > MAX_SHARED_MODULE_SOURCE:
        raise ValueError('共享模块源码无效或超过 500 KB')
    ast.parse(source)
    original = module.read_text(encoding='utf-8')
    locations = changed_locations(original, source)
    scope = 'all' if force_all or locations > 1 else 'representative'
    excluded = set(json.loads((project / 'project.json').read_text(encoding='utf-8')).get('non_chart_scripts', []))
    charts = [p for p in sorted((project / 'charts').glob('*.py')) if p.stem not in excluded]
    selected = charts if scope == 'all' else [entry]
    baseline = input_revision(host, project)
    ident = uuid.uuid4().hex
    folder = draft_path(project, module_id, ident)
    folder.mkdir(parents=True)
    try:
        checks=[]
        for entry in selected:
            try:
                report=render_candidate(project,entry.relative_to(project).as_posix(),{},folder/'checks'/entry.stem,
                                        shared_files={module.relative_to(project).as_posix():source})
            except Exception as error:
                raise ValueError(entry.stem + ' 验证失败：' + str(error)) from error
            shutil.copyfile(report['image_path'],folder/(entry.stem+'.png'))
            data=report['data_report']
            checks.append({'chart':entry.stem,'data_status':data['status'],
                'changed':len(data.get('changed',[])),'removed':len(data.get('removed',[])),
                'added':len(data.get('added',[])), 'visibility_changes':len(data.get('visibility_changes',[])),
                'axes_changes':len(data.get('axes_changes',[])),
                'layout_status':report['layout']['status'],'layout_issues':report['layout'].get('issues',[]),
                'warnings':report.get('warnings',[])})
        if input_revision(host, project) != baseline:
            raise ValueError('验证期间项目代码或数据发生变化，请重新生成候选')
        draft = {'id': ident, 'source': source, 'original_source': original, 'baseline': baseline, 'validation_scope': scope,
                 'changed_locations': locations, 'charts': [p.stem for p in selected],
                 'affected_charts': [p.stem for p in charts], 'applied': False,
                 'checks':checks, 'requires_data_review':any(c['changed'] or c['removed'] or c['added'] or c['visibility_changes'] or c['axes_changes'] for c in checks),
                 'limitations': '已比较所列图表的实际数据图元和布局；共享模块没有完整语义证明，数据/映射变化需单独审阅。保守影响范围为全部项目图表。'}
        (folder / 'draft.json').write_text(json.dumps(draft, ensure_ascii=False), encoding='utf-8')
        return draft
    except Exception:
        shutil.rmtree(folder)
        raise


def apply(host, project_id, module_id, draft_id, acknowledge_data_changes=False):
    from chat_harness import lock
    with lock(host.project_path(project_id)):
        return _apply_locked(host,project_id,module_id,draft_id,acknowledge_data_changes)


def _apply_locked(host, project_id, module_id, draft_id, acknowledge_data_changes):
    project = host.project_path(project_id)
    folder = draft_path(project, module_id, draft_id)
    draft = json.loads((folder / 'draft.json').read_text(encoding='utf-8'))
    if draft['applied']:
        raise ValueError('此候选已应用')
    if draft.get('requires_data_review') and acknowledge_data_changes is not True:
        raise ValueError('共享候选包含数据、图元或显示映射变化，请核对逐图报告后明确确认，尚未应用。')
    if input_revision(host, project) != draft['baseline']:
        raise ValueError('候选生成后正式代码或数据已变化，请重新验证，未覆盖任何文件')
    chart = draft['charts'][0]
    result = apply_module(project, module_id, draft['source'], chart,
                          lambda *args: (folder / (chart + '.png')).read_bytes(),
                          '应用人工确认的共享模块候选 ' + draft_id[:8],
                          expected_source=draft['original_source'], author=host.SYNC.config().get('name','本地协作者'))
    draft['applied'] = True
    (folder / 'draft.json').write_text(json.dumps(draft, ensure_ascii=False), encoding='utf-8')
    host.forget_module_previews(project)
    return {'applied': True, 'revision': result.get('revision'), 'validated_charts': draft['charts']}
