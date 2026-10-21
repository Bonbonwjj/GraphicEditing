"""Persistent, chart-scoped draft workflow. No candidate replaces an applied chart."""
import base64
import csv
import hashlib
import io
import json
import os
import re
import shutil
from pathlib import Path
import threading
import time
import uuid
from datetime import datetime, timezone

from agent_http import post_json
from chat_agent import propose, validate_response, MAX_MODEL_ATTEMPTS
from chat_diagnostics import explain_draft, check_results
from chat_parameters import propose_parameters
from model_config import effective as effective_model_config

LOCKS = {}
LOCK_GUARD = threading.Lock()


def lock(key):
    with LOCK_GUARD:
        return LOCKS.setdefault(str(key), threading.RLock())


def uid(prefix):
    return prefix + '_' + str(uuid.uuid4())


def digest(value):
    return 'sha256:' + hashlib.sha256(value if isinstance(value, bytes) else value.encode()).hexdigest()


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8', newline="\n")
    temporary.replace(path)


MAX_PROMPT_CSV_CHARS = 40_000


def scoped_plot_data(files, chart):
    """Keep revision hashes for every CSV, but send only chart-relevant rows to the model."""
    all_sources = '\n'.join(item['content'] for item in files.values() if item['path'].endswith('.py'))
    entry = files.get('charts/' + chart + '.py', {}).get('content', '')
    data_names = [Path(path).name for path in files if path.endswith(('.csv', '.tsv'))]
    sources = entry if any(name in entry for name in data_names) else all_sources
    result = []
    for item in files.values():
        path = item['path']
        if not path.endswith(('.csv', '.tsv')):
            continue
        delimiter = '\t' if path.endswith('.tsv') else ','
        rows = list(csv.reader(io.StringIO(item['content']), delimiter=delimiter))
        columns, data_rows = (rows[0], rows[1:]) if rows else ([], [])
        referenced = Path(path).name in sources or path in sources
        selected = data_rows if referenced else []
        scope = 'complete' if referenced else 'schema_only'
        id_column = next((i for i, name in enumerate(columns) if name in ('panel_id', 'chart_id')), None)
        if referenced and id_column is not None and chart in sources:
            matching = [row for row in data_rows if len(row) > id_column and row[id_column] == chart]
            if matching:
                selected, scope = matching, 'matching_chart_rows'
        output = io.StringIO()
        writer = csv.writer(output, delimiter=delimiter, lineterminator='\n')
        if columns:
            writer.writerow(columns)
        included = 0
        for row in selected:
            before = output.tell()
            writer.writerow(row)
            if output.tell() > MAX_PROMPT_CSV_CHARS:
                output.seek(before)
                output.truncate()
                scope = 'truncated_sample'
                break
            included += 1
        result.append({**item, 'content': output.getvalue(), 'columns': columns,
                       'read_only': True, 'content_scope': scope,
                       'source_row_count': len(data_rows), 'included_row_count': included})
    return result


