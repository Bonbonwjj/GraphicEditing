"""One-click local launcher. Uses a private venv created by the user's Python."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parent


def _python_version(python_executable):
    try:
        completed = subprocess.run(
            [str(python_executable), '-c', 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")'],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if completed.returncode != 0:
        return None
    version = completed.stdout.strip()
    try:
        return tuple(int(part) for part in version.split('.'))
    except ValueError:
        return None


def _conda_python_for_env(env_name):
    conda = shutil.which('conda')
    if not conda:
        return None
    if os.name == 'nt':
        suffix = 'Scripts/python.exe'
    else:
        suffix = 'bin/python'
    prefix = Path(os.environ.get('CONDA_PREFIX', ''))
    if env_name == 'base' and prefix.exists():
        candidate = prefix / suffix
        if candidate.exists():
            return str(candidate)
    try:
        result = subprocess.run([conda, 'info', '--base'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, check=False)
    except OSError:
        result = None
    if result and result.returncode == 0:
        base_prefix = result.stdout.strip()
        if base_prefix:
            candidate = Path(base_prefix) / suffix
            if candidate.exists():
                return str(candidate)
    try:
        result = subprocess.run([conda, 'run', '-n', env_name, 'python', '-c', 'import sys; print(sys.executable)'],
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, check=False)
    except OSError:
        return None
    if result.returncode == 0:
        executable = result.stdout.strip()
        if executable:
            return executable
    return None


def find_compatible_python():
    explicit = os.environ.get('PLOT_FORGE_PYTHON')
    if explicit:
        explicit_path = Path(explicit)
        if explicit_path.exists():
            version = _python_version(explicit_path)
            if version and version >= (3, 10):
                return str(explicit_path)
    candidates = []
    if os.name == 'nt':
        py_launcher = shutil.which('py')
        if py_launcher:
            for value in ('3.13', '3.12', '3.11', '3.10'):
                candidates.append([py_launcher, f'-{value}'])
    for program in ('python3.13', 'python3.12', 'python3.11', 'python3.10', 'python3', 'python'):
        resolved = shutil.which(program)
        if resolved:
            candidates.append(resolved)
    conda = shutil.which('conda')
    if conda:
        base_python = _conda_python_for_env('base')
        if base_python:
            candidates.append(base_python)
    seen = set()
    for candidate in candidates:
        if isinstance(candidate, list):
            executable = candidate[0]
            command = candidate
        else:
            executable = candidate
            command = [candidate]
        if executable in seen:
            continue
        seen.add(executable)
        try:
            version = _python_version(executable if not isinstance(candidate, list) else command[0])
        except TypeError:
            version = None
        if version and version >= (3, 10):
            return executable if not isinstance(candidate, list) else executable
        if isinstance(candidate, list):
            try:
                completed = subprocess.run(candidate + ['-c', 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")'],
                                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, check=False)
            except OSError:
                continue
            if completed.returncode == 0:
                version_text = completed.stdout.strip()
                try:
                    parsed = tuple(int(part) for part in version_text.split('.'))
                except ValueError:
                    continue
                if parsed >= (3, 10):
                    return candidate[0]
    return None


def create_conda_environment():
    conda = shutil.which('conda')
    if not conda:
        return None
    env_name = os.environ.get('PLOT_FORGE_CONDA_ENV', 'plot-forge')
    try:
        result = subprocess.run([conda, 'create', '-y', '-n', env_name, 'python=3.12'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=False)
    except OSError:
        return None
    if result.returncode != 0:
        return None
    return _conda_python_for_env(env_name)


def bootstrap_python_if_needed():
    if sys.version_info >= (3, 10):
        return sys.executable
    preferred = find_compatible_python()
    if preferred:
        env = os.environ.copy()
        env['PLOT_FORGE_BOOTSTRAP'] = '1'
        subprocess.run([preferred, str(ROOT / 'launch.py')], check=True, env=env)
        return None
    conda_python = create_conda_environment()
    if conda_python:
        env = os.environ.copy()
        env['PLOT_FORGE_BOOTSTRAP'] = '1'
        subprocess.run([conda_python, str(ROOT / 'launch.py')], check=True, env=env)
        return None
    raise RuntimeError('未找到 Python 3.10+。请先安装 Python 3.10+，或在 PATH 中配置 conda。')


def health(port):
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/health', timeout=1) as response:
            return json.load(response)
    except (OSError, ValueError):
        return None


def main():
    if os.environ.get('PLOT_FORGE_BOOTSTRAP') != '1' and sys.version_info < (3, 10):
        bootstrap_python_if_needed()
        return
    import socket
    port = None
    for candidate in range(8765, 8795):
        existing = health(candidate)
        if existing and existing.get('root') == str(ROOT):
            webbrowser.open(f'http://127.0.0.1:{candidate}/')
            return
        with socket.socket() as probe:
            try:
                probe.bind(('127.0.0.1', candidate))
                port = candidate
                break
            except OSError:
                continue
    if port is None:
        raise RuntimeError('本地端口 8765～8794 均被占用')
    python = ROOT / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    if not python.exists():
        subprocess.run([sys.executable, '-m', 'venv', str(ROOT / '.venv')], check=True)
    requirements = ROOT / 'requirements.txt'
    digest = hashlib.sha256(requirements.read_bytes()).hexdigest()
    stamp = ROOT / '.launcher-install.json'
    installed = json.loads(stamp.read_text(encoding='utf-8')) if stamp.exists() else {}
    if installed.get('requirements') != digest:
        print('首次启动/依赖更新：正在安装绘图库，完成后会自动打开网页。', flush=True)
        subprocess.run([str(python), '-m', 'pip', 'install', '-r', str(requirements)], check=True)
        stamp.write_text(json.dumps({'requirements': digest}), encoding='utf-8')
    environment = os.environ.copy()
    environment['CHART_STUDIO_PORT'] = str(port)
    environment['PYTHONUTF8'] = '1'
    options = {'start_new_session': True} if os.name != 'nt' else {
        'creationflags': subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP}
    with (ROOT / 'local-server.log').open('ab') as stdout, (ROOT / 'local-server-error.log').open('ab') as stderr:
        process = subprocess.Popen([str(python), str(ROOT / 'server.py')], cwd=ROOT,
                                   env=environment, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, **options)
    for _ in range(60):
        if process.poll() is not None:
            raise RuntimeError('启动失败，请查看 local-server-error.log')
        existing = health(port)
        if existing and existing.get('root') == str(ROOT):
            print(f'工作台已启动：http://127.0.0.1:{port}/')
            webbrowser.open(f'http://127.0.0.1:{port}/')
            return
        time.sleep(.5)
    process.terminate()
    raise RuntimeError('启动超时，请查看 local-server-error.log')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('Plot Forge：' + str(error))
        input('按回车键关闭…')
        sys.exit(1)
