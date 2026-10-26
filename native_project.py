"""Local adapters for the reviewed portable main-figure plotting package.

This direct-mode importer does not ask an LLM to regenerate frozen scientific
calculations. Every original source and supported asset is preserved.
"""
import ast
import hashlib
import json
import re
from pathlib import Path
import shutil
import tempfile
import threading
import time

import project_preparation as prep

PROFILES = {
    'fig1': ('redraw_uniform_axes.py', 'pixels',
             'import redraw_uniform_axes\nredraw_uniform_axes.main()'),
    'fig2': ('reorganize_main_figures_20261015.py', 'save',
             'import reorganize_main_figures_20261015 as renderer\nrenderer.figure2()'),
    'fig3': ('render_fig3.py', 'save',
             "import render_fig3 as renderer\nsys.argv=['render_fig3.py','--output-dir',str(root/'output')]\nrenderer.main()"),
    'fig4': ('render_fig4.py', 'build',
             "import render_fig4 as renderer\nrenderer.build(root/'output')"),
    'fig5': ('reassemble.py', 'save', 'import reassemble\nreassemble.figure5()'),
    'fig6': ('reassemble.py', 'save', 'import reassemble\nreassemble.figure6()'),
    'fig7': ('figure6_layout.py', 'assemble',
             "import render_fig6_full_joint90_free_beta as renderer\nsys.argv=['render_fig6_full_joint90_free_beta.py','--output-dir',str(root/'output')]\nrenderer.main()"),
}


def discover(root):
    """Recognize this supported frozen package, not arbitrary run.py folders."""
    root = Path(root)
    if not root.is_dir() or root.is_symlink():
        return None
    candidates = [root, *sorted(p for p in root.iterdir() if p.is_dir() and not p.is_symlink())]
    for folder in candidates:
        readme = folder/'README.md'
        if not readme.is_file():
            continue
        text = readme.read_text(encoding='utf-8-sig')
        if 'mini_DG' not in text or '冻结' not in text:
            continue
        if all((folder/key/'run.py').is_file() and (folder/key/'code'/profile[0]).is_file()
               and (folder/key/'reference'/(key+'.png')).is_file() for key, profile in PROFILES.items()):
            return folder
    return None


def chart_source(ident, invocation):
    body = '\n'.join('    '+line for line in invocation.splitlines())
    return f'''"""{ident}: independent native plot from frozen project inputs.

Edit customize() to change the visible artists. Coordinates, tables, ordering
and statistics stay in read-only data/native/{ident}; native helpers are in lib.
"""
import sys
from native_plot_runtime import prepare_native, render_native

NATIVE_FIGURE = {ident!r}


def customize(figure):
    # Presentation-only edits; all original axes and artists are available here.
    # Example: figure.axes[0].set_title("New title")
    pass


def produce():
    root = prepare_native(NATIVE_FIGURE)
{body}


render_native(NATIVE_FIGURE, customize, produce)
'''


def selection(project, entry, overrides=None):
    path = project/'native-project.json'
    if not path.is_file():
        return None
    registry = json.loads(path.read_text())
    if registry.get('schema') != 'plot-forge-native/1':
        raise ValueError('Unsupported native registry')
    text = (overrides or {}).get(entry)
    if text is None:
        text = (project/entry).read_text(encoding='utf-8')
    tree = ast.parse(text)
    values = [node.value.value for node in tree.body if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == 'NATIVE_FIGURE' for t in node.targets)
        and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)]
    if len(values) != 1 or not re.fullmatch(r'fig[1-9][0-9]*',values[0]) or values[0] not in registry['figures']:
        raise ValueError('Native entry must declare exactly one known NATIVE_FIGURE')
    return values[0]


