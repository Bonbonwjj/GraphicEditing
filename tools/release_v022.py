"""Reproducible Windows release assembly. Run from the repository root."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app_version import APP_VERSION
from desktop_launcher import prepare, python_path, runtime_environment
from prepare_release_runtime import augment


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def build(payload, wheel, home):
    runtime, _ = prepare(payload, home)
    augment(payload, wheel, ROOT/'.desktop-build/payload', runtime/'conda-meta/history')
    subprocess.run([str(python_path(runtime)), str(ROOT/'build_desktop.py'), '--reuse-runtime'],
                   cwd=ROOT, env=runtime_environment(runtime), check=True)


def verify(home):
    dist = ROOT/'dist'
    executable = dist/'Plot Forge/Plot Forge.exe'
    payload = executable.parent/'_internal/payload'
    manifest = json.loads((payload/'manifest.json').read_text(encoding='utf-8'))
    assert manifest['version'] == APP_VERSION == '0.2.2'
    app = payload/'app'
    forbidden = {'.git', '.chat', '.preparation', '.model-api.json', '.private-projects.json',
                 '.model-api-key.dpapi', 'jiahui', 'test_server_local.py', '__pycache__'}
    for path in app.rglob('*'):
        assert not forbidden.intersection(path.relative_to(app).parts), str(path)
    for path in ROOT.glob('*.py'):
        if path.name not in {'build_desktop.py','desktop_launcher.py','export_shared_projects.py'} and not path.name.startswith('test_'):
            assert (app/path.name).read_bytes() == path.read_bytes(), path.name
    for folder in ('static', 'skills'):
        for path in (ROOT/folder).rglob('*'):
            if path.is_file() and '__pycache__' not in path.parts:
                assert (app/path.relative_to(ROOT)).read_bytes() == path.read_bytes(), str(path)
    report = home/'native-smoke.json'
    home.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env['PLOT_FORGE_HOME'] = str(home.resolve())
    # Keep Windows itself available, with no system Python or Git in PATH.
    env['PATH'] = str(Path(env.get('SystemRoot', 'C:/Windows'))/'System32')
    subprocess.run([str(executable), '--smoke-report', str(report.resolve())], env=env,
                   check=True, timeout=300, creationflags=subprocess.CREATE_NO_WINDOW)
    smoke = json.loads(report.read_text(encoding='utf-8'))
    assert smoke['ok'] and smoke['health']['desktop_release'] == manifest['release']
    runtime, workspace = prepare(payload, home)
    feature = """import cloudpickle, sys
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
from interactive_style import apply_interactive_style
fig,ax=plt.subplots(); ax.boxplot([[1,2,3,4,20]],patch_artist=True,showmeans=True)
ax.scatter([1]*5,[1,2,3,4,20]); ax.set(xlabel='Group',ylabel='Value')
apply_interactive_style(fig,{})
copy=cloudpickle.loads(cloudpickle.dumps(fig)); assert copy.axes[0].get_ylabel()=='Value'
copy.savefig(sys.argv[1]); print('interactive runtime OK')
"""
    subprocess.run([str(python_path(runtime)), '-c', feature, str(workspace/'feature-smoke.png')],
                   cwd=workspace, env=runtime_environment(runtime), check=True, timeout=120)
    windows = dist/f'Plot-Forge-v{APP_VERSION}-Windows-x64.zip'
    shutil.copy2(dist/'Plot-Forge-win32-AMD64.zip', windows)
    clean_smoke = {'ok':True, 'version':APP_VERSION, 'native_startup':True,
                   'bundled_python':True, 'bundled_git':True, 'render_png':True,
                   'interactive_runtime':True, 'payload_matches_source':True,
                   'desktop_release':manifest['release']}
    (dist/f'smoke-report-v{APP_VERSION}.json').write_text(json.dumps(clean_smoke, indent=2), encoding='utf-8')
    return manifest


def finalize():
    dist = ROOT/'dist'
    source = dist/f'Plot-Forge-v{APP_VERSION}-source.zip'
    subprocess.run(['git','archive','--format=zip', f'--prefix=Plot-Forge-v{APP_VERSION}/',
                    '-o',str(source),'HEAD'], cwd=ROOT, check=True)
    commit = subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    info = {'version':APP_VERSION,'source_commit':commit,'platform':'Windows-x64',
            'runtime_addition':'cloudpickle==3.1.2','private_projects_included':False,
            'workflow_run':os.environ.get('GITHUB_RUN_ID'),
            'assets':{path.name:{'sha256':sha256(path),'size':path.stat().st_size}
                      for path in (source, dist/f'Plot-Forge-v{APP_VERSION}-Windows-x64.zip')}}
    (dist/f'build-info-v{APP_VERSION}.json').write_text(json.dumps(info, indent=2), encoding='utf-8')
    files = [source, dist/f'Plot-Forge-v{APP_VERSION}-Windows-x64.zip',
             dist/f'build-info-v{APP_VERSION}.json',dist/f'smoke-report-v{APP_VERSION}.json']
    (dist/f'SHA256SUMS-v{APP_VERSION}.txt').write_text(''.join(f'{sha256(p)}  {p.name}\n' for p in files),encoding='utf-8')
    print(json.dumps(info, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['build','verify','finalize'])
    parser.add_argument('--payload', type=Path)
    parser.add_argument('--wheel', type=Path)
    parser.add_argument('--home', type=Path)
    args = parser.parse_args()
    if args.action == 'build': build(args.payload, args.wheel, args.home)
    elif args.action == 'verify': verify(args.home)
    else: finalize()
