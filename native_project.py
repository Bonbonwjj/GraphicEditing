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
from interactive_style import apply_interactive_style

NATIVE_FIGURE = {ident!r}
FIGURE_SOURCE_REF = 'lib/native/{ident}/code'
FIGURE_DIRECT_INPUTS = ('data/native/{ident}',)
FIGURE_DRAWING_CODE = {invocation!r}

# --- PLOT_FORGE_INTERACTIVE_STYLE_START ---
INTERACTIVE_STYLE = {{'border_width': 1.0, 'border_color': '#333333',
                     'legend_location': 'best', 'legend_names': {{}}}}
# --- PLOT_FORGE_INTERACTIVE_STYLE_END ---


def customize(figure):
    # Presentation-only edits; all original axes and artists are available here.
    # Use panel_axes(figure, visible_panel, explicit_mapping) for panel-local edits.
    apply_interactive_style(figure, INTERACTIVE_STYLE)


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


def prepare(project, source, progress=None, previous_state=None, environment_mode="default"):
    """Stage all seven independent entries; install only after every render."""
    from chat_runner import _one_render, isolation_backend, CandidateRenderError
    from render_environment import describe, requirements
    from PIL import Image
    import numpy as np
    if environment_mode not in ('default','strict'):raise ValueError('未知绘图环境模式')
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
        registry = {'schema':'plot-forge-native/1', 'environment_mode':environment_mode,
                    'required_versions':requirements(package/'requirements.txt') or requirements(), 'figures':{}}
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
                    ('native_plot_runtime.py','interactive_style.py','chat_runner.py','font_policy.py','requirements-native.txt','render_environment.py')]
        try:
            environment = describe(staged,isolation_backend())
        except ValueError as exc:
            environment={'mode':environment_mode,'unavailable':True,'warnings':[str(exc)],
                         'required_versions':registry['required_versions'],
                         'fingerprint':hashlib.sha256((environment_mode+str(exc)).encode()).hexdigest()}

        prep.write_json(project/'.preparation/environment.json',environment)
        for index, ident in enumerate(PROFILES, 1):
            if progress:
                progress(index, len(PROFILES), ident)
            dependencies = [r for r in digest_records if r['stored'].startswith(('lib/native/'+ident+'/', 'data/native/'+ident+'/'))]
            fingerprint = hashlib.sha256(json.dumps([ident,dependencies,platform,environment['fingerprint'],
                (staged/'charts'/(ident+'.py')).read_text()],sort_keys=True).encode()).hexdigest()
            cached_report, cached_image = cache/(ident+'.json'), cache/(ident+'.png')
            try:
                if environment.get('unavailable'):
                    raise CandidateRenderError(environment['warnings'][0],'environment_invalid')
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
                    raise CandidateRenderError('Native entry must produce exactly one selected figure')
                (staged/'previews'/(ident+'.png')).write_bytes(report['image_bytes'])
                with Image.open(package/ident/'reference'/(ident+'.png')) as reference, Image.open(staged/'previews'/(ident+'.png')) as actual:
                    a, b = np.asarray(reference.convert('RGB')), np.asarray(actual.convert('RGB'))
                    matching = a.shape == b.shape and bool(np.array_equal(a,b))
                    reference_check = {'same_shape':a.shape == b.shape,'pixel_identical':matching,
                                       'reference_size':list(reference.size),'render_size':list(actual.size)}
                layout_warnings=report.get('native_layout_warnings',[])
                checks.append({'figure_id':ident,'render':'warning' if layout_warnings else 'passed','output_count':1,
                               'native_layout_warnings':layout_warnings,
                               'native_checks_complete':not bool(layout_warnings),
                               'reason':'; '.join(w['warning']+' '+w['condition']+'：'+w['message'] for w in layout_warnings),
                               'backend':report.get('render_backend','configured renderer'),
                               'os_sandbox':bool(report.get('os_sandbox')),
                               'render_environment':report.get('render_environment',environment),
                               'warnings':environment['warnings'],
                               'inputs':'byte-identical frozen source snapshot',
                               'source':'original native modules unchanged', 'reference':reference_check})
                prep.write_json(work/(ident+'-capture.json'), {k:v for k,v in report.items() if k != 'image_bytes'})
            except CandidateRenderError as exc:
                if exc.code=='scope_rejected':raise
                checks.append({'figure_id':ident,'render':'failed','output_count':0,
                               'reason':str(exc),'error_code':exc.code,'render_environment':environment})
        # Input and code copy integrity is checked again before install.
        for record in digest_records:
            if prep.sha(staged/record['stored']) != record['sha256']:
                raise ValueError('Frozen dependency bytes changed during preparation')
            if prep.sha(source/record['path']) != record['sha256']:
                raise ValueError('Original source changed during preparation; retry after reviewing it')
        prep.install_verified(project,staged,('charts','lib','data','previews'),work/'rollback')
        prep.write_json(project/'native-project.json', registry)
        from panel_index import build as build_panel_index
        for ident in PROFILES:
            build_panel_index(project, ident)
        references=preserve_references(project,package)
        passed=sum(c['render']=='passed' for c in checks)
        diagnostics=sum(c['render']=='warning' for c in checks)
        failed=sum(c['render']=='failed' for c in checks)
        validation_state='passed' if passed==len(PROFILES) else 'partial' if failed else 'warnings'
        prep.write_json(project/'validation/native.json', {'state':validation_state,'mode':'direct','import_completed':True,
            'checks':checks,'source_files':digest_records,'references':references,
            'basis':'Code and inputs imported byte-for-byte. Trial render results are recorded independently for each figure; import does not imply every figure rendered successfully.'})
        metadata = json.loads((project/'project.json').read_text())
        prep.write_json(project/'project.json', {**metadata,'data_source_type':'native_plot',
            'plot_forge_format':1,'description':'7 张独立原生图；冻结数据与绘图代码分离'})
        seed_previews(project)
        # Failed historical batches are retained, but no longer govern this
        # validated direct project. No old preparation evidence is destroyed.
        prep.write_json(project/'.preparation/prior-native-state.json', original_state)
        figures = [{'figure_id':ident,'entry_path':'charts/'+ident+'.py'} for ident in PROFILES]
        mismatches=sum(not c.get('reference',{}).get('pixel_identical',True) for c in checks)
        warnings=[*environment['warnings'],*[c['figure_id']+'：'+c['reason'] for c in checks if c['render']=='warning'],*[c['figure_id']+'：试绘未通过，尚无可用预览。'+c['reason'].strip().splitlines()[-1] for c in checks if c['render']=='failed']]
        reason=f'导入成功：已保留 {len(PROFILES)} 张图的代码和数据；可预览 {passed+diagnostics}/{len(PROFILES)} 张，完整试绘检查通过 {passed}/{len(PROFILES)} 张。'
        if failed:reason+=' 尚未生成图片的入口已保留代码和错误详情。'
        if diagnostics:reason+=f' {diagnostics} 张已显示布局警告预览，后续原程序检查未完成。'
        if environment['warnings'] and environment_mode=='default':reason+=' 使用默认绘图环境，版本差异已记录，请审阅环境警告。'
        if mismatches:
            reason+=f'其中 {mismatches} 张与历史参考 PNG 存在像素差异，请审阅预览和验证报告。'
        prep.save_state(project, {**original_state,'status':'ready','mode':'native',
            'reason':reason,'import_completed':True,'task_outcome':{'status':'success','label':'导入成功'+('（部分图试绘未通过，有警告）' if passed<len(PROFILES) else '：全部图试绘通过')},'environment_mode':environment_mode,'render_environment':environment,'warnings':warnings,
            'figures':figures,'generated_files':[], 'native_progress':{'completed':len(PROFILES),'passed':passed,'total':len(PROFILES),'failed':failed,'diagnostics':diagnostics}, 'validation':{'state':validation_state,'checks':checks},
            'updated_at':time.time()})
    return prep.status(project)