def prepare(project, source, progress=None, previous_state=None):
    """Stage all seven independent entries; install only after every render."""
    from chat_runner import _one_render
    from PIL import Image
    import numpy as np
    project, source = Path(project), Path(source)
    package = discover(source)
    if package is None:
        raise ValueError('未识别受支持的独立冻结绘图包')
    original_state = previous_state if previous_state is not None else prep.read_state(project)
    _, files, skipped = prep.inventory(source)
    digest_records = []
    with tempfile.TemporaryDirectory(prefix='plot-native-prepare-') as temp:
        work = Path(temp);staged = work/'project'
        for folder in ('charts','lib','data','previews','validation'):
            (staged/folder).mkdir(parents=True)
        prep.write_json(staged/'project.json', {'name': project.name, 'data_source_type': 'native_plot'})
        registry = {'schema':'plot-forge-native/1', 'figures':{}}
        for ident, (save_file, save_function, invocation) in PROFILES.items():
            registry['figures'][ident] = {'save_file':save_file,'save_function':save_function}
            if save_file == 'redraw_uniform_axes.py':
                registry['figures'][ident].update(save_occurrence=2,compose='native_results_with_approved_top',
                                                 cut_px=3024,approved_top='source/F1ab.png')
            (staged/'charts'/(ident+'.py')).write_text(chart_source(ident, invocation), encoding='utf-8')
            for item in files:
                original = source/item['path']
                if original.is_symlink() or not original.resolve().is_relative_to(source.resolve()):
                    raise ValueError('Native source changed to an external link')
                try:
                    relative = original.relative_to(package/ident)
                except ValueError:
                    continue
                # Preserve all source and assets, excluding only generated QA,
                # references and prior outputs from runtime dependencies.
                if relative.parts[0] in ('output','qa','reference','revisions'):
                    continue
                area = 'lib' if item['kind'] == 'code' else 'data'
                target = staged/area/'native'/ident/relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(original, target)
                digest_records.append({'path':item['path'],'sha256':prep.sha(original),
                                       'stored':target.relative_to(staged).as_posix()})
        copied = {r['path'] for r in digest_records}
        for item in files:
            if item['kind'] != 'code' or item['path'] in copied:
                continue
            original = source/item['path']
            target = staged/'lib/native_support'/item['path']
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(original, target)
            digest_records.append({'path':item['path'],'sha256':prep.sha(original),
                                   'stored':target.relative_to(staged).as_posix()})
        prep.write_json(staged/'native-project.json', registry)
        checks = []
        cache = project/'.preparation/native-cache'
        cache.mkdir(parents=True, exist_ok=True)
        platform = [prep.sha(prep.ROOT/name) for name in
                    ('native_plot_runtime.py','chat_runner.py','font_policy.py','requirements-native.txt')]
        environment = [(p.name,prep.sha(p)) for p in sorted(
            (prep.ROOT/'.native-venv').glob('lib/python*/site-packages/*.dist-info/METADATA'))]
        for index, ident in enumerate(PROFILES, 1):
            if progress:
                progress(index, len(PROFILES), ident)
            dependencies = [r for r in digest_records if r['stored'].startswith(('lib/native/'+ident+'/', 'data/native/'+ident+'/'))]
            fingerprint = hashlib.sha256(json.dumps([ident,dependencies,platform,environment,
                (staged/'charts'/(ident+'.py')).read_text()],sort_keys=True).encode()).hexdigest()
            cached_report, cached_image = cache/(ident+'.json'), cache/(ident+'.png')
            record = json.loads(cached_report.read_text()) if cached_report.is_file() else {}
            if (record.get('key') == fingerprint and cached_image.is_file()
                    and prep.sha(cached_image) == record.get('image_sha256')
                    and record.get('report',{}).get('output_count') == 1):
                report = {**record['report'],'image_bytes':cached_image.read_bytes()}
            else:
                report = _one_render(staged, 'charts/'+ident+'.py', {}, work/('render_'+ident), strict_io=True)
                cached_image.write_bytes(report['image_bytes'])
                prep.write_json(cached_report, {'key':fingerprint,'image_sha256':prep.sha(cached_image),
                    'report':{k:v for k,v in report.items() if k != 'image_bytes'}})
            if report['output_count'] != 1:
                raise ValueError('Native entry must produce exactly one selected figure')
            (staged/'previews'/(ident+'.png')).write_bytes(report['image_bytes'])
            with Image.open(package/ident/'reference'/(ident+'.png')) as reference, Image.open(staged/'previews'/(ident+'.png')) as actual:
                a, b = np.asarray(reference.convert('RGB')), np.asarray(actual.convert('RGB'))
                matching = a.shape == b.shape and bool(np.array_equal(a,b))
                reference_check = {'same_shape':a.shape == b.shape,'pixel_identical':matching,
                                   'reference_size':list(reference.size),'render_size':list(actual.size)}
            checks.append({'figure_id':ident,'render':'passed','output_count':1,
                           'backend':report.get('render_backend','configured renderer'),
                           'os_sandbox':bool(report.get('os_sandbox')),
                           'inputs':'byte-identical frozen source snapshot',
                           'source':'original native modules unchanged', 'reference':reference_check})
            prep.write_json(work/(ident+'-capture.json'), {k:v for k,v in report.items() if k != 'image_bytes'})
        # Input and code copy integrity is checked again before install.
        for record in digest_records:
            if prep.sha(staged/record['stored']) != record['sha256']:
                raise ValueError('Frozen dependency bytes changed during preparation')
            if prep.sha(source/record['path']) != record['sha256']:
                raise ValueError('Original source changed during preparation; retry after reviewing it')
        prep.install_verified(project,staged,('charts','lib','data','previews'),work/'rollback')
        prep.write_json(project/'native-project.json', registry)
        references=preserve_references(project,package)
        prep.write_json(project/'validation/native.json', {'state':'passed','mode':'direct',
            'checks':checks,'source_files':digest_records,'references':references,
            'basis':'Existing frozen plotting code and inputs preserved byte-for-byte; one native entry per figure. Reference image comparison is reported separately.'})
        metadata = json.loads((project/'project.json').read_text())
        prep.write_json(project/'project.json', {**metadata,'data_source_type':'native_plot',
            'plot_forge_format':1,'description':'7 张独立原生图；冻结数据与绘图代码分离'})
        seed_previews(project)
        # Failed historical batches are retained, but no longer govern this
        # validated direct project. No old preparation evidence is destroyed.
        prep.write_json(project/'.preparation/prior-native-state.json', original_state)
        figures = [{'figure_id':ident,'entry_path':'charts/'+ident+'.py'} for ident in PROFILES]
        mismatches=sum(not c['reference']['pixel_identical'] for c in checks)
        reason=f'{len(PROFILES)} 张原生图均已独立试绘通过；可进入对话改图。'
        if mismatches:
            reason+=f'其中 {mismatches} 张与历史参考 PNG 存在像素差异，请审阅预览和验证报告。'
        prep.save_state(project, {**original_state,'status':'ready','mode':'native',
            'reason':reason,
            'figures':figures,'generated_files':[], 'validation':{'state':'passed','checks':checks},
            'updated_at':time.time()})
    return prep.status(project)


