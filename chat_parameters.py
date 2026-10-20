"""Small, literal-only edits to a single explicit Matplotlib Axes.

Ambiguous language, dynamic code and shared helpers fall back to the Agent.
This generates a normal candidate; rendering and acceptance checks still apply.
"""
import ast
import re

from chat_agent import expand_compact_response, validate_response


def parse_request(message):
    text = message.strip().rstrip('。！!').strip()
    text = re.sub(r'[，,；;]\s*其他(?:内容)?(?:保持)?不变$', '', text)
    text = re.sub(r'^(?:请|帮我)\s*', '', text)
    text = re.sub(r'^(?:把|将)\s*', '', text)
    text = re.sub(r'^(?:这(?:个|张)?(?:图表|图)|当前(?:图表|图)|选中的(?:图表|图))(?:的)?\s*','',text)
    change = r'\s*(?:改为|改成|设为|设置为|调整为)\s*'
    # Explicit proportions, including ordinary batch wording, need no model.
    prefix=r'(?:我|现在|目前|希望|想要|想|请|帮我|把|将|这|些|两|个|张|选中|图表|图|的|[0-9]|\s)*'
    target=r'([xX][yY]轴|[xX]轴和[yY]轴|[xX]和[yY]轴|坐标轴|轴线|[xXyY]轴)'
    fraction=re.fullmatch(prefix+target+r'(?:的)?(?:线宽|粗细|轴线)?(?:调整一下|调整|改为|变为|设为|设置为)?[，,\s]*(?:都)?(?:细一些|细一点|变细|缩小)?[，,\s]*(?:线宽|粗细)?(?:是|为|改为)?(?:现在|当前|原来|上一版|原本|目前)?(?:的)?(一半|减半|1/2|50%|百分之五十)',text)
    if fraction:
        axis=fraction[1].lower();setting='xspine_scale' if axis=='x轴' else 'yspine_scale' if axis=='y轴' else 'spine_scale'
        return {'method':None,'keyword':None,'value':.5,'property':'linewidth','target':fraction[1],
                'setting':setting,'relative':True,'description':'依据当前实际导出线宽，将指定坐标轴线宽减半；数据、刻度线及其他样式保持不变。'}
    relative=re.fullmatch(r'(?:再)?(字|文字|字体|字号|[XYxy]轴(?:标题|标签)(?:字号)?|(?:坐标)?轴(?:线)?|[XYxy]轴(?:线)?)\s*(?:再|稍微|稍稍)?\s*(?:调|改|变|放|加)?\s*(大|小|粗|细)(?:一?点|一些)?',text)
    if relative:
        target,direction=relative.groups()
        ratio=1.2 if direction in ('大','粗') else 1/1.2
        if direction in ('大','小') and ('标题' in target or '标签' in target):
            setting=target[0].lower()+'label_scale'
        elif direction in ('大','小') and target in ('字','文字','字体','字号'):
            setting='text_scale'
        elif direction in ('粗','细') and '轴' in target and '标题' not in target and '标签' not in target:
            setting=target[0].lower()+'spine_scale' if target[0].lower() in ('x','y') else 'spine_scale'
        else:
            return None
        return {'method':None,'keyword':None,'value':ratio,'property':'linewidth' if 'spine' in setting else 'fontsize',
                'target':target,'setting':setting,'relative':True,
                'description':f'依据当前实际设置，将{target}{"增大" if ratio>1 else "减小"}一档（约 {abs(ratio-1):.0%}），保留数据和其他图。'}
    match = re.fullmatch(r'(刻度|图例)(?:的)?字号' + change + r'(\d+(?:\.\d+)?)\s*(?:pt|磅)?', text)
    if match and 1 <= float(match[2]) <= 200:
        return {'method':None,'keyword':None,'value':float(match[2]),'property':'fontsize',
                'target':match[1], 'setting':'tick_fontsize' if match[1]=='刻度' else 'legend_fontsize'}
    match = re.fullmatch(r'([XYxy])\s*轴(?:标题|标签)(?:的)?字号' + change + r'(\d+(?:\.\d+)?)\s*(?:pt|磅)?', text)
    if match and 1 <= float(match[2]) <= 200:
        return {'method': 'set_' + match[1].lower() + 'label', 'keyword': 'fontsize',
                'value': float(match[2]), 'property': 'fontsize', 'target': match[1].upper() + ' axis label'}
    match = re.fullmatch(r'图例(?:的)?位置?' + change + r'(右上角|左上角|右下角|左下角|正上方|正下方)', text)
    if match:
        return {'method': 'legend', 'keyword': 'loc', 'value': {
            '右上角':'upper right', '左上角':'upper left', '右下角':'lower right',
            '左下角':'lower left', '正上方':'upper center', '正下方':'lower center'}[match[1]],
            'property': 'legend location', 'target': 'legend'}
    match = re.fullmatch(r'(?:折线|线条)(?:的)?颜色' + change + r'(红色|蓝色|绿色|黑色|橙色|紫色|#[0-9a-fA-F]{6})', text)
    if match:
        return {'method': 'plot', 'keyword': 'color', 'value': {
            '红色':'red', '蓝色':'blue', '绿色':'green', '黑色':'black', '橙色':'orange', '紫色':'purple'}.get(match[1], match[1]),
            'property': 'color', 'target': 'single line'}
    match = re.fullmatch(r'([xyXY])\s*轴(?:的)?(?:显示)?范围' + change + r'(-?\d+(?:\.\d+)?)\s*(?:到|至|~|～)\s*(-?\d+(?:\.\d+)?)', text)
    if match and float(match[2]) < float(match[3]):
        return {'method': 'set_' + match[1].lower() + 'lim', 'keyword': None,
                'value': (float(match[2]), float(match[3])), 'property': match[1].lower() + 'lim',
                'target': match[1].upper() + ' axis'}
    return None


