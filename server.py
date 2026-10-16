"""Local-only chart studio. Start with `python server.py`."""
import ast
import cgi
import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, unquote, parse_qs
from agent_importer import import_package
from generic_importer import import_generic
from bundle_importer import PlotBundleAdapter, import_plot_bundle
from data_sources import resolve_allowed_path
from git_support import git_status, record_change
from shared_modules import MAX_SHARED_MODULE_SOURCE, apply_module, discover_modules, module_revision_source, read_module_history, resolve_module
import llm_client
from llm_workflows import edit_chart
from upload_importer import store_upload, store_multipart_upload, store_bundle_multipart
from agent_http import post_json
from chart_naming import RenderedImage
from chat_harness import ChatHarness, lock as workflow_lock
from model_config import public as public_model_config, save as save_model_config, clear as clear_model_config, test_connection as test_model_connection, effective as effective_model_config

from collaboration_sync import CollaborationSync, SyncConflict
from local_execution import require_trust, trusted
from chat_runner import isolation_backend

ROOT = Path(__file__).resolve().parent
SYNC = CollaborationSync(ROOT)
PROJECTS = ROOT / "projects"
STATIC = ROOT / "static"
STYLE = ROOT / "skills" / "plot-style" / "SKILL.md"
NORMALIZATION_SKILL = ROOT / "skills" / "chart-normalization" / "SKILL.md"
NORMALIZATION_PROFILE = NORMALIZATION_SKILL.parent / "assets" / "style-profile.v1.json"
SKILL_CATALOG = ROOT / "skills" / "normalization-catalog"
PREVIEW_POOL = ThreadPoolExecutor(max_workers=2)
PREVIEW_LOCKS = {}
PREVIEW_LOCKS_GUARD = threading.Lock()
IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".svg": "image/svg+xml"}
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



def source_revision(source):
    return "sha256:" + hashlib.sha256(source.encode("utf-8")).hexdigest()


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


def forget_module_previews(p):
    # Signature checks prevent stale caches; eagerly invalidate metadata for the gallery.
    for file in (p / "chart_metadata").glob("*.json"):
        file.unlink(missing_ok=True)


def read_history(p, chart):
    f = p / "history" / (chart + ".json")
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else []


def history_view(p, chart):
    entries = read_history(p, chart)
    allowed_code = {item["id"] for item in (entries[:1] + entries[-2:-1])}
    for entry in entries:
        old_source = (p / "history" / (entry["id"] + ".py")).is_file()
        entry["code_available"] = entry["id"] in allowed_code and old_source
        entry["image_available"] = old_source or any((p / "history" / (entry["id"] + ext)).is_file() for ext in IMAGE_TYPES)
    return entries


