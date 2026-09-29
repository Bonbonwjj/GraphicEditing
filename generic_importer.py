"""Generic one-script-per-chart adapter for uploaded plotting packages."""
import ast, json, re, shutil

def _normalise(source, data_names):
    if "CHART_PROJECT_DIR" not in source:
        source="import os\nfrom pathlib import Path\nproject = Path(os.environ['CHART_PROJECT_DIR'])\n"+source
    for name in data_names:
        source=re.sub(r"(['\"])(?:\.\./)?(?:csv|data)/"+re.escape(name)+r"\1", "project / 'data' / '"+name+"'", source)
    source=re.sub(r"(?:fig|plt)\.savefig\([^\n]+\)", "plt.savefig(os.environ['CHART_OUTPUT'], dpi=300, bbox_inches='tight')", source)
    source=source.replace("plt.show()", "plt.savefig(os.environ['CHART_OUTPUT'], dpi=300, bbox_inches='tight')")
    if "CHART_OUTPUT" not in source: source+="\nplt.savefig(os.environ['CHART_OUTPUT'], dpi=300, bbox_inches='tight')\n"
    ast.parse(source); return source

def import_generic(root, upload, project_id, name):
    target=root/"projects"/project_id; updating=target.exists()
    for d in ("data","charts","history"): (target/d).mkdir(parents=True,exist_ok=True)
    data_names=[]
    for p in sorted((upload/"csv").iterdir()):
        if p.is_file(): shutil.copy2(p,target/"data"/p.name); data_names.append(p.name)
    charts=[]; errors=[]
    for p in sorted((upload/"code").glob("*.py")):
        chart=re.sub(r"[^A-Za-z0-9_]+","_",p.stem).strip("_") or "chart"
        try:
            source=_normalise(p.read_text(encoding="utf-8"),data_names)
            (target/"charts"/(chart+".py")).write_text(source,encoding="utf-8"); charts.append(chart)
        except Exception as e: errors.append({"file":p.name,"error":str(e)})
    if not charts:
        if not updating: shutil.rmtree(target)
        raise ValueError("没有可转换的 Python 绘图文件："+json.dumps(errors,ensure_ascii=False))
    meta_file=target/"project.json"
    old=json.loads(meta_file.read_text(encoding="utf-8")) if meta_file.exists() else {}
    meta={"name":old.get("name",name) if updating else name,"description":f"{'Updated' if updating else 'Uploaded'} with {len(charts)} chart candidates."}
    meta_file.write_text(json.dumps(meta,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return {"project":project_id,"charts":charts,"files":len(data_names),"errors":errors,"adapter":"generic-update" if updating else "generic"}
