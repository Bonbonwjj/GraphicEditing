"""Generic adapter for uploaded plotting packages, with optional LLM splitting."""
import ast, csv, json, re, shutil

import llm_client
from llm_workflows import split_chart

def _normalise(source, data_names):
    if "CHART_PROJECT_DIR" not in source:
        source="import os\nfrom pathlib import Path\nproject = Path(os.environ['CHART_PROJECT_DIR'])\n"+source
    for name in data_names:
        source=re.sub(r"(['\"])(?:\.\./)?(?:csv|data)/"+re.escape(name)+r"\1", "project / 'data' / '"+name+"'", source)
    source=re.sub(r"(?:fig|plt)\.savefig\([^\n]+\)", "plt.savefig(os.environ['CHART_OUTPUT'], dpi=300, bbox_inches='tight')", source)
    source=source.replace("plt.show()", "plt.savefig(os.environ['CHART_OUTPUT'], dpi=300, bbox_inches='tight')")
    if "CHART_OUTPUT" not in source: source+="\nplt.savefig(os.environ['CHART_OUTPUT'], dpi=300, bbox_inches='tight')\n"
    ast.parse(source); return source


def _data_catalog(upload):
    catalog=[]
    for path in sorted((upload/"csv").iterdir()):
        item={"file":path.name}
        try:
            if path.suffix.lower() in (".csv", ".tsv"):
                with path.open(encoding="utf-8-sig", newline="") as stream:
                    item["columns"]=next(csv.reader(stream, delimiter="\t" if path.suffix.lower()==".tsv" else ","), [])
            elif path.suffix.lower()==".json":
                value=json.loads(path.read_text(encoding="utf-8"))
                sample=value[0] if isinstance(value,list) and value else value
                item["keys"]=list(sample)[:100] if isinstance(sample,dict) else []
        except (OSError, UnicodeError, csv.Error, json.JSONDecodeError) as error:
            item["inspection_error"]=str(error)[:200]
        catalog.append(item)
    return catalog


def _unique_name(name, used):
    candidate=name; index=2
    while candidate in used:
        candidate=f"{name}_{index}"; index+=1
    used.add(candidate)
    return candidate

def import_generic(root, upload, project_id, name):
    target=root/"projects"/project_id; updating=target.exists()
    for d in ("data","charts","history"): (target/d).mkdir(parents=True,exist_ok=True)
    data_names=[]
    for p in sorted((upload/"csv").iterdir()):
        if p.is_file(): shutil.copy2(p,target/"data"/p.name); data_names.append(p.name)
    charts=[]; errors=[]; used=set()
    catalog=_data_catalog(upload)
    for p in sorted((upload/"code").glob("*.py")):
        chart=re.sub(r"[^A-Za-z0-9_]+","_",p.stem).strip("_") or "chart"
        source=p.read_text(encoding="utf-8")
        if llm_client.is_configured():
            try:
                generated=split_chart(p.name,source,catalog)
                for item in generated:
                    output_name=_unique_name(item["name"],used)
                    (target/"charts"/(output_name+".py")).write_text(item["code"],encoding="utf-8")
                    charts.append(output_name)
                continue
            except Exception as error:
                errors.append({"file":p.name,"phase":"llm-split","error":str(error)})
        try:
            source=_normalise(source,data_names); chart=_unique_name(chart,used)
            (target/"charts"/(chart+".py")).write_text(source,encoding="utf-8"); charts.append(chart)
        except Exception as e: errors.append({"file":p.name,"phase":"fallback","error":str(e)})
    if not charts:
        if not updating: shutil.rmtree(target)
        raise ValueError("没有可转换的 Python 绘图文件："+json.dumps(errors,ensure_ascii=False))
    meta_file=target/"project.json"
    old=json.loads(meta_file.read_text(encoding="utf-8")) if meta_file.exists() else {}
    meta={"name":old.get("name",name) if updating else name,"description":f"{'Updated' if updating else 'Uploaded'} with {len(charts)} chart candidates."}
    if old.get("non_chart_scripts"):
        meta["non_chart_scripts"] = old["non_chart_scripts"]
    meta_file.write_text(json.dumps(meta,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return {"project":project_id,"charts":charts,"files":len(data_names),"errors":errors,"adapter":"generic-update" if updating else "generic"}
