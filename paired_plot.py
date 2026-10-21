"""Chart-scoped paired observations, shared by editing and normalization.

Pairability by ID is evidence of available records, not proof of an experimental
design. Callers must establish the pairing meaning from the source or user.
"""
import hashlib
import json
from pathlib import Path


def runtime_signature():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def prepare_paired_data(table, *, chart, groups, scope_column='panel_id',
                        group_column='group_label', subject_column='subject_id', value_column='value'):
    import numpy as np
    import pandas as pd
    required={scope_column, group_column, subject_column, value_column}
    if not required.issubset(table.columns):
        raise ValueError('配对数据缺少列：'+', '.join(sorted(required-set(table.columns))))
    if len(groups)!=2 or len(set(groups))!=2:
        raise ValueError('配对图需要两个明确且不同的条件。')
    scoped=table.loc[table[scope_column].astype(str).eq(str(chart))].copy()
    if scoped.empty:raise ValueError('当前指标没有逐条样本：'+str(chart))
    selected=scoped.loc[scoped[group_column].astype(str).isin(groups)].copy()
    if selected[subject_column].isna().any():raise ValueError('当前指标存在缺失的受试者 ID；不能自动配对。')
    selected[subject_column]=selected[subject_column].astype(str)
    selected[group_column]=selected[group_column].astype(str)
    if selected[subject_column].str.strip().eq('').any():raise ValueError('当前指标存在空受试者 ID；不能自动配对。')
    duplicated=selected.duplicated([group_column,subject_column],keep=False)
    if duplicated.any():
        examples=selected.loc[duplicated,[group_column,subject_column]].drop_duplicates().head(3).values.tolist()
        raise ValueError('当前指标内“条件 × 受试者 ID”不唯一；不能按行连线或自动求均值：'+str(examples))
    selected[value_column]=pd.to_numeric(selected[value_column],errors='raise')
    if not np.isfinite(selected[value_column].to_numpy(float)).all():
        raise ValueError('当前指标含缺失或非有限数值；未自动删除样本。')
    series=[selected.loc[selected[group_column].eq(g)].set_index(subject_column)[value_column] for g in groups]
    if any(s.empty for s in series):raise ValueError('当前指标的某个条件没有样本。')
    common=sorted(set(series[0].index)&set(series[1].index))
    return {'chart':str(chart),'groups':list(groups),'samples':[s.to_numpy(float) for s in series],
            'subject_ids':[list(s.index) for s in series], 'paired_ids':common,
            'paired_values':[[float(s.loc[ident]) for s in series] for ident in common],
            'unpaired_counts':[len(s)-len(common) for s in series],
            'columns':{'scope_column':scope_column,'group_column':group_column,
                       'subject_column':subject_column,'value_column':value_column}}


