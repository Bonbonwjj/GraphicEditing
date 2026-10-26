"""Whole-project extraction with bounded requests and an all-batches validation gate."""
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import tempfile
import threading
import time
import zipfile

import analysis_scope
import project_preparation as prep


def plan(project):
    sources = analysis_scope.sources_for(project)
    if not sources:
        raise ValueError('没有可分析的 Python 源码，请先备份源工程')
    trees, groups, blocked = {}, [], []
    # Union of independently resolved dependency closures is still a closure.
    # First-fit groups every target once; helpers may appear as context in more
    # than one request. Never cut a file or discard an oversized dependency.
    for target in sorted(sources):
        single = analysis_scope.build(project, targets=[target], source_cache=sources, tree_cache=trees, deduplicate=True)
        if not single['within_limit']:
            blocked.append({'targets': [target], 'files': set(single['files'])})
            continue
        for group in groups:
            union = group['files'] | set(single['files'])
            if sum(len(text) for text in {sources[p] for p in union}) <= analysis_scope.LIMIT:
                group['targets'].append(target);group['files'] = union
                break
        else:
            groups.append({'targets': [target], 'files': set(single['files'])})
    jobs = []
    for group in groups + blocked:
        detail = analysis_scope.build(project, targets=group['targets'], source_cache=sources, tree_cache=trees, deduplicate=True)
        ident = 'batch_' + hashlib.sha256('\n'.join(group['targets']).encode()).hexdigest()[:12]
        jobs.append({'id': ident, **detail})
    digest = hashlib.sha256(json.dumps([(j['id'], j['confirmation_token']) for j in jobs]).encode()).hexdigest()
    return {'version': 1, 'confirmation_token': digest, 'source_files': len(sources),
            'source_chars': sum(map(len, sources.values())), 'jobs': jobs}


def public_plan(value):
    return {**value, 'jobs': [{'id': j['id'], **analysis_scope.public(j)} for j in value['jobs']]}


def batch_path(project):
    return project/'.preparation/batch.json'


def read(project):
    return json.loads(batch_path(project).read_text(encoding='utf-8'))


def public_status(project):
    if not batch_path(project).is_file():
        return None
    value = read(project)
    if str(project) not in prep.RUNNING:
        value.pop('current', None)
        for job in value['jobs']:
            if job['status'] == 'working':
                job.update(status='interrupted', reason='上次任务中断，确认计划后可继续')
    return {**value, 'jobs': [{k: v for k, v in j.items() if k not in ('sources',)} for j in value['jobs']]}


def child_path(project, ident):
    if not isinstance(ident, str) or not re.fullmatch(r'batch_[0-9a-f]{12}', ident):
        raise ValueError('无效批次 ID')
    child = project/'.preparation/batches'/ident
    if child.is_symlink() or not child.resolve().is_relative_to(project.resolve()):
        raise ValueError('批次路径不安全')
    return child


def save(project, batch, working=False):
    prep.write_json(batch_path(project), batch)
    counts = {}
    for job in batch['jobs']:
        counts[job['status']] = counts.get(job['status'], 0) + 1
    all_ready = bool(batch['jobs']) and counts.get('ready') == len(batch['jobs'])
    pending = counts.get('pending_local_run', 0)
    failed = sum(counts.get(k, 0) for k in ('failed', 'needs_context', 'unsupported', 'blocked', 'validation_failed'))
    current = prep.read_state(project)
    state = 'working' if working else 'pending_local_run' if pending and not failed else 'needs_context'
    reason = f"整工程共 {len(batch['jobs'])} 批：已验证 {counts.get('ready', 0)}，待本地导出/验证 {pending}，需处理 {failed}。"
    if batch.get('current'):
        reason += ' 当前：' + batch['current']
    if all_ready and not working:
        state = 'ready' if batch.get('installed') else 'pending_local_run'
    prep.save_state(project, {**current, 'mode': 'batch', 'status': state,
                             'reason': reason, 'analysis_scope': '', 'analysis_summary': None,
                             'generated_files': [], 'figures': [], 'updated_at': time.time()})