class ChatHarness:
    def __init__(self, host, agent=None, renderer=None, visual_agent=None):
        self.host = host
        self.agent = agent or self.call_agent
        self.renderer = renderer
        self.visual_agent = visual_agent or self.call_agent

    def read_reference_features(self,session,context):
        from reference_visual_review import cache_key,visual_request,validate
        cache=session.setdefault('reference_feature_cache',{})
        key=cache_key(context)
        if key not in cache:
            session['progress']['stage']='reading_reference';self.save(session)
            request=visual_request(context,'extract')
            cache[key]=validate(request,self.visual_agent(request))
            # Bound cache growth while keeping pinned, reusable observations.
            while len(cache)>12:cache.pop(next(iter(cache)))
            self.save(session)
        return json.loads(json.dumps(cache[key]))

    def compare_reference_features(self,session,context,draft,budget):
        from reference_visual_review import visual_request,validate,unavailable
        draft['reference_features']=context['reference_features']
        if not draft.get('image_path'):
            draft['reference_comparison']=unavailable(draft['reference_features'],'候选尚未成功出图。');return
        if budget['used']>=MAX_MODEL_ATTEMPTS:
            draft['reference_comparison']=unavailable(draft['reference_features'],'本轮三次模型调用已用完；保留候选供审阅，尚未完成视觉对照。');return
        session['progress']['stage']='comparing_reference';self.save(session)
        try:
            request=visual_request(context,'compare',draft)
            draft['reference_comparison']=validate(request,self.visual_agent(request))
        except Exception as error:
            draft['reference_comparison']=unavailable(draft['reference_features'],'视觉对照未完成：'+str(error)[:500])
        comparison=draft['reference_comparison']
        draft.setdefault('check_results',[]).append({'name':'参考图关键特征（审阅项）',
            'status':{'match':'pass','different':'mismatch'}.get(comparison['status'],'unverified'),
            'reason':'视觉匹配结果供审阅，不阻断继续修改或应用；数据及版本检查独立执行。'})

    def call_agent(self, context):
        url = os.environ.get('CHAT_AGENT_URL')
        model_auth=effective_model_config()
        request=dict(context,_model_auth=model_auth)
        if not url:return propose(request)
        budget=context.get('_model_attempt_budget',{'used':0})
        remaining=MAX_MODEL_ATTEMPTS-budget['used']
        if remaining<=0:raise ValueError('本张图本轮模型调用已达到 3 次上限')
        try:
            response=post_json(url.rstrip('/')+'/v1/chat-edit', request, timeout=600)
        except Exception:
            # A failed remote Agent may already have spent its available calls.
            budget['used']=MAX_MODEL_ATTEMPTS
            raise
        used=response.get('model_attempts_used')
        budget.setdefault('calls',[]).extend(response.get('model_calls',[]))
        budget['used']+=used if type(used) is int and 1<=used<=remaining else remaining
        return response

    def directory(self, project):
        return self.host.project_path(project) / '.chat'

    def identity(self, project):
        folder = self.directory(project)
        with lock(folder):
            path = folder/'identity.json'
            value = read_json(path) if path.exists() else {'project_id':uid('prj'), 'charts':{}}
            p = self.host.project_path(project)
            excluded = set(read_json(p/'project.json').get('non_chart_scripts', []))
            for f in sorted((p/'charts').glob('*.py')):
                if f.stem not in excluded:
                    value['charts'].setdefault(f.stem, uid('cht'))
            atomic_json(path,value)
            return value

    def records(self, project, charts):
        p = self.host.project_path(project)
        identity = self.identity(project)
        result = []
        for chart in charts:
            self.host.chart_path(project,chart)
            if chart not in identity['charts']:
                raise ValueError('所选条目不是已登记的图')
            result.append({'chart':chart,'chart_id':identity['charts'][chart],
                           'display_name':self.host.chart_naming(p,chart)['display_name']})
        return result

    def snapshot(self, project, chart):
        p, entry = self.host.chart_path(project, chart)
        candidates = [entry]
        for directory in ('lib','data'):
            if (p/directory).exists():
                candidates += [f for f in (p/directory).rglob('*') if f.is_file() and '__pycache__' not in f.parts]
        # Root-level project helpers are also dependencies.
        candidates += list(p.glob('*.py'))
        if (p/'data_sources.json').is_file(): candidates.append(p/'data_sources.json')
        files = {}
        total = 0
        for f in sorted(set(candidates)):
            if f.is_symlink() or not f.resolve().is_relative_to(p.resolve()):
                raise ValueError('项目含有指向外部的依赖；请将绘图文件直接放入项目')
            if f.suffix.lower() not in ('.py','.csv','.tsv','.json'):
                continue
            raw = f.read_bytes(); total += len(raw)
            if total > 8_000_000:
                raise ValueError('绘图上下文超过 8 MB；请将这张图实际使用的汇总数据整理成较小文件')
            path = f.relative_to(p).as_posix()
            files[path] = {'path':path,'content':raw.decode('utf-8-sig').replace('\r\n', '\n').replace('\r', '\n'),'sha256':digest(raw),'writable':f==entry}
        dependencies = dict((k,v['sha256']) for k,v in files.items())
        # The Chat Skill controls future proposals, not the applied chart or
        # an already-rendered draft. Updating its wording must not invalidate
        # a candidate that was reviewed against unchanged drawing inputs.
        dependencies.update(self.platform_dependencies())
        if any('chart_type_defaults' in f.get('content','') for f in files.values()):
            helper=self.host.ROOT/'chart_type_defaults.py'
            dependencies['@platform/chart_type_defaults.py']=digest(helper.read_bytes())
        if any('paired_plot' in f.get('content','') for f in files.values()):
            dependencies['@platform/paired_plot.py']=digest((self.host.ROOT/'paired_plot.py').read_bytes())
        if any(any(name in f.get('content','') for name in ('axis_range_policy','chart_type_defaults')) for f in files.values()):
            dependencies['@platform/axis_range_policy.py']=digest((self.host.ROOT/'axis_range_policy.py').read_bytes())
        from bundle_bindings import signature as bundle_signature
        bundle_revision=bundle_signature(p)
        if bundle_revision: dependencies['@bundle/source']=bundle_revision
        revision = digest(json.dumps(dependencies,sort_keys=True))
        return files, revision

    def platform_dependencies(self):
        return {'@platform/'+str(f.relative_to(self.host.ROOT)):digest(f.read_bytes())
                for f in (self.host.ROOT/'studio_style.py',self.host.ROOT/'chart_overrides.py',self.host.NORMALIZATION_PROFILE)}

    def ensure_current_base(self,session,record):
        """Compatibility alias: version changes are informational, not a gate."""
        return self.refresh_action_base(session,record)

    def create(self, project, charts, references=None):
        if not isinstance(charts,list) or not charts or len(charts)>100 or len(set(charts))!=len(charts):
            raise ValueError('请选择 1 到 100 张不重复的图')
        records = self.records(project,charts)
        session = {'id':uid('ses'),'project':project,'project_id':self.identity(project)['project_id'],
                   'chart_ids':[r['chart_id'] for r in records], 'charts':records,
                   'base_revisions':{},'base_sources':{},'active_drafts':{},'turns':[], 'drafts':[],
                   'base_platform_hashes':self.platform_dependencies(),
                   'reference_images':[],'references':self.references(project,references or []),'layout_exceptions':{},'status':'open',
                   'created_at':datetime.now(timezone.utc).isoformat()}
        for record in records:
            files,revision = self.snapshot(project,record['chart'])
            session['base_revisions'][record['chart_id']] = revision
            session['base_sources'][record['chart_id']] = files
            record['_image']=self.cached_image(project,record['chart'],files['charts/'+record['chart']+'.py']['content'],revision)
            if self.snapshot(project,record['chart'])[1]!=revision:raise ValueError('项目在创建会话时发生变化，请重试')
        self.save(session)
        return self.public(session)

    def path(self, project, sid):
        if not isinstance(sid,str) or not sid.startswith('ses_'):
            raise ValueError('Invalid session ID')
        uuid.UUID(sid[4:])
        return self.directory(project)/'sessions'/sid/'session.json'

    def load(self, project, sid):
        path = self.path(project,sid)
        if not path.is_file():
            raise ValueError('改图会话不存在')
        return read_json(path)

    def save(self, session):
        atomic_json(self.path(session['project'],session['id']),session)

    def public(self, session):
        value=json.loads(json.dumps(session))
        value.pop('base_sources',None)
        value.pop('font_context_cache',None)
        value.pop('reference_feature_cache',None)
        for record in value['charts']:record.pop('_image',None)
        for draft in value['drafts']:
            draft['diagnostics'] = explain_draft(draft)
            draft['can_continue'] = self.can_continue_draft(draft)
            draft['can_apply_after_reference_review']=self.can_apply_after_reference_review(draft)
            draft['can_apply']=self.can_continue_draft(draft)
            if draft['can_continue'] and draft['status'] not in ('preview_ready','applied','discarded'):
                from edit_contract import finish_summary
                finish_summary(draft)
            if draft.get('baseline_image_path'):
                draft['baseline_image_url'] = (f"/api/projects/{session['project']}/chat/sessions/{session['id']}"
                                               f"/drafts/{draft['id']}/baseline-image")
            draft.pop('image_path',None)
            draft.pop('_image',None)
            draft.pop('baseline_image_path',None)
        for turn in value['turns']:
            for result in turn.get('results',[]):result.pop('_image',None)
        from chat_reference_images import public as public_images
        value['reference_images']=public_images(value.get('reference_images',[]))
        for ref in value['references']:
            ref.pop('source_files',None);ref.pop('plot_data',None);ref.pop('_image',None)
        return value

    def get(self, project, sid):
        path=self.path(project,sid)
        guard=lock(path)
        acquired=guard.acquire(blocking=False)
        try:
            session=self.load(project,sid)
            if acquired and session.get('status')=='running':
                session['status']='interrupted'
                session.pop('progress',None)
                self.save(session)
            return self.public(session)
        finally:
            if acquired:guard.release()

    def list(self, project, charts=None):
        result=[]
        for path in (self.directory(project)/'sessions').glob('*/session.json'):
            session=self.get(project,path.parent.name)
            if charts is None or set(charts)=={r['chart'] for r in session['charts']}:
                result.append(session)
        return sorted(result,key=lambda s:s['created_at'],reverse=True)

    def history(self, project):
        """Project-wide chat timeline without candidate source code or CSV snapshots."""
        sessions=[]
        draft_fields=('id','turn_id','chart','chart_id','display_name','status','summary',
                      'reason','warnings','layout','image_url','baseline_image_url',
                      'normalization_report','font_audit','visual_change','created_at','edit_contract',
                      'proposal_summary','check_results','diagnostics','chart_transform','chart_type_style','generation_path',
                      'reference_features','reference_comparison','can_apply_after_reference_review')
        for session in self.list(project):
            drafts=[]
            for draft in session['drafts']:
                item={key:draft[key] for key in draft_fields if key in draft}
                proposal=draft.get('proposal') or {}
                item['proposal']={key:proposal[key] for key in
                                  ('interpreted_request','expected_effects','normalization_checks')
                                  if key in proposal}
                drafts.append(item)
            sessions.append({'id':session['id'],'project':project,'charts':session['charts'],
                             'status':session['status'],'created_at':session['created_at'],
                             'active_drafts':session['active_drafts'],'turns':session['turns'],
                             'drafts':drafts,'reference_images':session.get('reference_images',[])})
        return sessions

    def cached_image(self,project,chart,source,revision):
        p=self.host.project_path(project)
        with self.host.preview_lock(p,chart):
            image=p/'previews'/(chart+'.png');meta=p/'previews'/(chart+'.json')
            if not image.is_file() or not meta.is_file():return None
            if read_json(meta).get('signature')!=self.host.preview_signature(p,source):return None
            assets=self.directory(project)/'reference_assets';assets.mkdir(parents=True,exist_ok=True)
            payload=image.read_bytes()
            # Both bytes and dependency revision contribute to this immutable asset name.
            target=assets/(digest(revision+digest(payload)).split(':')[1]+'.png')
            if not target.exists():
                with target.open('xb') as stream:stream.write(payload)
            return str(target)

    def references(self, project, names):
        if not isinstance(names,list) or len(names)>10:
            raise ValueError('最多选择 10 张参照图')
        result=[]
        p=self.host.project_path(project)
        for record in self.records(project,list(dict.fromkeys(names))):
            files,revision=self.snapshot(project,record['chart'])
            item={**record,'revision_id':revision,'read_only':True,
                  'source_files':[dict(f,writable=False) for f in files.values() if f['path'].endswith('.py')],
                  'plot_data':scoped_plot_data(files,record['chart'])}
            item['_image']=self.cached_image(project,record['chart'],files['charts/'+record['chart']+'.py']['content'],revision)
            if self.snapshot(project,record['chart'])[1]!=revision:raise ValueError('参照图在读取时发生变化，请重试')
            result.append(item)
        return result

    def context(self, session, record, turn, parent, exception, skip_font_audit=False):
        from shared_modules import discover_modules
        chart_id=record['chart_id']
        files=json.loads(json.dumps(session['base_sources'][chart_id]))
        if parent:
            for path,source in parent['code'].items():
                files[path]['content']=source;files[path]['sha256']=digest(source)
        plot_data=scoped_plot_data(files,record['chart'])
        from paired_plot import discover_contract
        paired_data=discover_contract(self.host.project_path(session['project']),record['chart'],plot_data)
        lineage=[];ancestor=parent
        by_id={d['id']:d for d in session['drafts']}
        while ancestor and ancestor['id'] not in lineage:
            lineage.append(ancestor['id']);ancestor=by_id.get(ancestor.get('parent_draft_id'))
        recent=[]
        for previous in session['turns'][-12:]:
            for result in previous.get('results',[]):
                if result.get('chart_id')==chart_id:
                    recent.append({'turn_id':previous['id'],'user_message':previous['user_message'],
                                   'status':result['status'],'summary':result.get('summary'),
                                   'reason':result.get('reason'),'draft_id':result.get('draft_id'),
                                   'in_active_lineage':result.get('draft_id') in lineage})
        refs=json.loads(json.dumps(session['references']))
        image_paths=[]
        for ref in refs:
            image_path=ref.pop('_image',None)
            if image_path:image_paths.append((ref['chart_id'],image_path))
        from chat_reference_images import select as select_images,public as public_images,MAX_MODEL_IMAGES
        uploaded=select_images(self.directory(session['project']),[r['reference_id'] for r in turn.get('reference_images',[])]) if turn['operation']!='normalize' else []
        image_paths=[(r['reference_id'],r['_image']) for r in uploaded]+image_paths
        target_image=parent.get('image_path') if parent else record.get('_image')
        if target_image:image_paths.insert(0,('current_target',target_image))
        images=[];image_order=[]
        if effective_model_config()['vision_enabled']:
            from PIL import Image
            for ident,path in image_paths[:MAX_MODEL_IMAGES]:
                with Image.open(path) as source_image:
                    preview=source_image.copy()
                    preview.thumbnail((1024,1024),Image.Resampling.LANCZOS)
                    encoded=io.BytesIO()
                    preview.save(encoded,format='PNG',optimize=True)
                    data=encoded.getvalue()
                if len(data)<2_000_000:
                    images.append('data:image/png;base64,'+base64.b64encode(data).decode());image_order.append(ident)
        if uploaded and any(r['reference_id'] not in image_order for r in uploaded):
            raise ValueError('参考图未能传入模型；请检查图片输入配置或重新上传较小的参考图')
        font_audit=parent.get('font_audit') if parent else None
        if turn['operation']!='normalize' and not font_audit and not skip_font_audit:
            cache_key=parent['id'] if parent else session['base_revisions'][chart_id]
            cache=session.setdefault('font_context_cache',{})
            font_audit=cache.get(cache_key)
            if font_audit is None:
                from chat_runner import inspect_chart_fonts
                try:
                    font_audit=inspect_chart_fonts(self.host.project_path(session['project']),
                                               'charts/'+record['chart']+'.py',parent['code'] if parent else None)
                except Exception as error:
                    font_audit={'status':'unverified','fonts':[],
                                'reason':'字体预检查未完成，继续生成修改方案：'+str(error)[:500]}
                cache[cache_key]=font_audit
                self.save(session)
        platform_helper=None
        entry_source=files['charts/'+record['chart']+'.py']['content']
        if turn['operation']=='chat_edit' and 'finish_normalized_figure' in entry_source:
            helper=(self.host.ROOT/'studio_style.py').read_text(encoding='utf-8')
            excerpt=helper[helper.index('def normalize_figure_geometry('):helper.index('def plotting_error_values(')]
            profile=read_json(self.host.NORMALIZATION_PROFILE)
            platform_helper={'path':'@platform/studio_style.py','read_only':True,
                             'content':excerpt,'profile_png_dpi':profile['global']['png_dpi']}
        return {'request_id':uid('req'),'edit_session_id':session['id'],'turn_id':turn['id'],
                'project_id':session['project_id'],'chart_id':chart_id,'target_display_name':record['display_name'],
                'base_revision':session['base_revisions'][chart_id],'parent_draft_id':parent['id'] if parent else None,
                'batch_target_count':len(session['chart_ids']),
                'chart_type_style':__import__('chart_type_defaults').conversion_style(turn['user_message']),
                'user_message':turn['user_message'],'source_files':[f for f in files.values() if f['path'].endswith('.py')],
                'plot_data':plot_data,'allowed_write_paths':['charts/'+record['chart']+'.py'],
                'paired_plot_data':paired_data,
                'reference_images':public_images(uploaded),'reference_charts':refs,'project_chart_catalog':self.records(session['project'],list(self.identity(session['project'])['charts'])),
                'shared_module_catalog':discover_modules(self.host.project_path(session['project'])),
                'conversation_context':{'recent_turns':recent,'active_parent_lineage':lineage,
                    'active_source_authoritative':True,'non_lineage_turns':'Historical context only; do not reapply their changes or preservation constraints to this branch.',
                    'active_draft_summary':parent.get('summary') if parent else None},
                'current_font_audit':font_audit,
                'harness_layout_feedback':({'candidate_code':parent['code'],'layout':parent.get('layout'),
                    'reason':parent.get('reason'),'accepted_exception':exception}
                    if parent and parent.get('status') not in ('preview_ready','applied') else None),
                'platform_render_helper':platform_helper,
                'constraints':['CSV and shared dependencies are read-only','Preserve data and scientific meaning','Only selected chart entry is writable','Default avoid unintended overlap; report unsupported checks'],
                'layout_exception':exception,'visual_context_available':bool(images),'target_image_available':'current_target' in image_order,
                'image_order':image_order,'_images':images}

    def resolve_parent(self,session,chart_id,parents):
        ident=parents.get(chart_id,session['active_drafts'].get(chart_id))
        if ident is None:return None
        candidate=next((d for d in session['drafts'] if d['id']==ident and d['chart_id']==chart_id),None)
        if not candidate or not self.can_continue_draft(candidate):
            raise ValueError('该版本没有可继续修改的候选代码')
        return candidate

    @staticmethod
    def can_apply_after_reference_review(draft):
        # Compatibility field. All candidate checks are advisory for actions.
        return ChatHarness.can_continue_draft(draft)

    @staticmethod
    def can_continue_draft(draft):
        return bool(isinstance(draft.get('code'),dict) and draft['code']
                    and all(isinstance(code,str) and code.strip() for code in draft['code'].values()))

    def refresh_action_base(self,session,record):
        """Use current dependencies without rejecting an older candidate branch."""
        files,revision=self.snapshot(session['project'],record['chart'])
        previous=session['base_revisions'].get(record['chart_id'])
        if previous!=revision:
            session.setdefault('base_refreshes',[]).append({'chart_id':record['chart_id'],
                'from':previous,'to':revision,'at':time.time()})
        session['base_sources'][record['chart_id']]=files
        session['base_revisions'][record['chart_id']]=revision
        session['base_platform_hashes']=self.platform_dependencies()
        return files,revision

    def exception(self,session,chart_id,body,message):
        requested=body.get('layout_exception')
        if not requested:return session.get('layout_exceptions',{}).get(chart_id)
        quote=requested.get('authorization_quote')
        if not isinstance(quote,str) or not quote or quote not in message:
            raise ValueError('布局例外必须包含本轮用户的明确授权原话')
        ids=requested.get('warning_ids',[])
        diagnostic=next((d for d in reversed(session['drafts']) if d['chart_id']==chart_id and d.get('layout',{}).get('issues')),None)
        known={i['id']:i for i in (diagnostic or {}).get('layout',{}).get('issues',[]) if i.get('id')}
        if not ids or any(i not in known for i in ids):raise ValueError('只能接受已显示的布局冲突')
        result={'chart_id':chart_id,'warning_ids':ids,'issues':[known[i] for i in ids],'authorization_quote':quote,
                'base_revision':session['base_revisions'][chart_id],'diagnostic_draft_id':diagnostic['id'],
                'layout_signature':diagnostic.get('layout_signature')}
        session.setdefault('layout_exceptions',{})[chart_id]=result
        return result

    def turn(self, project, sid, body, normalize=False):
        path=self.path(project,sid)
        guard=lock(path)
        if not guard.acquire(blocking=False):raise ValueError('该会话仍在生成，请等待上一轮结束')
        try:
            session=self.load(project,sid)
            if session.get('status')=='closed':session['status']='open'
            if 'reference_charts' in body:
                requested_refs=body['reference_charts']
                if not isinstance(requested_refs,list) or len(requested_refs)>10:raise ValueError('最多选择 10 张参照图')
                retained={r['chart']:r for r in session['references']}
                fresh={r['chart']:r for r in self.references(project,[r for r in requested_refs if r not in retained])}
                session['references']=[retained.get(r) or fresh[r] for r in dict.fromkeys(requested_refs)]
            message=body.get('user_message','') if not normalize else '按所选 Skill 规范化绘图'
            if not isinstance(message,str) or not message.strip() or len(message)>5000:raise ValueError('请输入不超过 5000 字的修改要求')
            from chat_reference_images import select as select_images,public as public_images
            image_refs=[] if normalize else select_images(self.directory(project),body.get('reference_image_ids',[r['reference_id'] for r in session.get('reference_images',[])]))
            if image_refs and not effective_model_config().get('vision_enabled'):
                raise ValueError('使用上传参考图需要支持图片输入的模型。请在顶部 API 配置中开启“改图时将当前图和参照图传给支持视觉的模型”，保存后重试。')
            if not normalize:session['reference_images']=public_images(image_refs)
            turn={'reference_images':public_images(image_refs),'id':uid('trn'),'user_message':message,'operation':'normalize' if normalize else 'chat_edit','results':[],'created_at':time.time()}
            session['turns'].append(turn);session['status']='running';session.pop('completed_at',None);self.save(session)
            records=session['charts']
            override_target=(body.get('layout_exception') or {}).get('chart_id')
            if body.get('layout_exception'):
                if not override_target and len(records)==1:override_target=records[0]['chart_id']
                if override_target not in session['chart_ids']:raise ValueError('请选择已显示冲突的具体目标图')
                records=[r for r in records if r['chart_id']==override_target]
            for record in records:
                result={**record}
                chart_started=time.monotonic()
                attempt_budget={'used':0}
                session['progress']={'stage':'preparing','chart_id':record['chart_id'],
                                     'display_name':record['display_name'],'started_at':time.time()}
                self.save(session)
                try:
                    self.refresh_action_base(session,record)
                    # Normalization always starts from the applied chart. A
                    # preview left active after the user declines it must not
                    # silently become the input to another standardization.
                    parent=None if normalize else self.resolve_parent(session,record['chart_id'],body.get('parent_drafts',{}))
                    exception=self.exception(session,record['chart_id'],body,message)
                    from chat_parameters import parse_requests
                    skip_font_audit=not normalize and not exception and parse_requests(message) is not None
                    context=self.context(session,record,turn,parent,exception,skip_font_audit=skip_font_audit)
                    context['_model_attempt_budget']=attempt_budget
                    if image_refs:
                        context['reference_features']=self.read_reference_features(session,context)
                    context['layout_exception_requested']=bool(body.get('layout_exception'))
                    if exception:
                        diagnostic=next((d for d in reversed(session['drafts']) if d['chart_id']==record['chart_id'] and d.get('layout',{}).get('issues')),None)
                        if diagnostic:
                            context['harness_layout_feedback']={'layout':diagnostic['layout'],'candidate_code':diagnostic['code'],'accepted_exception':exception}
                    if normalize:
                        session['progress']['stage']='model_request';self.save(session)
                        response=self.normalization(context,body.get('skill_id','chart-normalization'),project,
                                                    use_cache=not body.get('force_refresh',False))
                    else:
                        session['progress']['stage']='model_request';self.save(session)
                        from chart_transform import simple_distribution_request
                        requested_kind=simple_distribution_request(message)
                        verified=(parent or {}).get('chart_transform') or {}
                        if (not image_refs and requested_kind and parent and parent.get('status')=='preview_ready'
                                and verified.get('status')=='pass' and verified.get('kind')==requested_kind):
                            name='箱线图' if requested_kind=='boxplot' else '小提琴图'
                            response={'status':'already_compliant','existing_draft_id':parent['id'],
                                      'reason':f'当前候选已经是{name}，且原始样本检查通过；可直接应用此版，或继续提出具体修改。',
                                      'warnings':[]}
                        else:
                            response=None if image_refs else propose_parameters(context)
                            if response is None:
                                if skip_font_audit and not context.get('current_font_audit'):
                                    from chat_runner import inspect_chart_fonts
                                    try:context['current_font_audit']=inspect_chart_fonts(self.host.project_path(project),context['allowed_write_paths'][0],parent['code'] if parent else None)
                                    except Exception as error:context['current_font_audit']={'status':'unverified','fonts':[],'reason':str(error)[:500]}
                                response=validate_response(context,self.agent(context))
                        if response['status']=='needs_context':
                            # A uniquely identified reference can be loaded without changing the target.
                            wanted=json.dumps(response,ensure_ascii=False)
                            matches=[c['chart'] for c in context['project_chart_catalog'] if c['chart_id'] in wanted and c['chart_id']!=record['chart_id']]
                            existing={r['chart'] for r in session['references']}
                            if matches and set(matches)-existing:
                                session['references']+=self.references(project,[c for c in matches if c not in existing])
                                context=self.context(session,record,turn,parent,exception)
                                context['_model_attempt_budget']=attempt_budget
                                if image_refs:context['reference_features']=self.read_reference_features(session,context)
                                response=validate_response(context,self.agent(context))
                        if response['status']=='already_compliant' and (parse_requests(message) or self.axis_requirement(message)):
                            # Render the unchanged parent through the same Harness checks.
                            # An Agent assertion alone must not establish that ticks and
                            # the drawn spine actually match the requested endpoints.
                            entry=context['allowed_write_paths'][0]
                            source=next(f for f in context['source_files'] if f['path']==entry)
                            response={**response,'status':'candidate',
                                      'proposed_files':[{'path':entry,'base_sha256':source['sha256'],'content':source['content']}],
                                      'summary':response.get('reason') or '检查当前图的坐标轴',
                                      'warnings':response.get('warnings') or [],
                                      'layout_policy':{'mode':'avoid_overlap'},
                                      'expected_effects':['Check requested X/Y axis limits and continuous spine on exported image']}
                    if (not normalize and response['status']=='already_compliant' and not response.get('existing_draft_id')):
                        # Unsupported semantic assertions have no independent evidence.
                        response={**response,'status':'manual_review',
                                  'summary':'模型认为当前图已满足要求；本轮要求尚无法自动核对，请对照当前图人工审阅。',
                                  'reason':'模型的完成判断未被可测量的最终导出结果证实，不能标为自动验收通过。'}
                    if response['status']!='candidate':
                        result.update({k:response.get(k) for k in ('status','reason','question','summary','warnings')})
                        from chat_module_route import module_handoff
                        handoff=module_handoff(context,response)
                        if handoff:
                            result['module_handoff']=handoff
                            result['status']='needs_shared_module'
                        if response.get('existing_draft_id'):result['draft_id']=response['existing_draft_id']
                    else:
                        session['progress']['stage']='rendering';self.save(session)
                        draft=self.build_draft(session,record,turn,parent,context,response)
                        check_history=[{'status':draft['status'], 'diagnostics':explain_draft(draft)}]
                        # Format correction and render repair share three model calls.
                        for repair_attempt in range(MAX_MODEL_ATTEMPTS-1):
                            if (normalize or attempt_budget['used']>=MAX_MODEL_ATTEMPTS or exception or draft.get('review_blocker')=='paired_presentation' or
                                    draft.get('chart_transform',{}).get('source_evidence',{}).get('status') in ('summary_only','insufficient_samples') or
                                    (draft['status'] not in ('render_failed','needs_clarification','no_visible_change','axis_unmet','font_unverified','intent_unmet','intent_unverified')
                                     and draft.get('review_blocker') not in ('transform_unverified','paired_unverified','source_scope_mismatch'))):
                                break
                            session['progress']['stage']='repairing';self.save(session)
                            context['request_id']=uid('req')
                            if not context.get('current_font_audit'):
                                context['current_font_audit']=draft.get('baseline_font_audit')
                            context['harness_layout_feedback']={'candidate_code':draft['code'],'layout':draft.get('layout'),
                                                                 'visual_change':draft.get('visual_change'),
                                                                 'font_audit':draft.get('font_audit'),
                                                                 'chart_transform':draft.get('chart_transform'),
                                                                 'edit_contract':draft.get('edit_contract'),
                                                                 'reason':draft.get('reason'),
                                                                 'repair_attempts_remaining':MAX_MODEL_ATTEMPTS-attempt_budget['used']}
                            try:
                                repaired=validate_response(context,self.agent(context))
                                if repaired['status']=='candidate':
                                    draft=self.build_draft(session,record,turn,parent,context,repaired)
                                    check_history.append({'status':draft['status'], 'diagnostics':explain_draft(draft)})
                                else:
                                    draft['repair_result']={k:repaired.get(k) for k in ('status','reason','question')}
                                    draft['reason']=repaired.get('reason') or draft.get('reason')
                                    break
                            except Exception as error:
                                draft['warnings'].append('自动修复未完成：'+str(error))
                                break
                        if image_refs:self.compare_reference_features(session,context,draft,attempt_budget)
                        _,after_revision=self.snapshot(project,record['chart'])
                        if after_revision!=context['base_revision']:
                            draft.update(status='revision_conflict',reason='生成期间正式版本或依赖已变化，请新建会话')
                        from edit_contract import finish_summary
                        finish_summary(draft)
                        draft['check_history']=check_history
                        draft['diagnostics']=explain_draft(draft)
                        if normalize and draft['status']=='preview_ready' and not response.get('reused_cache'):
                            try:self.save_normalization_cache(project,context,response)
                            except OSError as error:print(f'Normalization cache unavailable: {error}',flush=True)
                        session['drafts'].append(draft)
                        if self.can_continue_draft(draft):
                            session['active_drafts'][record['chart_id']]=draft['id']
                        result.update(status=draft['status'],draft_id=draft['id'],summary=draft['summary'],reason=draft.get('reason'),warnings=draft.get('warnings',[]))
                except Exception as error:
                    result.update(status='revision_conflict' if 'revision_conflict' in str(error) else 'cannot_complete',reason=str(error))
                result['model_attempts']=attempt_budget['used']
                result['model_usage_scope']='normalization' if normalize else 'chat'
                result['elapsed_seconds']=round(time.monotonic()-chart_started,3)
                result['model_calls']=attempt_budget.get('calls',[])
                result['diagnostics']=explain_draft(result) if not result.get('draft_id') else []
                turn['results'].append(result);session.pop('progress',None);self.save(session)
            session['status']='open';session['completed_at']=time.time();session.pop('progress',None);self.save(session)
            return self.public(session)
        except Exception:
            if 'turn' in locals():
                session['status']='open';session['completed_at']=time.time();session.pop('progress',None);self.save(session)
            raise
        finally:guard.release()

    def normalization_cache_path(self,project,context,skill_id,skill_hash,profile_hash,model_name):
        identity=[context['chart_id'],context['base_revision'],skill_id,skill_hash,profile_hash,model_name]
        name=digest(json.dumps(identity,ensure_ascii=False,sort_keys=True)).split(':',1)[1]
        return self.directory(project)/'normalization_cache'/(name+'.json')

    def save_normalization_cache(self,project,context,response):
        interpreted=response.get('interpreted_request') or {}
        model_name=effective_model_config()['model']
        path=self.normalization_cache_path(project,context,interpreted['skill_id'],interpreted['skill_sha256'],
                                           interpreted['profile_sha256'],model_name)
        atomic_json(path,{'response':response,'source_sha256':next(f['sha256'] for f in context['source_files']
                                                                  if f['path']==context['allowed_write_paths'][0])})

    def normalization(self,context,skill_id,project,use_cache=True):
        from normalizer_agent import normalize_source
        skill,profile=self.host.skill_files(skill_id)
        entry=context['allowed_write_paths'][0]
        source=next(f for f in context['source_files'] if f['path']==entry)
        related={f['path']:f['content'] for f in context['source_files'] if f['path']!=entry}
        url=os.environ.get('NORMALIZER_AGENT_URL')
        model_auth=effective_model_config()
        skill_hash=digest(skill);profile_hash=digest(json.dumps(profile,sort_keys=True))
        cache_path=self.normalization_cache_path(project,context,skill_id,skill_hash,profile_hash,model_auth['model'])
        if use_cache and cache_path.is_file():
            try:cached=read_json(cache_path)
            except (OSError,ValueError) as error:
                print(f'Normalization cache ignored: {error}',flush=True)
                cached={}
            if cached.get('source_sha256')==source['sha256']:
                response=cached.get('response') or {}
                files=response.get('proposed_files') or []
                if (len(files)==1 and files[0].get('path')==entry and files[0].get('base_sha256')==source['sha256']
                        and response.get('status')=='candidate'):
                    print(f"Normalization cache hit: chart_id={context['chart_id']}",flush=True)
                    return {**response,**{k:context[k] for k in ('request_id','edit_session_id','turn_id','parent_draft_id',
                                                                  'chart_id','base_revision','user_message')},
                            'reused_cache':True}
        if url:
            result=post_json(url.rstrip('/')+'/v1/normalize', {'source':source['content'],'data_schema':context['plot_data'],
                           'style_profile':profile,'related_sources':related,'skill_text':skill,
                           'request_id':context['request_id'],'base_revision':context['base_revision'],
                           'model_auth':model_auth}, timeout=150)
            if result.get('request_id')!=context['request_id'] or result.get('base_revision')!=context['base_revision']:
                raise ValueError('规范化 Agent 返回的请求或版本标识不匹配')
        else:
            result=normalize_source(source['content'],context['plot_data'],profile,related,skill,model_auth=model_auth)
        if result['status']!='proposed':
            return {'status':('already_compliant' if result['status']=='already_compliant' else 'cannot_complete' if result['status']=='unsupported' else 'needs_clarification'),
                    'reason':result['message'],'warnings':result.get('warnings',[])}
        return {**{k:context[k] for k in ('request_id','edit_session_id','turn_id','parent_draft_id','chart_id','base_revision','user_message')},
                'status':'candidate','proposed_files':[{'path':entry,'base_sha256':source['sha256'],'content':result['normalized_source']}],
                'summary':result['message'],'warnings':result.get('warnings',[]),'normalization_checks':result.get('check'),
                'unsupported':result.get('unsupported',[]),'interpreted_request':{'operation':'normalize','skill_id':skill_id,
                    'skill_sha256':skill_hash,'profile_version':profile.get('version'),'profile_sha256':profile_hash,
                    'changes':result.get('changes',[])},
                'layout_policy':{'mode':'avoid_overlap'},'expected_effects':result.get('changes',[])}

    def build_draft(self,session,record,turn,parent,context,response):
        from chart_type_defaults import prepare_conversion_proposal
        response=prepare_conversion_proposal(context,response)
        if response.get('interpreted_request',{}).get('operation')!='normalize':
            from chat_parameters import prepare_axis_range_proposal
            response=prepare_axis_range_proposal(context,response,self.axis_requirement(context.get('user_message','')))
        if self.renderer is None:
            from chat_runner import render_candidate
        did=uid('dft');output=self.path(session['project'],session['id']).parent/'drafts'/did
        output.mkdir(parents=True)
        code={f['path']:f['content'] for f in response['proposed_files']}
        baseline={f['path']:f['content'] for f in context['source_files'] if f['writable']}
        draft={**record,'id':did,'turn_id':turn['id'],'base_revision':context['base_revision'],
               'parent_draft_id':context['parent_draft_id'],'code':code,'summary':response.get('summary') or '候选修改',
               'warnings':response.get('warnings',[]),'proposal':response,'created_at':time.time(),'status':'rendering'}
        draft['generation_path']=response.get('generation_path','model')
        if context.get('reference_features'):
            from reference_visual_review import unavailable
            draft['reference_features']=context['reference_features']
            draft['reference_comparison']=unavailable(context['reference_features'],'候选尚未完成视觉对照。')
        if response.get('parameter_intent'):draft['parameter_intent']=response['parameter_intent']
        if response.get('chart_type_style'):draft['chart_type_style']=response['chart_type_style']
        atomic_json(output/'proposal.json',response)
        try:
            render=self.renderer or render_candidate
            report=render(self.host.project_path(session['project']),context['allowed_write_paths'][0],code,output,baseline_files=baseline)
            if report.get('paired_plots'):
                from paired_plot import runtime_signature as paired_signature
                draft['paired_runtime_sha256']=paired_signature()
            draft.update({k:v for k,v in report.items() if k not in ('status',)})
            draft['warnings']=[*response.get('warnings',[]),*report.get('warnings',[])]
            draft['image_url']=f"/api/projects/{session['project']}/chat/sessions/{session['id']}/drafts/{did}/image"
            issues=report.get('layout',{}).get('issues',[])
            accepted=context.get('layout_exception') or {}
            if not accepted.get('layout_signature') or accepted.get('layout_signature')!=report.get('layout_signature') or accepted.get('base_revision')!=context['base_revision']:
                if accepted:draft['warnings'].append('布局或正式版本已变化；原有重叠例外不适用于本候选，请重新审阅。')
                accepted={}
            accepted_signatures={(i.get('kind'),json.dumps(i.get('elements'),sort_keys=True)) for i in accepted.get('issues',[])}
            remaining=[i for i in issues if (i.get('kind'),json.dumps(i.get('elements'),sort_keys=True)) not in accepted_signatures]
            for i in issues:i.setdefault('id',uid('warn'))
            data_report=report.get('data_report',{})
            from chart_transform import verify_distribution
            from paired_plot import verify_paired,scope_mismatch
            transform=(scope_mismatch(context,report) or
                       verify_paired(self.host.project_path(session['project']),record['chart'],context,response,report) or
                       verify_distribution(self.host.project_path(session['project']),record['chart'],context,response,report))
            if transform:
                draft['chart_transform']=transform
                draft['warnings'].extend(transform.get('warnings',[]))
            transformed=bool(transform and (transform['status']=='pass' or
                (transform.get('status')=='presentation_review' and transform.get('data_integrity_verified'))))
            font_issue=self.font_effect_issue(report)
            visual_issue=None if response.get('interpreted_request',{}).get('operation')=='normalize' else self.visual_effect_issue(context,response,report)
            # Accepting the displayed layout intentionally keeps the same pixels.
            # A carried-over exception must not waive later visual edit requests.
            if (context.get('layout_exception_requested') and accepted and issues and not remaining
                    and report.get('visual_change',{}).get('status')=='identical'):
                visual_issue=None
            axis_issue=self.axis_requirement_issue(context,report) if response.get('interpreted_request',{}).get('operation')!='normalize' else None
            view_issue=not transformed and bool(data_report.get('visibility_changes') or data_report.get('axes_changes')) and not self.view_change_authorized(response,context)
            addition_issue=not transformed and bool(data_report.get('added')) and not self.addition_authorized(response,context,data_report['added'])
            from edit_contract import verify_requirements
            if response.get('interpreted_request',{}).get('operation')!='normalize':
                draft['edit_contract']=verify_requirements(context.get('user_message',''),report)
            contract=draft.get('edit_contract') or {}
            draft['check_results']=check_results(draft,transform,font_issue,axis_issue,visual_issue,remaining,view_issue,addition_issue)
            if response.get('normalization_checks',{}).get('status')=='fail':
                draft.update(status='needs_clarification',reason='候选已出图，但尚未满足所选规范的结构检查；请查看检查结果。')
            elif transform and transform['status']!='pass':
                draft.update(status='validation_failed',reason=transform['reason'])
                if transform['status']=='unverified':draft['review_blocker']='transform_unverified'
                if transform.get('kind')=='paired_plot':draft['review_blocker']='paired_unverified'
                if transform.get('code')=='source_scope_mismatch':draft['review_blocker']='source_scope_mismatch'
                if transform.get('status')=='presentation_review' and transform.get('data_integrity_verified'):
                    draft.update(status='needs_clarification',review_blocker='paired_presentation')
            elif (data_report.get('status') in ('fail','changed','conflict') or
                  (not transformed and (data_report.get('changed') or data_report.get('removed')))):
                draft.update(status='validation_failed',reason='候选改变了原有绘图数据或映射，需要明确审阅；本轮未替换正式图。')
            elif view_issue:
                draft.update(status='needs_clarification',reason='可见范围或元素可见性发生了变化，但原话中尚无对应的明确修改项；请确认修改意图。')
            elif addition_issue:
                draft.update(status='needs_clarification',reason='候选新增了绘图元素，但没有与原话对应的明确新增要求；请确认新增元素及数据来源。')
            elif font_issue:
                draft.update(status='font_unverified',reason=font_issue)
            elif remaining and report.get('layout',{}).get('status')=='conflict':
                draft.update(status='needs_clarification',review_blocker='layout_conflict',
                    reason='候选存在布局冲突；可以直接继续对话，基于此版修复布局，通过检查后才能应用。也可在审阅后明确接受所列冲突。')
            elif axis_issue:
                draft.update(status='axis_unmet',reason=axis_issue)
            elif contract.get('blocking'):
                failed=next(r for r in contract['requirements'] if r['status']!='pass' and r.get('blocking'))
                draft.update(status='intent_unmet' if contract['status']=='fail' else 'intent_unverified',
                             reason=failed['request']+'：'+failed['reason'])
            elif (visual_issue and response.get('generation_path')=='local_parameters'
                  and response.get('parameter_value_unchanged')
                  and report.get('visual_change',{}).get('status')=='identical'):
                draft.update(status='already_compliant',reason='已实际出图核对：当前参数与要求相同，图片没有变化，无需重复应用。')
            elif visual_issue and report.get('visual_change',{}).get('status')=='identical' and self.axis_requirement(context.get('user_message','')):
                draft.update(status='already_compliant',reason='当前版导出图的坐标范围、所要求的端点刻度和连续轴线已符合本轮要求；图片未变化，无需应用新版本。')
            elif visual_issue:
                draft.update(status='no_visible_change',reason=visual_issue)
            else:
                draft['status']='preview_ready'
                if data_report.get('added') and not transformed:
                    draft['warnings'].append('新增绘图元素的数据含义需人工审阅；现有绘图数值检查保持不变。')
                if data_report.get('visibility_changes') or data_report.get('axes_changes'):
                    draft['warnings'].append('可见范围或元素可见性发生变化，请对照本轮要求审阅。')
                if issues and not remaining:
                    draft['layout']['status']='accepted_exception';draft['warnings'].append('已按你的明确要求保留所列布局冲突。')
                elif report.get('layout',{}).get('status')=='unverified':
                    draft['warnings'].append('部分布局无法自动确认，请审阅候选图片；此结果不表示完全无重叠。')
            if draft['status']=='already_compliant':
                draft['check_results'][-1].update(status='already_met',reason=draft['reason'])
            if report.get('naming',{}).get('display_name'):draft['display_name']=report['naming']['display_name']
        except Exception as error:
            draft.update(status='render_failed',reason=str(error))
        from edit_contract import finish_summary
        finish_summary(draft)
        return draft

    def font_effect_issue(self,report):
        audit=report.get('font_audit') or {}
        if audit.get('missing_glyphs'):
            sample=audit['missing_glyphs'][0]
            return (f"导出图中字体 {sample.get('font','未知')} 缺少字符 {sample.get('characters','')}；"
                    '该候选无法正确显示全部文字，不能标为已达到要求。')
        old={item['key']:item for item in (report.get('baseline_layout_signature') or {}).get('texts',[])}
        new={item['key']:item for item in (report.get('layout_signature') or {}).get('texts',[])}
        baseline_subs={(item.get('text'),item.get('requested_family'))
                       for item in (report.get('baseline_font_audit') or {}).get('substitutions',[])}
        introduced={(item.get('text'),item.get('requested_family'))
                    for item in audit.get('substitutions',[])}-baseline_subs
        if not introduced:
            return None
        for key,item in new.items():
            before=old.get(key)
            if not before or item.get('text')!=before.get('text') or not any(item.get('text')==text for text,_ in introduced):
                continue
            old_box,new_box=before['bbox'],item['bbox']
            for start,end in ((0,2),(1,3)):
                prior=old_box[end]-old_box[start]
                current=new_box[end]-new_box[start]
                if prior>1 and abs(current/prior-1)>.15:
                    return ('原字体缺失后使用 STHeiti，且相同文字在导出图中的尺寸变化超过 15%；'
                            '替代字体引起明显排版变化，请调整布局或字体后再审阅。')
        return None

    def axis_requirement(self,message):
        from chat_parameters import parse_requests
        parsed=parse_requests(message)
        if parsed:
            ranges=[{'axis':intent['method'][4], 'lower':float(intent['value'][0]),
                     'upper':float(intent['value'][1]),'ticks':False}
                    for _,intent in parsed if intent.get('method') in ('set_xlim','set_ylim')]
            return ranges or None
        axis_pattern=re.compile(r'([xy])\s*(?:轴|-axis|\s+axis)|xy\s*轴|x\s*[、,和与及]\s*y\s*轴',re.IGNORECASE)
        range_pattern=re.compile(r'(?<![\d.])(-?\d+(?:\.\d+)?)\s*(?:～|~|至|到|—|–)\s*(-?\d+(?:\.\d+)?)(?![\d.])')
        mentions=list(axis_pattern.finditer(message))
        ranges=list(range_pattern.finditer(message))
        if not mentions or not ranges:return None
        requirements=[]
        for index,mention in enumerate(mentions):
            end=mentions[index+1].start() if index+1<len(mentions) else len(message)
            clause=message[mention.start():end]
            match=next((item for item in ranges if mention.end()<=item.start()<end),None)
            if match is None and len(ranges)==1 and len(mentions)==1:
                match=ranges[0]
            if match is None:continue
            lower,upper=map(float,match.groups())
            if lower>=upper:continue
            names=[mention.group(1).lower()] if mention.group(1) else ['x','y']
            for name in names:
                requirements.append({'axis':name,'lower':lower,'upper':upper,
                                     'ticks':'刻度' in clause or 'tick' in clause.lower()})
        return requirements or None

    def axis_requirement_issue(self,context,report):
        requirement=self.axis_requirement(context.get('user_message',''))
        if not requirement:return None
        axes=report.get('axis_details') or []
        if len(axes)!=1:
            return '本轮要求涉及坐标轴范围，但导出图含多个坐标轴，无法自动确认目标轴；请指定是哪一幅子图。'
        axis=axes[0]
        for item in requirement:
            name=item['axis'];lower=item['lower'];upper=item['upper']
            label=name.upper();spine='bottom' if name=='x' else 'left'
            tolerance=max(abs(upper-lower)*1e-6,1e-8)
            near=lambda a,b:abs(a-b)<=tolerance
            limits=axis.get(name+'lim') or []
            if len(limits)!=2 or not all(near(a,b) for a,b in zip(limits,(lower,upper))):
                return f'导出图的 {label} 轴范围不是 {lower:g}～{upper:g}；请设置两端显示边界。'
            if item['ticks']:
                ticks=axis.get('major_'+name+'ticks') or []
                if not any(near(t,lower) for t in ticks) or not any(near(t,upper) for t in ticks):
                    return f'导出图的 {label} 轴刻度未同时显示 {lower:g} 和 {upper:g}；请明确设置端点刻度。'
            from edit_contract import equal_tick_spacing
            spacing=equal_tick_spacing(axis,name)
            if spacing is not None and not spacing['equal']:
                return f'导出图的 {label} 轴数值刻度间隔不均匀；请在所要求范围内重新生成整组等距刻度，不能只补端点。'
            bounds=axis.get(spine+'_spine_bounds') or []
            if not axis.get(spine+'_spine_visible') or len(bounds)!=2 or not all(near(a,b) for a,b in zip(bounds,(lower,upper))):
                return f'导出图的 {label} 轴线未从 {lower:g} 连续延伸到 {upper:g}；请调整轴线端点。'
            if not axis.get(spine+'_spine_continuous'):
                return f'导出图的 {label} 轴线不是连接 {lower:g}～{upper:g} 的同一条连续线；请修复断线或分段绘制。'
        return None

    def visual_effect_issue(self,context,response,report):
        visual=report.get('visual_change') or {}
        if visual.get('status')=='identical':
            return '候选图片与上一版逐像素相同；请检查请求是否已由上一版满足，或调整未生效的绘图参数。'
        intent=response.get('parameter_intent') or {}
        setting=intent.get('setting','')
        if setting in ('spine_scale','xspine_scale','yspine_scale'):
            before=(report.get('baseline_layout_signature') or {}).get('axes',[])
            after=(report.get('layout_signature') or {}).get('axes',[])
            if len(before)==len(after)==1:
                names=('bottom','top') if setting=='xspine_scale' else ('left','right') if setting=='yspine_scale' else ('left','right','bottom','top')
                for name in names:
                    old=before[0].get('spine_linewidths',{}).get(name)
                    current=after[0].get('spine_linewidths',{}).get(name)
                    if old is not None and (current is None or abs(current-old*intent['value'])>1e-6):
                        return f'导出后的 {name} 轴线宽未达到要求：目标 {old*intent["value"]:g} pt，实际 {current} pt；可能被后续样式覆盖。'
        message=context.get('user_message','')
        operation_text=' '.join(str(op.get('target_element',''))+' '+str(op.get('property',''))
                                for op in response.get('interpreted_request',{}).get('operations',[]) if isinstance(op,dict)).lower()
        if not (('y-axis label' in operation_text or 'y轴' in operation_text.lower())
                and ('weight' in operation_text or '粗度' in message or '字重' in message)):
            return None
        fraction=re.search(r'(?<!\d)(\d+)\s*/\s*(\d+)(?!\d)',message)
        if not fraction:return None
        denominator=int(fraction.group(2))
        if not denominator:return None
        expected=int(fraction.group(1))/denominator
        if not 0.1 <= expected < 1:return None
        ratios=visual.get('text_ink_ratios') or {}
        ylabel_ratios=[value for key,value in ratios.items() if key.endswith('.ylabel')]
        if len(ylabel_ratios)==1 and abs(ylabel_ratios[0]-expected)>0.1:
            actual=ylabel_ratios[0]
            return (f'候选图的 Y 轴标题墨色约为上一版的 {actual:.0%}，与要求的 {expected:.0%} 相差较大。'
                    '字体字重数值不等于实际笔画粗细；请调整可用字形或描边后重新出图。')
        return None

    def addition_authorized(self,response,context,added):
        if response.get('interpreted_request',{}).get('operation')=='normalize':
            return bool(context.get('plot_data')) and all(item.get('semantic_role') in ('errorbar','violin_quartiles') for item in added)
        for op in response.get('interpreted_request',{}).get('operations',[]):
            prop=str(op.get('property','')).lower()
            requested=('add','新增','添加','补','errorbar','error_bar','error bar','误差','quartile','分位','annotation','标注')
            if any(term in prop for term in requested) and any(q and q in context['user_message'] for q in op.get('source_quotes',[])):
                return True
        return False

    def view_change_authorized(self,response,context):
        # Explicit requested presentation changes can be reviewed; generic styling cannot hide data.
        if response.get('interpreted_request',{}).get('operation')=='normalize':
            return False
        properties=('xlim','ylim','axis range','axis_range','visible','visibility','alpha','opacity','scale','坐标范围','可见','隐藏','透明度')
        for op in response.get('interpreted_request',{}).get('operations',[]):
            prop=str(op.get('property','')).lower()
            if any(value in prop for value in properties) and any(q and q in context['user_message'] for q in op.get('source_quotes',[])):
                return True
        return False

    def draft_action(self,project,sid,did,action):
        path=self.path(project,sid)
        with lock(path),lock(self.host.project_path(project)):
            session=self.load(project,sid)
            if session.get('status')=='closed':session['status']='open'
            if session.get('status')=='running':raise ValueError('请等待本轮生成结束')
            draft=next((d for d in session['drafts'] if d['id']==did),None)
            if not draft:raise ValueError('候选不存在')
            if action=='recheck':
                if draft['status'] in ('applied','discarded') or not draft.get('proposal'):
                    raise ValueError('请选择尚未应用的候选重新检查')
                record=next(r for r in session['charts'] if r['chart_id']==draft['chart_id'])
                self.refresh_action_base(session,record)
                origin=next(t for t in session['turns'] if t['id']==draft['turn_id'])
                parent=next((d for d in session['drafts'] if d['id']==draft.get('parent_draft_id')),None)
                if draft.get('parent_draft_id') and not parent:raise ValueError('原候选的父版本已不存在，请重新生成')
                context=self.context(session,record,origin,parent,session.get('layout_exceptions',{}).get(draft['chart_id']))
                if draft.get('reference_features'):
                    context['reference_features']=draft['reference_features']
                proposal=json.loads(json.dumps(draft['proposal']))
                from chat_agent import ECHO_FIELDS
                for key in ECHO_FIELDS:proposal[key]=context[key]
                checked=self.build_draft(session,record,origin,parent,context,proposal)
                if context.get('reference_features'):
                    budget={'used':0};context['_model_attempt_budget']=budget
                    session['progress']={'stage':'comparing_reference','chart_id':draft['chart_id']}
                    self.compare_reference_features(session,context,checked,budget)
                    session.pop('progress',None)
                    checked['visual_recheck_model_calls']=budget.get('calls',[])
                    from edit_contract import finish_summary
                    finish_summary(checked)
                _,revision=self.snapshot(project,record['chart'])
                if revision!=context['base_revision']:
                    checked.update(status='revision_conflict',reason='检查期间正式版本或依赖已变化，请重新生成')
                checked['rechecked_from']=draft['id'];session['drafts'].append(checked)
                if self.can_continue_draft(checked):
                    session['active_drafts'][draft['chart_id']]=checked['id']
            elif action=='discard':
                if draft['status']=='applied':raise ValueError('正式版不能作为候选丢弃')
                draft['status']='discarded'
                if session['active_drafts'].get(draft['chart_id'])==did:session['active_drafts'].pop(draft['chart_id'],None)
            elif action=='activate':
                if not self.can_continue_draft(draft):raise ValueError('该版本不能作为继续修改的起点')
                self.resolve_parent(session,draft['chart_id'],{draft['chart_id']:did})
                session['active_drafts'][draft['chart_id']]=did
            elif action in ('apply','apply-reviewed'):
                if not self.can_continue_draft(draft):raise ValueError('该版本没有可应用的候选代码')
                record=next(r for r in session['charts'] if r['chart_id']==draft['chart_id'])
                _,revision=self.refresh_action_base(session,record)
                draft['application_checks_advisory']={'at':time.time(),'previous_status':draft['status'],
                    'candidate_base_revision':draft.get('base_revision'),'current_revision':revision}
                # Missing images are execution failures, not a quality gate. Try
                # rendering the exact code once; keep formal files if it fails.
                if not draft.get('image_path') or not Path(draft['image_path']).is_file():
                    from chat_runner import render_candidate
                    render=self.renderer or render_candidate
                    output=path.parent/'drafts'/draft['id']/uid('application')
                    report=render(self.host.project_path(project),'charts/'+draft['chart']+'.py',draft['code'],output)
                    draft.update(report)
                    if not draft.get('image_path') or not Path(draft['image_path']).is_file():
                        raise ValueError('候选代码执行后未生成可用图片；可以继续修改此代码后再应用。')
                    draft['image_url']=f"/api/projects/{project}/chat/sessions/{sid}/drafts/{did}/image"
                official_image=record.get('_image')
                if not official_image:
                    baseline_draft=next((d for d in session['drafts'] if d['chart_id']==draft['chart_id'] and d['base_revision']==draft['base_revision'] and d.get('parent_draft_id') is None and d.get('baseline_image_path')),None)
                    official_image=baseline_draft.get('baseline_image_path') if baseline_draft else None
                self.commit_draft(project,draft,official_image)
                draft['status']='applied'
                files,revision=self.snapshot(project,draft['chart'])
                session['base_sources'][draft['chart_id']]=files;session['base_revisions'][draft['chart_id']]=revision
                session['active_drafts'].pop(draft['chart_id'],None)
                for record in session['charts']:
                    if record['chart_id']==draft['chart_id']:
                        record['display_name']=draft['display_name'];record['_image']=draft.get('image_path')
            else:raise ValueError('Unknown draft action')
            self.save(session);return self.public(session)

    def finalize(self,project,chart):
        """Delete one chart's archived code/images only after the UI's finalize action."""
        p,_=self.host.chart_path(project,chart)
        chart_id=self.identity(project)['charts'][chart]
        paths=sorted((self.directory(project)/'sessions').glob('*/session.json'))
        guards=[]
        try:
            # Never clean files while a candidate is being written. Acquire session locks
            # before the project lock, matching draft_action's lock order.
            for path in paths:
                guard=lock(path)
                if not guard.acquire(blocking=False):raise ValueError('项目仍在生成候选，请结束后再清理历史')
                guards.append(guard)
            with lock(p):
                retained_assets=set()
                for path in paths:
                    session=read_json(path)
                    if chart_id in session['chart_ids']:
                        session['status']='closed'
                        session.get('base_sources',{}).pop(chart_id,None)
                        session.get('active_drafts',{}).pop(chart_id,None)
                        session.get('layout_exceptions',{}).pop(chart_id,None)
                        for record in session['charts']:
                            if record['chart_id']==chart_id:
                                record.pop('_image',None);record['finalized']=True
                        session['drafts']=[d for d in session['drafts'] if d['chart_id']!=chart_id]
                        for turn in session['turns']:
                            turn['results']=[r for r in turn.get('results',[]) if r['chart_id']!=chart_id]
                        session['turns']=[t for t in session['turns'] if t['results']]
                    session['references']=[r for r in session['references'] if r['chart_id']!=chart_id]
                    self.save(session)
                    for folder in (path.parent/'drafts').glob('dft_*'):
                        proposal=folder/'proposal.json'
                        if proposal.is_file() and read_json(proposal).get('chart_id')==chart_id:
                            shutil.rmtree(folder)
                    for record in [*session['charts'],*session['references'],*session['drafts']]:
                        if record.get('_image'):retained_assets.add(record['_image'])
                for asset in (self.directory(project)/'reference_assets').glob('*.png'):
                    if str(asset) not in retained_assets:asset.unlink()
                for item in self.host.read_history(p,chart):
                    for suffix in (*self.host.IMAGE_TYPES,'.py'):
                        (p/'history'/(item['id']+suffix)).unlink(missing_ok=True)
                (p/'history'/(chart+'.json')).unlink(missing_ok=True)
                return {'message':'已清理该图的历史代码、历史图片及 Chat 候选，当前代码和图片已保留。相关会话已结束；下一次修改会新建会话。既有 Git 提交不受影响。'}
        finally:
            for guard in reversed(guards):guard.release()

    def commit_draft(self,project,draft,official_image=None):
        from chart_naming import RenderedImage
        p,f=self.host.chart_path(project,draft['chart'])
        chart=draft['chart'];source=draft['code']['charts/'+chart+'.py'];old=f.read_text(encoding='utf-8')
        history=self.host.read_history(p,chart)
        # Snapshot all files this small commit touches so I/O failure can restore the prior state.
        existing_history=[p/'history'/(h['id']+ext) for h in history for ext in (*self.host.IMAGE_TYPES,'.py')]
        touched=[f,p/'history'/(chart+'.json'),*existing_history,*((p/'previews').glob(chart+'.*')),*((p/'chart_metadata').glob(chart+'.*'))]
        originals={path:path.read_bytes() for path in touched if path.is_file()}
        history_dir=p/'history';history_dir.mkdir(exist_ok=True)
        added_ids=[]
        try:
            now=datetime.now(timezone.utc).isoformat()
            if not history:
                base=uid('rev');added_ids.append(base);(history_dir/(base+'.py')).write_text(old,encoding='utf-8', newline="\n")
                baseline=Path(official_image or '')
                initial_image=baseline.read_bytes() if baseline.is_file() else None
                self.host.snapshot_image(p,chart,base,old,initial_image)
                history.append({'id':base,'time':now,'note':'初始版本'})
            else:(history_dir/(history[-1]['id']+'.py')).write_text(old,encoding='utf-8', newline="\n")
            revision=uid('rev')
            added_ids.append(revision)
            image=RenderedImage(Path(draft['image_path']).read_bytes());image.naming=draft.get('naming')
            temporary=f.with_suffix('.tmp');temporary.write_text(source,encoding='utf-8', newline="\n");temporary.replace(f)
            self.host.save_preview(p,chart,source,image)
            self.host.snapshot_image(p,chart,revision,source,image)
            history.append({'id':revision,'time':now,'note':str(draft['summary'])[:300],'draft_id':draft['id'],'author':self.host.SYNC.config().get('name','本地协作者')})
            keep={history[0]['id'],history[-2]['id']}
            for item in history:
                if item['id'] not in keep:(history_dir/(item['id']+'.py')).unlink(missing_ok=True)
            self.host.write_history(p,chart,history)
        except Exception:
            patterns=[(history_dir,ident+'.*') for ident in added_ids]+[(history_dir,chart+'.json'),(p/'previews',chart+'.*'),(p/'chart_metadata',chart+'.*')]
            for directory,pattern in patterns:
                for path in directory.glob(pattern):
                    if path.is_file() and path not in originals:path.unlink()
            for path,data in originals.items():path.write_bytes(data)
            raise
