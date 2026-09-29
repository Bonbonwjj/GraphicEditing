"""Validate and group browser uploads by project and batch."""
from datetime import datetime, timezone
from pathlib import Path
ALLOWED={".py",".csv",".tsv",".json"}

def store_upload(root, project_id, files):
    if not project_id or not project_id.replace("_","").replace("-","").isalnum():
        raise ValueError("项目 ID 只能包含字母、数字、_ 或 -")
    if not files: raise ValueError("请选择代码文件夹和数据文件夹")
    batch=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    target=root/"data"/"uploads"/project_id/batch
    total=0; counts={"code":0,"data":0}
    for item in files:
        name=Path(str(item.get("name",""))).name
        content=item.get("content",""); kind=item.get("kind")
        if kind not in counts: raise ValueError("上传文件缺少代码/数据分类")
        suffix=Path(name).suffix.lower()
        if not name or suffix not in ALLOWED or not isinstance(content,str): raise ValueError("仅支持 .py、.csv、.tsv、.json 文本文件")
        if kind=="code" and suffix!=".py": raise ValueError("代码文件夹只能包含 Python 文件")
        if kind=="data" and suffix==".py": raise ValueError("数据文件夹不能包含 Python 文件")
        total+=len(content.encode("utf-8"))
        if total>10_000_000: raise ValueError("上传总大小不能超过 10 MB")
        folder="code" if kind=="code" else "csv"
        out=target/folder/name; out.parent.mkdir(parents=True,exist_ok=True); out.write_text(content,encoding="utf-8")
        counts[kind]+=1
    if not counts["code"] or not counts["data"]: raise ValueError("必须分别上传代码文件夹和数据文件夹")
    return target
