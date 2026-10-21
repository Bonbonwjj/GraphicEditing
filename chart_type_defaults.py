"""Versioned defaults for explicit chart-type conversions; no global rcParams."""
import ast
import copy
import re

def runtime_signature():
    import hashlib
    from pathlib import Path
    root=Path(__file__).resolve().parent
    return hashlib.sha256(Path(__file__).read_bytes()+(root/'axis_range_policy.py').read_bytes()+(root/'skills/chart-normalization/assets/style-profile.v1.json').read_bytes()).hexdigest()


def _profile():
    import json
    from pathlib import Path
    return json.loads((Path(__file__).resolve().parent/'skills/chart-normalization/assets/style-profile.v1.json').read_text())


TEMPLATES={
    'violinplot':('小提琴图',['two_group_violin']),
    'boxplot':('箱线图',['two_group_box']),
    'bar':('柱状图',['two_group_bar','grouped_bar']),
    'plot':('折线图',['line']),
    'scatter':('散点图',['scatter']),
    'hist':('直方图',['histogram']),
    'heatmap':('热图',['heatmap']),
    'mean_sem':('均值与SEM图',['two_group_mean_sem','timecourse_mean_sem']),
}


def conversion_style(message):
    from chart_transform import requested_distribution
    kind=requested_distribution(message)
    if not kind:
        match=re.search(r'(?:改为|改成|转换为|转换成|转成|换成|换为|变成)\s*(?:一个|一张)?\s*(柱状图|条形图|折线图|散点图|直方图|热图|均值标准误图|均值误差图)',message)
        if not match or re.search(r'(?:不要|无需|别)\s*$',message[:match.start()]):return None
        kind={'柱状图':'bar','条形图':'bar','折线图':'plot','散点图':'scatter','直方图':'hist','热图':'heatmap','均值标准误图':'mean_sem','均值误差图':'mean_sem'}[match[1]]
    overrides=[]
    for key,pattern in (
        ('width',r'宽|窄|width'),('summary',r'(?:不显示|隐藏|不要|只显示|仅显示|内部箱|内嵌箱).{0,10}(?:中位|分位|均值|极值|统计|箱线)|内部箱|内嵌箱'),
        ('connector',r'不连接|不要连接|取消连接|去掉连接|移除连接|不连线'),
        ('linewidth',r'粗|细|线宽|linewidth'),('geometry',r'字号|字体|字大|字小|画布|尺寸|边距|dpi|分辨率')):
        if re.search(pattern,message,re.I):overrides.append(key)
    profile=_profile();name,templates=TEMPLATES[kind]
    import hashlib,json
    return {'version':profile['version'],'profile_id':profile['id'],
            'profile_sha256':hashlib.sha256(json.dumps(profile,sort_keys=True).encode()).hexdigest(),
            'source':'skills/chart-normalization/assets/style-profile.v1.json','kind':kind,'name':name,
            'templates':{key:profile['chart_types'][key] for key in templates},'global':profile['global'],
            'overrides':overrides,'priority':'用户明确要求优先；其他样式严格复用标准化Skill。未匹配组数/子图模板时只用适用规则并报告missing_template。',
            'preserve':'保留完整原始样本、分组、单位、颜色和统计标注；不改变已有分箱、密度带宽、离群点规则、拟合和误差定义；无依据不增加统计量。',
            'implementation':'fixed_renderer' if kind in ('violinplot','boxplot') else 'model_guideline'}


def _groups(data):
    from matplotlib.cbook import _reshape_2D
    import numpy as np
    groups=[np.asarray(g,dtype=float) for g in _reshape_2D(data,'dataset')]
    if not groups or any(not len(g) or not np.isfinite(g).all() for g in groups):
        raise ValueError('标准分布图需要完整有限的逐条样本；未自动删除或填补缺失值。')
    return groups


