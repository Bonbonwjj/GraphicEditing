"""Machine-local Bundle locations, kept out of shared Git and model prompts."""
import hashlib
import json
import os
from pathlib import Path


def resolve_source(project, source):
    project = Path(os.environ.get('CHART_BUNDLE_SOURCE_PROJECT') or project)
    location = source.get('location', '')
    if location.startswith('binding:'):
        file = project / '.bundle-bindings.json'
        bindings = json.loads(file.read_text(encoding='utf-8')) if file.exists() else {}
        location = bindings.get(source['id'], '')
        if not location:
            raise ValueError('此电脑尚未绑定 Bundle，请在“导入 Bundle / 绑定路径”中选择本机共享目录')
    if not location:
        raise ValueError('Bundle 来源路径未配置')
    path = Path(location)
    return (path if path.is_absolute() else project / path).resolve(strict=True)


def make_portable(project, share_mode):
    if share_mode not in {'reference', 'embedded'}:
        raise ValueError('请选择 Bundle 共享方式')
    project = Path(project)
    file = project / 'data_sources.json'
    value = json.loads(file.read_text(encoding='utf-8'))
    bindings = {}
    for source in value.get('sources', []):
        if source.get('kind') != 'plot_bundle':
            continue
        location = Path(source['location']).resolve()
        if share_mode == 'embedded':
            try:
                source['location'] = location.relative_to(project.resolve()).as_posix()
            except ValueError as exc:
                raise ValueError('内嵌共享需要浏览器上传 Bundle；共享目录请使用外部引用') from exc
        else:
            bindings[source['id']] = str(location)
            source['location'] = 'binding:' + source['id']
        source.setdefault('metadata', {}).pop('uploaded_from', None)
        if share_mode == 'embedded':
            (project / source['location'] / '.gitattributes').write_text('** -text\n', encoding='utf-8', newline='\n')
    file.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8', newline='\n')
    if bindings:
        (project / '.bundle-bindings.json').write_text(json.dumps(bindings, ensure_ascii=False), encoding='utf-8')


def signature(project):
    """Invalidate previews/drafts on source index or payload stat changes, without loading pickle."""
    project = Path(project)
    file = project / 'data_sources.json'
    if not file.is_file():
        return None
    value = json.loads(file.read_text(encoding='utf-8'))
    records = []
    for source in value.get('sources', []):
        if source.get('kind') != 'plot_bundle':
            continue
        root = resolve_source(project, source)
        manifest_file = root / 'manifest.json'
        raw = manifest_file.read_bytes()
        manifest = json.loads(raw)
        records.append([source['id'], hashlib.sha256(raw).hexdigest()])
        for entry in [manifest['plot_specs'], *manifest['payloads'].values()]:
            path = (root / entry['path']).resolve()
            if not path.is_relative_to(root):
                raise ValueError('Bundle 路径越界')
            stat = path.stat()
            records.append([entry['path'], stat.st_size, stat.st_mtime_ns])
    return hashlib.sha256(json.dumps(records, sort_keys=True).encode()).hexdigest() if records else None