def record_preview(project, chart, report):
    """Persist real diagnostic PNG status separately from hard render errors."""
    with prep.LOCK:
        value=prep.read_state(project)
        if not value.get('import_completed') or value.get('mode')!='native' or str(project) in prep.RUNNING:return
        checks=value.get('validation',{}).get('checks',[])
        check=next((c for c in checks if c.get('figure_id')==chart),None)
        if check is None:return
        findings=report.get('native_layout_warnings',[])
        if check.get('render')=='failed':check['original_trial_error']=check.get('reason')
        check.update(render='warning' if findings else 'passed',output_count=1,native_layout_warnings=findings,native_checks_complete=not bool(findings),
                     reason='; '.join(w['warning']+' '+w['condition']+'：'+w['message'] for w in findings),
                     reference_status='not_rechecked')
        check.pop('reference',None)
        passed=sum(c.get('render')=='passed' for c in checks)
        failed=sum(c.get('render')=='failed' for c in checks)
        diagnostics=sum(c.get('render')=='warning' for c in checks)
        environment=report.get('render_environment') or value.get('render_environment',{})
        warnings=[*environment.get('warnings',[]),*[c['figure_id']+'：'+c['reason'] for c in checks if c.get('render') in ('warning','failed')]]
        validation_state='partial' if failed else 'warnings' if diagnostics else 'passed'
        value.update(render_environment=environment,warnings=warnings,
            reason=f'导入成功：共 {len(checks)} 张图，正常预览 {passed} 张，布局警告预览 {diagnostics} 张，未出图 {failed} 张。',
            task_outcome={'status':'success','label':'导入成功'+('（有试绘警告）' if diagnostics or failed else '')},
            native_progress={'completed':len(checks),'total':len(checks),'passed':passed,'failed':failed,'diagnostics':diagnostics})
        value['validation'].update(state=validation_state,checks=checks)
        marker=project/'validation/native.json'
        audit=json.loads(marker.read_text(encoding='utf-8'));audit.update(state=validation_state,checks=checks)
        prep.write_json(marker,audit);prep.save_state(project,value)