def standard_violinplot(ax,*args,_style_overrides=(),**kwargs):
    import numpy as np
    from studio_style import add_normalized_violin_quartiles
    groups=_groups(args[0] if args else kwargs['dataset'])
    rule=_profile()['chart_types']['two_group_violin']
    positions=kwargs.get('positions',args[1] if len(args)>1 else None)
    positions=list(range(1,len(groups)+1)) if positions is None else positions
    # A two-group template must not impose its width on unrelated group counts.
    if len(groups)==2 and 'width' not in _style_overrides:kwargs['widths']=rule['violin_width_x']
    horizontal=kwargs.get('orientation')=='horizontal' or kwargs.get('vert') is False
    summary='summary' not in _style_overrides and len(groups)==2 and not horizontal
    if summary:kwargs.update(showmedians=False,showmeans=False,showextrema=False,quantiles=None)
    result=ax.violinplot(*args,**kwargs)
    for body in result['bodies']:
        body.set_edgecolor(rule['inner_line_color'])
        if 'linewidth' not in _style_overrides:body.set_linewidth(rule['violin_outline_width_pt'])
    if summary:
        quartiles=[np.percentile(g,np.asarray(rule['inner_quantile_levels'])*100).tolist() for g in groups]
        marks=add_normalized_violin_quartiles(ax,result['bodies'],positions,quartiles)
        if 'connector' in _style_overrides:
            for i,mark in enumerate(marks):
                if i%4==3:mark.remove()
    ax._plot_forge_conversion_template='two_group_violin' if len(groups)==2 and not horizontal else None
    return result


def standard_boxplot(ax,*args,_style_overrides=(),**kwargs):
    groups=_groups(args[0] if args else kwargs['x'])
    profile=_profile();rule=profile['chart_types']['two_group_box'];tokens=profile['global']['visual_tokens']
    if len(groups)==2 and 'width' not in _style_overrides:kwargs['widths']=rule['box_width_x']
    # Style normalization does not change whisker/outlier statistical choices.
    kwargs['patch_artist']=True
    for key,width in (('boxprops',rule['box_outline_width_pt']),('whiskerprops',tokens['box_whisker_width_pt']),
                      ('capprops',tokens['box_cap_width_pt']),('medianprops',rule['median_line_width_pt'])):
        props=dict(kwargs.get(key) or {})
        if 'linewidth' not in _style_overrides:props['linewidth']=width
        props.setdefault('edgecolor' if key=='boxprops' else 'color',profile['global']['ink'])
        kwargs[key]=props
    result=ax.boxplot(*args,**kwargs)
    horizontal=kwargs.get('orientation')=='horizontal' or kwargs.get('vert') is False
    ax._plot_forge_conversion_template='two_group_box' if len(groups)==2 and not horizontal else None
    return result


def _apply_final_parameters(fig, parameters):
    from axis_range_policy import apply_chart_parameters
    apply_chart_parameters(fig,parameters)


def finish_converted_figure(fig, output, *, _style_overrides=(), parameters=None, **kwargs):
    """Reuse the normalization export/geometry helper for a matching template."""
    from studio_style import normalize_figure_geometry
    import matplotlib
    import matplotlib.pyplot as plt
    if 'geometry' in _style_overrides:
        if parameters:_apply_final_parameters(fig,parameters)
        fig.savefig(output,**kwargs);plt.close(fig);return
    template=getattr(fig.axes[0],'_plot_forge_conversion_template',None) if len(fig.axes)==1 else None
    report=normalize_figure_geometry(fig,template)
    if not template:report['warnings'].append('missing_template: 未匹配两组竖向单子图模板，保留画布和布局，仅应用安全通用样式。')
    if parameters:
        _apply_final_parameters(fig,parameters)
        report['explicit_parameter_overrides']=dict(parameters)
    with matplotlib.rc_context({'savefig.bbox':None}):
        fig.savefig(output,dpi=_profile()['global']['png_dpi'],bbox_inches=None)
    plt.close(fig)
    return report