def _literal_proposal(context):
    intent = parse_request(context.get('user_message', ''))
    # Layout overrides and unresolved previous layout changes need the full workflow.
    if not intent or intent.get('method') in ('set_xlim','set_ylim') or context.get('layout_exception') or context.get('harness_layout_feedback'):
        return None
    paths = context['allowed_write_paths']
    if len(paths) != 1:
        return None
    source = next((s for s in context['source_files'] if s['path'] == paths[0]), None)
    if source is None:
        return None
    content = source['content']
    try:
        tree = ast.parse(content)
        if intent['method'] in ('set_xlim','set_ylim') and any(isinstance(n,ast.Attribute) and n.attr=='set_bounds' for n in ast.walk(tree)):
            return None
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == 'subplots':
                if n.args or any(k.arg in ('nrows','ncols') and ast.literal_eval(k.value)!=1 for k in n.keywords):
                    return None
        # Restrict the first version to straight-line scripts. No branches,
        # functions, loops, repeated bindings or inferred shared-helper effects.
        if any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.If,
                              ast.For, ast.While, ast.Try, ast.With, ast.Lambda, ast.comprehension)) for n in ast.walk(tree)):
            return None
        if any(not isinstance(n, (ast.Import, ast.ImportFrom, ast.Assign, ast.Expr)) for n in tree.body):
            return None
        pyplot = {n.asname or n.name for stmt in tree.body if isinstance(stmt, ast.Import)
                  for n in stmt.names if n.name == 'matplotlib.pyplot'}
        subplot_calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                         and n.func.attr == 'subplots' and isinstance(n.func.value, ast.Name) and n.func.value.id in pyplot]
        if len(subplot_calls) != 1:
            return None
        call = subplot_calls[0]
        if call.args or any(k.arg not in ('figsize', 'dpi') for k in call.keywords):
            return None
        assignment = next((n for n in tree.body if isinstance(n, ast.Assign) and n.value is call), None)
        if not assignment or len(assignment.targets) != 1 or not isinstance(assignment.targets[0], ast.Tuple):
            return None
        names = assignment.targets[0].elts
        if len(names) != 2 or not all(isinstance(n, ast.Name) for n in names):
            return None
        axes = names[1].id
        if sum(isinstance(n, ast.Name) and n.id == axes and isinstance(n.ctx, ast.Store) for n in ast.walk(tree)) != 1:
            return None
        # Unknown calls may replace style or mutate axes after the edit. Use a
        # conservative whitelist of Matplotlib/pandas/numpy/path operations only.
        allowed_methods = {'subplots', 'plot', 'set_xlabel', 'set_ylabel', 'set_xlim', 'set_ylim',
                           'legend', 'savefig', 'close', 'subplots_adjust', 'tight_layout',
                           'read_csv', 'read_table', 'array', 'arange', 'linspace'}
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and (not isinstance(n.func, ast.Attribute) or n.func.attr not in allowed_methods):
                return None
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                 and isinstance(n.func.value, ast.Name) and n.func.value.id == axes
                 and n.func.attr == intent['method']]
        if len(calls) != 1:
            return None
        target = calls[0]
        if any(k.arg is None for k in target.keywords):
            return None
        if intent['method'] == 'plot' and len(target.args) != 2:
            return None
        if intent['method'] == 'legend' and any(k.arg in ('bbox_to_anchor', 'bbox_transform', 'mode') for k in target.keywords):
            return None
        keyword = intent['keyword']
        if keyword:
            values = [k.value for k in target.keywords if k.arg == keyword]
            if len(values) != 1:
                return None
            node = values[0]
        else:
            if target.keywords or len(target.args) not in (1, 2):
                return None
            # Replace the whole call to support both set_xlim(a,b) and (a,b).
            node = target
        old_value = ast.literal_eval(node) if keyword else [ast.literal_eval(a) for a in target.args]
        if not keyword:
            old_value = old_value[0] if len(old_value) == 1 else old_value
            if not isinstance(old_value, (tuple, list)) or len(old_value) != 2:
                return None
        replacement = repr(intent['value']) if keyword else f'{axes}.{intent["method"]}({intent["value"]!r})'
        lines = content.encode('utf-8').splitlines(keepends=True)
        start = sum(map(len, lines[:node.lineno-1])) + node.col_offset
        end = sum(map(len, lines[:node.end_lineno-1])) + node.end_col_offset
        edited = (content.encode('utf-8')[:start] + replacement.encode() + content.encode('utf-8')[end:]).decode('utf-8')
        ast.parse(edited)
    except (SyntaxError, ValueError, TypeError):
        return None
    unchanged = old_value == intent['value'] if keyword else tuple(old_value) == intent['value']
    response = {'status':'candidate', 'generation_path':'local_parameters', 'parameter_value_unchanged':unchanged,
        'summary':'已通过本机参数路径生成候选；仍需出图和检查。',
        'interpreted_request':{'operations':[{'target_element':intent['target'], 'property':intent['property'],
            'current_value':old_value, 'desired_change':intent['value'], 'source_quotes':[context['user_message']]}]},
        'intent_check':{'status':'consistent', 'unresolved_items':[], 'implementation_choices':[]},
        'proposed_files':[{'path':paths[0], 'content':edited}],
        'read_data_refs':[{'path':d['path'], 'columns':[{'name':c, 'role':'unchanged_source'} for c in d['columns']]}
                          for d in context.get('plot_data', []) if d.get('columns')],
        'warnings':[]}
    return validate_response(context, expand_compact_response(context, response))