def load_paired_data(path, **kwargs):
    import pandas as pd
    path=Path(path)
    result=prepare_paired_data(pd.read_csv(path,sep='\t' if path.suffix=='.tsv' else ','),**kwargs)
    result['source_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def signature(data):
    from chart_transform import sample_signature
    return {'chart':data['chart'],'groups':data['groups'],'columns':data['columns'],
            'samples':[sample_signature(g) for g in data['samples']],
            'pair_count':len(data['paired_ids']), 'unpaired_counts':data['unpaired_counts'],
            'pairs_sha256':hashlib.sha256(json.dumps(list(zip(data['paired_ids'],data['paired_values'])),
                                                    ensure_ascii=False,separators=(',',':')).encode()).hexdigest()}


def _geometry(obj):
    """Full numerical geometry, independent of sampled UI diagnostics."""
    import numpy as np
    if hasattr(obj,'get_offsets') and obj.__class__.__name__=='PathCollection':
        arrays=[obj.get_offsets()]
    elif hasattr(obj,'get_xdata'):
        arrays=[obj.get_xdata(orig=False),obj.get_ydata(orig=False)]
    else:arrays=[p.vertices for p in obj.get_paths()]
    digest=hashlib.sha256()
    for array in arrays:
        a=np.asarray(array,dtype='<f8');digest.update(str(a.shape).encode());digest.update(a.tobytes())
    return digest.hexdigest()


def _value_geometry(obj):
    """Hash ordered observed Y values, excluding categorical display positions."""
    import numpy as np
    if obj.__class__.__name__=='PathCollection':
        offsets=np.ma.asarray(obj.get_offsets())
        if offsets.ndim!=2 or offsets.shape[1]!=2 or np.ma.getmaskarray(offsets).any() or not np.isfinite(offsets).all():return None
        arrays=[offsets[:,1]]
    elif hasattr(obj,'get_ydata'):arrays=[obj.get_ydata(orig=False)]
    else:arrays=[p.vertices[:,1] for p in obj.get_paths()]
    digest=hashlib.sha256()
    for array in arrays:
        a=np.asarray(array,dtype='<f8')
        if not np.isfinite(a).all():return None
        digest.update(str(a.shape).encode());digest.update(a.tobytes())
    return digest.hexdigest()


def _pair_endpoints_aligned(record):
    import numpy as np
    if not record['connect']:return True
    if len(record['lines'])!=len(record['paired_ids']):return False
    points=[np.ma.asarray(obj.get_offsets()) for obj in record['points']]
    if any(p.ndim!=2 or p.shape!=(len(ids),2) or np.ma.getmaskarray(p).any() or not np.isfinite(p).all()
           for p,ids in zip(points,record['subject_ids'])):return False
    indices=[{ident:i for i,ident in enumerate(ids)} for ids in record['subject_ids']]
    for ident,line in zip(record['paired_ids'],record['lines']):
        actual=np.asarray(line.get_xydata(),dtype=float)
        expected=np.asarray([points[g][indices[g][ident]] for g in range(2)],dtype=float)
        if actual.shape!=(2,2) or not np.allclose(actual,expected,rtol=0,atol=1e-9):return False
    return True


def draw_paired_plot(ax, data, *, half_violin=True, connect=True, positions=(0.,1.),
                     colors=('#7FB069','#9E2B25'), width=.30, alpha=.55):
    """Retain all group observations; connect only exact, unique ID matches.

    Clip the already generated violin vertices to their left/right half. No
    Bbox/set_clip_path combination and no KDE evaluation over mixed metrics.
    """
    import numpy as np
    if len(positions)!=2 or positions[0]>=positions[1] or not 0<width<(positions[1]-positions[0])/2:
        raise ValueError('半小提琴宽度应为正数且小于组间距的一半。')
    artists=[];bodies=[];lines=[];points=[]
    if half_violin:
        if any(len(g)<2 or np.ptp(g)==0 for g in data['samples']):
            raise ValueError('半小提琴需要每组至少两个非恒定观测；可改用配对散点连线图。')
        violin=ax.violinplot(data['samples'],positions=positions,widths=2*width,
                             showmeans=False,showmedians=False,showextrema=False)
        bodies=violin['bodies']
        for i,body in enumerate(bodies):
            for path in body.get_paths():
                path.vertices[:,0]=(np.minimum if i==0 else np.maximum)(path.vertices[:,0],positions[i])
            body.set_facecolor(colors[i]);body.set_edgecolor('none');body.set_alpha(alpha)
        artists.extend(bodies)
    if connect:
        if not data['paired_ids']:raise ValueError('当前两个条件没有可一一对应的受试者；不能绘制配对连线。')
        for pair in data['paired_values']:
            lines.extend(ax.plot(positions,pair,color='0.65',lw=1,zorder=2))
        artists.extend(lines)
    for x,values,color in zip(positions,data['samples'],colors):
        points.append(ax.scatter(np.full(len(values),x),values,s=35,facecolor='white',edgecolor=color,linewidth=1.3,zorder=3))
    artists.extend(points)
    ax.set_xticks(positions,data['groups'])
    ax.set_xlim(positions[0]-width*1.5,positions[1]+width*1.5)
    ax.margins(y=.12)
    record={'signature':signature(data),'half_violin':bool(half_violin),'connect':bool(connect),
            'positions':list(positions),'artists':artists,'bodies':bodies,'lines':lines,'points':points,
            'initial_geometry':[_geometry(a) for a in artists],
            'initial_value_geometry':[_value_geometry(a) for a in artists],
            'subject_ids':data['subject_ids'],'paired_ids':data['paired_ids']}
    ax._paired_plot_record=record
    return record


def capture(ax):
    record=getattr(ax,'_paired_plot_record',None)
    if not record:return None
    import numpy as np
    artists=record['artists'];children=ax.get_children();ylim=sorted(ax.get_ylim());xlim=sorted(ax.get_xlim())
    geometry=[_geometry(a) for a in artists]
    values=[_value_geometry(a) for a in artists]
    visible=all(a in children and a.get_visible() and (a.get_alpha() is None or a.get_alpha()>0) for a in artists)
    # Check density has visible horizontal width and vertical extent in export.
    density_visible=True
    for body in record['bodies']:
        points=np.concatenate([p.vertices for p in body.get_paths()])
        shown=points[(points[:,1]>=ylim[0])&(points[:,1]<=ylim[1])&(points[:,0]>=xlim[0])&(points[:,0]<=xlim[1])]
        if len(shown)<2 or np.ptp(ax.transData.transform(shown)[:,0])<3 or np.ptp(ax.transData.transform(shown)[:,1])<10:
            density_visible=False
    return {k:record[k] for k in ('signature','half_violin','connect','positions')} | {
        'geometry_unchanged':geometry==record['initial_geometry'],'visible':visible,
        'values_unchanged':all(v is not None for v in values) and values==record['initial_value_geometry'],
        'pair_endpoints_aligned':_pair_endpoints_aligned(record),
        'observations_visible':all(a in children and a.get_visible() and (a.get_alpha() is None or a.get_alpha()>0) for a in record['points']+record['lines']),
        'density_visible':density_visible}


def discover_contract(project, chart, plot_data):
    """Conservative schema discovery: ambiguous sources are never auto-selected."""
    import pandas as pd
    found=[]
    root=Path(project).resolve()
    for item in plot_data:
        path=item['path'];target=(root/path).resolve()
        if not target.is_relative_to(root) or not target.is_file() or target.suffix not in ('.csv','.tsv'):continue
        if hashlib.sha256(target.read_bytes()).hexdigest()!=item['sha256'].removeprefix('sha256:'):continue
        try:table=pd.read_csv(target,sep='\t' if target.suffix=='.tsv' else ',')
        except (ValueError,UnicodeError):continue
        scope=next((c for c in ('panel_id','chart_id','plot_id') if c in table.columns),None)
        group=next((c for c in ('group_label','group','condition') if c in table.columns),None)
        if not scope or not group or not {'subject_id','value'}.issubset(table.columns):continue
        scoped=table.loc[table[scope].astype(str).eq(chart)]
        labels=list(scoped[group].drop_duplicates().astype(str))
        if len(labels)!=2:continue
        base={'path':path,'chart':chart,'groups':labels,'scope_column':scope,'group_column':group,
              'subject_column':'subject_id','value_column':'value','source_sha256':item['sha256'].removeprefix('sha256:')}
        try:
            data=prepare_paired_data(table,**{k:v for k,v in base.items() if k not in ('path','source_sha256')})
            found.append({**base,'status':'available','expected':signature(data),
                          'meaning':'ID matching is available; use paired connections only when supported by source design or user instruction.'})
        except (ValueError,TypeError) as error:found.append({**base,'status':'invalid','reason':str(error)})
    return found[0] if len(found)==1 else None


def verify_paired(project, chart, context, proposal, report):
    contract=context.get('paired_plot_data')
    traces=report.get('paired_plots') or []
    import re
    declared=' '.join(str(op.get('desired_change','')) for op in proposal.get('interpreted_request',{}).get('operations',[]))
    if not traces:
        needs_capture=bool(contract and context.get('reference_images') and re.search(r'half.?violin|split.?violin|半小提琴|paired|配对',declared,re.I))
        if proposal.get('_reference_connection_omitted') or needs_capture:
            return {'kind':'paired_plot','status':'unverified','warnings':[],
                    'required_api':'paired_plot.load_paired_data + paired_plot.draw_paired_plot',
                    'reason':'当前指标数据已定位，但候选未提供半小提琴／配对图完整核查记录；请复用 paired_plot_data 与平台绘制函数，无需重新上传数据。'}
        return None
    result={'kind':'paired_plot','status':'unverified','warnings':[],'matches':[]}
    def stop(reason,status='fail'):return {**result,'status':status,'reason':reason}
    if not contract or contract.get('status')!='available':return stop('无法确定配对图的当前指标样本来源；请明确数据列和指标。','unverified')
    path=(Path(project)/contract['path']).resolve()
    if not path.is_relative_to(Path(project).resolve()) or hashlib.sha256(path.read_bytes()).hexdigest()!=contract['source_sha256']:
        return stop('配对图原数据已变化，请重新读取。')
    if len(traces)!=1 or len(report.get('layout_signature',{}).get('axes',[]))!=1:
        return stop('多子图配对关系尚无法自动核对。','unverified')
    trace=traces[0]
    request=context.get('user_message','')
    if trace['connect'] and (proposal.get('_reference_connection_omitted') or
            re.search(r'不连线|不连接|不要连接|取消配对|不配对|无配对|没有配对|独立样本|两组独立',request)):
        return stop('本轮要求省略配对连接，但候选仍绘制了连接线。')
    if not (re.search(r'配对|连线|连接|paired|connect',request,re.I) or
            (context.get('reference_images') and re.search(r'类似|参照|参考|相似|similar|like',request,re.I)
             and re.search(r'violin|小提琴|paired|connect|配对|连线',declared,re.I))):
        if not any('paired_plot' in f.get('content','') for f in context.get('source_files',[]) if f.get('writable')):
            return stop('本轮没有可追溯的配对图或半小提琴图修改要求。','unverified')
    if trace['signature']!=contract['expected']:
        return stop('当前指标的样本、受试者对应或配对数不一致；禁止混入其他指标或删除未配对样本。')
    if not trace.get('values_unchanged',trace.get('geometry_unchanged',False)):
        return stop('配对图的实际观测值、样本顺序或分布纵轴数值被修改；横向排版偏移不属于此项阻断。')
    if not trace.get('pair_endpoints_aligned',trace.get('geometry_unchanged',False)):
        return stop('配对连线端点没有对齐同一被试的两个实际数据点，请同步调整点与连线。')
    if not trace.get('observations_visible',trace['visible']):
        return stop('配对图的观测点或连接线被隐藏。')
    if not trace['visible'] or (trace['half_violin'] and not trace['density_visible']):
        if context.get('reference_images'):
            result['warnings'].append('半小提琴隐藏、被裁切或压缩到不可见；完整样本和配对已另行核对，此外观差异请对照参考图审阅。')
        else:return stop('半小提琴在最终导出中被裁切或压缩到不可见，请修复显示范围。')
    axes=report.get('layout_signature',{}).get('axes',[])
    before=report.get('baseline_layout_signature',{}).get('axes',[])
    if len(before)!=1 or axes[0].get('labels')!=before[0].get('labels'):
        return stop('配对图改变了轴标题或单位。')
    presentation=[]
    if (axes[0].get('tick_texts') or [[]])[0]!=contract['groups']:
        presentation.append('组别未按原刻度形式显示；需继续核对图例中的组别表达。')
    for artist in report.get('candidate_artists',[]):
        if artist.get('paired_plot_member'):continue
        data=artist.get('data') or {};x=data.get('x',{});y=data.get('y',{})
        if not (artist.get('kind')=='line' and x.get('shape')==[4] and y.get('shape')==[4]
                and len(x.get('sample',[]))==3 and x['sample'][0]==x['sample'][1]
                and len(y.get('sample',[]))==3 and y['sample'][1]==y['sample'][2]):
            return stop('配对图之外存在未核对的数据元素。','unverified')
    # Keep all original non-legend scientific annotations verbatim.
    def annotations(sig):
        return sorted(t['text'] for t in sig.get('texts',[]) if not __import__('re').search(r'\.[xy](?:tick_|offset)|legend',t['key']))
    if annotations(report.get('layout_signature',{}))!=annotations(report.get('baseline_layout_signature',{})):
        presentation.append('统计标注或标题表达发生变化，仍需核对实际 P 值和表达方式。')
    result['matches']=[{'path':contract['path'],'groups':contract['expected']['samples'],
                        'pair_count':contract['expected']['pair_count'],'unpaired_counts':contract['expected']['unpaired_counts']}]
    if any(contract['expected']['unpaired_counts']):result['warnings'].append('未配对样本保留在各组分布和散点中，仅完整配对观测之间绘制连线。')
    if presentation:
        if not context.get('reference_images'):return stop('；'.join(presentation))
        return {**result,'status':'presentation_review','data_integrity_verified':True,
                'presentation_issues':presentation,'reason':'原始样本、观测值和被试配对已核对；'+'；'.join(presentation)+' 可基于此版本继续修改。'}
    return {**result,'status':'pass','reason':'当前指标完整样本、唯一受试者 ID、逐对连线与最终可见图元核对通过。'}


def scope_mismatch(context, report):
    """Explain the observed cross-metric failure before generic geometry errors."""
    contract=context.get('paired_plot_data')
    if not contract or contract.get('status')!='available':return None
    scatter=[a for a in report.get('candidate_artists',[]) if a.get('kind')=='scatter']
    expected=contract['expected']['samples']
    if len(scatter)!=2:return None
    counts=[(a.get('data',{}).get('offsets',{}).get('shape') or [0])[0] for a in scatter]
    wanted=[g['count'] for g in expected]
    if sum(counts)>sum(wanted):
        return {'kind':'source_scope','status':'fail','code':'source_scope_mismatch','warnings':[],
                'reason':f'候选样本数为 {counts}，当前指标应为 {wanted}；疑似遗漏 {contract["scope_column"]}={contract["chart"]} 筛选或重复受试者匹配，请先筛选指标再按 ID 配对。'}
    return None


def resolve_optional_reference_items(context, response):
    """Resolve explicit optional omissions; arbitrary uncertainties still block."""
    import ast
    import re
    check=response.get('intent_check') or {};items=check.get('unresolved_items')
    if not context.get('reference_images') or check.get('status')!='consistent' or not items:return
    if re.search(r'配对|连线|连接|paired|connect',context.get('user_message',''),re.I):return
    if not all(isinstance(i,dict) and i.get('resolution')=='omit_optional_reference_connection'
               and isinstance(i.get('reason'),str) and i['reason'].strip() for i in items):return
    calls=[]
    for file in response.get('proposed_files',[]):
        try:tree=ast.parse(file.get('content',''))
        except SyntaxError:return
        aliases={n.asname or n.name for stmt in tree.body if isinstance(stmt,ast.ImportFrom)
                 and stmt.module=='paired_plot' for n in stmt.names if n.name=='draw_paired_plot'}
        calls.extend(n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id in aliases)
    if len(calls)!=1 or not any(k.arg=='connect' and isinstance(k.value,ast.Constant) and k.value.value is False for k in calls[0].keywords):return
    response['_reference_connection_omitted']=True
    check['implementation_choices']=str(check.get('implementation_choices') or '')+'；未确认的参考配对线已省略，保留原始样本。'
    check['unresolved_items']=[]
    response.setdefault('warnings',[]).extend('参考图连接线已省略：'+i['reason'] for i in items)