def start(project, consent, token):
    if not consent:
        raise ValueError('请先确认整工程的批次数、源码范围及云端发送权限')
    with prep.LOCK:
        if str(project) in prep.RUNNING:
            raise ValueError('工程任务正在运行')
        if prep.read_state(project).get('status') == 'ready':
            raise ValueError('工程已可改图；重新拆分请另建副本，避免覆盖已应用修改')
        if prep.read_state(project).get('mode') != 'batch' and prep.read_state(project).get('generated_files'):
            raise ValueError('当前已有单组提取方案，请另建副本进行整工程拆分，避免覆盖已有成果')
        if prep.read_state(project).get('mode') != 'batch' and any((project/'charts').glob('*.py')):
            raise ValueError('当前副本已有绘图代码，请另建副本批量提取，避免覆盖已有图表')
        computed = plan(project)
        if token != computed['confirmation_token']:
            raise ValueError('整工程源码或批次计划已变化，请重新规划并确认')
        from model_transport import guard_secrets
        guard_secrets(analysis_scope.sources_for(project))
        if batch_path(project).is_file():
            batch = read(project)
            if batch['confirmation_token'] != token:
                raise ValueError('已有批次与当前源码不一致，请另建副本，保留原批次成果')
        else:
            batch = public_plan(computed)
            for job in batch['jobs']:
                job['status'] = 'pending' if job['within_limit'] else 'blocked'
                job['reason'] = '' if job['within_limit'] else '单个目标的完整依赖超过单次上限，未截断或发送'
        # A model asking for more context cannot recover by receiving the same
        # unchanged source scope again. Only transport failures/interruption and
        # previously unsubmitted jobs are retryable with this confirmation.
        retryable = {'pending', 'failed', 'interrupted', 'working'}
        attempt_jobs = [j['id'] for j in batch['jobs'] if j['status'] in retryable]
        if not attempt_jobs:
            raise ValueError('没有可直接重试的批次。缺少依赖或不支持的批次须先修正源码/依赖规划并重新确认；重复发送相同源码无法解决。已生成的方案请继续本机导出与验证。')
        batch['attempt'] = {'started_at': time.time(), 'jobs': attempt_jobs, 'returned': []}
        batch['phase'] = 'analysis'
        prep.RUNNING.add(str(project));save(project, batch, working=True)
        def work():
            try:
                for detail, job in zip(computed['jobs'], batch['jobs']):
                    if job['id'] not in attempt_jobs:
                        continue
                    child = child_path(project, job['id'])
                    for folder in ('charts','data','lib','previews','history','validation','.preparation'):
                        (child/folder).mkdir(parents=True, exist_ok=True)
                    prep.write_json(child/'project.json', {'name': job['id']})
                    prep.write_json(child/'batch-child.json', {'version': 1})
                    original = prep.read_state(project)
                    prep.save_state(child, {'status': 'needs_analysis', 'batch_child': True,
                                           'files': original['files'], 'source_path': original.get('source_path')})
                    job.update(status='working', reason='正在分析完整源码并生成独立提取方案',
                               started_at=time.time())
                    batch['current'] = job['id'];save(project, batch, working=True)
                    try:
                        result = prep.analyze(child, True, plan=detail)
                        job.update(status=result['status'], reason=result.get('reason', ''))
                    except Exception as exc:
                        job.update(status='failed', reason=str(exc)[:1500])
                    job['finished_at'] = time.time()
                    batch['attempt']['returned'].append(job['id'])
                    save(project, batch, working=True)
            except Exception as exc:
                batch['error'] = str(exc)[:1500]
            finally:
                batch.pop('current', None)
                batch['attempt']['finished_at'] = time.time()
                for job in batch['jobs']:
                    if job['status'] == 'working':job.update(status='failed', reason='批次中断，可重试')
                with prep.LOCK:
                    save(project, batch);prep.RUNNING.discard(str(project))
        threading.Thread(target=work, daemon=True).start()
        return prep.status(project)


def archive(project):
    batch = read(project)
    output = io.BytesIO();total = 0
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr(project.name+'/batch-plan.json', json.dumps(batch, ensure_ascii=False, indent=2))
        for job in batch['jobs']:
            child = child_path(project, job['id'])
            for item in prep.read_state(child).get('generated_files', []):
                total += len(item['content'].encode())
                if total > 200*1024**2:raise ValueError('批次源文件包超过 200 MiB')
                z.writestr(project.name+'/'+job['id']+'/'+str(prep.relative_path(item['path'])), item['content'])
        z.writestr(project.name+'/RUN_EXPORT.txt',
            '每批先审阅 *_export.py 与 render_plot.py。逐批把导出程序放到原工程根目录，用原分析环境执行。\n'
            '每批输出到新的 <统一导出目录>/<batch_ID>/，其中须包含 manifest.json。不要覆盖原数据。\n'
            '全部导出后，在应用中填写统一导出目录并确认本机验证；任一批次未通过，不会把整个工程标记为完成。\n'
            '此包只是提取方案，不是可直接改图的完成备份；blocked/failed/needs_context 批次仍需处理。\n')
    return output.getvalue()


