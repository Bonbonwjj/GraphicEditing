"""Build on the target OS using the redistributable Conda environment itself."""
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parent


def stage_application(destination):
    destination.mkdir(parents=True, exist_ok=True)
    excluded = {'build_desktop.py', 'desktop_launcher.py', 'export_shared_projects.py'}
    for source in ROOT.glob('*.py'):
        if source.name not in excluded:
            shutil.copy2(source, destination/source.name)
    for name in ('static', 'skills', 'projects'):
        def ignored(folder, names):
            return [n for n in names if (n.startswith('.') and n != '.gitattributes')
                    or n == '__pycache__' or n.endswith(('.pyc', '.log'))
                    or n in ('previews', 'chart_metadata')]
        shutil.copytree(ROOT/name, destination/name, ignore=ignored)
    for name in ('team_collaboration.json', 'README.md', 'requirements.txt'):
        shutil.copy2(ROOT/name, destination/name)
    (destination/'docs').mkdir(exist_ok=True)
    shutil.copy2(ROOT/'docs/DESKTOP_APP.md',destination/'docs/DESKTOP_APP.md')
    # Release source may already have canonical GitHub data/code projects. Seed
    # the private renderer workspace with its compatible logical paths.
    for metadata in (destination/'projects').glob('*/code/project.json'):
        code=metadata.parent; project=code.parent
        for source in sorted(code.rglob('*')):
            if source.is_file():
                target=project/source.relative_to(code)
                if target.exists() and target.read_bytes()!=source.read_bytes():
                    raise ValueError('Conflicting seed project layouts: '+str(target))
                target.parent.mkdir(parents=True,exist_ok=True)
                source.replace(target)
    return sorted(p.name for p in (destination/'projects').iterdir() if (p/'project.json').is_file())


def main():
    if not (Path(sys.prefix)/'conda-meta').is_dir():
        raise SystemExit('Run this build inside the dedicated Conda desktop environment.')
    import conda_pack
    staging = ROOT/'.desktop-build'/'payload'
    reuse = '--reuse-runtime' in sys.argv
    environment_digest=hashlib.sha256((Path(sys.prefix)/'conda-meta/history').read_bytes()).hexdigest()
    previous={}
    if reuse:
        previous=json.loads((staging/'manifest.json').read_text())
        if previous.get('environment_sha256',environment_digest)!=environment_digest:
            raise SystemExit('Runtime environment changed; build again without --reuse-runtime.')
        with (staging/'runtime.tar.gz').open('rb') as stream:
            if hashlib.file_digest(stream,'sha256').hexdigest()!=previous['runtime_sha256']:
                raise SystemExit('Cached runtime checksum mismatch.')
        app=staging/'app'
        if app.resolve().parent!=staging.resolve():
            raise SystemExit('Invalid staging directory.')
        shutil.rmtree(app)
    elif staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True,exist_ok=True)
    projects = stage_application(staging/'app')
    # Keep all third-party package licences in the runtime, including Git's GPL.
    if not reuse:
        conda_pack.pack(prefix=sys.prefix, output=str(staging/'runtime.tar.gz'),
                        ignore_editable_packages=False, force=True)
    with (staging/'runtime.tar.gz').open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    release_hash = hashlib.sha256()
    for path in sorted((staging/'app').rglob('*')):
        if path.is_file():
            release_hash.update(str(path.relative_to(staging)).encode()); release_hash.update(path.read_bytes())
    (staging/'manifest.json').write_text(json.dumps({'release':release_hash.hexdigest(),
        'runtime_sha256':digest,'seed_projects':projects,'platform':sys.platform,
        'architecture':platform.machine(),'environment_sha256':environment_digest},indent=2),encoding='utf-8')
    command = [sys.executable,'-m','PyInstaller','--noconfirm','--clean','--onedir','--windowed',
        '--name','Plot Forge','--distpath',str(ROOT/'dist'),
        '--workpath',str(ROOT/'.desktop-build'/'pyinstaller'),
        '--specpath',str(ROOT/'.desktop-build'),
        '--add-data',str(staging)+os.pathsep+'payload']
    if sys.platform == 'darwin':
        command += ['--osx-bundle-identifier','org.plotforge.desktop']
    build_env=os.environ.copy()
    build_env['PYTHONNOUSERSITE']='1'
    build_env['PYTHONUSERBASE']=str(ROOT/'.desktop-build/userbase')
    build_env['PYINSTALLER_CONFIG_DIR']=str(ROOT/'.desktop-build/pyinstaller-cache')
    subprocess.run(command+[str(ROOT/'desktop_launcher.py')],check=True,env=build_env)
    artifact = ROOT/'dist'/('Plot Forge.app' if sys.platform=='darwin' else 'Plot Forge')
    label = f'Plot-Forge-{sys.platform}-{platform.machine()}'
    if sys.platform == 'darwin':
        subprocess.run(['ditto','-c','-k','--sequesterRsrc','--keepParent',str(artifact),str(ROOT/'dist'/(label+'.zip'))],check=True)
    else:
        shutil.make_archive(str(ROOT/'dist'/label),'zip',root_dir=ROOT/'dist',base_dir=artifact.name)
    print('Desktop build:',artifact,flush=True)


if __name__ == '__main__':
    main()
