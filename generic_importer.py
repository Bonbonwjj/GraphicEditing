"""Generic adapter for uploaded plotting packages, with optional LLM splitting."""
import ast, csv, json, re, shutil
from pathlib import Path

import llm_client
from llm_workflows import split_chart

FIGURE_CALLS = {"figure", "subplots", "subplot_mosaic"}
OUTPUT_CALLS = {"savefig", "show"}

def _call_name(node):
    return node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id if isinstance(node.func, ast.Name) else ""

def _needs_model_split(source):
    """Conservatively identify programs that may emit more than one figure."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    class FigureCounter(ast.NodeVisitor):
        def __init__(self):
            self.figures = self.outputs = self.loop_depth = 0
            self.repeated = False
        def visit_Call(self, node):
            name = _call_name(node)
            self.figures += name in FIGURE_CALLS
            self.outputs += name in OUTPUT_CALLS
            self.repeated |= self.loop_depth > 0 and name in FIGURE_CALLS | OUTPUT_CALLS
            self.generic_visit(node)
        def _loop(self, node):
            self.loop_depth += 1; self.generic_visit(node); self.loop_depth -= 1
        visit_For = visit_AsyncFor = visit_While = visit_ListComp = visit_SetComp = visit_DictComp = visit_GeneratorExp = _loop
    counter = FigureCounter(); counter.visit(tree)
    return counter.repeated or counter.figures > 1 or counter.outputs > 1

def _explicit_roots(code_root):
    """Return charts/lib roots for the documented layout, if present."""
    code_root = Path(code_root)
    candidates = [code_root]
    candidates.extend(sorted(path for path in code_root.iterdir() if path.is_dir()))
    for base in candidates:
        charts = base / "charts"
        library = base / "lib"
        if charts.is_dir() or library.is_dir():
            return charts, library
    return None

def _normalise(source, data_names):
    if "CHART_PROJECT_DIR" not in source:
        source="import os\nfrom pathlib import Path\nproject = Path(os.environ['CHART_PROJECT_DIR'])\n"+source
    for name in data_names:
        def replace_data_path(match):
            # A Path(...) / 'data/file.csv' expression is already relative to
            # its chosen base. Replacing just its string would duplicate bases.
            if source[:match.start()].rstrip().endswith('/'):
                return match.group(0)
            return "project / 'data' / '"+name+"'"
        source=re.sub(r"(['\"])(?:\.\./)?(?:csv|data)/"+re.escape(name)+r"\1", replace_data_path, source)
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
                    columns=next(csv.reader(stream, delimiter="\t" if path.suffix.lower()==".tsv" else ","), [])
                    item["columns"]=columns[:64]
                    if len(columns)>64: item["omitted_columns"]=len(columns)-64
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

def import_generic(root, upload, project_id, name, progress=None):
    notify = progress or (lambda **fields: None)
    notify(stage='copying', message='正在复制数据并检查代码目录。')
    target=root/"projects"/project_id; updating=target.exists()
    for d in ("data","charts","lib","outputs","history"): (target/d).mkdir(parents=True,exist_ok=True)
    data_names=[]
    for p in sorted((upload/"csv").rglob("*")):
        if p.is_file() and p.suffix.lower() in {".csv", ".tsv", ".json"}:
            relative=p.relative_to(upload/"csv")
            destination=target/"data"/relative;destination.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(p,destination);data_names.append(relative.as_posix())
    charts=[]; errors=[]; used=set()
    catalog=_data_catalog(upload)
    explicit=_explicit_roots(upload/"code")
    chart_root=explicit[0] if explicit else upload/"code"
    if explicit and explicit[1].is_dir():
        shutil.copytree(explicit[1],target/"lib",dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    entries = sorted(chart_root.rglob("*.py")) if chart_root.is_dir() else []
    for index, p in enumerate(entries):
        chart=re.sub(r"[^A-Za-z0-9_]+","_","_".join(p.relative_to(chart_root).with_suffix("").parts)).strip("_") or "chart"
        source=p.read_text(encoding="utf-8")
        use_model = not explicit and _needs_model_split(source) and llm_client.is_configured()
        notify(stage='splitting', completed=index, total=len(entries), current_file=p.relative_to(chart_root).as_posix(),
               message='正在拆分代码'+('，等待模型返回。' if use_model else '，建立独立绘图入口。'))
        if use_model:
            try:
                generated=split_chart(p.name,source,catalog)
                for item in generated:
                    output_name=_unique_name(item["name"],used)
                    (target/"charts"/(output_name+".py")).write_text(item["code"],encoding="utf-8", newline="\n")
                    charts.append(output_name)
                notify(completed=index+1, message='当前文件拆分完成。')
                continue
            except Exception as error:
                errors.append({"file":p.name,"phase":"llm-split","error":str(error)})
        try:
            source=_normalise(source,data_names); chart=_unique_name(chart,used)
            (target/"charts"/(chart+".py")).write_text(source,encoding="utf-8", newline="\n"); charts.append(chart)
        except Exception as e: errors.append({"file":p.name,"phase":"fallback","error":str(e)})
        notify(completed=index+1, message='当前文件处理完成。')
    if not charts:
        if not updating: shutil.rmtree(target)
        raise ValueError("没有可转换的 Python 绘图文件："+json.dumps(errors,ensure_ascii=False))
    meta_file=target/"project.json"
    notify(stage='saving', message='正在保存绘图代码和项目登记。', completed=len(entries), total=len(entries))
    old=json.loads(meta_file.read_text(encoding="utf-8")) if meta_file.exists() else {}
    meta={**old,"name":old.get("name",name) if updating else name,"description":f"{'Updated' if updating else 'Uploaded'} with {len(charts)} chart candidates."}
    if old.get("non_chart_scripts"):
        meta["non_chart_scripts"] = old["non_chart_scripts"]
    meta_file.write_text(json.dumps(meta,ensure_ascii=False,indent=2)+"\n",encoding="utf-8", newline="\n")
    sources_file=target/"data_sources.json"
    previous=json.loads(sources_file.read_text(encoding="utf-8")) if sources_file.exists() else {"version":1,"sources":[]}
    sources=[source for source in previous.get("sources",[]) if source.get("kind")!="tabular"]
    sources.append({
        "id":"tabular-{}".format(project_id),
        "kind":"tabular",
        "mode":"upload",
        "location":"data",
        "read_only":True,
        "trusted":True,
        "metadata":{"files":sorted(data_names),"file_count":len(data_names)},
    })
    sources_file.write_text(json.dumps({"version":1,"sources":sources},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return {"project":project_id,"charts":charts,"files":len(data_names),"errors":errors,"adapter":"generic-update" if updating else "generic"}
