"""Choose native chart interpreters without changing application dependencies."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parent


def requirements(path=None):
    path=Path(path) if path else ROOT/'requirements-native.txt'
    result={}
    if path.is_file():
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            match=re.fullmatch(r'\s*([A-Za-z0-9_.-]+)==([^;\s#]+)\s*(?:#.*)?',line)
            if match:result[match[1]]=match[2]
    return result


def describe(project, backend='local-python'):
    registry=Path(project)/'native-project.json'
    saved=json.loads(registry.read_text(encoding='utf-8')) if registry.is_file() else {}
    mode=saved.get('environment_mode','default')
    if mode not in ('default','strict'):raise ValueError('未知绘图环境模式')
    required=saved.get('required_versions',requirements())
    executable=sys.executable
    if mode=='strict':
        if backend not in ('local-python','macos-seatbelt'):
            raise ValueError('严格复现需要本机独立环境；当前容器后端未配置对应环境，未自动回退。')
        executable=str(ROOT/('.native-venv/Scripts/python.exe' if os.name=='nt' else '.native-venv/bin/python'))
        if not Path(executable).is_file():
            raise ValueError('已选择严格复现，但独立环境 .native-venv 不存在。可改用“默认环境优先”试绘，或准备 requirements-native.txt 指定的独立环境。')
    if backend=='docker':
        return {'mode':mode,'backend':backend,'executable':executable,'required_versions':required,
                'versions':{},'fingerprint':'docker:'+os.environ.get('CHART_RENDERER_IMAGE','plot-forge-renderer'),
                'warnings':['使用当前容器的默认绘图环境；包版本以实际容器为准，未宣称严格复现。']}
    code='''import sys,json,importlib.metadata as m
packages={d.metadata['Name']:d.version for d in m.distributions() if d.metadata['Name']}
print(json.dumps({'python':sys.version,'prefix':sys.prefix,'base_prefix':sys.base_prefix,'versions':packages}))
'''
    try:
        run=subprocess.run([executable,'-I','-c',code],capture_output=True,text=True,encoding='utf-8',timeout=20)
        if run.returncode:raise ValueError(run.stderr[-1200:])
        actual=json.loads(run.stdout)
    except (OSError,subprocess.TimeoutExpired,ValueError) as exc:
        raise ValueError('无法检查所选绘图环境：'+str(exc)) from exc
    normalized={k.lower().replace('_','-'):v for k,v in actual['versions'].items()}
    differences=[f"{name}：项目指定 {version}，当前 {normalized.get(name.lower().replace('_','-'),'未安装')}"
                 for name,version in required.items() if normalized.get(name.lower().replace('_','-'))!=version]
    if mode=='strict' and differences:
        raise ValueError('严格复现环境的版本不符合项目声明：'+'；'.join(differences))
    warnings=(['使用平台默认环境试绘；版本差异不阻止执行，出图成功不代表严格复现。',*differences] if differences else [])
    fingerprint=hashlib.sha256(json.dumps([mode,backend,executable,actual,required],sort_keys=True).encode()).hexdigest()
    return {**actual,'mode':mode,'backend':backend,'executable':executable,'required_versions':required,
            'warnings':warnings,'fingerprint':fingerprint}
