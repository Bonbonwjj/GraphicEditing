"""Validate and group browser uploads by project and batch."""
from datetime import datetime, timezone
from pathlib import Path
ALLOWED={".py",".csv",".tsv",".json"}
MAX_UPLOAD_BYTES=500_000_000

def _target(root, project_id):
    if not project_id or not project_id.replace("_","").replace("-","").isalnum():
        raise ValueError("项目 ID 只能包含字母、数字、_ 或 -")
    batch=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return root/"data"/"uploads"/project_id/batch

def store_multipart_upload(root, project_id, fields):
    target=_target(root,project_id); total=0; counts={"code":0,"data":0}
    items=fields.list or []
    for item in items:
        if item.name not in ("code_files","data_files") or not item.filename: continue
        kind="code" if item.name=="code_files" else "data"
        name=Path(item.filename).name; suffix=Path(name).suffix.lower()
        if suffix not in ALLOWED or (kind=="code" and suffix!=".py") or (kind=="data" and suffix==".py"):
            continue
        folder="code" if kind=="code" else "csv"; out=target/folder/name
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
    target=_target(root,project_id); total=0; counts={"code":0,"data":0}
    for item in files:
        name=Path(str(item.get("name",""))).name; content=item.get("content",""); kind=item.get("kind")
        if kind not in counts: raise ValueError("上传文件缺少代码/数据分类")
        suffix=Path(name).suffix.lower()
        if not name or suffix not in ALLOWED or not isinstance(content,str): raise ValueError("仅支持 .py、.csv、.tsv、.json")
        total+=len(content.encode("utf-8"))
        if total>MAX_UPLOAD_BYTES: raise ValueError("单次上传总大小不能超过 500 MB")
        folder="code" if kind=="code" else "csv"; out=target/folder/name
        out.parent.mkdir(parents=True,exist_ok=True); out.write_text(content,encoding="utf-8"); counts[kind]+=1
    if not counts["code"] or not counts["data"]: raise ValueError("必须分别上传代码文件夹和数据文件夹")
    return target
