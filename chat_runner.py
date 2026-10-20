"""Render trusted candidates locally, or use optional Seatbelt/Docker isolation.

Local Python runs with user permissions. Only Seatbelt/Docker provide OS isolation. The metadata
checks are conservative diagnostics, not a proof of scientific equivalence or a
security boundary against a malicious Python program falsifying its own artists.
"""
from __future__ import annotations

import ast
from collections import Counter
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import signal
import subprocess
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parent
TIMEOUT_SECONDS = 45
MAX_INPUT_BYTES = 100 * 1024 * 1024
MAX_IMAGE_BYTES = 30 * 1024 * 1024


def _runtime_warnings(stderr):
    lines = [line.strip() for line in (stderr or '').splitlines() if line.strip()]
    counts = Counter(lines)
    result = []
    for line in dict.fromkeys(lines):
        if line.startswith('findfont: Font family') and 'not found' in line:
            result.append(f'{line}（重复 {counts[line]} 次；已合并字体日志）')
        elif counts[line] > 2:
            result.append(f'{line}（重复 {counts[line]} 次）')
        else:
            result.extend([line] * counts[line])
    return result


def _visual_change(baseline_path, candidate_path, baseline_signature, candidate_signature):
    from PIL import Image, ImageChops
    with Image.open(baseline_path) as original, Image.open(candidate_path) as edited:
        before, after = original.convert('RGB'), edited.convert('RGB')
    if before.size != after.size:
        return {'status':'changed','baseline_size':list(before.size),'candidate_size':list(after.size),
                'text_ink_ratios':{}}
    difference = ImageChops.difference(before, after)
    box = difference.getbbox()
    if box:
        red,green,blue = difference.split()
        mask = ImageChops.lighter(ImageChops.lighter(red,green),blue)
        changed = before.width * before.height - mask.histogram()[0]
    else:
        changed = 0
    before_texts = {item['key']:item for item in baseline_signature.get('texts', [])}
    text_ratios = {}
    text_items = candidate_signature.get('texts', []) if min(before.getpixel((0,0))) >= 220 else []
    for item in text_items:
        key = item['key']
        old = before_texts.get(key)
        if not old or old['text'] != item['text'] or not key.endswith(('.xlabel','.ylabel')):
            continue
        def ink(image, bbox):
            x0,y0,x1,y1 = bbox
            bounds = (max(0,int(x0)), max(0,int(image.height-y1)),
                      min(image.width,int(x1)+1), min(image.height,int(image.height-y0)+1))
            if bounds[2] <= bounds[0] or bounds[3] <= bounds[1]:
                return 0
            region = image.crop(bounds)
            return sum(255-sum(pixel)/3 for pixel in region.getdata())
        baseline_ink = ink(before, old['bbox'])
        if baseline_ink > 0:
            text_ratios[key] = round(ink(after, item['bbox']) / baseline_ink, 4)
    return {'status':'changed' if box else 'identical','changed_pixels':changed,
            'total_pixels':before.width*before.height,'changed_bbox':list(box) if box else None,
            'text_ink_ratios':text_ratios}


class CandidateRenderError(ValueError):
    def __init__(self, message, code="render_failed"):
        super().__init__(message)
        self.code = code


def _relative(value):
    path = PurePosixPath(str(value))
    if path.is_absolute() or not path.parts or any(p in {"..", "."} for p in path.parts) or "\\" in str(value):
        raise CandidateRenderError("Only project-relative paths are allowed", "scope_rejected")
    return str(path)


def _validate_sources(entry, files):
    if sum(len(source.encode()) for source in files.values() if isinstance(source, str)) > MAX_INPUT_BYTES:
        raise CandidateRenderError("Candidate files exceed the 100 MiB limit", "scope_rejected")
    for path, source in files.items():
        path = _relative(path)
        if path != entry and not (path.startswith("charts/overrides/") and path.endswith(".py")):
            raise CandidateRenderError("Candidate may only replace its entry or chart-local adapters: " + path,
                                       "scope_rejected")
        if not isinstance(source, str) or len(source.encode()) > 2 * 1024 * 1024:
            raise CandidateRenderError("Candidate source exceeds the source limit", "scope_rejected")
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError as exc:
            raise CandidateRenderError("Invalid Python: " + str(exc)) from exc
        # Early feedback only. These checks are not an OS isolation boundary.
        forbidden = {"subprocess", "socket", "requests", "urllib", "http", "ftplib", "ctypes", "multiprocessing"}
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [n.name for n in node.names] if isinstance(node, ast.Import) else [node.module or ""]
                if any(name.split(".")[0] in forbidden for name in names):
                    raise CandidateRenderError("Network, native memory, and process imports are not allowed",
                                               "scope_rejected")
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in {"system", "popen", "fork", "forkpty", "spawnv", "spawnve", "execv", "execve"}:
                    raise CandidateRenderError("Launching processes is not allowed", "scope_rejected")


def _snapshot(project, destination, overrides, entry=None):
    total = 0
    hashes = {}
    for dirname, suffixes in (("", {".py", ".json"}), ("charts", {".py"}), ("lib", {".py"}), ("data", {".csv", ".tsv", ".json"})):
        source_root = project / dirname
        if source_root.is_symlink():
            raise CandidateRenderError("Symlinked project directories are not allowed", "scope_rejected")
        if not source_root.exists():
            continue
        candidates = source_root.glob("*") if dirname == "" else source_root.rglob("*")
        for source in sorted(candidates):
            if source.is_symlink():
                raise CandidateRenderError("Symlinked project files are not allowed", "scope_rejected")
            if not source.is_file() or source.suffix.lower() not in suffixes:
                continue
            relative = source.relative_to(project).as_posix()
            if dirname == "charts" and entry is not None and relative != entry and relative not in overrides:
                continue
            size = source.stat().st_size
            total += size
            if total > MAX_INPUT_BYTES:
                raise CandidateRenderError("Drawing project exceeds the 100 MiB snapshot limit", "scope_rejected")
            data = source.read_bytes()
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            hashes[relative] = "sha256:" + hashlib.sha256(data).hexdigest()
    for relative, content in overrides.items():
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
    return hashes


def _scheme_string(value):
    return json.dumps(str(value))


def _sandbox_profile(work, writable):
    # Runtime locations contain Python/Matplotlib native libraries; no home,
    # project checkout, SSH, application credentials, or environment files.
    read_roots = {Path(sys.prefix).resolve(), Path(sys.base_prefix).resolve(),
                  Path(sys.executable).resolve().parent.parent, Path("/System/Library"),
                  Path("/usr/lib"), Path("/usr/share"), Path("/Library/Fonts"),
                  Path("/System/Library/Fonts"), work}
    read_rules = " ".join("(subpath " + _scheme_string(p) + ")" for p in sorted(read_roots))
    return "\n".join([
        "(version 1)", "(deny default)",
        "(allow process-exec (literal " + _scheme_string(Path(sys.executable).resolve()) + "))",
        "(allow signal (target self))", "(allow sysctl-read)",
        "(allow file-read* " + read_rules + ")",
        '(allow file-read* (literal "/"))',
        '(allow file-read-metadata)',
        '(allow file-read* (literal "/dev/urandom") (literal "/dev/random") (literal "/private/etc/localtime"))',
        '(allow file-read* file-write* (literal "/dev/null"))',
        "(allow file-write* (subpath " + _scheme_string(writable) + "))",
        "(deny network*)", "(deny process-fork)",
    ])



