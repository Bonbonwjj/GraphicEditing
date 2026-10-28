"""Delete only a named workspace copy; never follow a source directory."""
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat

import project_preparation as prep
from chat_harness import lock


def validate_tree(project):
    def check(path):
        attributes = getattr(path.lstat(), 'st_file_attributes', 0)
        if path.is_symlink() or attributes & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0):
            raise ValueError('工程副本包含符号链接或重解析目录，已停止删除；请先检查路径')
        if path.is_mount():
            raise ValueError('工程副本包含挂载目录，已停止删除')
    def fail(error):
        raise error
    check(project)
    # Inspect directory entries before descending, including Windows junctions.
    # Do not scan the contents of an external mount just to decide it is unsafe.
    for directory, dirs, files in os.walk(project, followlinks=False, onerror=fail):
        for name in dirs + files:
            check(Path(directory) / name)


def deletion_info(projects, name):
    projects = Path(projects).absolute()
    # A redirected workspace or project is not an acceptable deletion target.
    if projects.resolve() != projects or projects.is_symlink():
        raise ValueError('工作区路径包含符号链接，已停止删除')
    project = prep.project_path(projects, name)
    if project.resolve().parent != projects:
        raise ValueError('只能删除工作区内的独立工程副本')
    validate_tree(project)
    sources = []
    for other in projects.iterdir():
        if other.name.startswith('.') or not (other / 'project.json').is_file():
            continue
        metadata = json.loads((other / 'project.json').read_text(encoding='utf-8'))
        state = prep.read_state(other)
        for value in (state.get('source_path'), metadata.get('source_root')):
            if not value:
                continue
            source = Path(value).expanduser()
            if not source.is_absolute():
                raise ValueError('工程来源路径不明确，已停止删除')
            source = source.resolve()
            if source == project or source.is_relative_to(project) or project.is_relative_to(source):
                raise ValueError('该副本与已登记的原始工程目录重叠，不能删除')
            if other == project:
                sources.append(str(source))
    stat = project.stat()
    identity = [str(project), stat.st_dev, stat.st_ino, stat.st_ctime_ns, sorted(set(sources))]
    token = hashlib.sha256(json.dumps(identity).encode()).hexdigest()
    return {'project': name, 'local_path': str(project), 'source_paths': sorted(set(sources)),
            'confirmation_token': token,
            'scope': '仅删除此工作副本内的拆分代码、复制数据、源文件备份、预览及修改历史；不访问或删除原始目录。'}


def delete_project(projects, name, confirmation, token, preview_lock=None):
    if confirmation != name or not isinstance(token, str) or not token:
        raise ValueError('请确认删除范围，并输入完整工程名称')
    with prep.LOCK, ExitStack() as guards:
        project = prep.project_path(Path(projects).absolute(), name)
        if str(project) in prep.RUNNING:
            raise ValueError('工程正在准备或验证，请完成后再删除')
        # Match chat's session -> project lock ordering. Do not wait and delete
        # silently after a long model request: ask the user to retry instead.
        keys = sorted((project / '.chat/sessions').glob('*/session.json'))
        locks = [lock(path) for path in keys] + [lock(project), lock(project / '.chat')]
        if preview_lock:
            locks += [preview_lock(project, path.stem) for path in sorted((project / 'charts').glob('*.py'))]
        for guard in locks:
            if not guard.acquire(blocking=False):
                raise ValueError('工程正在改图或渲染，请完成后再删除')
            guards.callback(guard.release)
        info = deletion_info(projects, name)
        if token != info['confirmation_token']:
            raise ValueError('工程目录已变化，请重新查看删除范围并确认')
        # Keep privacy registration / gitignore entries: reusing this name must
        # not accidentally publish research files. Never traverse source_paths.
        shutil.rmtree(project)
        return {'deleted': True, 'project': name, 'deleted_path': info['local_path'],
                'source_paths': info['source_paths'], 'originals_preserved': True}
