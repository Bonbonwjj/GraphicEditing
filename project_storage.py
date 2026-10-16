"""Canonical GitHub project layout, independent of legacy renderer paths.

Shared projects have exactly two top-level groups: data/ and code/. The renderer
continues to use logical charts/lib paths, so existing Python imports and reviewed
draft revisions do not change solely because the repository layout changed.
"""
from pathlib import PurePosixPath


def _insert(result, path, content):
    if path in result and result[path] != content:
        raise ValueError('项目新旧目录中存在不同内容，请先决定保留哪个版本：' + path)
    result[path] = content


def from_shared(files):
    canonical = {PurePosixPath(path).parts[0] for path in files
                 if len(PurePosixPath(path).parts) == 3
                 and PurePosixPath(path).parts[1:] == ('code', 'project.json')}
    result = {}
    for path, content in files.items():
        parts = PurePosixPath(path).parts
        if len(parts) < 2 or any(part in ('..', '.') for part in parts) or path.startswith('/'):
            raise ValueError('无效的共享项目路径：' + path)
        if parts[0] in canonical and parts[1] == 'code':
            path = '/'.join((parts[0], *parts[2:]))
        _insert(result, path, content)
    return result


def to_shared(files):
    result = {}
    for path, content in from_shared(files).items():
        project, relative = path.split('/', 1)
        shared = path if relative.startswith('data/') else project + '/code/' + relative
        _insert(result, shared, content)
    return result