def isolation_backend():
    requested = os.environ.get("PLOT_FORGE_RENDER_BACKEND", "auto")
    if requested == "auto":
        requested = "local"
    if requested == "local" and sys.platform in {"win32", "darwin", "linux"}:
        return "local-python"
    if requested == "seatbelt" and sys.platform == "darwin" and Path("/usr/bin/sandbox-exec").is_file():
        return "macos-seatbelt"
    if requested == "docker" and sys.platform in {"win32", "darwin", "linux"} and shutil.which("docker"):
        return "docker"
    raise CandidateRenderError("No supported renderer. On Windows install/start Docker Desktop (Linux containers) and build the renderer image; on macOS use Seatbelt or Docker.", "sandbox_unavailable")


def _docker_command(work, snapshot, environment, name):
    # Only the disposable snapshot is readable; only runtime output is writable.
    command = ["docker", "run", "--rm", "--pull=never", "--name", name,
               "--network=none", "--read-only", "--cap-drop=ALL",
               "--security-opt=no-new-privileges", "--memory=1g", "--memory-swap=1g",
               "--cpus=2", "--pids-limit=64", "--log-driver=none",
               "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",
               "--mount", f"type=bind,source={work},target=/work,readonly",
               "--mount", f"type=bind,source={work / 'runtime'},target=/work/runtime",
               "--workdir", "/work/" + snapshot.relative_to(work).as_posix()]
    for key, value in environment.items():
        command += ["--env", key + "=" + value]
    return command + [os.environ.get("PLOT_FORGE_RENDER_IMAGE", "plot-forge-renderer:local"),
                      "python", "-s", "-B", "/work/worker.py", "--worker", "/work/config.json"]


def _one_render(project, entry, files, directory):
    backend = isolation_backend()
    if backend == "local-python":
        from local_execution import require_trust
        require_trust(project)
    from bundle_bindings import signature as bundle_signature
    bundle_revision = bundle_signature(project)
    if bundle_revision and backend != "local-python":
        raise CandidateRenderError("Bundle 候选目前需要本机 Python 模式；外部目录尚未接入 OS 沙箱", "scope_rejected")
    work = directory.resolve()
    snapshot = work / "packages" / "projects" / project.name
    snapshot.mkdir(parents=True)
    input_hashes = _snapshot(project, snapshot, files, entry=entry)
    if not (snapshot / entry).is_file():
        raise CandidateRenderError("Drawing entry does not exist: " + entry, "scope_rejected")
    # Keep existing projects.<name>.lib imports working inside the snapshot.
    package_root = work / "packages"
    for package in (package_root / "projects", snapshot):
        (package / "__init__.py").touch()
    for trusted in ("studio_style.py", "chart_naming.py", "font_policy.py", "chart_transform.py", "chart_overrides.py", "chart_type_defaults.py", "axis_range_policy.py"):
        shutil.copyfile(ROOT / trusted, package_root / trusted)
    profile_relative = Path("skills/chart-normalization/assets/style-profile.v1.json")
    target = package_root / profile_relative
    target.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / profile_relative, target)
    writable = work / "runtime"
    writable.mkdir()
    (writable / "mpl").mkdir()
    runner = work / "worker.py"
    shutil.copyfile(__file__, runner)
    profile_data = json.loads((ROOT / profile_relative).read_text(encoding="utf-8"))
    panel_gap_multiple = float(profile_data["global"]["multi_panel_min_gap_label_axis_multiple"])
    config = {"project": str(snapshot), "entry": entry, "package_root": str(package_root),
              "output": str(writable / "figure.png"), "metadata": str(writable / "metadata.json"),
              "input_hashes": input_hashes, "panel_gap_multiple": panel_gap_multiple,
              "bundle": (project / "data_sources.json").is_file() and any(item.get("kind") == "plot_bundle" for item in json.loads((project / "data_sources.json").read_text(encoding="utf-8")).get("sources", []))}
    config_path = work / "config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8", newline="\n")
    if backend == "docker":
        for key in ("project", "package_root", "output", "metadata"):
            config[key] = "/work/" + Path(config[key]).relative_to(work).as_posix()
        config_path.write_text(json.dumps(config), encoding="utf-8", newline="\n")
    profile = work / "sandbox.sb"
    if backend == "macos-seatbelt":
        profile.write_text(_sandbox_profile(work, writable), encoding="utf-8", newline="\n")
    environment = {"PATH": "/usr/bin:/bin", "HOME": str(writable), "TMPDIR": str(writable),
                   "MPLCONFIGDIR": str(writable / "mpl"), "MPLBACKEND": "Agg", "PYTHONHASHSEED": "0",
                   "PYTHONDONTWRITEBYTECODE": "1", "LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8",
                   "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
                   "CHART_PROJECT_DIR": str(snapshot), "CHART_OUTPUT": config["output"]}
    # A completely replaced environment and -s exclude user site/PYTHONPATH;
    # -I would additionally ignore our deterministic PYTHONHASHSEED. The script
    # directory contains only trusted worker/config files, not project modules.
    command = ["/usr/bin/sandbox-exec", "-f", str(profile), sys.executable, "-s", "-B", str(runner), "--worker", str(config_path)]
    container_name = "plot-forge-" + uuid.uuid4().hex if backend == "docker" else None
    if backend == "docker":
        environment.update(HOME="/work/runtime", TMPDIR="/tmp", MPLCONFIGDIR="/work/runtime/mpl",
                           CHART_PROJECT_DIR=config["project"], CHART_OUTPUT=config["output"])
        environment.pop("PATH", None)
        command = _docker_command(work, snapshot, environment, container_name)
    if backend == "local-python":
        command = [sys.executable, "-s", "-B", str(runner), "--worker", str(config_path)]
        environment["PATH"] = os.environ.get("PATH", "")
        environment["PYTHONIOENCODING"] = "utf-8"
        environment["PYTHONUTF8"] = "1"
        environment["CHART_BUNDLE_SOURCE_PROJECT"] = str(project)
        if os.name == "nt":
            environment["SystemRoot"] = os.environ.get("SystemRoot", r"C:\Windows")
            environment["WINDIR"] = environment["SystemRoot"]
            environment["TEMP"] = str(writable)
            environment["TMP"] = str(writable)
    log_path = writable / "render.log"
    try:
        with log_path.open("wb") as log, subprocess.Popen(command, cwd=snapshot, env=(os.environ.copy() if backend == "docker" else environment), stdin=subprocess.DEVNULL, stdout=log,
                              stderr=log, start_new_session=(os.name != "nt")) as process:
            try:
                process.wait(timeout=TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired as exc:
                if backend == "docker":
                    try:
                        subprocess.run(["docker", "rm", "-f", container_name], capture_output=True, timeout=10)
                    except (OSError, subprocess.TimeoutExpired):
                        pass
                    process.kill()
                elif os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, timeout=10)
                else:
                    os.killpg(process.pid, signal.SIGKILL)
                process.wait()
                raise CandidateRenderError("Rendering exceeded 45 seconds", "render_timeout") from exc
    except OSError as exc:
        raise CandidateRenderError("OS sandbox could not be started: " + str(exc), "sandbox_unavailable") from exc
    finally:
        if container_name:
            try:
                subprocess.run(["docker", "rm", "-f", container_name], capture_output=True, timeout=10)
            except (OSError, subprocess.TimeoutExpired):
                pass
    with log_path.open("rb") as log:
        log.seek(max(0, log_path.stat().st_size - 3500))
        error = log.read(3500).decode("utf-8", errors="replace")
    if process.returncode:
        if (backend == "docker" and (process.returncode in {125, 126, 127} or any(marker in error for marker in ("error during connect", "config.json: open", "Cannot connect to the Docker daemon")))) or "sandbox_apply" in error or "sandbox-exec:" in error:
            raise CandidateRenderError("OS isolation is unavailable; check Docker Desktop and build Dockerfile.renderer when using Docker. " + error,
                                       "sandbox_unavailable")
        raise CandidateRenderError("Isolated render failed (exit " + str(process.returncode) + "): " + error)
    output = writable / "figure.png"
    metadata = writable / "metadata.json"
    if (not output.is_file() or output.is_symlink() or output.stat().st_size > MAX_IMAGE_BYTES
            or not metadata.is_file() or metadata.is_symlink() or metadata.stat().st_size > 5 * 1024 * 1024):
        raise CandidateRenderError("Render did not produce a valid bounded PNG and report")
    if output.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n":
        raise CandidateRenderError("Expected a PNG candidate output")
    report = json.loads(metadata.read_text(encoding="utf-8"))
    # Read-only snapshot must also remain byte-identical (OS enforcement is the
    # primary protection, this detects accidental platform/profile regressions).
    for path, digest in input_hashes.items():
        expected = files.get(path)
        expected_hash = "sha256:" + hashlib.sha256(expected.encode()).hexdigest() if expected is not None else digest
        if "sha256:" + hashlib.sha256((snapshot / path).read_bytes()).hexdigest() != expected_hash:
            raise CandidateRenderError("Read-only snapshot changed: " + path, "scope_rejected")
    if bundle_signature(project) != bundle_revision:
        raise CandidateRenderError("Bundle 数据在渲染期间发生变化，请重试", "scope_rejected")
    report["image_bytes"] = output.read_bytes()
    report["stderr"] = error
    return report


