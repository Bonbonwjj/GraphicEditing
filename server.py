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
from urllib.parse import urlparse, unquote
from agent_importer import import_package
from generic_importer import import_generic
from upload_importer import store_upload, store_multipart_upload

ROOT = Path(__file__).resolve().parent
PROJECTS = ROOT / "projects"
STATIC = ROOT / "static"
STYLE = ROOT / "skills" / "plot-style" / "SKILL.md"
MAX_BODY = 12_000_000
MAX_UPLOAD_BODY = 550_000_000


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


def render(p, source, suffix=".png"):
    with tempfile.TemporaryDirectory(prefix="chart-studio-") as d:
        temp = Path(d)
        script = temp / "chart.py"
        output = temp / ("figure" + suffix)
        script.write_text(source, encoding="utf-8")
        env = os.environ.copy()
        env["CHART_PROJECT_DIR"] = str(p)
        env["CHART_OUTPUT"] = str(output)
        env["PYTHONPATH"] = str(ROOT)
        env["MPLCONFIGDIR"] = str(temp / "mpl")
        try:
            result = subprocess.run([sys.executable, str(script)], cwd=p, env=env,
                                    capture_output=True, text=True, timeout=20)
        except subprocess.TimeoutExpired:
            raise ValueError("Render timed out after 20 seconds")
        if result.returncode or not output.is_file():
            raise ValueError("Render failed: " + (result.stderr[-3500:] or "No output file"))
        return output.read_bytes()


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)


def list_projects():
    result = []
    for p in sorted(PROJECTS.iterdir()):
        if (p / "project.json").is_file():
            meta = json.loads((p / "project.json").read_text(encoding="utf-8"))
            result.append({"id": p.name, **meta,
                           "charts": [f.stem for f in sorted((p / "charts").glob("*.py"))],
                           "data": [f.name for f in sorted((p / "data").glob("*.csv"))]})
    return result


def csv_preview(p):
    out = []
    for f in sorted((p / "data").glob("*.csv")):
        with f.open(newline="", encoding="utf-8-sig") as stream:
            reader = csv.reader(stream)
            head = next(reader, [])
            rows = [r for _, r in zip(range(3), reader)]
        out.append({"file": f.name, "columns": head, "sample": rows})
    return out


def llm_proposal(prompt, source, data):
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise ValueError("Set OPENAI_API_KEY in your terminal to enable chat editing")
    url = os.environ.get("LLM_API_URL", "https://api.siliconflow.cn/v1/chat/completions")
    if urlparse(url).scheme != "https":
        raise ValueError("LLM_API_URL must use HTTPS")
    instruction = ("You edit one Python Matplotlib chart script. Return only the complete Python source, "
                   "without markdown fences. Follow the plot-style skill. Use only the listed CSV columns, "
                   "preserve CHART_PROJECT_DIR and CHART_OUTPUT, and never include network, shell, or secret access. "
                   "The user will review before applying.\n\n" + STYLE.read_text(encoding="utf-8"))
    payload = {"model": os.environ.get("LLM_MODEL", "Qwen/Qwen3.5-4B"),
               "messages": [{"role": "system", "content": instruction},
                            {"role": "user", "content": json.dumps({
                                "request": prompt, "csv_files": data, "current_code": source}, ensure_ascii=False)}],
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
    if len(proposed) > 100_000:
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
                                       "llm_enabled": bool(os.environ.get("OPENAI_API_KEY"))})
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
            git("add", str((PROJECTS / project_id).relative_to(ROOT)))
            commit = git("-c", "user.name=Chart Studio Agent", "-c", "user.email=agent-at-localhost", "commit", "-m", "Upload project " + project_id)
            if commit.returncode != 0:
                raise ValueError("项目已转换，但 Git 提交失败：" + commit.stderr[-500:])
            pushed = git("push", "origin", "main")
            result["github_synced"] = pushed.returncode == 0
            if pushed.returncode != 0:
                result["github_error"] = pushed.stderr[-700:]
            return self.json_response(result)
        if self.command == "POST" and path == "/api/agent/import":
            body = self.body_json()
            result = import_package(ROOT, str(body.get("source", "")), str(body.get("project_id", "")), str(body.get("name", "")) or None)
            git("add", str((PROJECTS / result["project"]).relative_to(ROOT)))
            git("-c", "user.name=Chart Studio Agent", "-c", "user.email=agent-at-localhost", "commit", "-m", "Agent import " + result["project"])
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
                "description": str(body.get("description", ""))[:300]}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            git("add", str(p.relative_to(ROOT)))
            git("-c", "user.name=Chart Studio", "-c", "user.email=chart-studio@localhost", "commit", "-m", f"Create project {ident}")
            return self.json_response({"project": ident})
        if len(parts) >= 3 and parts[:2] == ["api", "projects"]:
            p = project_path(parts[2])
            if self.command == "POST" and len(parts) == 4 and parts[3] == "data":
                body = self.body_json()
                name = str(body.get("name", ""))
                if not name.endswith(".csv") or not name[:-4].replace("_", "").replace("-", "").isalnum():
                    raise ValueError("CSV filename must contain only letters, numbers, _ or -")
                content = body.get("content", "")
                if not isinstance(content, str) or len(content) > 250_000:
                    raise ValueError("CSV exceeds 250 KB; place larger files directly in project/data")
                rows = list(csv.reader(content.splitlines()))
                if len(rows) < 2 or not rows[0]:
                    raise ValueError("CSV needs a header and at least one data row")
                f = p / "data" / name
                f.write_text(content, encoding="utf-8")
                git("add", str(f.relative_to(ROOT)))
                git("-c", "user.name=Chart Studio", "-c", "user.email=chart-studio@localhost", "commit", "-m", f"Import data {parts[2]}/{name}")
                return self.json_response({"file": name, "rows": len(rows)-1})
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
                git("add", str(f.relative_to(ROOT)))
                git("-c", "user.name=Chart Studio", "-c", "user.email=chart-studio@localhost", "commit", "-m", f"Create chart {parts[2]}/{name}")
                return self.json_response({"chart": name})
            if self.command == "GET" and len(parts) == 4 and parts[3] == "data":
                return self.json_response({"data": csv_preview(p)})
            if len(parts) == 6 and parts[3] == "charts":
                project, chart, action = parts[2], parts[4], parts[5]
                p, f = chart_path(project, chart)
                if self.command == "GET" and action == "detail":
                    return self.json_response({"code": f.read_text(encoding="utf-8"),
                                               "history": read_history(p, chart),
                                               "data": csv_preview(p), "style": STYLE.read_text(encoding="utf-8")})
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
                        code = llm_proposal(prompt, f.read_text(encoding="utf-8"), csv_preview(p))
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
                    git("add", str(f.relative_to(ROOT)), str((p / "history").relative_to(ROOT)))
                    commit = git("-c", "user.name=Chart Studio", "-c", "user.email=chart-studio@localhost",
                                 "commit", "-m", f"Update {project}/{chart}: {note[:80]}")
                    return self.json_response({"message": "已保存并记录版本", "revision": revision,
                                               "git": commit.returncode == 0})
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