def _propose_single_parameters(context):
    response = _literal_proposal(context)
    if response is not None:
        return response
    intent = parse_request(context.get('user_message', ''))
    if not intent or context.get('layout_exception') or context.get('harness_layout_feedback'):
        return None
    paths = context.get('allowed_write_paths', [])
    if len(paths) != 1:
        return None
    source = next((s for s in context['source_files'] if s['path'] == paths[0]), None)
    if not source:
        return None
    content = source['content']
    try:
        tree = ast.parse(content)
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == 'subplots':
                if n.args or any(k.arg in ('nrows','ncols') and ast.literal_eval(k.value)!=1 for k in n.keywords):
                    return None
        # A known conversion finalizer accepts post-normalization parameters.
        # Other shared exporters remain unsafe insertion boundaries.
        finalizers={a.asname or a.name for n in tree.body if isinstance(n,ast.ImportFrom)
                    and n.module=='chart_type_defaults' for a in n.names if a.name=='finish_converted_figure'}
        exports = [n for n in ast.walk(tree) if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
                   and ((isinstance(n.value.func, ast.Attribute) and n.value.func.attr == 'savefig'
                         and isinstance(n.value.func.value, ast.Name))
                        or (isinstance(n.value.func,ast.Name) and n.value.func.id in finalizers))]
        if len(exports) != 1:
            return None
        export = exports[0]
        finalizer=isinstance(export.value.func,ast.Name)
        if finalizer and (not export.value.args or not isinstance(export.value.args[0],ast.Name)):return None
        figure = export.value.args[0].id if finalizer else export.value.func.value.id
        pyplot = {a.asname or a.name for n in ast.walk(tree) if isinstance(n, ast.Import)
                  for a in n.names if a.name == 'matplotlib.pyplot'}
        if figure in pyplot:
            return None
        # Do not override an anchored/external legend with an inside placement.
        if intent['method'] == 'legend' and any(isinstance(n, ast.keyword) and n.arg in ('bbox_to_anchor','bbox_transform') for n in ast.walk(tree)):
            return None
        # A color request needs a single statically observable data-line call;
        # unknown helper/multiple-series color choices require the Agent.
        if intent['method'] == 'plot':
            plots=[n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr=='plot']
            if len(plots)!=1 or len(plots[0].args)!=2:
                return None
            axes_names={n.targets[0].elts[1].id for n in ast.walk(tree) if isinstance(n,ast.Assign)
                        and len(n.targets)==1 and isinstance(n.targets[0],ast.Tuple) and len(n.targets[0].elts)==2
                        and isinstance(n.targets[0].elts[1],ast.Name) and isinstance(n.value,ast.Call)
                        and isinstance(n.value.func,ast.Attribute) and n.value.func.attr=='subplots'}
            if not isinstance(plots[0].func.value,ast.Name) or plots[0].func.value.id not in axes_names:
                return None
        setting = intent.get('setting') or {'set_xlabel':'xlabel_fontsize', 'set_ylabel':'ylabel_fontsize',
                    'legend':'legend_loc', 'plot':'line_color', 'set_xlim':'xlim', 'set_ylim':'ylim'}[intent['method']]
        edits = {setting:intent['value']}
        # Consolidate our own earlier override instead of accumulating blocks.
        final_parameters=next((kw for kw in export.value.keywords if kw.arg=='parameters'),None) if finalizer else None
        overrides = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                     and n.func.id == '_plot_forge_apply_parameters']
        if finalizer and overrides and not final_parameters:return None
        lines = content.encode('utf-8').splitlines(keepends=True)
        if overrides or final_parameters:
            if final_parameters:
                node=final_parameters.value
            else:
                if len(overrides)!=1 or len(overrides[0].args)!=2 or not isinstance(overrides[0].args[0],ast.Name) or overrides[0].args[0].id!=figure:return None
                node=overrides[0].args[1]
            prior=ast.literal_eval(node)
            if not isinstance(prior,dict):
                return None
            unchanged=prior.get(setting)==intent['value']
            if intent.get('relative'):
                absolute={'xlabel_scale':'xlabel_fontsize','ylabel_scale':'ylabel_fontsize'}.get(setting)
                if absolute in prior:
                    edits={absolute:float(prior[absolute])*intent['value']}
                else:
                    edits[setting]=float(prior.get(setting,1))*intent['value']
                if setting=='text_scale':
                    for absolute in ('xlabel_fontsize','ylabel_fontsize','tick_fontsize','legend_fontsize'):
                        if absolute in prior:
                            edits[absolute]=float(prior[absolute])*intent['value']
                unchanged=False
            prior.update(edits)
            start=sum(map(len,lines[:node.lineno-1]))+node.col_offset
            end=sum(map(len,lines[:node.end_lineno-1]))+node.end_col_offset
            edited=(content.encode()[:start]+repr(prior).encode()+content.encode()[end:]).decode()
        elif finalizer:
            call=export.value
            call.keywords.append(ast.keyword(arg='parameters',value=ast.parse(repr(edits),mode='eval').body))
            start=sum(map(len,lines[:call.lineno-1]))+call.col_offset
            end=sum(map(len,lines[:call.end_lineno-1]))+call.end_col_offset
            edited=(content.encode()[:start]+ast.unparse(call).encode()+content.encode()[end:]).decode()
            unchanged=False
        else:
            line=content.splitlines()[export.lineno-1]
            indent=line[:export.col_offset]
            if indent.strip():
                return None
            start=sum(map(len,lines[:export.lineno-1]))
            module='axis_range_policy' if setting in ('xlim','ylim') else 'chart_overrides'
            block=(indent+f'from {module} import apply_chart_parameters as _plot_forge_apply_parameters\n'
                   +indent+f'_plot_forge_apply_parameters({figure}, {edits!r})\n')
            edited=(content.encode()[:start]+block.encode()+content.encode()[start:]).decode()
            unchanged=False
        if setting in ('xlim','ylim'):
            edited=edited.replace('from chart_overrides import apply_chart_parameters as _plot_forge_apply_parameters',
                                  'from axis_range_policy import apply_chart_parameters as _plot_forge_apply_parameters')
        ast.parse(edited)
    except (SyntaxError, ValueError, TypeError, KeyError):
        return None
    response={'status':'candidate','generation_path':'local_parameters','parameter_value_unchanged':unchanged,
        'parameter_intent':intent,
        'summary':intent.get('description') or '已生成仅作用于当前图的参数候选；共享函数和其他图的默认参数不变。',
        'interpreted_request':{'operations':[{'target_element':intent['target'],'property':intent['property'],
            'current_value':None,'desired_change':intent['value'],'source_quotes':[context['user_message']]}]},
        'intent_check':{'status':'consistent','unresolved_items':[],'implementation_choices':['在本图导出前覆盖明确的显示参数。']},
        'proposed_files':[{'path':paths[0],'content':edited}],
        'read_data_refs':[{'path':d['path'],'columns':[{'name':c,'role':'unchanged_source'} for c in d['columns']]}
                          for d in context.get('plot_data',[]) if d.get('columns')], 'warnings':[]}
    return validate_response(context,expand_compact_response(context,response))