def compare_reports(before, after):
    """Compare observed geometry, separately from display style/visibility.

    Changes are diagnostics: a permitted error-bar addition or a user-requested
    remapping can legitimately change geometry and needs the intent policy.
    """
    old = {item["key"]: item for item in before.get("artists", [])}
    new = {item["key"]: item for item in after.get("artists", [])}
    added, removed, changed, visibility, style = [], [], [], [], []
    for key in sorted(old.keys() | new.keys()):
        a, b = old.get(key), new.get(key)
        if a is None:
            added.append(b)
        elif b is None:
            removed.append(a)
        else:
            if a.get("data_hash") != b.get("data_hash"):
                changed.append({"key": key, "kind": b["kind"], "before": a, "after": b})
            if a.get("visibility") != b.get("visibility"):
                visibility.append({"key": key, "before": a.get("visibility"), "after": b.get("visibility")})
            if a.get("style") != b.get("style"):
                style.append({"key": key, "before": a.get("style"), "after": b.get("style")})
    prior_inputs=before.get('distribution_inputs') or []
    next_inputs=after.get('distribution_inputs') or []
    if prior_inputs and next_inputs:
        prior=[(c['kind'],c['groups']) for c in prior_inputs]
        current=[(c['kind'],c['groups']) for c in next_inputs]
        if prior!=current:
            changed.append({'key':'distribution_samples','kind':'source_samples','before':prior,'after':current})
    axes_changed = []
    for i in range(max(len(before.get("axes", [])), len(after.get("axes", [])))):
        a = before.get("axes", [])[i] if i < len(before.get("axes", [])) else None
        b = after.get("axes", [])[i] if i < len(after.get("axes", [])) else None
        if a != b:
            axes_changed.append({"axis": i, "before": a, "after": b})
    return {"status": "review_required" if added or removed or changed or visibility or axes_changed else "unchanged",
            "added": added, "removed": removed, "changed": changed,
            "visibility_changes": visibility, "style_changes": style, "axes_changes": axes_changed,
            "limitations": ["Artist positions are version-local, not persistent semantic IDs.",
                            "Geometry differences require comparison with user intent; they do not prove altered CSV values.",
                            "Custom artists, complex transforms and scientific interpretation are not fully verified."]}


def inspect_chart_fonts(project_path, chart_path_relative, files=None):
    """Resolve the fonts of the applied chart in the same isolated export path."""
    isolation_backend()
    project = Path(project_path)
    if project.is_symlink() or not project.is_dir():
        raise CandidateRenderError("Invalid project directory", "scope_rejected")
    entry = _relative(chart_path_relative)
    if not entry.startswith("charts/") or not entry.endswith(".py"):
        raise CandidateRenderError("Expected a chart Python entry", "scope_rejected")
    _validate_sources(entry, files or {})
    with tempfile.TemporaryDirectory(prefix="chat-font-audit-") as directory:
        report = _one_render(project.resolve(), entry, files or {}, Path(directory) / "applied")
        return report.get("font_audit") or {}