def write_history(p, chart, entries):
    (p / "history").mkdir(exist_ok=True)
    (p / "history" / (chart + ".json")).write_text(
        json.dumps(entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def skill_catalog():
    hidden_file = SKILL_CATALOG / ".hidden.json"
    hidden = json.loads(hidden_file.read_text(encoding="utf-8")) if hidden_file.exists() else []
    skills = []
    if "chart-normalization" not in hidden:
        skills.append({"id": "chart-normalization", "name": "统一绘图规范", "built_in": True})
    if SKILL_CATALOG.exists():
        for folder in sorted(SKILL_CATALOG.iterdir()):
            if folder.is_dir() and (folder / "SKILL.md").is_file():
                meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
                skills.append({"id": folder.name, "name": meta["name"], "built_in": False})
    return skills


def skill_files(skill_id):
    if skill_id == "chart-normalization":
        folder = NORMALIZATION_SKILL.parent
    elif skill_id and skill_id.replace("_", "").replace("-", "").isalnum():
        folder = SKILL_CATALOG / skill_id
    else:
        raise ValueError("Invalid skill ID")
    if skill_id not in {item["id"] for item in skill_catalog()}:
        raise ValueError("Skill not found")
    skill = folder / "SKILL.md"
    profile = folder / "assets" / "style-profile.v1.json"
    return skill.read_text(encoding="utf-8"), json.loads(profile.read_text(encoding="utf-8")) if profile.exists() else {}


def preview_signature(p, source):
    files = [*p.glob('*.py'), *p.glob('data_sources.json'), *((p/'data').rglob('*')), *((p/'lib').rglob('*'))]
    dependencies=[]
    for f in sorted(set(files)):
        if f.is_file() and f.suffix.lower() in ('.py','.csv','.tsv','.json') and '__pycache__' not in f.parts:
            if f.is_symlink() or not f.resolve().is_relative_to(p.resolve()):raise ValueError('External project dependency')
            dependencies.append((f.relative_to(p).as_posix(),hashlib.sha256(f.read_bytes()).hexdigest()))
    from bundle_bindings import signature as bundle_signature
    bundle_revision=bundle_signature(p)
    if bundle_revision: dependencies.append(('@bundle/source',bundle_revision))
    for f in (ROOT/'studio_style.py',NORMALIZATION_PROFILE):
        dependencies.append(('@platform/'+str(f.relative_to(ROOT)),hashlib.sha256(f.read_bytes()).hexdigest()))
    return hashlib.sha256(json.dumps(['preview-v2',source_revision(source),dependencies]).encode()).hexdigest()


def preview_lock(p, chart):
    key = (str(p), chart)
    with PREVIEW_LOCKS_GUARD:
        return PREVIEW_LOCKS.setdefault(key, threading.RLock())


def save_preview(p, chart, source, data, suffix=".png"):
    with preview_lock(p, chart):
        entry=p/'charts'/(chart+'.py')
        if entry.is_file() and entry.read_text(encoding='utf-8')!=source:
            raise ValueError('Chart changed before saving the preview; retry with its current version')
        folder = p / "previews"
        folder.mkdir(exist_ok=True)
        for old in folder.glob(chart + ".*"):
            if old.suffix in IMAGE_TYPES and old.suffix != suffix:
                old.unlink()
        target = folder / (chart + suffix)
        temp = folder / (chart + ".tmp")
        temp.write_bytes(data)
        temp.replace(target)
        (folder / (chart + ".json")).write_text(json.dumps({"signature": preview_signature(p, source), "suffix": suffix}), encoding="utf-8", newline="\n")
        if getattr(data, "naming", None) is not None:
            save_naming(p, chart, source, data.naming)
        return data, IMAGE_TYPES[suffix]


def preview_asset(p, chart, source):
    folder = p / "previews"
    meta_file = folder / (chart + ".json")
    with preview_lock(p, chart):
        entry=p/'charts'/(chart+'.py')
        if entry.is_file() and entry.read_text(encoding='utf-8')!=source:
            # Historical snapshots must never overwrite the current chart preview.
            return render(p,source),'image/png'
        signature=preview_signature(p,source)
        if meta_file.exists():
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
                target = folder / (chart + meta["suffix"])
                if meta["signature"] == signature and target.is_file():
                    return target.read_bytes(), IMAGE_TYPES[meta["suffix"]]
            except (KeyError, ValueError):
                pass
        rendered=render(p,source)
        if signature!=preview_signature(p,source):raise ValueError('Chart dependencies changed during rendering; retry')
        return save_preview(p, chart, source, rendered)


def snapshot_image(p, chart, revision, source, data=None):
    data, mime = (data, "image/png") if data is not None else preview_asset(p, chart, source)
    suffix = next(ext for ext, kind in IMAGE_TYPES.items() if kind == mime)
    (p / "history").mkdir(exist_ok=True)
    (p / "history" / (revision + suffix)).write_bytes(data)
    return suffix


def save_naming(p, chart, source, naming):
    folder = p / "chart_metadata"
    folder.mkdir(exist_ok=True)
    target = folder / (chart + ".json")
    temp = folder / (chart + "." + uuid.uuid4().hex + ".tmp")
    temp.write_text(json.dumps({"signature": preview_signature(p, source), **naming}, ensure_ascii=False), encoding="utf-8", newline="\n")
    temp.replace(target)


def chart_naming(p, chart):
    source = (p / "charts" / (chart + ".py")).read_text(encoding="utf-8")
    try:
        info = json.loads((p / "chart_metadata" / (chart + ".json")).read_text(encoding="utf-8"))
        if info.get("signature") == preview_signature(p, source):
            return {"display_name": chart, **info}
    except (OSError, ValueError):
        pass
    return {"display_name": chart, "status": "pending"}


def warm_project_previews(project_id):
    p = project_path(project_id)
    if json.loads((p / "project.json").read_text(encoding="utf-8")).get("data_source_type") == "plot_bundle":
        return  # Large Bundles are rendered on demand, not all at startup.
    if isolation_backend() == "local-python" and not trusted(p):
        return
    meta = json.loads((p / "project.json").read_text(encoding="utf-8"))
    excluded = set(meta.get("non_chart_scripts", []))
    for f in sorted((p / "charts").glob("*.py")):
        if f.stem in excluded:
            continue
        try:
            source = f.read_text(encoding="utf-8")
            preview_asset(p, f.stem, source)
            if chart_naming(p, f.stem)["status"] == "pending":
                rendered = render(p, source)
                if f.read_text(encoding="utf-8") == source:
                    save_naming(p, f.stem, source, rendered.naming or {"status": "fallback"})
        except Exception as error:
            print(f"Preview {project_id}/{f.stem}: {error}", flush=True)


def copy_uploaded_images(upload, p):
    source = upload / "images"
    if not source.is_dir():
        return 0
    original = p / "images" / "original"
    original.mkdir(parents=True, exist_ok=True)
    count = 0
    for image in source.iterdir():
        if not image.is_file() or image.suffix.lower() not in IMAGE_TYPES:
            continue
        shutil.copy2(image, original / image.name)
        chart = image.stem
        if not (p / "charts" / (chart + ".py")).is_file():
            import re
            chart = re.sub(r"[^A-Za-z0-9_]+", "_", chart).strip("_")
        target = p / "charts" / (chart + ".py")
        if target.is_file():
            save_preview(p, chart, target.read_text(encoding="utf-8"), image.read_bytes(), image.suffix.lower())
        count += 1
    return count


def render(p, source, suffix=".png", library_path=None):
    if isolation_backend() == "local-python":
        require_trust(p)
    with tempfile.TemporaryDirectory(prefix="chart-studio-") as d:
        temp = Path(d)
        script = temp / "chart.py"
        output = temp / ("figure" + suffix)
        script.write_text(source, encoding="utf-8", newline="\n")
        metadata = temp / "naming.json"
        runner = temp / "runner.py"
        runner.write_text("from chart_naming import install_capture\nfrom render_paths import install_project_library\nimport runpy\n"
                          + f"install_project_library({str(p)!r}, {str(library_path or p / 'lib')!r})\n"
                          + f"install_capture({str(output)!r}, {str(metadata)!r})\n"
                          + f"runpy.run_path({str(script)!r}, run_name='__main__')\n", encoding="utf-8", newline="\n")
        env = os.environ.copy()
        env["CHART_PROJECT_DIR"] = str(p)
        env["CHART_OUTPUT"] = str(output)
        env["PYTHONPATH"] = os.pathsep.join(([str(library_path)] if library_path else []) + [str(p / "lib"), str(ROOT)])
        env["PYTHONIOENCODING"] = "utf-8"
        mpl_cache = ROOT / ".mplconfig"
        mpl_cache.mkdir(exist_ok=True)
        env["MPLCONFIGDIR"] = str(mpl_cache)
        timeout = int(os.environ.get("CHART_RENDER_TIMEOUT", "120"))
        try:
            result = subprocess.run([sys.executable, str(runner)], cwd=p, env=env,
                                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
        except subprocess.TimeoutExpired:
            raise ValueError(f"Render timed out after {timeout} seconds")
        if result.returncode or not output.is_file():
            raise ValueError("Render failed: " + (result.stderr[-3500:] or "No output file"))
        image = RenderedImage(output.read_bytes())
        image.naming = json.loads(metadata.read_text(encoding="utf-8")) if metadata.exists() else {"status": "fallback", "reason": "未捕获到绘图轴信息"}
        return image


def git(*args):
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
    except (OSError, subprocess.TimeoutExpired) as error:
        return subprocess.CompletedProcess(["git", *args], 127, "", str(error))


def list_projects():
    result = []
    for p in sorted(PROJECTS.iterdir()):
        if (p / "project.json").is_file():
            meta = json.loads((p / "project.json").read_text(encoding="utf-8"))
            excluded = set(meta.get("non_chart_scripts", []))
            charts = [f.stem for f in sorted((p / "charts").glob("*.py")) if f.stem not in excluded]
            result.append({"id": p.name, **meta, "chart_metadata": {c: chart_naming(p, c) for c in charts},
                           "charts": [f.stem for f in sorted((p / "charts").glob("*.py")) if f.stem not in excluded],
                           "modules": discover_modules(p), "data_sources": project_data_sources(p),
                           "data": [f.relative_to(p / "data").as_posix() for f in sorted((p / "data").rglob("*")) if f.is_file() and f.suffix.lower() in {".csv", ".tsv", ".json"}]})
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
        "source_revision": source_revision(module.read_text(encoding="utf-8")),
    }


def save_shared_module(project, module_id, source, chart, note, validation_scope="representative", base_revision=None):
    p, chart_file = chart_path(project, chart)
    if validation_scope not in {"representative", "all"}:
        raise ValueError("请选择代表图验证或全项目图表验证")
    module = resolve_module(p, module_id)
    if base_revision is not None and source_revision(module.read_text(encoding="utf-8")) != base_revision:
        raise ValueError("共享模块已变化，请重新打开后再修改")

    def render_candidate(selected_chart, candidate_library):
        if selected_chart != chart:
            raise ValueError("代表图已发生变化")
        sources = [chart_file] if validation_scope == "representative" else sorted((p / "charts").glob("*.py"))
        if not sources: raise ValueError("项目没有可用于验证的图表")
        preview = None
        for entry in sources:
            preview = render(p, entry.read_text(encoding="utf-8"), library_path=candidate_library)
        return preview

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




CHAT = ChatHarness(sys.modules[__name__])

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


def llm_proposal(prompt, source, data, validator=None, resource_type="chart", module_path=None, chart=None):
    if resource_type != "module":
        return edit_chart(prompt, source, data, validator=validator)
    message = llm_client.chat([
        {"role": "system", "content": llm_instruction("module")},
        {"role": "user", "content": json.dumps({"request": prompt, "current_code": source,
            "module_path": module_path, "validation_chart": chart}, ensure_ascii=False)}])
    code = message.strip()
    if code.startswith("```"):
        code = code.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    ast.parse(code)
    if len(code) > MAX_SHARED_MODULE_SOURCE:
        raise ValueError("模型返回的共享模块过大")
    return code + "\n"



class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print("%s %s" % (self.address_string(), fmt % args))

    def json_response(self, value, status=200):
        body = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
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
        port = int(os.environ.get('CHART_STUDIO_PORT', '8765'))
        if self.headers.get('Host') not in (f'127.0.0.1:{port}', f'localhost:{port}'):
            raise ValueError('请通过本机 localhost 或 127.0.0.1 打开工作台')
        origin = self.headers.get('Origin')
        if self.command != 'GET' and origin and origin not in (f'http://127.0.0.1:{port}', f'http://localhost:{port}'):
            raise ValueError('修改请求必须来自当前本地工作台')
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        parts = [x for x in path.split("/") if x]
        from ly_api import handle_data_sources
        if path.startswith("/api/data-sources/"):
            return handle_data_sources(self, path)
        if path == "/api/health" and self.command == "GET":
            return self.json_response({"app": "plot-forge", "root": str(ROOT), "backend": isolation_backend(),
                "pid": os.getpid(), "desktop_release": os.environ.get('PLOT_FORGE_DESKTOP_RELEASE')})
        if path == "/api/collaboration":
            if self.command == "GET":
                return self.json_response({**SYNC.status(), "backend": isolation_backend(),
                    "trusted_projects": [p.name for p in PROJECTS.iterdir() if p.is_dir() and trusted(p)]})
            if self.command == "POST":
                self.check_local_json()
                return self.json_response(SYNC.configure(self.body_json()))
        if path in ("/api/collaboration/pull", "/api/collaboration/publish") and self.command == "POST":
            self.check_local_json()
            body = self.body_json()
            try:
                return self.json_response(SYNC.sync(path.endswith("/publish"), body.get("message", "")))
            except SyncConflict as exc:
                return self.json_response({"error": str(exc), "conflicts": exc.paths}, 409)
        if self.command == "GET" and path in ("/", "/index.html"):
            return self.bytes_response((STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
        if self.command == "GET" and path in ("/legacy", "/legacy/"):
            return self.bytes_response((STATIC / "legacy" / "index.html").read_bytes(), "text/html; charset=utf-8")
        if self.command == "GET" and path == "/static/app.css":
            return self.bytes_response((STATIC / "app.css").read_bytes(), "text/css; charset=utf-8")
        if self.command == "GET" and path == "/static/ly_features.js":
            return self.bytes_response((STATIC / "ly_features.js").read_bytes(), "text/javascript; charset=utf-8")
        if self.command == "GET" and path == "/static/collaboration.js":
            return self.bytes_response((STATIC / "collaboration.js").read_bytes(), "text/javascript; charset=utf-8")
        if self.command == "GET" and path == "/static/app.js":
            return self.bytes_response((STATIC / "app.js").read_bytes(), "text/javascript; charset=utf-8")
        if self.command == "GET" and path in ("/static/legacy/app.css", "/static/legacy/app.js"):
            name = Path(path).name
            mime = "text/css; charset=utf-8" if name.endswith(".css") else "text/javascript; charset=utf-8"
            return self.bytes_response((STATIC / "legacy" / name).read_bytes(), mime)
        if path == '/api/model-config' or path == '/api/model-config/test':
            if self.command == 'GET' and path == '/api/model-config':
                return self.json_response(public_model_config())
            if ((self.command == 'POST' and path in ('/api/model-config', '/api/model-config/test'))
                    or (self.command == 'DELETE' and path == '/api/model-config')):
                origin = self.headers.get('Origin')
                port = int(os.environ.get('CHART_STUDIO_PORT', '8765'))
                if origin and origin not in (f'http://127.0.0.1:{port}', f'http://localhost:{port}'):
                    raise ValueError('配置请求必须来自当前工作台')
                if self.headers.get('Content-Type', '').split(';')[0].strip().lower() != 'application/json':
                    raise ValueError('配置请求需要 application/json')
                if self.command == 'DELETE':
                    return self.json_response(clear_model_config())
                if path.endswith('/test'):
                    self.body_json()
                    return self.json_response(test_model_connection())
                return self.json_response(save_model_config(self.body_json()))
            return self.json_response({'error': 'Model config route not found'}, 404)
        if self.command == "GET" and path == "/api/projects":
            return self.json_response({"projects": list_projects(), "root": str(ROOT),
                                       "llm_enabled": bool(effective_model_config()['api_key']) or llm_client.is_configured()})
        if len(parts) == 5 and parts[:2] == ["api", "projects"] and parts[3:5] == ["chat", "history"] and self.command == "GET":
            project_path(parts[2])
            return self.json_response({"sessions": CHAT.history(parts[2])})
        if len(parts) >= 5 and parts[:2] == ["api", "projects"] and parts[3:5] == ["chat", "sessions"]:
            project = parts[2]
            project_path(project)
            if len(parts) == 5:
                if self.command == "GET":
                    query = parse_qs(parsed.query)
                    charts = query.get("charts", [None])[0]
                    return self.json_response({"sessions": CHAT.list(project, charts.split(",") if charts else None)})
                if self.command == "POST":
                    body = self.body_json()
                    return self.json_response(CHAT.create(project, body.get("charts"), body.get("reference_charts", [])))
            if len(parts) == 6 and self.command == "GET":
                return self.json_response(CHAT.get(project, parts[5]))
            if len(parts) == 7 and self.command == "POST" and parts[6] in ("turns", "normalize"):
                return self.json_response(CHAT.turn(project, parts[5], self.body_json(), normalize=parts[6] == "normalize"))
            if len(parts) == 9 and parts[6] == "drafts":
                sid, did, action = parts[5], parts[7], parts[8]
                if self.command == "GET" and action in ("image", "baseline-image"):
                    session = CHAT.load(project, sid)
                    draft = next((d for d in session["drafts"] if d["id"] == did), None)
                    image_key = "image_path" if action == "image" else "baseline_image_path"
                    if not draft or not draft.get(image_key):
                        raise ValueError("该版本的图片尚未生成")
                    image = Path(draft[image_key])
                    if not image.resolve().is_relative_to(CHAT.path(project, sid).parent.resolve()):
                        raise ValueError("Invalid draft image path")
                    return self.bytes_response(image.read_bytes(), "image/png")
                if self.command == "POST" and action in ("apply", "activate", "discard", "recheck"):
                    self.body_json()
                    return self.json_response(CHAT.draft_action(project, sid, did, action))
            return self.json_response({"error": "Chat route not found"}, 404)
        if path == "/api/normalization-skills":
            if self.command == "GET":
                return self.json_response({"skills": skill_catalog()})
            if self.command == "POST":
                body = self.body_json()
                ident, name = str(body.get("id", "")).strip(), str(body.get("name", "")).strip()
                content = body.get("content", "")
                profile = body.get("profile", {})
                if not ident or not ident.replace("_", "").replace("-", "").isalnum() or ident == "chart-normalization":
                    raise ValueError("Skill ID must contain letters, numbers, _ or - and be unique")
                if not name or len(name) > 80 or not isinstance(content, str) or not content.strip() or len(content) > 100_000:
                    raise ValueError("Invalid Skill name or SKILL.md content")
                if not isinstance(profile, dict):
                    raise ValueError("Style profile must be a JSON object")
                folder = SKILL_CATALOG / ident
                if folder.exists():
                    raise ValueError("Skill ID already exists")
                (folder / "assets").mkdir(parents=True)
                (folder / "SKILL.md").write_text(content, encoding="utf-8", newline="\n")
                (folder / "assets" / "style-profile.v1.json").write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
                (folder / "meta.json").write_text(json.dumps({"name": name}, ensure_ascii=False), encoding="utf-8", newline="\n")
                return self.json_response({"id": ident, "name": name})
        if len(parts) == 3 and parts[:2] == ["api", "normalization-skills"]:
            skill_id = parts[2]
            if self.command == "GET":
                content, profile = skill_files(skill_id)
                return self.json_response({"id": skill_id, "content": content, "profile": profile})
            if self.command == "DELETE":
                skill_files(skill_id)
                if skill_id == "chart-normalization":
                    SKILL_CATALOG.mkdir(exist_ok=True)
                    (SKILL_CATALOG / ".hidden.json").write_text('["chart-normalization"]', encoding="utf-8", newline="\n")
                else:
                    shutil.rmtree(SKILL_CATALOG / skill_id)
                return self.json_response({"deleted": skill_id})
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
            metadata_file = PROJECTS / project_id / "project.json"
            metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
            metadata.setdefault("created_by", SYNC.config().get("name", "本地协作者"))
            metadata["updated_by"] = SYNC.config().get("name", "本地协作者")
            metadata["updated_at"] = datetime.now(timezone.utc).isoformat()
            metadata_file.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
            result["images"] = copy_uploaded_images(upload, PROJECTS / project_id)
            result["github_synced"] = False
            PREVIEW_POOL.submit(warm_project_previews, project_id)
            return self.json_response(result)
        if self.command == "POST" and path == "/api/agent/import":
            body = self.body_json()
            result = import_package(ROOT, str(body.get("source", "")), str(body.get("project_id", "")), str(body.get("name", "")) or None)
            git("add", str((PROJECTS / result["project"]).relative_to(ROOT)))
            git("-c", "user.name=Chart Studio Agent", "-c", "user.email=agent-at-localhost", "commit", "-m", "Agent import " + result["project"])
            PREVIEW_POOL.submit(warm_project_previews, result["project"])
            return self.json_response(result)
        if self.command == "POST" and path == "/api/projects":
            body = self.body_json()
            ident = str(body.get("id", "")).strip()
            if not ident or not ident.replace("_", "").replace("-", "").isalnum():
                raise ValueError("Project ID must contain only letters, numbers, _ or -")
            p = PROJECTS / ident
            if p.exists():
                raise ValueError("Project already exists")
            for directory in (p / "data", p / "charts", p / "history"):
                directory.mkdir(parents=True, exist_ok=True)
            (p / "project.json").write_text(json.dumps({"name": str(body.get("name", ident))[:80],
                "description": str(body.get("description", ""))[:300], "created_by": SYNC.config().get("name", "本地协作者")}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
            git("add", str(p.relative_to(ROOT)))
            git("-c", "user.name=Chart Studio", "-c", "user.email=chart-studio@localhost", "commit", "-m", f"Create project {ident}")
            return self.json_response({"project": ident})
        if len(parts) >= 3 and parts[:2] == ["api", "projects"]:
            p = project_path(parts[2])
            if self.command == "POST" and len(parts) == 4 and parts[3] == "data":
                body = self.body_json()
                name = str(body.get("name", ""))
                if Path(name).name != name or Path(name).suffix.lower() not in {'.csv', '.tsv', '.json'} or not Path(name).stem.replace('_','').replace('-','').isalnum():
                    raise ValueError('表格文件名只能包含字母、数字、_ 或 -')
                content = body.get('content', '')
                if not isinstance(content, str) or len(content) > 250_000:
                    raise ValueError('数据文件超过 250 KB，请使用数据源导入')
                row_count = validate_tabular_content(name, content)
                f = p / "data" / name
                f.write_text(content, encoding="utf-8", newline="\n")
                git("add", str(f.relative_to(ROOT)))
                git("-c", "user.name=Chart Studio", "-c", "user.email=chart-studio@localhost", "commit", "-m", f"Import data {parts[2]}/{name}")
                return self.json_response({"file": name, "rows": row_count})
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
                f.write_text(source, encoding="utf-8", newline="\n")
                git("add", str(f.relative_to(ROOT)))
                git("-c", "user.name=Chart Studio", "-c", "user.email=chart-studio@localhost", "commit", "-m", f"Create chart {parts[2]}/{name}")
                PREVIEW_POOL.submit(warm_project_previews, parts[2])
                return self.json_response({"chart": name})
            if self.command == "GET" and len(parts) == 4 and parts[3] == "data":
                return self.json_response({"data": data_preview(p), "data_sources": project_data_sources(p)})
            if self.command == "GET" and len(parts) == 8 and parts[3] == "charts" and parts[5] == "history" and parts[7] == "image":
                p, _ = chart_path(parts[2], parts[4])
                entry = next((x for x in read_history(p, parts[4]) if x["id"] == parts[6]), None)
                if entry is None:
                    raise ValueError("History entry not found")
                for suffix, mime in IMAGE_TYPES.items():
                    image = p / "history" / (entry["id"] + suffix)
                    if image.is_file():
                        return self.bytes_response(image.read_bytes(), mime)
                old_code = p / "history" / (entry["id"] + ".py")
                if old_code.is_file():
                    suffix = snapshot_image(p, parts[4], entry["id"], old_code.read_text(encoding="utf-8"),
                                            render(p, old_code.read_text(encoding="utf-8")))
                    entries = read_history(p, parts[4])
                    allowed_code = {item["id"] for item in (entries[:1] + entries[-2:-1])}
                    if entry["id"] not in allowed_code:
                        old_code.unlink(missing_ok=True)
                    return self.bytes_response((p / "history" / (entry["id"] + suffix)).read_bytes(), IMAGE_TYPES[suffix])
                raise ValueError("This older version has no saved image")
            if len(parts) >= 6 and parts[3] == "modules":
                from ly_api import handle_modules
                return handle_modules(self, parts, parsed)
            if len(parts) == 6 and parts[3] == "charts":
                project, chart, action = parts[2], parts[4], parts[5]
                p, f = chart_path(project, chart)
                if self.command == "GET" and action == "detail":
                    current_code = f.read_text(encoding="utf-8")
                    return self.json_response({"code": current_code, "revision": source_revision(current_code),
                                               "history": history_view(p, chart),
                                               "data": data_preview(p), "data_sources": project_data_sources(p), "style": NORMALIZATION_SKILL.read_text(encoding="utf-8")})
                if self.command == "GET" and action in ("preview", "svg", "pdf"):
                    suffix = {"preview": ".png", "svg": ".svg", "pdf": ".pdf"}[action]
                    source = f.read_text(encoding="utf-8")
                    if action == "preview":
                        data, mime = save_preview(p, chart, source, render(p, source)) if "force=1" in parsed.query.split("&") else preview_asset(p, chart, source)
                    else:
                        data, mime = render(p, source, suffix), {".svg": "image/svg+xml", ".pdf": "application/pdf"}[suffix]
                    return self.bytes_response(data, mime, f"{chart}{suffix}" if action != "preview" else None)
                if self.command == "POST" and action in ("propose", "normalize", "apply", "restore", "finalize"):
                    body = self.body_json()
                    current_code = f.read_text(encoding="utf-8")
                    if action == "finalize":
                        return self.json_response(CHAT.finalize(project,chart))
                    if action == "normalize":
                        session = CHAT.create(project, [chart])
                        return self.json_response(CHAT.turn(project, session["id"],
                            {"user_message": body.get("prompt", ""), "skill_id": body.get("skill_id", "chart-normalization")},
                            normalize=True))
                    if action == "propose":
                        prompt = str(body.get("prompt", "")).strip()
                        if not prompt or len(prompt) > 5000:
                            raise ValueError("Enter an instruction under 5000 characters")
                        validator = (lambda candidate: render(p, candidate)) if os.environ.get(
                            "LLM_VALIDATE_RENDER", "").lower() in {"1", "true", "yes"} else None
                        code = llm_proposal(prompt, f.read_text(encoding="utf-8"), csv_preview(p), validator)
                        return self.json_response({"code": code, "reply": "代码已生成。检查后点击“应用修改”以渲染和保存。"})
                    if action == "restore":
                        history = read_history(p, chart)
                        entry = next((x for x in history if x["id"] == body.get("id")), None)
                        if entry is None:
                            raise ValueError("History entry not found")
                        allowed_code = {item["id"] for item in (history[:1] + history[-2:-1])}
                        if entry["id"] not in allowed_code:
                            raise ValueError("此版本只保留图片；代码仅能恢复最早版或上一轮版")
                        new_code = (p / "history" / (entry["id"] + ".py")).read_text(encoding="utf-8")
                        note = "恢复版本：" + entry["id"]
                    else:
                        new_code = body.get("code", "")
                        note = str(body.get("note", "手动修改"))[:300]
                        if not isinstance(new_code, str) or len(new_code) > 100_000:
                            raise ValueError("Invalid source")
                    expected_revision = body.get("base_revision")
                    if expected_revision and expected_revision != source_revision(current_code):
                        raise ValueError("Chart changed since normalization started; refresh before applying")
                    ast.parse(new_code)
                    rendered = render(p, new_code)  # Validate before replacing the working chart.
                    old_code = f.read_text(encoding="utf-8")
                    if old_code != current_code:
                        raise ValueError("Chart changed during rendering; refresh before applying")
                    if old_code == new_code:
                        return self.json_response({"message": "代码没有变化"})
                    stamp = datetime.now(timezone.utc).isoformat()
                    revision = uuid.uuid4().hex[:12]
                    history = read_history(p, chart)
                    if not history:
                        base_id = uuid.uuid4().hex[:12]
                        (p / "history" / (base_id + ".py")).write_text(old_code, encoding="utf-8", newline="\n")
                        try:
                            snapshot_image(p, chart, base_id, old_code)
                        except ValueError:
                            pass
                        history.append({"id": base_id, "time": stamp, "note": "初始版本"})
                    else:
                        prior_id = history[-1]["id"]
                        (p / "history" / (prior_id + ".py")).write_text(old_code, encoding="utf-8", newline="\n")
                        if not any((p / "history" / (prior_id + ext)).exists() for ext in IMAGE_TYPES):
                            try:
                                snapshot_image(p, chart, prior_id, old_code)
                            except ValueError:
                                pass
                    f.write_text(new_code, encoding="utf-8", newline="\n")
                    save_preview(p, chart, new_code, rendered)
                    snapshot_image(p, chart, revision, new_code, rendered)
                    history.append({"id": revision, "time": stamp, "note": note})
                    keep_code = {history[0]["id"], history[-2]["id"]}
                    for entry in history:
                        old_snapshot = p / "history" / (entry["id"] + ".py")
                        if old_snapshot.is_file() and not any((p / "history" / (entry["id"] + ext)).is_file() for ext in IMAGE_TYPES):
                            keep_code.add(entry["id"])
                        if entry["id"] not in keep_code:
                            old_snapshot.unlink(missing_ok=True)
                    write_history(p, chart, history)
                    git("add", "-A", str(f.relative_to(ROOT)), str((p / "history").relative_to(ROOT)), str((p / "previews").relative_to(ROOT)))
                    commit = git("-c", "user.name=Chart Studio", "-c", "user.email=chart-studio@localhost",
                                 "commit", "-m", f"Update {project}/{chart}: {note[:80]}")
                    return self.json_response({"message": "已保存并记录版本", "revision": revision,
                                               "git": commit.returncode == 0})
        self.json_response({"error": "Route not found"}, 404)

    def check_local_json(self):
        port = int(os.environ.get('CHART_STUDIO_PORT', '8765'))
        if self.headers.get('Origin') not in (None, f'http://127.0.0.1:{port}', f'http://localhost:{port}'):
            raise ValueError('请求必须来自当前本地工作台')
        if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
            raise ValueError('请求需要 application/json')

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
        with SYNC.lock:
            self.post_locked()

    def post_locked(self):
        try:
            parts=[p for p in unquote(urlparse(self.path).path).split('/') if p]
            if len(parts)>=4 and parts[:2]==['api','projects'] and parts[3]!='chat' and parts[-1]!='finalize':
                with workflow_lock(project_path(parts[2])):self.route()
            else:self.route()
        except Exception as e:
            self.json_response({"error": str(e)}, 400)

    def do_DELETE(self):
        with SYNC.lock:
            self.delete_locked()

    def delete_locked(self):
        try:
            self.route()
        except Exception as e:
            self.json_response({"error": str(e)}, 400)


if __name__ == "__main__":
    port = int(os.environ.get("CHART_STUDIO_PORT", "8765"))
    print(f"Chart Studio: http://127.0.0.1:{port}\nProject folder: {ROOT}", flush=True)
    for existing in list_projects():
        PREVIEW_POOL.submit(warm_project_previews, existing["id"])
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
