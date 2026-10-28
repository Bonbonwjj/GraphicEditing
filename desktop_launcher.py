"""Frozen desktop entry point; unpack a bundled runtime, never install software."""
import contextlib
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import tarfile
import time
import urllib.request
import webbrowser


def user_home():
    if os.environ.get('PLOT_FORGE_HOME'):
        return Path(os.environ['PLOT_FORGE_HOME']).expanduser().resolve()
    if sys.platform == 'win32':
        return Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData/Local')) / 'PlotForge'
    if sys.platform == 'darwin':
        return Path.home() / 'Library/Application Support/PlotForge'
    # Linux follows the XDG user-data conventions while remaining portable for
    # single-user desktop installs. This keeps the bundled runtime and workspace
    # isolated from the application directory itself.
    return Path.home() / '.local' / 'share' / 'PlotForge'


@contextlib.contextmanager
def startup_lock(home):
    home.mkdir(parents=True, exist_ok=True)
    with (home / 'startup.lock').open('a+b') as handle:
        handle.seek(0)
        if not handle.read(1):
            handle.write(b'0'); handle.flush()
        if os.name == 'nt':
            import msvcrt
            while True:
                try:
                    handle.seek(0); msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    time.sleep(.2)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == 'nt':
                handle.seek(0); msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def runtime_environment(runtime):
    env = os.environ.copy()
    # A frozen launcher's library paths must not contaminate its child Python.
    for key in ('PYTHONHOME', 'PYTHONPATH', 'LD_LIBRARY_PATH', 'DYLD_LIBRARY_PATH'):
        env.pop(key, None)
    paths = [runtime, runtime/'git/cmd', runtime/'Library/ucrt64/bin', runtime/'Library/mingw-w64/bin', runtime/'Library/usr/bin',
             runtime/'Library/bin', runtime/'Scripts', runtime/'bin']
    env['PATH'] = os.pathsep.join(map(str, paths)) + os.pathsep + env.get('PATH', '')
    env['CONDA_PREFIX'] = str(runtime)
    env['PYTHONUTF8'] = '1'
    env['PYTHONNOUSERSITE'] = '1'
    env['PLOT_FORGE_RENDER_BACKEND'] = 'local'
    env['MPLBACKEND'] = 'Agg'
    env['MPLCONFIGDIR'] = str(runtime.parent.parent / 'matplotlib')
    if os.name == 'nt':
        # Bundled Git supports OpenSSL. Avoid Schannel's dependency on a Windows
        # logon credential session, while retaining normal certificate checking.
        slot=int(env.get('GIT_CONFIG_COUNT','0'))
        env[f'GIT_CONFIG_KEY_{slot}']='http.sslBackend'
        env[f'GIT_CONFIG_VALUE_{slot}']='openssl'
        env['GIT_CONFIG_COUNT']=str(slot+1)
    certificate = runtime / ('Library/ssl/cacert.pem' if os.name == 'nt' else 'ssl/cacert.pem')
    if certificate.exists():
        env['SSL_CERT_FILE'] = str(certificate)
        env['GIT_SSL_CAINFO'] = str(certificate)
    # PyInstaller sets a process-global DLL directory on Windows.
    if os.name == 'nt' and getattr(sys, 'frozen', False):
        import ctypes
        ctypes.windll.kernel32.SetDllDirectoryW(None)
    return env


def python_path(runtime):
    return runtime / ('python.exe' if os.name == 'nt' else 'bin/python')


def extract_runtime(archive, destination):
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive) as bundle:
        # Python 3.11's data filter prevents paths/links escaping the destination.
        bundle.extractall(destination, filter='data')
    env = runtime_environment(destination)
    unpack = destination / ('Scripts/conda-unpack-script.py' if os.name == 'nt' else 'bin/conda-unpack')
    if not unpack.exists():
        raise RuntimeError('安装包缺少 conda-unpack，无法完成运行环境初始化')
    subprocess.run([str(python_path(destination)), str(unpack)], env=env,
                   check=True, capture_output=True, timeout=180)
    (destination / '.ready').write_text('ready', encoding='utf-8')