def parse_requests(message):
    """Accept only complete, disjoint supported clauses; never drop a clause."""
    one=parse_request(message)
    if one:return [(message,one)]
    text=re.sub(r'[，,；;]\s*(?:其他|其余)(?:内容)?(?:保持)?不变[。！!]*$', '',message.strip())
    parts=[p.strip() for p in re.split(r'[，,；;]|并且|同时',text) if p.strip()]
    if not 1<len(parts)<=6:return None
    intents=[];used=set()
    for part in parts:
        intent=parse_request(part)
        if not intent:return None
        key=intent.get('setting') or {'set_xlabel':'xlabel_fontsize','set_ylabel':'ylabel_fontsize','legend':'legend_loc','plot':'line_color','set_xlim':'xlim','set_ylim':'ylim'}.get(intent.get('method'))
        fields=({'xlabel','ylabel','ticks','legend_font','other_text'} if key=='text_scale' else
                {'xlabel'} if key.startswith('xlabel') else {'ylabel'} if key.startswith('ylabel') else
                {'ticks'} if key=='tick_fontsize' else {'legend_font'} if key=='legend_fontsize' else
                {'xspine','yspine'} if key=='spine_scale' else {'xspine'} if key=='xspine_scale' else
                {'yspine'} if key=='yspine_scale' else {key})
        if fields&used:return None
        used.update(fields);intents.append((part,intent))
    return intents


