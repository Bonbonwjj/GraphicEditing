"""Explicit project upload/download through a shared directory, with conflicts."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import socket
import uuid


class SharedFolderSync:
    def __init__(self,root,target):
        self.root=Path(root)
        self.target=target
        self.shared=Path(target['path'])
        self.local=self.root/'.collaboration'
        identity=hashlib.sha256(str(self.shared).encode()).hexdigest()[:16]
        self.config_file=self.local/'folder-config.json'
        self.baseline_file=self.local/f'folder-baseline-{identity}.json'

    def config(self):
        return json.loads(self.config_file.read_text(encoding='utf-8')) if self.config_file.is_file() else {}

    def projects(self):
        return self.config().get('shared_projects',self.target.get('projects',[]))

    def status(self):
        config=self.config()
        direct=self.target.get('mode')=='direct';folder=self.shared/'projects' if direct else self.root/'projects'
        projects=sorted(p.name for p in folder.iterdir() if p.is_dir() and (p/'project.json').is_file()) if folder.is_dir() else []
        return {**config,'mode':'direct' if direct else 'folder','path':str(self.shared),'target_fixed':True,'target_ready':True,
                'available':(self.shared/'projects').is_dir() if direct else self.shared.is_dir(),'configured':bool(config),'shared_projects':projects if direct else self.projects(),
                'projects':projects,'auto_pull':False}

    def configure(self,body):
        name=str(body.get('name','')).strip()
        if not name or len(name)>100:raise ValueError('请填写协作者姓名')
        projects=body.get('shared_projects',self.projects())
        if not isinstance(projects,list) or not projects or any(not isinstance(p,str) or not re.fullmatch(r'[A-Za-z0-9_-]+',p) for p in projects):
            raise ValueError('请至少选择一个需要共享的工程')
        config={'name':name,'shared_projects':sorted(set(projects))}
        self.local.mkdir(exist_ok=True)
        self.config_file.write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding='utf-8')
        return self.status()

    @contextmanager
    def locked(self):
        if not self.shared.is_absolute():raise ValueError('共享目录必须是绝对路径')
        if not self.shared.is_dir():raise ValueError('共享目录不可访问，请先连接共享盘：'+str(self.shared))
        if self.shared.is_symlink() or any(p.is_symlink() for p in self.shared.parents):raise ValueError('共享目录不能经过符号链接')
        a,b=self.shared.resolve(),self.root.resolve()
        if a.is_relative_to(b) or b.is_relative_to(a):raise ValueError('公共目录应与程序本地目录分开')
        lock=self.shared/'.plot-forge-sync.lock'
        try:lock.mkdir()
        except FileExistsError:raise ValueError('其他成员正在同步，请稍后重试；如同步意外中断，请由维护者核对锁目录后再清理') from None
        try:
            (lock/'owner.json').write_text(json.dumps({'name':self.config().get('name',''),'computer':socket.gethostname(),'started':datetime.now(timezone.utc).isoformat()},ensure_ascii=False),encoding='utf-8')
            yield
        finally:
            (lock/'owner.json').unlink(missing_ok=True)
            lock.rmdir()

    def sync(self,publish=False,message=''):
        if self.target.get('mode')=='direct':raise ValueError('当前直接读写公共工程，无需上传或获取副本；重新选择图表可读取最新版本')
        from collaboration_sync import CollaborationSync
        from project_storage import from_shared,to_shared
        config=self.config();selected=self.projects()
        if not selected:raise ValueError('请先选择需要共享的工程')
        if publish and not config.get('name'):raise ValueError('上传前请保存协作者姓名与共享工程选择')
        if publish and not str(message).strip():raise ValueError('请填写本次修改说明')
        files=lambda folder:CollaborationSync.files(folder,include_private=selected,only_projects=selected,normalize_text=False)
        with self.locked():
            local_root=self.root/'projects';remote_root=self.shared/'projects'
            local_raw,remote_raw=files(local_root),files(remote_root)
            local,remote=from_shared(local_raw),from_shared(remote_raw)
            base=json.loads(self.baseline_file.read_text(encoding='utf-8')) if self.baseline_file.is_file() else {}
            base={key:value for key,value in base.items() if key.split('/')[0] in selected}
            merged=CollaborationSync.merge(base,local,remote)
            if CollaborationSync.hashes(files(local_root))!=CollaborationSync.hashes(local_raw):raise ValueError('同步期间本机工程发生变化，请稍后重试')
            hashes=CollaborationSync.hashes
            if publish:
                shared_files=to_shared(merged)
                try:CollaborationSync.write_files(remote_root,remote_raw,shared_files)
                except OSError:
                    # Restore already-written selected files if a network write fails.
                    CollaborationSync.write_files(remote_root,shared_files,remote_raw)
                    raise
                remote=merged
            revision=hashlib.sha256(json.dumps(hashes(remote),sort_keys=True).encode()).hexdigest()
            CollaborationSync.write_files(local_root,local_raw,merged)
            self.local.mkdir(exist_ok=True)
            self.baseline_file.write_text(json.dumps(hashes(remote),indent=2),encoding='utf-8')
            if publish:
                history=self.shared/'.plot-forge-history';history.mkdir(exist_ok=True)
                (history/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]+'.json')).write_text(json.dumps(
                    {'revision':revision,'author':config['name'],'message':str(message).strip()[:500],'projects':selected,'files':hashes(remote)},ensure_ascii=False,indent=2),encoding='utf-8')
            return {'published':publish,'files':len(merged),'revision':revision,'author':config.get('name',''),
                    'local_changes':sum(hashes(merged).get(p)!=hashes(remote).get(p) for p in merged.keys()|remote.keys())}