def prepare(payload, home):
    manifest = json.loads((payload / 'manifest.json').read_text(encoding='utf-8'))
    if not re.fullmatch('[a-f0-9]{64}', manifest['runtime_sha256']):
        raise RuntimeError('运行环境清单校验失败')
    runtime = home / 'runtimes' / manifest['runtime_sha256'][:16]
    if not (runtime / '.ready').is_file():
        archive = payload / 'runtime.tar.gz'
        with archive.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if digest != manifest['runtime_sha256']:
            raise RuntimeError('运行环境校验失败，请重新下载完整安装包')
        if runtime.exists():
            if runtime.resolve().parent != (home/'runtimes').resolve():
                raise RuntimeError('运行环境目录超出应用数据目录')
            shutil.rmtree(runtime)  # Only our incomplete, versioned runtime under home.
        extract_runtime(archive, runtime)
    workspace = home / 'workspace'
    workspace.mkdir(exist_ok=True)
    previous_file = workspace / '.desktop-release.json'
    previous = json.loads(previous_file.read_text(encoding='utf-8')) if previous_file.exists() else {}
    # Application upgrades replace application resources; user projects/settings stay intact.
    if previous.get('release') != manifest['release']:
        for source in sorted((payload / 'app').rglob('*')):
            if not source.is_file():
                continue
            relative = source.relative_to(payload / 'app')
            target = workspace / relative
            if relative.parts[0] == 'projects':
                project = workspace / 'projects' / relative.parts[1]
                if (project / 'project.json').exists() or relative.parts[1] in previous.get('seed_projects', []):
                    continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        previous_file.write_text(json.dumps(manifest), encoding='utf-8')
    return runtime, workspace


def health(port):
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f'http://127.0.0.1:{port}/api/health', timeout=1) as response:
            return json.load(response)
    except (OSError, ValueError):
        return None


def start_server(runtime, workspace):
    port = None
    for candidate in range(8765, 8795):
        existing = health(candidate)
        if existing and existing.get('root') == str(workspace):
            return candidate, None
        with socket.socket() as probe:
            try:
                probe.bind(('127.0.0.1', candidate)); port = candidate; break
            except OSError:
                continue
    if port is None:
        raise RuntimeError('本地端口 8765～8794 均被占用')
    env = runtime_environment(runtime)
    env['CHART_STUDIO_PORT'] = str(port)
    env['PLOT_FORGE_DESKTOP_RELEASE'] = json.loads((workspace/'.desktop-release.json').read_text())['release']
    options = {'start_new_session': True} if os.name != 'nt' else {
        'creationflags': subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP}
    with (workspace/'local-server.log').open('ab') as stdout, (workspace/'local-server-error.log').open('ab') as stderr:
        process = subprocess.Popen([str(python_path(runtime)), '-X', 'utf8', str(workspace/'server.py')],
            cwd=workspace, env=env, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, **options)
    for _ in range(120):
        if process.poll() is not None:
            raise RuntimeError(f'后台启动失败，请查看 {workspace / "local-server-error.log"}')
        existing = health(port)
        if existing and existing.get('root') == str(workspace):
            return port, process
        time.sleep(.5)
    process.terminate()
    raise RuntimeError('后台启动超时')


def smoke_test(runtime, workspace, report):
    env = runtime_environment(runtime)
    python = str(python_path(runtime))
    output = workspace / 'desktop-smoke.png'
    script = "import sys,json,matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as p; import numpy,pandas,scipy,PIL,keyring; p.plot([0,1],[1,2]); p.savefig(sys.argv[1]); print(json.dumps({'prefix':sys.prefix,'base_prefix':sys.base_prefix}))"
    rendered=subprocess.run([python, '-c', script, str(output)], env=env, check=True, capture_output=True, text=True, timeout=90)
    interpreter=json.loads(rendered.stdout)
    if any(Path(value).resolve()!=runtime.resolve() for value in interpreter.values()):
        raise RuntimeError('测试失败：Python 依赖了安装包之外的环境')
    assert output.read_bytes().startswith(b'\x89PNG')
    git = shutil.which('git', path=env['PATH'])
    if not git or not Path(git).resolve().is_relative_to(runtime.resolve()):
        raise RuntimeError('测试失败：未使用内置 Git')
    version = subprocess.check_output([git, '--version'], env=env, text=True).strip()
    fixture = workspace/'desktop-git-smoke'
    fixture.mkdir(exist_ok=True)
    subprocess.run([git,'init',str(fixture)],env=env,check=True,capture_output=True)
    (fixture/'probe.txt').write_text('bundled git',encoding='utf-8')
    subprocess.run([git,'-C',str(fixture),'add','probe.txt'],env=env,check=True,capture_output=True)
    subprocess.run([git,'-C',str(fixture),'-c','commit.gpgsign=false','-c','user.name=Desktop Smoke','-c','user.email=smoke@example.test',
                    'commit','--allow-empty','-m','Verify bundled Git'],env=env,check=True,capture_output=True)
    port, process = start_server(runtime, workspace)
    try:
        report.write_text(json.dumps({'ok': True, 'git': version, 'git_path': git,
            'python': python, 'interpreter':interpreter, 'health': health(port), 'rendered_png': str(output)}, ensure_ascii=False, indent=2), encoding='utf-8')
    finally:
        if process:
            process.terminate(); process.wait(timeout=15)