def propose_parameters(context):
    requests=parse_requests(context.get('user_message',''))
    if not requests:return None
    if len(requests)==1:return _propose_single_parameters(context)
    import copy,hashlib
    working=copy.deepcopy(context);operations=[];intents=[];responses=[]
    for message,intent in requests:
        working['user_message']=message
        response=_propose_single_parameters(working)
        if response is None:return None
        responses.append(response);intents.append(intent)
        operations.extend(response['interpreted_request']['operations'])
        for file in response['proposed_files']:
            source=next(f for f in working['source_files'] if f['path']==file['path'])
            source.update(content=file['content'],sha256='sha256:'+hashlib.sha256(file['content'].encode()).hexdigest())
    result=copy.deepcopy(responses[-1]);result.pop('parameter_intent',None)
    result.update({key:context[key] for key in ('request_id','edit_session_id','turn_id','parent_draft_id','chart_id','base_revision','user_message')})
    result['parameter_intents']=intents;result['interpreted_request']['operations']=operations
    for index,op in enumerate(operations,1):op['operation_id']='op_'+str(index)
    for file in result['proposed_files']:
        file['base_sha256']=next(f['sha256'] for f in context['source_files'] if f['path']==file['path'])
    result['parameter_value_unchanged']=all(r.get('parameter_value_unchanged') for r in responses)
    result['summary']=f'已生成包含 {len(requests)} 项参数调整的候选，等待最终导出核对。'
    return validate_response(context,result)


def prepare_axis_range_proposal(context,response,requirements):
    """Persist trusted range defaults in the proposed entry, also for model edits.

    Reuse the conservative exporter adapter; unsupported exporters remain subject
    to final validation instead of silently claiming an adjustment was applied.
    """
    if not requirements or response.get('status')!='candidate':return response
    import copy,hashlib
    from decimal import Decimal
    result=copy.deepcopy(response);working=copy.deepcopy(context)
    working.pop('harness_layout_feedback',None);working.pop('layout_exception',None)
    for file in result['proposed_files']:
        source=next(s for s in working['source_files'] if s['path']==file['path'])
        source.update(content=file['content'],sha256='sha256:'+hashlib.sha256(file['content'].encode()).hexdigest())
    for requirement in requirements:
        lower=format(Decimal(str(requirement['lower'])),'f');upper=format(Decimal(str(requirement['upper'])),'f')
        working['user_message']=requirement['axis'].upper()+'轴范围改为'+lower+'到'+upper
        patched=propose_parameters(working)
        if patched is None:return response
        for file in patched['proposed_files']:
            source=next(s for s in working['source_files'] if s['path']==file['path'])
            source.update(content=file['content'],sha256='sha256:'+hashlib.sha256(file['content'].encode()).hexdigest())
    for file in result['proposed_files']:
        file['content']=next(s['content'] for s in working['source_files'] if s['path']==file['path'])
    result['axis_range_policy']='equal_numeric_linear_ticks'
    return result
