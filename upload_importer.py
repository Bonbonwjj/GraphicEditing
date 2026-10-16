"""Validate and group browser uploads by project and batch."""
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
import shutil
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
    if not counts["code"] or not counts["data"]:
        raise ValueError("必须分别选择包含 Python 的代码文件夹和包含 CSV/TSV/JSON 的数据文件夹")
    return target

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
