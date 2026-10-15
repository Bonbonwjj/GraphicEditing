"""Local-only chart studio. Start with `python server.py`."""
import ast
import cgi
import csv
import json
import os
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse, unquote
from agent_importer import import_package
from bundle_importer import PlotBundleAdapter, import_plot_bundle
from data_sources import resolve_allowed_path
from generic_importer import import_generic
from git_support import git_status, record_change
from shared_modules import (
    MAX_SHARED_MODULE_SOURCE,
    apply_module,
    discover_modules,
    module_revision_source,
    read_module_history,
    resolve_module,
)
from upload_importer import store_upload, store_multipart_upload, store_bundle_multipart

ROOT = Path(__file__).resolve().parent
PROJECTS = ROOT / "projects"
STATIC = ROOT / "static"
STYLE = ROOT / "skills" / "plot-style" / "SKILL.md"
MAX_BODY = 12_000_000
MAX_UPLOAD_BODY = 550_000_000


def shared_roots_from_env(environ=None):
    environ = os.environ if environ is None else environ
    raw = str(environ.get("CHART_STUDIO_SHARED_ROOTS", "")).strip()
    if not raw:
        return []
    roots = []
    for item in raw.split(os.pathsep):
        if item.strip():
            roots.append(Path(item.strip()).resolve(strict=True))
    return roots


def resolve_server_path(path, environ=None):
    return resolve_allowed_path(Path(path), shared_roots_from_env(environ))


def project_data_sources(p):
    source_file = Path(p) / "data_sources.json"
    if not source_file.is_file():
        return []
    value = json.loads(source_file.read_text(encoding="utf-8"))
    return value.get("sources", []) if isinstance(value, dict) else []


def project_path(project):
    if not project or not project.replace("_", "").replace("-", "").isalnum():
        raise ValueError("Invalid project name")
    p = PROJECTS / project
    if not (p / "project.json").is_file():
        raise ValueError("Project not found")
    return p


def chart_path(project, chart):
    if not chart or not chart.replace("_", "").isalnum():
        raise ValueError("Invalid chart name")
    p = project_path(project)
    c = p / "charts" / (chart + ".py")
    if not c.is_file():
        raise ValueError("Chart not found")
    return p, c


def read_history(p, chart):
    f = p / "history" / (chart + ".json")
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else []


