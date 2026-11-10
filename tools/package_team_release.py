"""Package the current working tree and explicitly selected project, without credentials."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app_version import APP_VERSION


def package(destination,projects):
    from collaboration_sync import CollaborationSync
    from project_storage import to_shared
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=True)
    package_root=f'Plot-Forge-v{APP_VERSION}-team/'
    output=[destination/f'Plot-Forge-v{APP_VERSION}-team.zip']
    if projects:output.append(destination/'figure_DATA_code-initial.zip')
    if any(path.exists() for path in output):raise ValueError('目标目录已有发布包，请选择新的输出目录')
    for name in projects:
        if not (ROOT/'projects'/name/'project.json').is_file():raise ValueError('工程不存在：'+name)
    project_files=CollaborationSync.files(ROOT/'projects',include_private=projects,only_projects=projects,normalize_text=False) if projects else {}
    source_files={}
    for path in ROOT.iterdir():
        if path.is_file() and not path.name.startswith('.') and (path.suffix in ('.py','.cmd','.command','.yml') or path.name.startswith('requirements') or path.name in ('README.md','VERSION','Dockerfile.renderer','team_collaboration.json')):
            source_files[path.name]=path.read_bytes()
    for name in ('static','skills','docs','tests','tools'):
        for path in (ROOT/name).rglob('*'):
            if path.is_symlink():raise ValueError('包内不能包含符号链接：'+str(path))
            if path.is_file() and not any(part.startswith('.') or part=='__pycache__' for part in path.relative_to(ROOT).parts):
                source_files[path.relative_to(ROOT).as_posix()]=path.read_bytes()
    source_files.update({'projects/'+name:data for name,data in project_files.items()})
    source_files['团队协作与启动说明.md']=(ROOT/'docs/团队共享文件夹与打包.md').read_bytes()
    target=json.loads((ROOT/'team_collaboration.json').read_text(encoding='utf-8'))
    shared_files={'projects/'+name:data for name,data in (project_files if target.get('mode')=='direct' else to_shared(project_files)).items()}
    shared_files['公共目录初始化说明.md']=(ROOT/'docs/团队共享文件夹与打包.md').read_bytes()
    for archive,files,prefix in zip(output,[source_files,shared_files],[package_root,'']):
        manifest={'version':APP_VERSION,'created_utc':datetime.now(timezone.utc).isoformat(),'projects':projects,'python_runtime_included':False,
                  'files':{name:hashlib.sha256(data).hexdigest() for name,data in sorted(files.items())}}
        with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
            for name,data in sorted(files.items()):z.writestr(prefix+name,data)
            z.writestr(prefix+'PACKAGE_MANIFEST.json',json.dumps(manifest,ensure_ascii=False,indent=2))
        with zipfile.ZipFile(archive) as z:
            if set(z.namelist())!={*(prefix+name for name in files),prefix+'PACKAGE_MANIFEST.json'}:raise ValueError('ZIP 文件清单不匹配')
            for name,data in files.items():
                if hashlib.sha256(z.read(prefix+name)).hexdigest()!=manifest['files'][name]:raise ValueError('包内容不匹配：'+name)
    checksums=[]
    for path in output:
        with path.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
        checksums.append(f'{digest}  {path.name}\n')
    (destination/'SHA256SUMS.txt').write_text(''.join(checksums),encoding='utf-8')
    (destination/'团队协作与启动说明.md').write_bytes((ROOT/'docs/团队共享文件夹与打包.md').read_bytes())
    return [{'path':str(path.resolve()),'size_mb':round(path.stat().st_size/1024**2,2)} for path in output]


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);parser.add_argument('--project',action='append',default=[])
    args=parser.parse_args();print(json.dumps(package(args.output,args.project),ensure_ascii=False,indent=2))