def render_candidate(project_path, chart_path_relative, files, output_dir, baseline_files=None, shared_files=None):
    """Return a saved candidate PNG and observed baseline/candidate diagnostics.

    files and baseline_files map project-relative allowed paths to full sources.
    This function saves only candidate artifacts. Local mode requires project
    consent and is not an OS sandbox. Optional isolated backends fail closed.
    output_dir must be a fresh, trusted caller path.
    """
    isolation_backend()
    project = Path(project_path)
    if project.is_symlink() or not project.is_dir():
        raise CandidateRenderError("Invalid project directory", "scope_rejected")
    project = project.resolve()
    entry = _relative(chart_path_relative)
    if not entry.startswith("charts/") or not entry.endswith(".py"):
        raise CandidateRenderError("Expected a chart Python entry", "scope_rejected")
    _validate_sources(entry, files)
    _validate_sources(entry, baseline_files or {})
    # Only the shared-module workflow supplies this separate argument. Normal
    # Chat proposals remain constrained to their selected chart entry.
    library_overrides={}
    for path,source in (shared_files or {}).items():
        relative=_relative(path)
        target=project/relative
        if (not relative.startswith('lib/') or not relative.endswith('.py') or not target.is_file()
                or target.is_symlink() or not target.resolve().is_relative_to((project/'lib').resolve())):
            raise CandidateRenderError('共享候选只能替换项目中已有的 lib Python 模块','scope_rejected')
        _validate_sources(entry,{entry:source})
        library_overrides[relative]=source
    output = Path(output_dir)
    if any(parent.is_symlink() for parent in [output, *output.parents]):
        raise CandidateRenderError("Symlinked output directories are not allowed", "scope_rejected")
    with tempfile.TemporaryDirectory(prefix="chat-candidate-") as temporary:
        temp = Path(temporary)
        baseline = _one_render(project, entry, baseline_files or {}, temp / "baseline")
        candidate = _one_render(project, entry, {**files,**library_overrides}, temp / "candidate")
        output.mkdir(parents=True, exist_ok=True)
        target = output / "candidate.png"
        if target.exists():
            raise CandidateRenderError("Candidate output is immutable; use a new output directory", "scope_rejected")
        with target.open("xb") as stream:
            stream.write(candidate.pop("image_bytes"))
        baseline_target = output / "baseline.png"
        with baseline_target.open("xb") as stream:
            stream.write(baseline.pop("image_bytes"))
        visual_change = _visual_change(baseline_target, target, baseline.get('layout_signature') or {},
                                       candidate.get('layout_signature') or {})
        report = {"image_path": str(target.resolve()), "baseline_image_path": str(baseline_target.resolve()), "layout": candidate["layout"],
                  "baseline_layout": baseline["layout"], "data_report": compare_reports(baseline, candidate),
                  "visual_change": visual_change,
                  "axis_details": candidate.get("axis_details"), "baseline_axis_details": baseline.get("axis_details"),
                  "naming": candidate["naming"], "render_size_px": candidate.get("render_size_px"),
                  "layout_signature": candidate.get("layout_signature"),
                  "baseline_layout_signature": baseline.get("layout_signature"),
                  "normalization_report": candidate.get("normalization_report"),
                  "distribution_inputs": candidate.get("distribution_inputs", []),
                  "baseline_distribution_inputs": baseline.get("distribution_inputs", []),
                  "distribution_overlays": candidate.get("distribution_overlays", []),
                  "candidate_artists": candidate.get("artists", []),
                  "font_audit": candidate.get("font_audit"),
                  "baseline_font_audit": baseline.get("font_audit"),
                  "warnings": _runtime_warnings(candidate.get("stderr")),
                  "isolation": {"backend": isolation_backend(), "readonly_snapshot": isolation_backend() != "local-python", "network": "python-audit-hook" if isolation_backend() == "local-python" else "denied", "os_sandbox": isolation_backend() != "local-python"}}
        substitutions=(report.get("font_audit") or {}).get("substitutions", [])
        if substitutions:
            replacements=sorted({f"{item['requested_family']} → {item['selected_family']}" for item in substitutions})
            report["warnings"].append("原字体缺失；导出时使用替代字体：" + ", ".join(replacements))
        baseline_issues = {issue["id"] for issue in baseline["layout"].get("issues", [])}
        for issue in report["layout"].get("issues", []):
            issue["preexisting"] = issue["id"] in baseline_issues
        (output / "checks.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
        return report


def _number_array(values):
    import numpy as np
    array = np.ma.asarray(values)
    if array.dtype.kind in "biufc":
        array = array.astype(float)
    data = np.asarray(array.filled(float("nan")) if np.ma.isMaskedArray(array) else array)
    if data.dtype.kind in "biufc":
        payload = data.astype("float64").tolist()
    else:
        payload = data.astype(str).tolist()
    encoded = json.dumps(payload, allow_nan=True, sort_keys=True, separators=(",", ":"))
    sample = payload[:3] if isinstance(payload, list) else payload
    sample = json.loads(json.dumps(sample, allow_nan=True), parse_constant=lambda _: None)
    return {"shape": list(data.shape), "sha256": hashlib.sha256(encoded.encode()).hexdigest(), "sample": sample}


def _distribution_values(obj, dimension):
    if hasattr(obj, 'get_ydata'):
        return _number_array(obj.get_ydata(orig=False) if dimension else obj.get_xdata(orig=False))
    if hasattr(obj, 'get_segments'):
        return [_number_array(segment[:, dimension]) for segment in obj.get_segments()]
    if hasattr(obj, 'get_paths'):
        return [_number_array(path.vertices[:, dimension]) for path in obj.get_paths()]
    return _number_array(obj.get_path().vertices[:, dimension])


def _capture(fig, renderer, panel_gap_multiple=2.0):
    import numpy as np
    from matplotlib.collections import LineCollection, PathCollection, PolyCollection, QuadMesh
    from matplotlib.container import ErrorbarContainer, BarContainer
    from matplotlib.colors import to_hex
    from matplotlib.lines import Line2D
    from matplotlib.patches import Rectangle
    from matplotlib.transforms import Bbox
    from chart_naming import figure_naming

    records, texts, issues, unsupported, axes_info, axes_layout, legend_regions = [], [], [], [], [], [], []
    distribution_inputs = []
    distribution_overlays = []
    axis_details = []
    panel_spacing = {'status': 'not_applicable', 'minimum_multiple': panel_gap_multiple, 'pairs': []}
    errorbar_roles = {}
    horizontal_bars = set()
    dpi_scale = fig.dpi / 72.0
    tolerance = max(0.75 * dpi_scale, 1.0)
    canvas = fig.bbox
    def issue(kind, elements, message):
        key = json.dumps([kind, sorted(elements)], ensure_ascii=False)
        issues.append({"id": "layout_" + hashlib.sha256(key.encode()).hexdigest()[:16],
                       "kind": kind, "elements": elements, "message": message})
    def outside(box, boundary):
        return box.x0 < boundary.x0 - tolerance or box.y0 < boundary.y0 - tolerance or box.x1 > boundary.x1 + tolerance or box.y1 > boundary.y1 + tolerance
    def continuous_spine(ax, name, lower, upper):
        spine = ax.spines.get(name)
        if spine is None or not spine.get_visible():
            return False
        path = spine.get_path()
        vertices = spine.get_transform().transform(path.vertices)
        if len(vertices) < 2 or not np.isfinite(vertices).all():
            return False
        if path.codes is not None and any(code == path.MOVETO for code in path.codes[1:]):
            return False
        coordinate = 0 if name == 'bottom' else 1
        across = 1 - coordinate
        along = vertices[:, coordinate]
        if np.ptp(vertices[:, across]) > 1.0:
            return False
        if np.any(np.diff(along) > 1.0) and np.any(np.diff(along) < -1.0):
            return False
        if name == 'bottom':
            expected = ax.transData.transform([(lower, ax.get_ylim()[0]), (upper, ax.get_ylim()[0])])[:, 0]
        else:
            expected = ax.transData.transform([(ax.get_xlim()[0], lower), (ax.get_xlim()[0], upper)])[:, 1]
        return bool(abs(min(along[0], along[-1]) - min(expected)) <= 1.0 and
                    abs(max(along[0], along[-1]) - max(expected)) <= 1.0)
    def collect_text(text, key, group, owner):
        if not text.get_visible() or not text.get_text() or text.get_alpha() == 0:
            return
        box = text.get_window_extent(renderer)
        if not np.isfinite(box.extents).all():
            return
        texts.append({"key": key, "box": box, "group": group, "owner": owner, "text": text.get_text(), "fontsize": float(text.get_fontsize())})
        if outside(box, canvas):
            issue("text_clipped", [key], "Text extends beyond the exported canvas: " + text.get_text())
        if text.get_clip_on() and text.get_clip_box() is not None and outside(box, text.get_clip_box()):
            issue("text_clipped_by_axes", [key], "Text is clipped by its axes: " + text.get_text())
    def artist(key, kind, data, obj):
        geometry = data
        if hasattr(obj, "_chat_semantic_data"):
            # Preserve the actual plotted numerical coordinate as well as the
            # supplied stats: later set_ydata/set_xdata mutations must not be
            # hidden by a tag attached during initial distribution creation.
            dimension = obj._chat_numeric_dimension
            if kind == "line":
                values = _number_array(obj.get_ydata(orig=False) if dimension else obj.get_xdata(orig=False))
            elif hasattr(obj, "get_segments"):
                values = [_number_array(segment[:, dimension]) for segment in obj.get_segments()]
            elif hasattr(obj, "get_paths"):
                values = [_number_array(path.vertices[:, dimension]) for path in obj.get_paths()]
            else:
                values = _number_array(obj.get_path().vertices[:, dimension])
            data = {"supplied": obj._chat_semantic_data, "rendered_values": values}
        joined = json.dumps(data, sort_keys=True, allow_nan=True)
        alpha = obj.get_alpha()
        visibility = {"visible": obj.get_visible(), "alpha": np.asarray(alpha).tolist() if alpha is not None else None}
        style = {}
        if hasattr(obj, "_chat_semantic_data"):
            style["display_geometry"] = geometry
        for prop in ("color", "facecolor", "edgecolor", "linewidth", "markersize"):
            getter = getattr(obj, "get_" + prop, None)
            if getter is not None:
                value = getter()
                try:
                    style[prop] = np.asarray(value).tolist()
                except Exception:
                    style[prop] = str(value)
        role = "data_artist"
        evidence = None
        component = errorbar_roles.get(id(obj))
        if component:
            role = "data_series" if component == "data_line" else "errorbar"
            evidence = "matplotlib.container.ErrorbarContainer"
        elif hasattr(obj, "_chat_semantic_data"):
            role = "distribution_statistics"
            evidence = "captured_matplotlib_distribution_statistics"
        elif (isinstance(obj, (Line2D, LineCollection))
              and getattr(obj, "_normalization_role", None) == "violin_quartiles"):
            role = "violin_quartiles"
            evidence = "normalization_helper_tag"
        records.append({"key": key, "kind": kind, "label": obj.get_label(),
                        "data_hash": hashlib.sha256(joined.encode()).hexdigest(),
                        "data": data, "visibility": visibility, "style": style,
                        "semantic_role": role, "role_evidence": evidence,
                        "distribution_mutated": (hasattr(obj, '_chat_initial_numeric') and
                            obj._chat_initial_numeric != data.get('rendered_values')),
                        "errorbar_component": component,
                        "signature_basis": "supplied_statistics" if hasattr(obj, "_chat_semantic_data") else "drawn_geometry"})
    for ai, ax in enumerate(fig.axes):
        if not ax.get_visible():
            continue
        prefix = "axes_" + str(ai)
        calls = getattr(ax, '_chat_distribution_inputs', [])
        scatter = [(i, c) for i, c in enumerate(ax.collections) if isinstance(c, PathCollection)]
        if len(calls) == 1 and scatter:
            from chart_transform import sample_signature
            call = calls[0]
            positions = np.asarray(call.get('positions', range(1, len(call['groups'])+1)), dtype=float)
            groups = [[] for _ in positions]
            valid = bool(len(positions) and len(set(positions)) == len(positions))
            radius = np.min(np.diff(np.sort(positions))) / 2 if len(positions)>1 else .5
            for _, collection in scatter:
                offsets = np.ma.asarray(collection.get_offsets())
                alpha=collection.get_alpha()
                valid = valid and collection.get_visible() and (alpha is None or bool(np.all(np.asarray(alpha)>0)))
                if np.ma.getmaskarray(offsets).any() or offsets.ndim!=2 or offsets.shape[1]!=2 or not np.isfinite(offsets).all():
                    valid = False
                    continue
                for point in offsets:
                    distances = np.abs(positions-point[1-call['dimension']])
                    index = int(np.argmin(distances))
                    if distances[index] >= radius:
                        valid = False
                    groups[index].append(float(point[call['dimension']]))
            distribution_overlays.append({'axis':ai, 'valid':bool(valid),
                'groups':[sample_signature(g) for g in groups],
                'collection_keys':[prefix+'.collection_'+str(i) for i,_ in scatter]})
        for call in getattr(ax, '_chat_distribution_inputs', []):
            dimension = call['dimension']
            labels = ax.get_xticklabels() if dimension == 1 else ax.get_yticklabels()
            distribution_inputs.append({**call, 'axis': ai, 'labels': [t.get_text() for t in labels]})
        for container in ax.containers:
            if isinstance(container, BarContainer) and container.orientation == 'horizontal':
                horizontal_bars.update(id(patch) for patch in container.patches)
            if isinstance(container, ErrorbarContainer):
                data_line, cap_lines, bar_collections = container.lines
                if data_line is not None:
                    errorbar_roles[id(data_line)] = "data_line"
                for obj in cap_lines:
                    errorbar_roles[id(obj)] = "cap"
                for obj in bar_collections:
                    errorbar_roles[id(obj)] = "range"
        axes_info.append({"xlim": list(map(float, ax.get_xlim())), "ylim": list(map(float, ax.get_ylim())),
                          "xscale": ax.get_xscale(), "yscale": ax.get_yscale()})
        lower, upper = sorted(map(float, ax.get_ylim()))
        xlower, xupper = sorted(map(float, ax.get_xlim()))
        ytolerance = max((upper - lower) * 1e-9, 1e-12)
        xtolerance = max((xupper - xlower) * 1e-9, 1e-12)
        left_spine = ax.spines.get('left')
        bottom_spine = ax.spines.get('bottom')
        configured_bounds = left_spine.get_bounds() if left_spine is not None else None
        bottom_bounds = bottom_spine.get_bounds() if bottom_spine is not None else None
        def numeric_ticklabels(axis):
            converter=axis.get_converter() if hasattr(axis,'get_converter') else axis.converter
            if converter is not None:return False
            labels=[t.get_text() for t in axis.get_ticklabels() if t.get_visible() and t.get_text()]
            try:
                for label in labels:float(label.replace('−','-'))
            except ValueError:return False
            return bool(labels)
        axis_details.append({
            'xscale': ax.get_xscale(), 'yscale': ax.get_yscale(),
            'numeric_xticks': numeric_ticklabels(ax.xaxis), 'numeric_yticks': numeric_ticklabels(ax.yaxis),
            'xlim': [xlower, xupper],
            'ylim': [lower, upper],
            'major_xticks': [float(value) for value in ax.xaxis.get_majorticklocs()
                             if xlower - xtolerance <= value <= xupper + xtolerance],
            'major_yticks': [float(value) for value in ax.yaxis.get_majorticklocs()
                             if lower - ytolerance <= value <= upper + ytolerance],
            'left_spine_visible': bool(left_spine and left_spine.get_visible()),
            'left_spine_bounds': list(map(float, configured_bounds)) if configured_bounds is not None else [lower, upper],
            'left_spine_continuous': continuous_spine(ax, 'left', lower, upper),
            'bottom_spine_visible': bool(bottom_spine and bottom_spine.get_visible()),
            'bottom_spine_bounds': list(map(float, bottom_bounds)) if bottom_bounds is not None else [xlower, xupper],
            'bottom_spine_continuous': continuous_spine(ax, 'bottom', xlower, xupper),
        })
        axes_layout.append({"position": list(map(float, ax.get_position().bounds)),
                            "labels": [ax.get_xlabel(), ax.get_ylabel()],
                            "label_fontsizes": [ax.xaxis.label.get_fontsize(), ax.yaxis.label.get_fontsize()],
                            "line_colors": [to_hex(line.get_color(), keep_alpha=True) for line in ax.lines if line.get_visible() and len(line.get_xdata()) > 0],
                            "legend": ({"loc": ax.get_legend()._loc, "fontsizes": [float(t.get_fontsize()) for t in ax.get_legend().get_texts()], "labels": [t.get_text() for t in ax.get_legend().get_texts()]} if ax.get_legend() is not None and ax.get_legend().get_visible() else None),
                            "tick_texts": [[t.get_text() for t in ax.get_xticklabels()], [t.get_text() for t in ax.get_yticklabels()]],
                            "tick_fontsizes": [[t.get_fontsize() for t in ax.get_xticklabels()], [t.get_fontsize() for t in ax.get_yticklabels()]],
                            "spine_linewidths": {name: float(spine.get_linewidth()) for name,spine in ax.spines.items() if spine.get_visible()},
                            "spines": {name: list(map(float, spine.get_window_extent(renderer).extents))
                                       for name, spine in ax.spines.items() if spine.get_visible()}})
        if ax.name != "rectilinear":
            unsupported.append(prefix + ": non-rectilinear axes")
        if ax.axison and ax.xaxis.get_visible():
            collect_text(ax.xaxis.label, prefix + ".xlabel", "axis", ai)
        if ax.axison and ax.yaxis.get_visible():
            collect_text(ax.yaxis.label, prefix + ".ylabel", "axis", ai)
        for name, axis in (("x", ax.xaxis), ("y", ax.yaxis)):
            if not ax.axison or not axis.get_visible():
                continue
            lower, upper = sorted(map(float, axis.get_view_interval()))
            epsilon = max(abs(upper - lower) * 1e-9, 1e-12)
            for level, ticks in (("major", axis.get_major_ticks()), ("minor", axis.get_minor_ticks())):
                # Locators include ticks just beyond the limits; Matplotlib does
                # not draw these even when their Text.visible flag is true.
                for ti, tick in enumerate(ticks):
                    if not lower - epsilon <= tick.get_loc() <= upper + epsilon:
                        continue
                    for side, text in (("1", tick.label1), ("2", tick.label2)):
                        collect_text(text, prefix + "." + name + "tick_" + level + "_" + str(ti) + "_" + side,
                                     "tick", ai)
            collect_text(axis.get_offset_text(), prefix + "." + name + "offset", "tick", ai)
        for ti, text in enumerate([ax.title, ax._left_title, ax._right_title]):
            collect_text(text, prefix + ".title_" + str(ti), "title", ai)
        for ti, text in enumerate(ax.texts):
            # Heatmap annotations are expected to sit over colored cells, but
            # text/text and canvas clipping still apply.
            collect_text(text, prefix + ".annotation_" + str(ti), "annotation", ai)
        legend = ax.get_legend()
        if legend and legend.get_visible():
            for ti, text in enumerate([legend.get_title(), *legend.get_texts()]):
                collect_text(text, prefix + ".legend_text_" + str(ti), "legend", ai)
            box = legend.get_window_extent(renderer)
            legend_regions.append((prefix + ".legend", box, ai))
            if outside(box, canvas):
                issue("legend_clipped", [prefix + ".legend"], "Legend extends beyond the exported canvas")
        for li, line in enumerate(ax.lines):
            artist(prefix + ".line_" + str(li), "line", {"x": _number_array(line.get_xdata(orig=False)),
                                                         "y": _number_array(line.get_ydata(orig=False))}, line)
        for ci, collection in enumerate(ax.collections):
            key = prefix + ".collection_" + str(ci)
            if isinstance(collection, LineCollection):
                data = {"segments": [_number_array(s) for s in collection.get_segments()]}
                artist(key, "line_collection", data, collection)
            elif isinstance(collection, PathCollection):
                data = {"offsets": _number_array(collection.get_offsets())}
                if collection.get_array() is not None:
                    data['scalar_values'] = _number_array(collection.get_array())
                artist(key, "scatter", data, collection)
            elif isinstance(collection, QuadMesh):
                artist(key, "heatmap", {"array": _number_array(collection.get_array()),
                                       "coordinates": _number_array(collection.get_coordinates())}, collection)
            elif isinstance(collection, PolyCollection):
                artist(key, "polygon_collection", {"paths": [_number_array(p.vertices) for p in collection.get_paths()]}, collection)
            else:
                unsupported.append(key + ": " + type(collection).__name__)
        for ii, img in enumerate(ax.images):
            artist(prefix + ".image_" + str(ii), "heatmap", {"array": _number_array(img.get_array()),
                                                             "extent": list(img.get_extent())}, img)
        for pi, patch in enumerate(ax.patches):
            if id(patch) in horizontal_bars:
                # In barh, width encodes the value and height is style thickness.
                data = {"center_y": float(patch.get_y() + patch.get_height() / 2),
                        "left": float(patch.get_x()), "width": float(patch.get_width())}
            elif isinstance(patch, Rectangle):
                # Width is a style token; center/base/height encode bar geometry.
                data = {"center": float(patch.get_x() + patch.get_width() / 2),
                        "bottom": float(patch.get_y()), "height": float(patch.get_height())}
            else:
                data = {"path": _number_array(patch.get_path().vertices)}
            artist(prefix + ".patch_" + str(pi), "patch", data, patch)
        # An axis line through a label is also a conflict. Restrict to spines,
        # not data curves/error bars whose intersections can be intentional.
        spine_boxes = [(name, spine.get_window_extent(renderer)) for name, spine in ax.spines.items() if spine.get_visible() and ax.axison]
        for text in [t for t in texts if t["owner"] == ai and t["group"] in {"axis", "tick", "title"}]:
            for name, box in spine_boxes:
                expanded = Bbox.from_extents(box.x0 - tolerance / 2, box.y0 - tolerance / 2,
                                            box.x1 + tolerance / 2, box.y1 + tolerance / 2)
                if text["box"].overlaps(expanded):
                    issue("text_spine_overlap", [text["key"], prefix + ".spine_" + name], "Text intersects an axis spine")
    for ti, text in enumerate(fig.texts):
        collect_text(text, "figure.text_" + str(ti), "figure", None)
    for li, legend in enumerate(fig.legends):
        if not legend.get_visible():
            continue
        legend_regions.append(("figure.legend_" + str(li), legend.get_window_extent(renderer), None))
        for ti, text in enumerate([legend.get_title(), *legend.get_texts()]):
            collect_text(text, "figure.legend_" + str(li) + ".text_" + str(ti), "legend", None)
        if outside(legend.get_window_extent(renderer), canvas):
            issue("legend_clipped", ["figure.legend_" + str(li)], "Figure legend extends beyond the exported canvas")
    for i, left in enumerate(texts):
        for right in texts[i + 1:]:
            a, b = left["box"], right["box"]
            if min(a.x1, b.x1) - max(a.x0, b.x0) > tolerance and min(a.y1, b.y1) - max(a.y0, b.y0) > tolerance:
                issue("text_overlap", [left["key"], right["key"]],
                      "Text bounding boxes overlap: " + left["text"] + " / " + right["text"])
        if left["group"] != "legend":
            for key, box, owner in legend_regions:
                if left["box"].overlaps(box):
                    issue("text_legend_overlap", [left["key"], key], "Text intersects a legend area: " + left["text"])
    # Check only panels sharing a row or column. Twin axes with the same plot
    # rectangle are one panel; a colorbar is part of its heatmap, not another
    # chart panel. Distances are measured on the final exported canvas.
    panels = []
    for ai, ax in enumerate(fig.axes):
        if not ax.get_visible() or ax.get_label() == '<colorbar>' or ax.name != 'rectilinear':
            continue
        plot = ax.bbox
        panel = next((p for p in panels if max(abs(a-b) for a,b in zip(p['plot'].extents,plot.extents)) <= tolerance),None)
        if panel is None:
            panel = {'plot':plot,'owners':[],'box':plot,'x_gaps':[],'y_gaps':[]}
            panels.append(panel)
        panel['owners'].append(ai)
        own_boxes = [t['box'] for t in texts if t['owner'] == ai]
        own_boxes += [box for _,box,owner in legend_regions if owner == ai]
        panel['box'] = Bbox.union([panel['box'],*own_boxes]) if own_boxes else panel['box']
        for axis_name, gaps in (('x',panel['x_gaps']),('y',panel['y_gaps'])):
            label = (ax.xaxis if axis_name == 'x' else ax.yaxis).label
            if not label.get_visible() or not label.get_text():
                continue
            label_box = label.get_window_extent(renderer)
            if axis_name == 'x':
                side = 'bottom' if label_box.y1 <= plot.y0 + tolerance else 'top'
                spine = ax.spines[side]
                if spine.get_visible():
                    line = spine.get_window_extent(renderer)
                    gaps.append(max(0.0, line.y0-label_box.y1 if side == 'bottom' else label_box.y0-line.y1))
            else:
                side = 'left' if label_box.x1 <= plot.x0 + tolerance else 'right'
                spine = ax.spines[side]
                if spine.get_visible():
                    line = spine.get_window_extent(renderer)
                    gaps.append(max(0.0, line.x0-label_box.x1 if side == 'left' else label_box.x0-line.x1))
    if len(panels) > 1:
        panel_spacing['status'] = 'pass'
        for left_index, first in enumerate(panels):
            for right_index in range(left_index+1,len(panels)):
                second=panels[right_index]
                a,b=first['plot'],second['plot']
                horizontal_overlap=max(0.0,min(a.x1,b.x1)-max(a.x0,b.x0))
                vertical_overlap=max(0.0,min(a.y1,b.y1)-max(a.y0,b.y0))
                same_row=vertical_overlap>=.25*min(a.height,b.height) and horizontal_overlap<=tolerance
                same_column=horizontal_overlap>=.25*min(a.width,b.width) and vertical_overlap<=tolerance
                if not (same_row or same_column):
                    continue
                direction='horizontal' if same_row else 'vertical'
                if same_row:
                    near,far=sorted((first,second),key=lambda p:p['plot'].x0)
                    gap=far['box'].x0-near['box'].x1
                    references=near['y_gaps']+far['y_gaps']
                else:
                    near,far=sorted((first,second),key=lambda p:p['plot'].y0,reverse=True)
                    gap=near['box'].y0-far['box'].y1
                    references=near['x_gaps']+far['x_gaps']
                if not references:
                    panel_spacing['status']='unverified' if panel_spacing['status']=='pass' else panel_spacing['status']
                    panel_spacing['pairs'].append({'panels':[left_index,right_index],'direction':direction,
                                                   'status':'unverified','reason':'visible axis title or spine unavailable'})
                    continue
                required=panel_gap_multiple*max(references)
                passed=gap+tolerance>=required
                panel_spacing['pairs'].append({'panels':[left_index,right_index],'direction':direction,
                                               'gap_px':round(gap,2),'required_px':round(required,2),
                                               'status':'pass' if passed else 'conflict'})
                if not passed:
                    panel_spacing['status']='conflict'
                    names=[f'panel_{left_index+1}',f'panel_{right_index+1}']
                    issue('panel_spacing',names,
                          f'{direction} panel gap {gap:.1f}px is below {panel_gap_multiple:g} × axis-title-to-spine gap ({required:.1f}px)')
        if not panel_spacing['pairs']:
            panel_spacing['status']='unverified'
            panel_spacing['reason']='No regular adjacent row or column could be identified'
        if panel_spacing['status']=='unverified':
            unsupported.append('Multi-panel spacing could not be verified for every adjacent pair')
    limitations = ["Checks use Matplotlib text bounding boxes at the final PNG save size.",
                   "Data curve crossings and heatmap-cell/text overlays are intentional and excluded.",
                   "Text against arbitrary data artists, 3D/custom artists, and visual meaning require review."]
    if unsupported:
        limitations += unsupported
    if not records:
        unsupported.append("No supported data artist was captured")
        limitations.append(unsupported[-1])
    return {"artists": records, "axes": axes_info, "axis_details": axis_details, "naming": figure_naming(fig),
            "distribution_inputs": distribution_inputs, "distribution_overlays":distribution_overlays,
            "normalization_report": getattr(fig, "_normalization_report", None),
            "render_size_px": [round(canvas.width), round(canvas.height)],
            "layout_signature": {"size_inches": list(map(float, fig.get_size_inches())), "dpi": float(fig.dpi),
                                 "axes": axes_layout,
                                 "texts": [{"key": t["key"], "text": t["text"], "fontsize": t["fontsize"],
                                            "bbox": [round(float(v), 4) for v in t["box"].extents]} for t in texts],
                                 "legends": [{"key": key, "bbox": list(map(float, box.extents))} for key, box, _ in legend_regions]},
            "layout": {"status": "conflict" if issues else "unverified" if unsupported else "pass",
                       "issues": issues, "limitations": limitations, "scope": "text_spines_canvas_and_panel_spacing",
                       "panel_spacing": panel_spacing}}


def _worker_main(config_path):
    import runpy
    if os.name != "nt":
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (30, 35))
        resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_IMAGE_BYTES, MAX_IMAGE_BYTES))
        resource.setrlimit(resource.RLIMIT_NOFILE, (128, 128))
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    sys.dont_write_bytecode = True
    sys.path.insert(0, config["package_root"])
    sys.path.insert(0, config["project"])
    sys.path.insert(0, str(Path(config["project"]) / "charts"))
    sys.path.insert(0, str(Path(config["project"]) / "lib"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from font_policy import audit_figure_fonts, register_platform_font
    from matplotlib.figure import Figure
    from matplotlib.axes import Axes
    import numpy as np
    np.random.seed(0)
    import random
    random.seed(0)
    register_platform_font()
    _install_stat_capture(Axes)
    # A script may call fig.show() after finish_figure has closed its manager.
    Figure.show = lambda self, *args, **kwargs: None
    original = Figure.savefig
    captured = []
    artifacts = {}
    if config.get("bundle"):
        import bundle_runtime
        def observe_output(source, destination):
            report = artifacts.get(str(Path(source).resolve()))
            if report is not None:
                captured[:] = [report]
        bundle_runtime.OUTPUT_OBSERVER = observe_output
    def savefig(fig, fname, *args, **kwargs):
        if isinstance(fname, (str, os.PathLike)) and (config.get("bundle") or Path(fname).resolve() == Path(config["output"])):
            font_audit = audit_figure_fonts(fig)
            draws = []
            def on_draw(event):
                captured_figure = _capture(fig, event.renderer, config["panel_gap_multiple"])
                captured_figure["font_audit"] = font_audit
                draws.append(captured_figure)
            connection = fig.canvas.mpl_connect("draw_event", on_draw)
            try:
                result = original(fig, fname, *args, **kwargs)
            finally:
                fig.canvas.mpl_disconnect(connection)
            if not draws:
                raise RuntimeError("No export-size draw event was observed")
            artifacts[str(Path(fname).resolve())] = draws[-1]
            if Path(fname).resolve() == Path(config["output"]):
                captured[:] = [draws[-1]]
            return result
        return original(fig, fname, *args, **kwargs)
    Figure.savefig = savefig
    # Extra protection and clearer error messages; not a substitute for Seatbelt.
    def audit(event, args):
        if event.startswith(("socket.", "subprocess.", "ctypes.")) or event in {"os.system", "os.fork", "os.posix_spawn", "os.exec", "pty.spawn"}:
            raise PermissionError("Chart runner denied network/process/native-memory access: " + event)
    sys.addaudithook(audit)
    runpy.run_path(str(Path(config["project"]) / config["entry"]), run_name="__main__")
    if not captured:
        raise RuntimeError("Script must save its target figure to CHART_OUTPUT")
    def json_scalar(value):
        import numpy as np
        if isinstance(value, np.generic):
            return value.item()
        raise TypeError(f'Object of type {type(value).__name__} is not JSON serializable')
    Path(config["metadata"]).write_text(json.dumps(captured[-1], ensure_ascii=False,
                                                  allow_nan=False, default=json_scalar), encoding="utf-8", newline="\n")
    plt.close("all")


def _install_stat_capture(axes_type):
    """Capture the numerical statistics supplied to Matplotlib distributions.

    Width/position normalization changes box and violin vertices, so comparing
    these vertices alone would incorrectly label a valid style edit as changed
    observations. Tag the artists with their actual supplied statistics. Other
    custom distribution implementations retain conservative geometry checks.
    """
    import functools
    import inspect
    originals = {name: getattr(axes_type, name) for name in ("bxp", "violin")}
    def safe_stats(stats):
        cleaned = []
        for row in stats:
            cleaned.append({str(key): str(value) if isinstance(value, str) else _number_array(value)
                            for key, value in sorted(row.items()) if key != "label"})
        return cleaned
    def numeric_dimension(name, ax, stats, args, kwargs):
        bound = inspect.signature(originals[name]).bind(ax, stats, *args, **kwargs)
        bound.apply_defaults()
        if "orientation" in bound.arguments and bound.arguments["orientation"] is not None:
            return 1 if bound.arguments["orientation"] == "vertical" else 0
        return 1 if bound.arguments.get("vert", True) else 0
    @functools.wraps(originals["bxp"])
    def bxp(self, bxpstats, *args, **kwargs):
        statistics = safe_stats(bxpstats)
        dimension = numeric_dimension("bxp", self, bxpstats, args, kwargs)
        result = originals["bxp"](self, bxpstats, *args, **kwargs)
        for component, artists in result.items():
            stride = 2 if component in {"whiskers", "caps"} else 1
            for index, obj in enumerate(artists):
                group = index // stride
                if group < len(statistics):
                    obj._chat_semantic_data = {"type": "box_statistics", "group": group,
                                               "component": component, "segment": index % stride,
                                               "statistics": statistics[group]}
                    obj._chat_numeric_dimension = dimension
                    obj._chat_initial_numeric = _distribution_values(obj, dimension)
        return result
    @functools.wraps(originals["violin"])
    def violin(self, vpstats, *args, **kwargs):
        statistics = safe_stats(vpstats)
        dimension = numeric_dimension("violin", self, vpstats, args, kwargs)
        result = originals["violin"](self, vpstats, *args, **kwargs)
        for component, objects in result.items():
            if component == "bodies":
                for group, obj in enumerate(objects):
                    obj._chat_semantic_data = {"type": "violin_statistics", "group": group,
                                               "component": component, "statistics": statistics[group]}
                    obj._chat_numeric_dimension = dimension
                    obj._chat_initial_numeric = _distribution_values(obj, dimension)
            else:
                objects._chat_semantic_data = {"type": "violin_statistics", "component": component,
                                               "statistics": statistics}
                objects._chat_numeric_dimension = dimension
                objects._chat_initial_numeric = _distribution_values(objects, dimension)
        return result
    axes_type.bxp = bxp
    axes_type.violin = violin
    # Observe the actual samples passed to public distribution APIs, independently
    # of their changing artist geometry. Do not duplicate wrappers in unit tests.
    for method, kind in (('boxplot', 'boxplot'), ('violinplot', 'violinplot')):
        original = getattr(axes_type, method)
        original = getattr(original, '_chat_original', original)
        def wrap(original, kind):
            @functools.wraps(original)
            def observed(self, *args, **kwargs):
                from matplotlib.cbook import _reshape_2D
                from chart_transform import sample_signature
                signature = inspect.signature(original)
                bound = signature.bind(self, *args, **kwargs)
                bound.apply_defaults()
                options = bound.arguments
                dataset = options[list(signature.parameters)[1]]
                import matplotlib
                dimension = 0 if options.get('orientation') == 'horizontal' or options.get('vert') is False else 1
                groups = [sample_signature(group) for group in _reshape_2D(dataset, 'dataset')]
                positions=options.get('positions')
                record = {'kind': kind, 'dimension': dimension, 'groups': groups,
                          'positions':list(map(float,positions)) if positions is not None else list(range(1,len(groups)+1)),
                          'showfliers': options.get('showfliers', True),
                          'whis': (options.get('whis') if options.get('whis') is not None else matplotlib.rcParams['boxplot.whiskers'])}
                result = original(self, *args, **kwargs)
                if not hasattr(self, '_chat_distribution_inputs'): self._chat_distribution_inputs = []
                self._chat_distribution_inputs.append(record)
                return result
            observed._chat_original = original
            return observed
        setattr(axes_type, method, wrap(original, kind))


if __name__ == "__main__" and len(sys.argv) == 3 and sys.argv[1] == "--worker":
    _worker_main(sys.argv[2])
