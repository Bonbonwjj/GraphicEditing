"""Validate and group browser uploads by project and batch."""
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
import shutil
import os
ALLOWED={".py",".csv",".tsv",".json",".png",".jpg",".jpeg",".svg"}
MAX_UPLOAD_BYTES=500_000_000

def safe_upload_path(filename):
    """Return a portable relative upload path and reject traversal/drive names."""
    raw = str(filename or "").replace("\\", "/")
    path = PurePosixPath(raw)
    if (
        not raw
        or path.is_absolute()
        or any(part in ("", ".", "..") or ":" in part for part in path.parts)
    ):
        raise ValueError("不安全的上传文件路径")
    return Path(*path.parts)

def _target(root, project_id):
    if not project_id or not project_id.replace("_","").replace("-","").isalnum():
        raise ValueError("项目 ID 只能包含字母、数字、_ 或 -")
    batch=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return root/"data"/"uploads"/project_id/batch

def store_multipart_upload(root, project_id, fields):
    target=_target(root,project_id); total=0; counts={"code":0,"data":0,"image":0}
    items=fields.list or []
    for item in items:
        if item.name not in ("code_files","data_files","image_files") or not item.filename: continue
        kind={"code_files":"code","data_files":"data","image_files":"image"}[item.name]
        name=safe_upload_path(item.filename); suffix=Path(name).suffix.lower()
        if suffix not in ALLOWED or (kind=="code" and suffix!=".py") or (kind=="data" and suffix not in {".csv",".tsv",".json"}) or (kind=="image" and suffix not in {".png",".jpg",".jpeg",".svg"}):
            continue
        folder={"code":"code","data":"csv","image":"images"}[kind]; out=target/folder/name
        out.parent.mkdir(parents=True,exist_ok=True)
        with out.open("wb") as stream:
            while True:
                chunk=item.file.read(1024*1024)
                if not chunk: break
                total+=len(chunk)
                if total>MAX_UPLOAD_BYTES: raise ValueError("单次上传总大小不能超过 500 MB")
                stream.write(chunk)
        counts[kind]+=1
    local = {kind: fields.getfirst(kind+'_path', '') for kind in ('code','data','image')} if hasattr(fields,'getfirst') else {}
    total, local_counts = copy_local_sources(target, local, total)
    for kind, count in local_counts.items(): counts[kind] += count
    if not counts["code"] or not counts["data"]:
        raise ValueError("必须分别选择包含 Python 的代码文件夹和包含 CSV/TSV/JSON 的数据文件夹")
    return target


def copy_local_sources(target, paths, total=0):
    """Copy explicitly selected local files; never traverse hidden/symlink trees."""
    counts = {'code':0, 'data':0, 'image':0}
    types = {'code':{'.py'}, 'data':{'.csv','.tsv','.json'}, 'image':{'.png','.jpg','.jpeg','.svg'}}
    for kind, raw in paths.items():
        if kind not in counts or not str(raw).strip(): continue
        source = Path(os.path.expandvars(str(raw).strip().strip('"').strip("'"))).expanduser()
        if source.is_symlink() or not source.exists():
            raise ValueError('路径不存在或为符号链接：'+str(source))
        if any(p.is_symlink() for p in source.parents):
            raise ValueError('路径不能经过符号链接。')
        source=source.resolve()
        entries=[]
        if source.is_file(): entries=[source]
        else:
            for directory, dirs, files in os.walk(source):
                dirs[:]=[d for d in dirs if not d.startswith('.') and d not in {'__pycache__','node_modules'} and not (Path(directory)/d).is_symlink()]
                entries.extend(Path(directory)/name for name in files if not name.startswith('.'))
                if len(entries)>10000: raise ValueError('所选目录超过 10000 个文件，请选择更小的子目录。')
        for path in sorted(entries):
            if path.is_symlink() or path.suffix.lower() not in types[kind]: continue
            relative=Path(path.name) if source.is_file() else path.relative_to(source)
            if any(token in part.lower() for part in relative.parts for token in ('.env','credential','secret','api-key','api_key')):
                continue
            total+=path.stat().st_size
            if total>MAX_UPLOAD_BYTES: raise ValueError('单次上传总大小不能超过 500 MB')
            destination=target/{'code':'code','data':'csv','image':'images'}[kind]/relative
            if destination.exists(): raise ValueError('文件选择与路径输入有同名文件，请只使用其中一种方式：'+str(relative))
            destination.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,destination)
            counts[kind]+=1
        if not counts[kind]: raise ValueError('所填路径中没有支持的'+{'code':'Python 代码','data':'CSV/TSV/JSON 数据','image':'图片'}[kind]+'。')
    return total, counts

def store_upload(root, project_id, files):
    target=_target(root,project_id); total=0; counts={"code":0,"data":0,"image":0}
    for item in files:
        name=safe_upload_path(item.get("name","")); content=item.get("content",""); kind=item.get("kind")
        if kind not in counts: raise ValueError("上传文件缺少代码/数据分类")
        suffix=Path(name).suffix.lower()
        if not name or suffix not in ALLOWED or not isinstance(content,str): raise ValueError("仅支持 .py、.csv、.tsv、.json")
        total+=len(content.encode("utf-8"))
        if total>MAX_UPLOAD_BYTES: raise ValueError("单次上传总大小不能超过 500 MB")
        if (kind=="code" and suffix!=".py") or (kind=="data" and suffix not in {".csv",".tsv",".json"}) or (kind=="image" and suffix not in {".png",".jpg",".jpeg",".svg"}): raise ValueError("文件类型与分类不匹配")
        folder={"code":"code","data":"csv","image":"images"}[kind]; out=target/folder/name
        out.parent.mkdir(parents=True,exist_ok=True); out.write_text(content,encoding="utf-8", newline="\n"); counts[kind]+=1
    if not counts["code"] or not counts["data"]: raise ValueError("必须分别上传代码文件夹和数据文件夹")
    return target


def store_bundle_multipart(root, project_id, fields):
    """Store a small browser-uploaded Plot Bundle without flattening its tree."""
    target = _target(root, project_id) / "bundle_upload"
    total = 0
    count = 0
    try:
        for item in fields.list or []:
            if item.name != "bundle_files" or not item.filename:
                continue
            relative = safe_upload_path(item.filename)
            if relative.suffix.lower() not in (".json", ".gz"):
                raise ValueError("Plot Bundle 上传仅支持 .json 和 .gz 文件")
            output = target / relative
            output.parent.mkdir(parents=True, exist_ok=True)
            with output.open("wb") as stream:
                while True:
                    chunk = item.file.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_UPLOAD_BYTES:
                        raise ValueError("单次上传总大小不能超过 500 MB")
                    stream.write(chunk)
            count += 1
        if not count:
            raise ValueError("没有收到 Plot Bundle 文件")
        manifests = list(target.rglob("manifest.json"))
        if len(manifests) != 1:
            raise ValueError("Plot Bundle 必须且只能包含一个 manifest.json")
        return manifests[0].parent
    except Exception:
        if target.exists():
            shutil.rmtree(target)
        raise
