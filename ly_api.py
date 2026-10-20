"""Bundle import and optional local path binding endpoints."""
import json
import os
from pathlib import Path
import sys


def settings(root):
    file = root / '.data-sources-local.json'
    return json.loads(file.read_text(encoding='utf-8')) if file.exists() else {}


def handle_data_sources(handler, path):
    host = sys.modules[handler.__class__.__module__]
    from bundle_importer import PlotBundleAdapter, import_plot_bundle, _sha256
    from bundle_bindings import make_portable
    from data_sources import resolve_allowed_path
    local = settings(host.ROOT)
    roots = [*host.shared_roots_from_env(), *[Path(item) for item in local.get('shared_roots', [])]]
    if path.endswith('/capabilities') and handler.command == 'GET':
        return handler.json_response({'types': ['tabular', 'plot_bundle'], 'modes': ['upload', 'server_path'],
            'shared_roots': list(map(str, roots)), 'max_upload_bytes': 500_000_000,
            'plot_bundle_trusted_only': True, 'runtime_source': local.get('runtime_source', '')})
    if handler.command != 'POST':
        return handler.json_response({'error': 'Not found'}, 404)
    upload = path.endswith('/import-upload')
    if upload:
        form = handler.body_multipart()
        body = {key: form.getfirst(key, '') for key in ('project_id', 'name', 'trusted', 'share_mode')}
        body['trusted'] = str(body['trusted']).lower() == 'true'
        source = host.store_bundle_multipart(host.ROOT, body['project_id'], form)
    else:
        handler.check_local_json()
        body = handler.body_json()
    if path.endswith('/settings'):
        shared = [str(Path(item).resolve(strict=True)) for item in body.get('shared_roots', []) if str(item).strip()]
        if any(not Path(item).is_dir() for item in shared):
            raise ValueError('共享根目录必须是本机已存在的目录')
        runtime = str(body.get('runtime_source', '')).strip()
        if runtime and not (Path(runtime) / 'behavior_analysis').is_dir():
            raise ValueError('运行时代码路径应包含 behavior_analysis 目录')
        (host.ROOT / '.data-sources-local.json').write_text(json.dumps({'shared_roots': shared, 'runtime_source': runtime}), encoding='utf-8')
        return handler.json_response({'saved': True})
    if not upload:
        source = resolve_allowed_path(Path(body.get('source_path', '')), roots)
    if body.get('trusted') is not True:
        raise ValueError('Bundle 包含 pickle，请先确认来源可信')
    if path.endswith('/inspect'):
        return handler.json_response(PlotBundleAdapter().inspect(source, mode='server_path', trusted=True).as_dict())
    if path.endswith('/bind'):
        project = host.project_path(body.get('project_id'))
        sources = host.project_data_sources(project)
        record = next((s for s in sources if s.get('id') == body.get('source_id')), None)
        descriptor = PlotBundleAdapter().inspect(source, mode='server_path', trusted=True)
        if not record or descriptor.source_id != record['id']:
            raise ValueError('该目录不是项目登记的同一份 Bundle，未绑定')
        file = project / '.bundle-bindings.json'
        bindings = json.loads(file.read_text(encoding='utf-8')) if file.exists() else {}
        bindings[record['id']] = str(source)
        file.write_text(json.dumps(bindings), encoding='utf-8')
        from local_execution import revoke_all
        revoke_all()
        return handler.json_response({'bound': True})
    if path not in ('/api/data-sources/import', '/api/data-sources/import-upload'):
        return handler.json_response({'error': 'Not found'}, 404)
    share = body.get('share_mode')
    if share not in {'embedded', 'reference'}:
        raise ValueError('请选择数据随 GitHub 项目共享，或仅保留本机引用')
    if not upload and share == 'embedded':
        # Copy source into the project, so GitHub collaborators get the data as well.
        mode = 'upload'
    else:
        mode = 'upload' if upload else 'server_path'
    runtime = local.get('runtime_source') or os.environ.get('BEHAVIOR_ANALYSIS_CODE_ROOT')
    if not runtime:
        raise ValueError('请先设置 behavior_analysis 绘图运行时代码目录')
    result = import_plot_bundle(host.ROOT, source, project_id=body['project_id'], name=body.get('name', ''),
                                mode=mode, trusted=True, runtime_source=Path(runtime))
    project = host.PROJECTS / result['project']
    make_portable(project, share)
    metadata_file = project / 'project.json'
    metadata = json.loads(metadata_file.read_text(encoding='utf-8'))
    metadata['created_by'] = host.SYNC.config().get('name', '本地协作者')
    metadata_file.write_text(json.dumps(metadata, ensure_ascii=False), encoding='utf-8')
    result['data_source'] = host.project_data_sources(project)[0]
    result['github_synced'] = False
    return handler.json_response(result)


def handle_modules(handler, parts, parsed):
    host = sys.modules[handler.__class__.__module__]
    from shared_modules import resolve_module, module_revision_source
    import module_workflow
    from urllib.parse import parse_qs
    project_id, module_id, action = parts[2], parts[4], parts[5]
    project = host.project_path(project_id)
    module = resolve_module(project, module_id)
    if action == 'drafts' and len(parts) == 9 and parts[7] == 'image' and handler.command == 'GET':
        folder = module_workflow.draft_path(project, module_id, parts[6])
        draft = json.loads((folder/'draft.json').read_text(encoding='utf-8'))
        if parts[8] not in draft['charts']:
            raise ValueError('此图不属于该候选')
        return handler.bytes_response((folder/(parts[8]+'.png')).read_bytes(), 'image/png')
    if action == 'detail' and handler.command == 'GET':
        return handler.json_response(host.shared_module_detail(project, module_id))
    if handler.command != 'POST':
        return handler.json_response({'error': 'Not found'}, 404)
    handler.check_local_json()
    body = handler.body_json()
    if action == 'propose':
        prompt = str(body.get('prompt','')).strip()
        if not prompt or len(prompt)>5000:
            raise ValueError('请输入不超过 5000 字符的修改要求')
        source = body.get('source', module.read_text(encoding='utf-8'))
        if not isinstance(source,str) or len(source)>host.MAX_SHARED_MODULE_SOURCE:
            raise ValueError('共享模块源码过大')
        code=host.llm_proposal(prompt,source,[],resource_type='module',module_path=str(module.relative_to((project/'lib').resolve())),chart=body.get('chart'))
        return handler.json_response({'code':code,'reply':'建议已填入编辑器，尚未保存；请生成候选并检查图片。'})
    if action in ('preview','restore-preview'):
        source = module_revision_source(project,module_id,body.get('revision')) if action=='restore-preview' else body.get('source')
        draft=module_workflow.preview(host,project_id,module_id,source,body.get('chart'),body.get('force_all') is True)
        return handler.json_response(draft)
    if action == 'apply':
        if body.get('acknowledge') is not True:
            raise ValueError('请先检查候选图片并明确确认应用')
        return handler.json_response(module_workflow.apply(host,project_id,module_id,body.get('draft_id',''),body.get('acknowledge_data_changes') is True))
    return handler.json_response({'error':'Not found'},404)
