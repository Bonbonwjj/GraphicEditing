"""One-click local launcher. Uses a private venv created by the user's Python."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parent


def health(port):
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/health', timeout=1) as response:
            return json.load(response)
    except (OSError, ValueError):
        return None


def main():
    if sys.version_info < (3, 10):
        raise RuntimeError('请安装 Python 3.10 或更高版本')
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