def seed_previews(project):
    """Reuse the verified PNGs without triggering seven gallery re-renders."""
    from server import save_preview, save_naming
    for entry in sorted((project/'charts').glob('*.py')):
        image=project/'previews'/(entry.stem+'.png')
        record=project/'.preparation/native-cache'/(entry.stem+'.json')
        if not image.is_file() or not record.is_file():
            continue
        source=entry.read_text(encoding='utf-8')
        save_preview(project,entry.stem,source,image.read_bytes(),'.png')
        value=json.loads(record.read_text())['report']
        save_naming(project,entry.stem,source,value.get('naming',{}))


def preserve_references(project,package):
    records=[]
    for ident in PROFILES:
        original=package/ident/'reference'/(ident+'.png')
        target=project/'images/original'/(ident+'.png')
        target.parent.mkdir(parents=True,exist_ok=True)
        if target.exists() and prep.sha(target)!=prep.sha(original):
            raise ValueError('已有同名原图不同，未覆盖：'+ident)
        if not target.exists():shutil.copy2(original,target)
        records.append({'figure_id':ident,'path':target.relative_to(project).as_posix(),'sha256':prep.sha(target)})
    return records


def start(project, consent):
    if not consent:
        raise ValueError('请先确认信任此本机绘图工程，并允许逐图试绘')
    with prep.LOCK:
        if str(project) in prep.RUNNING:
            raise ValueError('工程正在准备中')
        previous = prep.read_state(project)
        if prep.can_open(project):
            return prep.status(project)
        if any((project/'charts').glob('*.py')):
            raise ValueError('工程已有绘图代码，请另建副本，避免覆盖已有修改')
        source = Path(previous.get('source_path', ''))
        if not previous.get('source_path') or discover(source) is None:
            raise ValueError('原始独立绘图包已移动或不受支持，请重新选择目录')
        prep.RUNNING.add(str(project))
        started = time.time()

        def progress(index, total, ident):
            prep.save_state(project, {**previous,'status':'working','mode':'native',
                'reason':f'本机拆分与验证：第 {index}/{total} 张 · {ident}；不调用模型。',
                'native_progress':{'completed':index-1,'total':total,'current':ident,'started_at':started},
                'updated_at':time.time()})

        progress(1,len(PROFILES),'fig1')

        def work():
            try:
                prepare(project, source, progress=progress, previous_state=previous)
            except Exception as exc:
                prep.save_state(project, {**previous,'status':'needs_context','mode':'native',
                    'reason':'本机绘图验证未通过：'+str(exc)[:2500],
                    'validation':{'state':'failed'},'updated_at':time.time()})
            finally:
                with prep.LOCK:
                    prep.RUNNING.discard(str(project))
        threading.Thread(target=work,daemon=True).start()
        return prep.status(project)