def write_history(p, chart, entries):
    (p / "history").mkdir(exist_ok=True)
    (p / "history" / (chart + ".json")).write_text(
        json.dumps(entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def render(p, source, suffix=".png", library_path=None):
    with tempfile.TemporaryDirectory(prefix="chart-studio-") as d:
        temp = Path(d)
        script = temp / "chart.py"
        output = temp / ("figure" + suffix)
        script.write_text(source, encoding="utf-8")
        env = os.environ.copy()
        env["CHART_PROJECT_DIR"] = str(p)
        env["CHART_OUTPUT"] = str(output)
        python_paths = []
        if library_path is not None:
            python_paths.append(str(Path(library_path)))
        python_paths.extend([str(p / "lib"), str(ROOT)])
        if env.get("PYTHONPATH"):
            python_paths.append(env["PYTHONPATH"])
        env["PYTHONPATH"] = os.pathsep.join(python_paths)
        env["MPLCONFIGDIR"] = str(temp / "mpl")
        timeout = int(os.environ.get("CHART_RENDER_TIMEOUT", "120"))
        try:
            result = subprocess.run([sys.executable, str(script)], cwd=p, env=env,
                                    capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise ValueError("Render timed out after {} seconds".format(timeout))
        if result.returncode or not output.is_file():
            raise ValueError("Render failed: " + (result.stderr[-3500:] or "No output file"))
        return output.read_bytes()


def list_projects():
    result = []
    if not PROJECTS.is_dir():
        return result
    for p in sorted(PROJECTS.iterdir()):
        if (p / "project.json").is_file():
            meta = json.loads((p / "project.json").read_text(encoding="utf-8"))
            result.append({"id": p.name, **meta,
                           "charts": [f.stem for f in sorted((p / "charts").glob("*.py"))],
                           "modules": discover_modules(p),
                           "data": [f.relative_to(p / "data").as_posix() for f in sorted((p / "data").rglob("*"))
                                    if f.is_file() and f.suffix.lower() in (".csv", ".tsv", ".json")],
                           "data_sources": project_data_sources(p)})
    return result


def data_preview(p):
    out = []
    data_root = Path(p) / "data"
    if not data_root.is_dir():
        return out
    for f in sorted(data_root.rglob("*")):
        if not f.is_file() or f.suffix.lower() not in (".csv", ".tsv", ".json"):
            continue
        name = f.relative_to(data_root).as_posix()
        if f.suffix.lower() in (".csv", ".tsv"):
            with f.open(newline="", encoding="utf-8-sig") as stream:
                reader = csv.reader(stream, delimiter="\t" if f.suffix.lower() == ".tsv" else ",")
                head = next(reader, [])
                rows = [r for _, r in zip(range(3), reader)]
        elif f.stat().st_size > 5_000_000:
            head, rows = [], []
        else:
            value = json.loads(f.read_text(encoding="utf-8-sig"))
            records = value if isinstance(value, list) else [value]
            records = [record for record in records[:3] if isinstance(record, dict)]
            head = list(records[0]) if records else []
            rows = [[record.get(column) for column in head] for record in records]
        out.append({"file": name, "columns": head, "sample": rows, "format": f.suffix.lower()[1:]})
    return out


csv_preview = data_preview


def shared_module_detail(project, module_id):
    project = Path(project)
    module = resolve_module(project, module_id)
    descriptor = next(
        item for item in discover_modules(project) if item["id"] == module_id
    )
    return {
        "code": module.read_text(encoding="utf-8"),
        "history": read_module_history(project, module_id),
        "data": data_preview(project),
        "data_sources": project_data_sources(project),
        "style": STYLE.read_text(encoding="utf-8"),
        "module": descriptor,
    }


def save_shared_module(project, module_id, source, chart, note):
    p, chart_file = chart_path(project, chart)

    def render_candidate(selected_chart, candidate_library):
        if selected_chart != chart:
            raise ValueError("代表图已发生变化")
        return render(
            p,
            chart_file.read_text(encoding="utf-8"),
            library_path=candidate_library,
        )

    return apply_module(
        p, module_id, source, chart, render_candidate, str(note)[:300]
    )


def validate_tabular_content(name, content):
    suffix = Path(name).suffix.lower()
    if suffix not in (".csv", ".tsv", ".json"):
        raise ValueError("仅支持 CSV、TSV 或 JSON")
    if suffix == ".json":
        value = json.loads(content)
        records = value if isinstance(value, list) else [value]
        if not records or not all(isinstance(record, dict) for record in records):
            raise ValueError("JSON 必须是对象或对象数组")
        return len(records)
    rows = list(csv.reader(content.splitlines(), delimiter="\t" if suffix == ".tsv" else ","))
    if len(rows) < 2 or not rows[0]:
        raise ValueError("表格需要标题行和至少一行数据")
    return len(rows) - 1


def llm_instruction(resource_type="chart"):
    if resource_type == "module":
        opening = (
            "You edit one project-local shared visualization module used by one or more "
            "Python charts. Return only the complete Python source, without markdown fences. "
            "Change visualization behavior only; do not add data loading, processing, statistics, "
            "network, shell, or secret access. The user will review and validate the change with "
            "one representative chart before applying.\n\n"
        )
    else:
        opening = (
            "You edit one Python Matplotlib chart script. Return only the complete Python source, "
            "without markdown fences. Follow the plot-style skill. Use only the listed data-source fields, "
            "preserve CHART_PROJECT_DIR and CHART_OUTPUT, and never include network, shell, or secret access. "
            "The user will review before applying.\n\n"
        )
    return opening + STYLE.read_text(encoding="utf-8")


def llm_proposal(prompt, source, data, resource_type="chart", module_path=None, chart=None):
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise ValueError("Set OPENAI_API_KEY in your terminal to enable chat editing")
    url = os.environ.get("LLM_API_URL", "https://api.siliconflow.cn/v1/chat/completions")
    if urlparse(url).scheme != "https":
        raise ValueError("LLM_API_URL must use HTTPS")
    instruction = llm_instruction(resource_type)
    request_context = {"request": prompt, "current_code": source}
    if resource_type == "module":
        request_context.update({"module_path": module_path, "validation_chart": chart})
    else:
        request_context["data_sources"] = data
    payload = {"model": os.environ.get("LLM_MODEL", "Qwen/Qwen3.5-4B"),
               "messages": [{"role": "system", "content": instruction},
                            {"role": "user", "content": json.dumps(request_context, ensure_ascii=False)}],
               "temperature": 0.2}
    request = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                     headers={"Authorization": "Bearer " + key,
                                              "Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            message = json.load(response)["choices"][0]["message"]["content"]
    except (urllib.error.HTTPError, urllib.error.URLError) as e:
        detail = e.read().decode(errors="replace")[:700] if isinstance(e, urllib.error.HTTPError) else str(e)
        raise ValueError("LLM request failed: " + detail)
    proposed = message.strip()
    if proposed.startswith("```"):
        proposed = proposed.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    try:
        ast.parse(proposed)
    except SyntaxError as e:
        raise ValueError(f"Model returned invalid Python: {e}")
    source_limit = MAX_SHARED_MODULE_SOURCE if resource_type == "module" else 100_000
    if len(proposed) > source_limit:
        raise ValueError("Model returned an oversized script")
    return proposed + "\n"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print("%s %s" % (self.address_string(), fmt % args))

    def json_response(self, value, status=200):
        body = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def bytes_response(self, body, mime, filename=None):
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(body)

    def route(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        parts = [x for x in path.split("/") if x]
        if self.command == "GET" and path in ("/", "/index.html"):
            return self.bytes_response((STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
        if self.command == "GET" and path == "/static/app.css":
            return self.bytes_response((STATIC / "app.css").read_bytes(), "text/css; charset=utf-8")
        if self.command == "GET" and path == "/static/app.js":
            return self.bytes_response((STATIC / "app.js").read_bytes(), "text/javascript; charset=utf-8")
        if self.command == "GET" and path == "/api/projects":
            return self.json_response({"projects": list_projects(), "root": str(ROOT),
                                       "llm_enabled": bool(os.environ.get("OPENAI_API_KEY")),
                                       "git": git_status(ROOT),
                                       "shared_roots": [str(root) for root in shared_roots_from_env()]})
        if self.command == "GET" and path == "/api/data-sources/capabilities":
            return self.json_response({
                "types": ["tabular", "plot_bundle"],
                "modes": ["upload", "server_path"],
                "shared_roots": [str(root) for root in shared_roots_from_env()],
                "max_upload_bytes": 500_000_000,
                "plot_bundle_trusted_only": True,
            })
        if self.command == "POST" and path == "/api/data-sources/inspect":
            body = self.body_json()
            source = resolve_server_path(str(body.get("source_path", "")))
            descriptor = PlotBundleAdapter().inspect(
                source, mode="server_path", trusted=bool(body.get("trusted"))
            )
            return self.json_response({"data_source": descriptor.as_dict()})
        if self.command == "POST" and path == "/api/data-sources/import":
            body = self.body_json()
            source = resolve_server_path(str(body.get("source_path", "")))
            runtime_source = os.environ.get("BEHAVIOR_ANALYSIS_CODE_ROOT")
            result = import_plot_bundle(
                ROOT,
                source,
                project_id=str(body.get("project_id", "")).strip(),
                name=str(body.get("name", "")).strip(),
                mode="server_path",
                trusted=bool(body.get("trusted")),
                runtime_source=Path(runtime_source).resolve(strict=True) if runtime_source else None,
            )
            result["git"] = record_change(
                ROOT, [PROJECTS / result["project"]], "Import Plot Bundle " + result["project"]
            )
            return self.json_response(result)
        if self.command == "POST" and path == "/api/data-sources/import-upload":
            if not self.headers.get("Content-Type", "").startswith("multipart/form-data"):
                raise ValueError("Plot Bundle 浏览器上传必须使用 multipart/form-data")
            form = self.body_multipart()
            project_id = str(form.getfirst("project_id", "")).strip()
            name = str(form.getfirst("name", "")).strip()
            trusted = str(form.getfirst("trusted", "false")).lower() == "true"
            source = store_bundle_multipart(ROOT, project_id, form)
            runtime_source = os.environ.get("BEHAVIOR_ANALYSIS_CODE_ROOT")
            result = import_plot_bundle(
                ROOT,
                source,
                project_id=project_id,
                name=name,
                mode="upload",
                trusted=trusted,
                runtime_source=Path(runtime_source).resolve(strict=True) if runtime_source else None,
            )
            result["git"] = record_change(
                ROOT, [PROJECTS / result["project"]], "Import uploaded Plot Bundle " + result["project"]
            )
            return self.json_response(result)
        if self.command == "POST" and path == "/api/uploads/import":
            if self.headers.get("Content-Type", "").startswith("multipart/form-data"):
                form = self.body_multipart()
                project_id = str(form.getfirst("project_id", "")).strip()
                name = str(form.getfirst("name", "")).strip()
                existing = str(form.getfirst("existing", "false")).lower() == "true"
                files_source = store_multipart_upload(ROOT, project_id, form)
            else:
                body = self.body_json()
                project_id = str(body.get("project_id", "")).strip()
                name = str(body.get("name", "")).strip()
                existing = bool(body.get("existing"))
                files_source = None
            if not name: raise ValueError("必须填写项目名称")
            if existing != (PROJECTS / project_id).exists():
                raise ValueError("项目状态已变化，请刷新后重试")
            upload = files_source or store_upload(ROOT, project_id, body.get("files", []))
            try:
                if existing:
                    raise ValueError("Use generic updater")
                result = import_package(ROOT, str(upload.relative_to(ROOT / "data")), project_id, name)
                result["adapter"] = "reproducibility-package"
            except ValueError as error:
                if "Project already exists" in str(error): raise
                result = import_generic(ROOT, upload, project_id, name)
            result["git"] = record_change(
                ROOT, [PROJECTS / project_id], "Upload project " + project_id
            )
            return self.json_response(result)
        if self.command == "POST" and path == "/api/agent/import":
            body = self.body_json()
            result = import_package(ROOT, str(body.get("source", "")), str(body.get("project_id", "")), str(body.get("name", "")) or None)
            result["git"] = record_change(
                ROOT, [PROJECTS / result["project"]], "Agent import " + result["project"]
            )
            return self.json_response(result)
        if self.command == "POST" and path == "/api/projects":
            body = self.body_json()
            ident = str(body.get("id", "")).strip()
            if not ident or not ident.replace("_", "").replace("-", "").isalnum():
                raise ValueError("Project ID must contain only letters, numbers, _ or -")
            p = PROJECTS / ident
            if p.exists():
                raise ValueError("Project already exists")
            for directory in (p / "data", p / "charts", p / "lib", p / "outputs", p / "history"):
                directory.mkdir(parents=True, exist_ok=True)
            (p / "project.json").write_text(json.dumps({"name": str(body.get("name", ident))[:80],
                "description": str(body.get("description", ""))[:300]}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            (p / "data_sources.json").write_text(
                json.dumps({"version": 1, "sources": []}, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            change = record_change(ROOT, [p], f"Create project {ident}")
            return self.json_response({"project": ident, "git": change})
        if len(parts) >= 3 and parts[:2] == ["api", "projects"]:
            p = project_path(parts[2])
            if self.command == "POST" and len(parts) == 4 and parts[3] == "data":
                body = self.body_json()
                name = str(body.get("name", ""))
                suffix = Path(name).suffix.lower()
                stem = Path(name).stem
                if suffix not in (".csv", ".tsv", ".json") or not stem.replace("_", "").replace("-", "").isalnum():
                    raise ValueError("表格文件名只能包含字母、数字、_ 或 -")
                content = body.get("content", "")
                if not isinstance(content, str) or len(content) > 250_000:
                    raise ValueError("数据文件超过 250 KB；请使用数据源导入")
                row_count = validate_tabular_content(name, content)
                f = p / "data" / name
                f.write_text(content, encoding="utf-8")
                change = record_change(ROOT, [f], f"Import data {parts[2]}/{name}")
                return self.json_response({"file": name, "rows": row_count, "git": change})
            if self.command == "POST" and len(parts) == 4 and parts[3] == "charts":
                body = self.body_json()
                name = str(body.get("name", ""))
                if not name or not name.replace("_", "").isalnum():
                    raise ValueError("Chart name must contain only letters, numbers or _")
                f = p / "charts" / (name + ".py")
                if f.exists():
                    raise ValueError("Chart already exists")
                source = ("import os\nfrom pathlib import Path\nimport matplotlib.pyplot as plt\n"
                    "from studio_style import apply_style, finish_figure\n\napply_style()\n"
                    "project = Path(os.environ['CHART_PROJECT_DIR'])\n"
                    "fig, ax = plt.subplots(figsize=(4.5, 3.2))\n"
                    "ax.set(xlabel='X', ylabel='Y', title='New chart')\n"
                    "finish_figure(fig, os.environ['CHART_OUTPUT'])\n")
                f.write_text(source, encoding="utf-8")
                change = record_change(ROOT, [f], f"Create chart {parts[2]}/{name}")
                return self.json_response({"chart": name, "git": change})
            if self.command == "GET" and len(parts) == 4 and parts[3] == "data":
                return self.json_response({"data": data_preview(p),
                                           "data_sources": project_data_sources(p)})
            if len(parts) == 6 and parts[3] == "modules":
                project, module_id, action = parts[2], parts[4], parts[5]
                module = resolve_module(p, module_id)
                query = parse_qs(parsed.query)
                selected_chart = str((query.get("chart") or [""])[0]).strip()
                if self.command == "GET" and action == "detail":
                    return self.json_response(shared_module_detail(p, module_id))
                if self.command == "GET" and action in ("preview", "svg", "pdf"):
                    _, chart_file = chart_path(project, selected_chart)
                    suffix = {"preview": ".png", "svg": ".svg", "pdf": ".pdf"}[action]
                    data = render(p, chart_file.read_text(encoding="utf-8"), suffix)
                    mime = {".png": "image/png", ".svg": "image/svg+xml", ".pdf": "application/pdf"}[suffix]
                    filename = f"{selected_chart}{suffix}" if action != "preview" else None
                    return self.bytes_response(data, mime, filename)
                if self.command == "POST" and action in ("propose", "apply", "restore"):
                    body = self.body_json()
                    selected_chart = str(body.get("chart", selected_chart)).strip()
                    chart_path(project, selected_chart)
                    if action == "propose":
                        prompt = str(body.get("prompt", "")).strip()
                        if not prompt or len(prompt) > 5000:
                            raise ValueError("Enter an instruction under 5000 characters")
                        descriptor = next(
                            item for item in discover_modules(p) if item["id"] == module_id
                        )
                        code = llm_proposal(
                            prompt,
                            module.read_text(encoding="utf-8"),
                            [],
                            resource_type="module",
                            module_path=descriptor["path"],
                            chart=selected_chart,
                        )
                        return self.json_response({
                            "code": code,
                            "reply": "共享绘图模块代码已生成。检查后点击“应用修改”进行代表图验证。",
                        })
                    if action == "restore":
                        revision = str(body.get("id", ""))
                        new_code = module_revision_source(p, module_id, revision)
                        note = "恢复版本：" + revision
                    else:
                        new_code = body.get("code", "")
                        note = str(body.get("note", "手动修改共享绘图模块"))[:300]
                    result = save_shared_module(
                        project, module_id, new_code, selected_chart, note
                    )
                    if result["changed"]:
                        change = record_change(
                            ROOT,
                            [module, p / "history" / "modules" / module_id],
                            f"Update shared module {project}/{module.name}: {note[:80]}",
                        )
                        message = "共享绘图模块已验证、保存并记录版本"
                    else:
                        change = git_status(ROOT)
                        message = "代码没有变化，代表图验证通过"
                    return self.json_response({
                        "message": message,
                        "revision": result.get("revision"),
                        "git": change,
                    })
            if len(parts) == 6 and parts[3] == "charts":
                project, chart, action = parts[2], parts[4], parts[5]
                p, f = chart_path(project, chart)
                if self.command == "GET" and action == "detail":
                    return self.json_response({"code": f.read_text(encoding="utf-8"),
                                               "history": read_history(p, chart),
                                               "data": data_preview(p),
                                               "data_sources": project_data_sources(p),
                                               "style": STYLE.read_text(encoding="utf-8")})
                if self.command == "GET" and action in ("preview", "svg", "pdf"):
                    suffix = {"preview": ".png", "svg": ".svg", "pdf": ".pdf"}[action]
                    data = render(p, f.read_text(encoding="utf-8"), suffix)
                    mime = {".png": "image/png", ".svg": "image/svg+xml", ".pdf": "application/pdf"}[suffix]
                    return self.bytes_response(data, mime, f"{chart}{suffix}" if action != "preview" else None)
                if self.command == "POST" and action in ("propose", "apply", "restore"):
                    body = self.body_json()
                    if action == "propose":
                        prompt = str(body.get("prompt", "")).strip()
                        if not prompt or len(prompt) > 5000:
                            raise ValueError("Enter an instruction under 5000 characters")
                        code = llm_proposal(prompt, f.read_text(encoding="utf-8"), data_preview(p))
                        return self.json_response({"code": code, "reply": "代码已生成。检查后点击“应用修改”以渲染和保存。"})
                    if action == "restore":
                        history = read_history(p, chart)
                        entry = next((x for x in history if x["id"] == body.get("id")), None)
                        if entry is None:
                            raise ValueError("History entry not found")
                        new_code = (p / "history" / (entry["id"] + ".py")).read_text(encoding="utf-8")
                        note = "恢复版本：" + entry["id"]
                    else:
                        new_code = body.get("code", "")
                        note = str(body.get("note", "手动修改"))[:300]
                        if not isinstance(new_code, str) or len(new_code) > 100_000:
                            raise ValueError("Invalid source")
                    ast.parse(new_code)
                    render(p, new_code)  # Validate before replacing the working chart.
                    old_code = f.read_text(encoding="utf-8")
                    if old_code == new_code:
                        return self.json_response({"message": "代码没有变化"})
                    stamp = datetime.now(timezone.utc).isoformat()
                    revision = uuid.uuid4().hex[:12]
                    history = read_history(p, chart)
                    if not history:
                        base_id = uuid.uuid4().hex[:12]
                        (p / "history" / (base_id + ".py")).write_text(old_code, encoding="utf-8")
                        history.append({"id": base_id, "time": stamp, "note": "初始版本"})
                    (p / "history" / (revision + ".py")).write_text(new_code, encoding="utf-8")
                    f.write_text(new_code, encoding="utf-8")
                    history.append({"id": revision, "time": stamp, "note": note})
                    write_history(p, chart, history)
                    change = record_change(
                        ROOT, [f, p / "history"], f"Update {project}/{chart}: {note[:80]}"
                    )
                    return self.json_response({"message": "已保存并记录版本", "revision": revision,
                                               "git": change})
        self.json_response({"error": "Route not found"}, 404)

    def body_multipart(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length < 1 or length > MAX_UPLOAD_BODY:
            raise ValueError("上传内容为空或超过 550 MB 请求上限")
        return cgi.FieldStorage(fp=self.rfile, headers=self.headers, environ={
            "REQUEST_METHOD": "POST",
            "CONTENT_TYPE": self.headers.get("Content-Type", ""),
            "CONTENT_LENGTH": str(length),
        })

    def body_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length < 1 or length > MAX_BODY:
            raise ValueError("Request body too large or missing")
        return json.loads(self.rfile.read(length))

    def do_GET(self):
        try:
            self.route()
        except Exception as e:
            self.json_response({"error": str(e)}, 400)

    def do_POST(self):
        try:
            self.route()
        except Exception as e:
            self.json_response({"error": str(e)}, 400)


if __name__ == "__main__":
    port = int(os.environ.get("CHART_STUDIO_PORT", "8765"))
    print(f"Chart Studio: http://127.0.0.1:{port}\nProject folder: {ROOT}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
