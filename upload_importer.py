"""Validate and group browser uploads before project conversion."""
import re
from pathlib import Path
ALLOWED={".py",".csv",".tsv",".json"}
def store_upload(root, project_id, files):
    if not project_id or not project_id.replace("_","").replace("-","").isalnum(): raise ValueError("项目 ID 只能包含字母、数字、_ 或 -")
    if not files: raise ValueError("请选择代码和数据文件")
    target=root/"data"/"uploads"/project_id
    if target.exists(): raise ValueError("该项目名称已有上传记录")
    total=0
    for item in files:
        name=Path(str(item.get("name",""))).name
        content=item.get("content","")
        if not name or Path(name).suffix.lower() not in ALLOWED or not isinstance(content,str): raise ValueError("仅支持 .py、.csv、.tsv、.json 文本文件")
        total+=len(content.encode("utf-8"))
        if total>10_000_000: raise ValueError("上传总大小不能超过 10 MB")
        folder="code" if name.endswith(".py") else "csv"
        out=target/folder/name; out.parent.mkdir(parents=True,exist_ok=True); out.write_text(content,encoding="utf-8")
    if not (target/"code").is_dir() or not (target/"csv").is_dir(): raise ValueError("每个项目必须同时上传 Python 代码和数据")
    return target