def prepare_conversion_proposal(context,response):
    """Route public distribution calls through fixed helpers before real checks.

    Other chart types receive a model guideline only. Unsupported/custom calls
    remain subject to the existing conversion checks, never marked compliant.
    """
    policy=conversion_style(context.get('user_message',''))
    if not policy:
        from chat_reference_images import inferred_distribution
        kind=inferred_distribution(context,response)
        if kind:
            policy=conversion_style(context.get('user_message','')+'；改为'+('小提琴图' if kind=='violinplot' else '箱线图'))
            policy['inferred_from_reference']=True
    if not policy or response.get('status')!='candidate':return response
    result=copy.deepcopy(response);result['chart_type_style']=policy
    result['chart_type_style']['runtime_sha256']=runtime_signature()
    kind=policy['kind']
    if kind not in ('violinplot','boxplot'):return result
    wrapped=0
    for file in result.get('proposed_files',[]):
        source=file['content'];tree=ast.parse(source);raw=source.encode();edits=[]
        alias='_pf_standard_'+kind
        helper_names={n.asname or n.name for stmt in tree.body
                      if isinstance(stmt,ast.ImportFrom) and stmt.module=='chart_type_defaults'
                      for n in stmt.names if n.name=='standard_'+kind}
        for node in ast.walk(tree):
            if not isinstance(node,ast.Call):continue
            public=isinstance(node.func,ast.Attribute) and node.func.attr==kind
            existing=isinstance(node.func,ast.Name) and node.func.id in helper_names
            if not (public or existing):continue
            replacement=copy.deepcopy(node);replacement.func=ast.Name(id=alias,ctx=ast.Load())
            if public:replacement.args.insert(0,copy.deepcopy(node.func.value))
            replacement.keywords=[kw for kw in replacement.keywords if kw.arg!='_style_overrides']
            replacement.keywords.append(ast.keyword(arg='_style_overrides',value=ast.parse(repr(policy['overrides']),mode='eval').body))
            lines=raw.splitlines(keepends=True)
            start=sum(map(len,lines[:node.lineno-1]))+node.col_offset;end=sum(map(len,lines[:node.end_lineno-1]))+node.end_col_offset
            edits.append((start,end,ast.unparse(replacement).encode()))
        draw_count=len(edits)
        export_alias='_pf_finish_converted_figure'
        export_names={n.asname or n.name for stmt in tree.body
                      if isinstance(stmt,ast.ImportFrom) and stmt.module in ('studio_style','chart_type_defaults')
                      for n in stmt.names if n.name in ('finish_figure','finish_normalized_figure','finish_converted_figure')}
        export_count=0
        if draw_count:
            for node in ast.walk(tree):
                if not isinstance(node,ast.Call):continue
                named=isinstance(node.func,ast.Name) and node.func.id in export_names
                direct=isinstance(node.func,ast.Attribute) and node.func.attr=='savefig'
                if not (named or direct) or not node.args:continue
                output=node.args[1] if named and len(node.args)>1 else node.args[0] if direct else None
                if output is None or 'CHART_OUTPUT' not in ast.unparse(output):continue
                replacement=copy.deepcopy(node);replacement.func=ast.Name(id=export_alias,ctx=ast.Load())
                if direct:replacement.args.insert(0,copy.deepcopy(node.func.value))
                replacement.keywords=[kw for kw in replacement.keywords if kw.arg not in ('chart_type','_style_overrides')]
                replacement.keywords.append(ast.keyword(arg='_style_overrides',value=ast.parse(repr(policy['overrides']),mode='eval').body))
                lines=raw.splitlines(keepends=True)
                start=sum(map(len,lines[:node.lineno-1]))+node.col_offset;end=sum(map(len,lines[:node.end_lineno-1]))+node.end_col_offset
                edits.append((start,end,ast.unparse(replacement).encode()));export_count+=1
        if edits:
            for start,end,text in sorted(edits,reverse=True):raw=raw[:start]+text+raw[end:]
            source=raw.decode();tree=ast.parse(source)
            # Keep module docstrings and __future__ imports first.
            offset=0;lines=source.splitlines(keepends=True)
            for i,node in enumerate(tree.body):
                if (i==0 and isinstance(node,ast.Expr) and isinstance(node.value,ast.Constant) and isinstance(node.value.value,str)) or (isinstance(node,ast.ImportFrom) and node.module=='__future__'):
                    offset=sum(map(len,lines[:node.end_lineno]))
                else:break
            if alias not in helper_names:
                prefix=source[:offset]
                if prefix and not prefix.endswith('\n'):prefix+='\n'
                source=prefix+f'from chart_type_defaults import standard_{kind} as {alias}\n'+source[offset:]
            if export_count and export_alias not in export_names:
                # Both imports follow future statements; the draw import's offset is valid.
                prefix=source[:offset]
                if prefix and not prefix.endswith('\n'):prefix+='\n'
                source=prefix+f'from chart_type_defaults import finish_converted_figure as {export_alias}\n'+source[offset:]
            file['content']=source;wrapped+=draw_count
            result['chart_type_style']['routed_exports']=result['chart_type_style'].get('routed_exports',0)+export_count
    result['chart_type_style']['routed_calls']=wrapped
    return result