def seed_previews(project):
    """Reuse the verified PNGs without triggering seven gallery re-renders."""
    from server import save_preview, save_naming
    from chart_naming import RenderedImage
    for entry in sorted((project/'charts').glob('*.py')):
        image=project/'previews'/(entry.stem+'.png')
        record=project/'.preparation/native-cache'/(entry.stem+'.json')
        if not image.is_file() or not record.is_file():
            continue
        source=entry.read_text(encoding='utf-8')
        value=json.loads(record.read_text())['report']
        payload=RenderedImage(image.read_bytes());payload.render_report=value
        save_preview(project,entry.stem,source,payload,'.png')
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


def start(project, consent, environment_mode="default"):
    if environment_mode not in ("default","strict"):raise ValueError("未知绘图环境模式")
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
        (project/'.preparation/environment.json').unlink(missing_ok=True)
        source = prep.source_root(project)
        if discover(source) is None:source=Path(previous.get('source_path',''))
        if discover(source) is None:
            raise ValueError('原始独立绘图包已移动或不受支持，请重新选择目录')
        prep.RUNNING.add(str(project))
        started = time.time()

        def progress(index, total, ident):
            environment_file=project/'.preparation/environment.json'
            current_environment=json.loads(environment_file.read_text(encoding='utf-8')) if environment_file.is_file() else {}
            prep.save_state(project, {**previous,'status':'working','mode':'native',
                'reason':f'本机拆分与验证：第 {index}/{total} 张 · {ident}；不调用模型。',
                'environment_mode':environment_mode,'task_outcome':None,
                'render_environment':current_environment,'warnings':current_environment.get('warnings',[]),
                'native_progress':{'completed':index-1,'total':total,'current':ident,'started_at':started},
                'updated_at':time.time()})

        progress(1,len(PROFILES),'fig1')

        def work():
            try:
                prepare(project, source, progress=progress, previous_state=previous, environment_mode=environment_mode)
            except Exception as exc:
                environment_file=project/'.preparation/environment.json'
                environment=json.loads(environment_file.read_text(encoding='utf-8')) if environment_file.is_file() else {}
                failed_progress=prep.read_state(project).get('native_progress',{})
                summary=f"已处理 {failed_progress.get('completed',0)}/{failed_progress.get('total',len(PROFILES))} 张；当前 {failed_progress.get('current','准备阶段')} 未通过。"
                prep.save_state(project, {**previous,'status':'needs_context','mode':'native',
                    'environment_mode':environment_mode,'render_environment':environment,'warnings':environment.get('warnings',[]),
                    'native_progress':failed_progress,'reason':summary+'本机绘图验证未通过：'+str(exc)[:2500],
                    'validation':{'state':'failed','completed':failed_progress.get('completed',0),'total':failed_progress.get('total',len(PROFILES)),'failed_figure':failed_progress.get('current')},'task_outcome':{'status':'failed','label':'失败：'+('默认环境' if environment_mode=='default' else '严格复现环境')+'试绘未通过'},'updated_at':time.time()})
            finally:
                with prep.LOCK:
                    prep.RUNNING.discard(str(project))
        threading.Thread(target=work,daemon=True).start()
        return prep.status(project)
