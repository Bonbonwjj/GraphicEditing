"""Three-way project synchronization through a separate Git checkout.

The application checkout and private drafts/credentials are never staged.
Git authentication is supplied by the user's existing credential helper or SSH.
"""
import hashlib
import json
import re
import shutil
import subprocess
import threading
from pathlib import Path
from project_storage import from_shared, to_shared


class SyncConflict(ValueError):
    def __init__(self, paths):
        self.paths = sorted(paths)
        super().__init__('双方都修改了以下文件；请先解决冲突：' + ', '.join(self.paths))


class CollaborationSync:
    def __init__(self, root):
        self.root = Path(root)
        self.folder = self.root / '.collaboration'
        self.checkout = self.folder / 'repository'
        self.config_file = self.folder / 'config.json'
        self.state_file = self.folder / 'baseline.json'
        self.lock = threading.RLock()

    def git(self, *args, cwd=None):
        import os
        if not shutil.which("git"):
            raise ValueError("请先安装 Git，并完成 GitHub Git 登录或 SSH 配置")
        env = os.environ.copy()
        env['GIT_TERMINAL_PROMPT'] = '0'
        result = subprocess.run(['git', *args], cwd=cwd or self.checkout, env=env,
                                capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=90)
        if result.returncode:
            raise ValueError('Git 操作失败：' + result.stderr[-1800:])
        return result.stdout.strip()

    def config(self):
        return json.loads(self.config_file.read_text(encoding='utf-8')) if self.config_file.exists() else {}

    def team_target(self):
        path = self.root / 'team_collaboration.json'
        return json.loads(path.read_text(encoding='utf-8')) if path.exists() else None

    def status(self):
        config = self.config()
        target = self.team_target()
        matches = target is None or all(config.get(k) == target.get(k) for k in ('remote', 'branch'))
        return {**config, **(target or {}), 'target_fixed': target is not None,
                'target_ready': target is None or bool(target.get('remote') and target.get('branch')),
                'configured': bool(config) and matches,
                'projects': sorted(p.name for p in (self.root / 'projects').iterdir() if (p / 'project.json').is_file())}

    def configure(self, body, *, reader=False):
        with self.lock:
            target = self.team_target()
            if target is not None:
                if not target.get('remote') or not target.get('branch'):
                    raise ValueError('团队同步分支尚未由平台维护者设置')
                if any(k in body and body[k] != target[k] for k in ('remote', 'branch')):
                    raise ValueError('团队同步位置由平台固定，不能从个人页面更改')
                body = {**body, **target}
            remote = str(body.get('remote', '')).strip()
            # No credentials in stored URLs, custom hosts, Git options or file transports.
            if not re.fullmatch(r'(?:https://github\.com/|git@github\.com:)[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?', remote):
                raise ValueError('请输入不含密钥的 GitHub HTTPS 或 SSH 仓库地址')
            branch = str(body.get('branch', 'main')).strip()
            if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_./-]*', branch) or '..' in branch or branch.endswith(('/', '.')):
                raise ValueError('分支名称无效')
            name = str(body.get('name', '')).strip()
            email = str(body.get('email', '')).strip()
            if not reader and (not name or len(name) > 100 or not re.fullmatch(r'[^\s<>@]+@[^\s<>@]+', email)):
                raise ValueError('请填写协作者姓名和 Git 提交邮箱')
            old = self.config()
            if old and (old['remote'], old['branch']) != (remote, branch):
                raise ValueError('此工作区已连接其他仓库/分支；请另建本地工作区，避免混入项目')
            self.folder.mkdir(exist_ok=True)
            if not self.checkout.exists():
                self.git('-c', 'core.autocrlf=false', 'clone', '--single-branch', '--branch', branch, '--', remote, str(self.checkout), cwd=self.root)
            if name and email:
                self.git('config', 'user.name', name)
                self.git('config', 'user.email', email)
            config = {'remote': remote, 'branch': branch, 'name': name, 'email': email}
            self.config_file.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
            return self.status()

    @staticmethod
    def files(root):
        result = {}
        root = Path(root)
        if not root.exists():
            return result
        if root.is_symlink():
            raise ValueError('共享项目目录不能是符号链接')
        references = set()
        from private_projects import names
        private = names(root.parent)
        for metadata in [*root.glob('*/data_sources.json'), *root.glob('*/code/data_sources.json')]:
            value=json.loads(metadata.read_text(encoding='utf-8'))
            if any(item.get('kind')=='plot_bundle' and str(item.get('location','')).startswith('binding:') for item in value.get('sources',[])):
                references.add(metadata.parent.parent.name if metadata.parent.name == 'code' else metadata.parent.name)
        for path in root.rglob('*'):
            relative = path.relative_to(root)
            if relative.parts and relative.parts[0] in private:
                continue
            if relative.parts and relative.parts[0] in references and relative.parts[1:3] == ('data','bundle'):
                continue
            if any((part.startswith('.') and part != '.gitattributes') or part == '__pycache__' for part in relative.parts):
                continue
            if path.is_symlink():
                raise ValueError('共享项目不接受符号链接：' + str(relative))
            if path.is_file():
                if any(':' in part or '\\' in part for part in relative.parts):
                    raise ValueError('文件名不兼容 Windows：' + str(relative))
                data = path.read_bytes()
                if relative.parts[1:3] != ('data', 'bundle') and path.suffix.lower() in {'.py', '.csv', '.tsv', '.json', '.md', '.svg'}:
                    data = data.replace(b'\r\n', b'\n')
                if len(data) > 95 * 1024 * 1024:
                    raise ValueError('单文件超过 95 MiB，请使用较小的绘图数据文件：' + str(relative))
                result[relative.as_posix()] = data
                if sum(map(len, result.values())) > 2 * 1024 * 1024 * 1024:
                    raise ValueError('共享绘图项目总大小超过 2 GiB')
        return result

    @staticmethod
    def hashes(files):
        return {path: hashlib.sha256(data).hexdigest() for path, data in files.items()}

    @staticmethod
    def merge(base, local, remote):
        lh, rh = CollaborationSync.hashes(local), CollaborationSync.hashes(remote)
        conflicts = [p for p in base.keys() | lh.keys() | rh.keys()
                     if lh.get(p) != base.get(p) and rh.get(p) != base.get(p) and lh.get(p) != rh.get(p)]
        if conflicts:
            raise SyncConflict(conflicts)
        result = dict(local)
        for path in base.keys() | rh.keys():
            if rh.get(path) != base.get(path):
                if path in remote:
                    result[path] = remote[path]
                else:
                    result.pop(path, None)
        return result

    @staticmethod
    def write_files(root, old, new):
        root = Path(root)
        for path in old.keys() - new.keys():
            (root / path).unlink(missing_ok=True)
        for path, data in new.items():
            target = root / path
            if target.is_symlink() or any(p.is_symlink() for p in target.parents):
                raise ValueError('写入目标不能经过符号链接')
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name('.' + target.name + '.sync-tmp')
            temporary.write_bytes(data)
            temporary.replace(target)

    def refresh(self):
        config = self.config()
        target = self.team_target()
        if not config and target is not None:
            self.configure({}, reader=True)
            config = self.config()
        if target is not None and any(config.get(k) != target.get(k) for k in ('remote', 'branch')):
            raise ValueError('请先保存协作者身份，连接平台固定的团队同步位置')
        if not config:
            raise ValueError('请先连接共享 GitHub 仓库')
        if self.git('status', '--porcelain'):
            raise ValueError('同步检出目录有未提交更改，请保留现场并检查 .collaboration/repository')
        self.git('fetch', 'origin', config['branch'])
        self.git('merge', '--ff-only', 'FETCH_HEAD')
        return config

    def sync(self, publish=False, message=''):
        with self.lock:
            if publish and not (self.config().get('name') and self.config().get('email')):
                raise ValueError('提交修改前请在团队协作中保存姓名和 Git 提交邮箱')
            config = self.refresh()
            local_root, remote_root = self.root / 'projects', self.checkout / 'projects'
            local_raw, remote_raw = self.files(local_root), self.files(remote_root)
            local, remote = from_shared(local_raw), from_shared(remote_raw)
            base = json.loads(self.state_file.read_text(encoding='utf-8')) if self.state_file.exists() else {}
            from private_projects import names
            private = names(self.root)
            collisions = sorted(p for p in set(remote) | set(base) if p.split('/')[0] in private)
            if collisions:
                raise SyncConflict(collisions)
            merged = self.merge(base, local, remote)  # Detect every conflict before changing local files.
            if publish:
                if not str(message).strip():
                    raise ValueError('请填写本次修改说明')
                self.write_files(remote_root, remote_raw, to_shared(merged))
                ignored = self.git('ls-files', '--others', '--ignored', '--exclude-standard', '--', 'projects')
                if ignored:
                    raise ValueError('Git 忽略规则阻止发布以下项目文件，请检查共享仓库 .gitignore 或本机 Git ignore：' + ignored[:1200])
                self.git('add', '-A', '--', 'projects')
                if self.git('diff', '--cached', '--name-only'):
                    self.git('commit', '-m', str(message).strip()[:500])
                try:
                    self.git('push', 'origin', 'HEAD:refs/heads/' + config['branch'])
                except ValueError as exc:
                    raise ValueError('发布未成功，已保留本地提交。若远端有新提交，请先协调或在同步检出目录解决分歧。' + str(exc)) from exc
                remote = merged
            if self.hashes(self.files(local_root)) != self.hashes(local_raw):
                raise ValueError('同步期间本机文件被其他程序修改，已保留本机文件。若发布已完成，请重新拉取并检查版本。')
            self.write_files(local_root, local_raw, merged)
            self.state_file.write_text(json.dumps(self.hashes(remote), indent=2), encoding='utf-8')
            return {'published': publish, 'files': len(merged), 'revision': self.git('rev-parse', 'HEAD'),
                    'author': config['name'], 'local_changes': sum(self.hashes(merged).get(p) != self.hashes(remote).get(p) for p in merged.keys() | remote.keys())}