def main(open_browser=True):
    payload = Path(getattr(sys, '_MEIPASS', Path(__file__).parent)) / 'payload'
    home = user_home()
    with startup_lock(home):
        release = json.loads((payload/'manifest.json').read_text())['release']
        workspace = home/'workspace'
        for candidate in range(8765,8795):
            existing = health(candidate)
            if (existing and existing.get('root') == str(workspace)
                    and existing.get('desktop_release') and existing['desktop_release'] != release):
                os.kill(existing['pid'],signal.SIGTERM)
                for _ in range(50):
                    if not health(candidate):
                        break
                    time.sleep(.1)
                else:
                    raise RuntimeError('旧版后台尚未退出，请稍后重试')
        runtime, workspace = prepare(payload, home)
        if '--smoke-report' in sys.argv:
            smoke_test(runtime, workspace, Path(sys.argv[sys.argv.index('--smoke-report') + 1]))
            return
        port, _ = start_server(runtime, workspace)
    url=f'http://127.0.0.1:{port}/'
    if open_browser:
        webbrowser.open(url)
    return url


def launch_with_progress():
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    status={}; delivered=threading.Event()
    page='''<!doctype html><meta charset="utf-8"><title>Plot Forge</title>
<style>body{font:16px system-ui;background:#17181b;color:#f7f7f7;display:grid;place-content:center;min-height:90vh;padding:24px}h1{color:#ff655c}p{max-width:560px;line-height:1.8}</style>
<h1>Plot Forge · 图表工坊</h1><p id="message">正在启动。首次打开需初始化内置绘图环境，可能需要一至两分钟，请稍候。</p>
<script>setInterval(async()=>{try{const s=await(await fetch('/status')).json();if(s.url)location.replace(s.url);if(s.error)document.getElementById('message').textContent=s.error;}catch(e){}},500)</script>'''
    class ProgressHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            is_status=self.path=='/status'
            body=json.dumps(status,ensure_ascii=False).encode() if is_status else page.encode()
            self.send_response(200);self.send_header('Content-Type','application/json; charset=utf-8' if is_status else 'text/html; charset=utf-8')
            self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(body)
            if is_status and status.get('url'):
                delivered.set()
        def log_message(self,*args):
            pass
    http=ThreadingHTTPServer(('127.0.0.1',0),ProgressHandler)
    threading.Thread(target=http.serve_forever,daemon=True).start()
    webbrowser.open(f'http://127.0.0.1:{http.server_port}/')
    try:
        status['url']=main(open_browser=False)
        delivered.wait(10)
    except Exception as exc:
        status['error']=str(exc)
        # Let the opened startup page receive the failure before closing.
        time.sleep(3)
        raise
    finally:
        http.shutdown();http.server_close()


if __name__ == '__main__':
    try:
        main() if '--smoke-report' in sys.argv else launch_with_progress()
    except Exception as exc:
        home = user_home(); home.mkdir(parents=True, exist_ok=True)
        (home/'desktop-error.log').write_text(str(exc), encoding='utf-8')
        if '--smoke-report' not in sys.argv:
            if os.name=='nt':
                import ctypes
                ctypes.windll.user32.MessageBoxW(None,str(exc),'Plot Forge',0x10)
            else:
                subprocess.run(['osascript','-e','on run argv\ndisplay alert "Plot Forge" message (item 1 of argv)\nend run',str(exc)],check=False)
        sys.exit(1)