def merge_verified(project, batch):
    if not batch['jobs'] or any(j['status'] != 'ready' for j in batch['jobs']):
        raise ValueError('全部批次验证通过前不能汇总为完成工程')
    from chat_runner import _one_render
    # Final project is installed atomically only after re-rendering namespaced
    # adapters. No direct-mode module rewriting and no bypass of value checks.
    with tempfile.TemporaryDirectory(prefix='plot-batch-merge-') as temp:
        work = Path(temp);staged = work/'project'
        for name in ('charts','data','previews'):(staged/name).mkdir(parents=True)
        prep.write_json(staged/'project.json', {'name': project.name})
        checks = []
        for job in batch['jobs']:
            child = child_path(project, job['id']);value = prep.read_state(child)
            if value.get('status') != 'ready' or value.get('mode') != 'extract':
                raise ValueError('批次不是已验证的独立提取结果')
            renderer = next(f['content'] for f in value['generated_files'] if f['role'] == 'renderer')
            prep.validate_renderer(renderer)
            bundle = child/'data/plot-data'
            manifest, _, _ = prep.validate_package(bundle)
            exporter = next(f['content'] for f in value['generated_files'] if f['role'] == 'export_program')
            if manifest['producer']['source_sha256'] != hashlib.sha256(exporter.encode()).hexdigest():
                raise ValueError('批次导出程序绑定发生变化')
            destination = staged/'data'/job['id']
            shutil.copytree(bundle, destination)
            ids = [f['figure_id'] for f in manifest['figures']]
            if set(ids) != {f['figure_id'] for f in value.get('figures', [])}:
                raise ValueError('批次图表集合与已审阅的提取方案不一致')
            for ident in ids:
                name = job['id']+'__'+ident
                adapter = renderer + '\n\nimport os as _pf_os\nfrom pathlib import Path as _PFPath\n'
                adapter += '_pf_bundle = _PFPath(_pf_os.environ["CHART_PROJECT_DIR"])/"data"/'+repr(job['id'])+'\n'
                adapter += '_pf_ids = list_figures(_pf_bundle)\n_pf_ids = [x["figure_id"] if isinstance(x, dict) else x for x in _pf_ids]\n'
                adapter += 'assert _pf_ids == '+repr(ids)+', "Renderer figure registry differs from manifest"\n'
                adapter += 'render(_pf_bundle, '+repr(ident)+', _pf_os.environ["CHART_OUTPUT"])\n'
                (staged/'charts'/(name+'.py')).write_text(adapter, encoding='utf-8')
                report = _one_render(staged, 'charts/'+name+'.py', {}, work/name)
                if report['output_count'] != 1:raise ValueError('汇总图必须单次只输出一张图')
                (staged/'previews'/(name+'.png')).write_bytes(report['image_bytes'])
                checks.append({'chart': name, 'batch': job['id'], 'figure_id': ident, 'render': 'passed'})
        prep.install_verified(project, staged, ('charts','data','previews'), work/'rollback')
        prep.write_json(project/'validation/batch.json', {'state': 'passed', 'checks': checks,
                                                       'coverage': [{'id':j['id'],'targets':j['target_files']} for j in batch['jobs']]})
    batch['installed'] = True


def start_finalize(project, bundle_root, consent):
    if not consent:raise ValueError('请先审阅全部批次代码，并确认允许本机验证')
    root = Path(bundle_root).expanduser()
    if not bundle_root or not root.is_dir() or root.is_symlink():
        raise ValueError('请选择包含各 batch_ID 子目录的统一导出目录')
    with prep.LOCK:
        if str(project) in prep.RUNNING:raise ValueError('工程任务正在运行')
        batch = read(project)
        if batch.get('installed'):return prep.status(project)
        batch['phase'] = 'validation'
        prep.RUNNING.add(str(project));save(project, batch, working=True)
        def work():
            try:
                for job in batch['jobs']:
                    if job['status'] not in ('pending_local_run','validation_failed'):continue
                    batch['current'] = job['id'];save(project, batch, working=True)
                    try:
                        prep.finalize(child_path(project, job['id']), str(root/job['id']), True)
                        job.update(status='ready', reason='绘图输入与逐图渲染验证通过')
                    except Exception as exc:job.update(status='validation_failed', reason=str(exc)[:1500])
                    save(project, batch, working=True)
                if all(j['status'] == 'ready' for j in batch['jobs']):
                    batch['phase'] = 'merge';save(project, batch, working=True)
                    merge_verified(project, batch)
            except Exception as exc:batch['error'] = str(exc)[:1500]
            finally:
                batch.pop('current', None)
                with prep.LOCK:
                    save(project, batch);prep.RUNNING.discard(str(project))
        threading.Thread(target=work, daemon=True).start()
        return prep.status(project)
