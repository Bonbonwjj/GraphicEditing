"""Verify explicitly requested distribution conversions against full source rows.

Artist geometry is expected to change when changing chart type. Source sample
signatures, group labels and annotations remain independently checked. This is
an observable-data check, not an OS security boundary or scientific approval.
"""
import hashlib
import json
from pathlib import Path
import re


def sample_signature(values):
    import numpy as np
    values = np.asarray(values, dtype=float).reshape(-1)
    if not len(values) or not np.isfinite(values).all():
        return {'count': len(values), 'sha256': None}
    # Sorting preserves multiplicity while ignoring observation order.
    raw = np.sort(values).astype('<f8').tobytes()
    return {'count': len(values), 'sha256': hashlib.sha256(raw).hexdigest()}


def requested_distribution(message):
    pattern = (r'(?:改为|改成|转换为|转换成|转成|换成|换为|变成|改用|换用|使用)\s*'
               r'(?:一个|一张|两张|两个|这类|这种)?\s*(箱线图|箱形图|箱型图|盒须图|小提琴图|box\s*plot|violin\s*plot)'
               r'|(?:change|convert|switch|turn)\b.{0,60}?\b(?:to|into)\s+(?:a\s+)?(box\s*plot|violin\s*plot)')
    match = re.search(pattern, message, re.IGNORECASE)
    if not match or re.search(r'(?:不要|不想|无需|别|do not|don.t)\s*$', message[max(0,match.start()-12):match.start()], re.I):
        return None
    word = next(group for group in match.groups() if group).lower()
    return 'violinplot' if 'violin' in word or '小提琴' in word else 'boxplot'


def simple_distribution_request(message):
    """Only a conversion alone may reuse a previously verified active draft."""
    prefix=r'(?:请|麻烦|帮我|我希望|现在|把|将|我选中的|选中的|这些|这|那|所|选|中|的|两|一|二|三|四|五|六|七|八|九|十|图表|图|个|张|\d|\s)*'
    action=r'(?:改为|改成|转换为|转换成|转成|换成|换为|变成)\s*'
    kind=r'(?:箱线图|箱形图|箱型图|盒须图|小提琴图|box\s*plot|violin\s*plot)'
    if re.fullmatch(r'\s*'+prefix+action+kind+r'\s*[。.!！]*\s*',message,re.I):
        return requested_distribution(message)
    return None


def _verify_iqr_connectors(artists, call, samples):
    """Verify quartile bars/connectors against matched full source rows."""
    import numpy as np
    dimension=call['dimension'];positions=call.get('positions',[])
    verified=[];seen=set()
    for artist in artists:
        key=artist.get('key','unknown')
        def reject(detail):
            return [],f'图元 {key}：{detail}；尚不能作为小提琴的分位统计线放行。'
        visibility=artist.get('visibility') or {}
        if visibility.get('visible') is False or visibility.get('alpha')==0:
            return reject('连接线不可见')
        data=artist.get('data') or {};segments=[]
        if artist.get('kind')=='line':
            x,y=data.get('x',{}),data.get('y',{})
            if x.get('shape')==[2] and y.get('shape')==[2] and len(x.get('sample',[]))==len(y.get('sample',[]))==2:
                segments=[list(zip(x['sample'],y['sample']))]
        elif artist.get('kind')=='line_collection':
            recorded=data.get('segments',[])
            if recorded and all(seg.get('shape')==[2,2] and len(seg.get('sample',[]))==2 for seg in recorded):
                segments=[seg['sample'] for seg in recorded]
        if not segments or call.get('kind')!='violinplot':
            return reject('额外元素不是可完整读取的两端点线段')
        for segment in segments:
            points=np.asarray(segment,dtype=float)
            if points.shape!=(2,2) or not np.isfinite(points).all():
                return reject('线段坐标不完整或含非有限值')
            groups=[i for i,pos in enumerate(positions) if np.allclose(points[:,1-dimension],pos,rtol=0,atol=1e-8)]
            if len(groups)==1:
                group=groups[0];q1,q3=np.percentile(samples[group],[25,75])
                if not np.allclose(np.sort(points[:,dimension]),[q1,q3],rtol=1e-9,atol=1e-9):
                    return reject(f"{call['labels'][group]} 组端点应为 Q1={q1:.8g}、Q3={q3:.8g}")
                if group in seen:return reject('同组出现重复的四分位连接线')
                seen.add(group)
                verified.append({'key':key,'group':call['labels'][group],'statistic':'Q1-Q3',
                                 'q1':float(q1),'q3':float(q3)})
                continue
            # Outer/median bars are orthogonal to the value axis and centered
            # on exactly one group. Their values come from full matched rows.
            if not np.allclose(points[:,dimension],points[0,dimension],rtol=1e-9,atol=1e-9):
                return reject('线段既不位于组中心，也不是水平于分位值的统计线')
            center=float(np.mean(points[:,1-dimension]))
            groups=[i for i,pos in enumerate(positions) if np.isclose(center,pos,rtol=0,atol=1e-8)]
            if len(groups)!=1:return reject('分位横线未唯一对齐某一组中心')
            group=groups[0];quartiles=np.percentile(samples[group],[25,50,75])
            matches=[name for name,value in zip(('Q1','median','Q3'),quartiles)
                     if np.isclose(points[0,dimension],value,rtol=1e-9,atol=1e-9)]
            if not matches:return reject(f"{call['labels'][group]} 组横线数值不等于原始样本的 Q1、中位数或 Q3")
            distances=[abs(pos-positions[group]) for i,pos in enumerate(positions) if i!=group]
            if distances and np.ptp(points[:,1-dimension])>=min(distances):
                return reject('分位横线跨入其他组的位置')
            verified.append({'key':key,'group':call['labels'][group],'statistic':'/'.join(matches),
                             'value':float(points[0,dimension])})
    return verified,None


def _verify_single_distribution(project, chart, context, proposal, report):
    """Return None for ordinary edits, otherwise a pass/fail/unverified report."""
    kind = requested_distribution(context.get('user_message', ''))
    if not kind:
        return None
    result = {'kind': kind, 'status': 'unverified', 'warnings': [], 'matches': []}
    def stop(reason, status='unverified'):
        return {**result, 'status': status, 'reason': reason}
    calls = report.get('distribution_inputs') or []
    if not calls or any(c.get('kind') != kind for c in calls):
        from chart_source_evidence import inspect_source_samples
        source=inspect_source_samples(project,chart,context,proposal.get('read_data_refs',[]))
        if source['status']=='available' and kind=='violinplot' and not any(all(g['count']>=2 for g in s['groups']) for s in source['sources']):
            source={**source,'status':'insufficient_samples','reason':'已找到分组数据，但部分组不足两条观测值，无法可靠表达小提琴分布；请补充逐条样本或选择适合现有数据的图型。'}
        name='小提琴图' if kind=='violinplot' else '箱线图'
        if source['status']=='changed':
            result=stop(source['reason'],'fail')
        elif source['status']=='available':
            files='、'.join(item['path'] for item in source['sources'])
            result=stop(f'原分组数据已找到（{files}），但本轮尚未取得候选{name}实际使用的完整样本记录，不能确认转换是否生效。平台应优先用已有数据修复，无需重复上传。')
        else:
            result=stop(source['reason'])
        return {**result,'source_evidence':source,'required_api':'Axes.'+kind}
    before_axes = (report.get('baseline_layout_signature') or {}).get('axes', [])
    after_axes = (report.get('layout_signature') or {}).get('axes', [])
    if len(calls) != 1 or len(before_axes) != 1 or len(after_axes) != 1:
        return stop('多子图或多次分布绘制的分组对应关系尚无法自动核对。')
    call = calls[0]
    dimension = call['dimension']; labels = call['labels']; groups = call['groups']
    if not labels or len(labels) != len(groups) or len(set(labels)) != len(labels):
        return stop('箱线/小提琴图的每组样本需要有唯一且完整的组标签。')
    group_axes = [index for index,ticks in enumerate(before_axes[0]['tick_texts']) if ticks == labels]
    if len(group_axes)!=1:
        return stop('转换前后的组标签或顺序发生变化，请保留原组别对应关系。', 'fail')
    expected_labels = before_axes[0].get('labels')
    if group_axes[0] != 1-dimension:
        expected_labels=list(reversed(expected_labels))
    if expected_labels != after_axes[0].get('labels'):
        return stop('转换改变了轴标题或单位，请先核对科学含义。', 'fail')
    def annotations(signature):
        return sorted(t['text'] for t in signature.get('texts', [])
                      if not re.search(r'\.[xy](?:tick_|offset)', t['key']))
    if annotations(report.get('baseline_layout_signature') or {}) != annotations(report.get('layout_signature') or {}):
        return stop('转换改变了原有标题、图例或统计标注，尚未确认其对应关系。', 'fail')
    artists = report.get('candidate_artists') or []
    if not any(a.get('semantic_role') == 'distribution_statistics' for a in artists):
        return stop('没有捕获可核对的分布统计元素。')
    # Reject arbitrary added data artists alongside the requested distribution.
    # A significance bracket can move vertically to accommodate the new range.
    overlays=report.get('distribution_overlays') or []
    overlay_keys=set()
    for overlay in overlays:
        if not overlay.get('valid'):
            return stop('叠加散点无法唯一归组，或含不可见、缺失点；请调整抖动范围或明确显示规则后重新核对。')
        if overlay.get('groups') != groups:
            return stop('叠加散点的样本或组别与分布图不一致，不能自动放行。','fail')
        overlay_keys.update(overlay.get('collection_keys',[]))
    extra_artists=[]
    for artist in artists:
        if artist.get('key') in overlay_keys:
            continue
        if artist.get('semantic_role') == 'distribution_statistics':
            if artist.get('distribution_mutated'):
                return stop('分布图生成后又修改了统计线条或箱体数值，不能按原始样本核对通过。', 'fail')
            visibility = artist.get('visibility') or {}
            if visibility.get('visible') is False or visibility.get('alpha') == 0:
                return stop('分布图包含被隐藏的统计元素，请保留可见的箱体和统计线条。', 'fail')
            continue
        data = artist.get('data') or {}
        x, y = data.get('x') or {}, data.get('y') or {}
        bracket = (artist.get('kind') == 'line' and x.get('shape') == [4] and y.get('shape') == [4]
                   and len(x.get('sample', [])) == 3 and x['sample'][0] == x['sample'][1]
                   and len(y.get('sample', [])) == 3 and y['sample'][1] == y['sample'][2])
        if not bracket:
            extra_artists.append(artist)
    import pandas as pd
    known = {item['path']: item for item in context.get('plot_data', [])}
    comparable=False
    missing_values=False
    for ref in proposal.get('read_data_refs', []):
        path = ref.get('path'); original = known.get(path)
        if not original or not path.lower().endswith(('.csv', '.tsv')):
            continue
        target = Path(project) / path
        if not target.resolve().is_relative_to(Path(project).resolve()):
            continue
        raw = target.read_bytes()
        actual = hashlib.sha256(raw).hexdigest()
        if original.get('sha256', '').removeprefix('sha256:') != actual:
            return stop('输入数据已变化，请重新生成候选。', 'fail')
        table = pd.read_csv(target, sep='\t' if path.lower().endswith('.tsv') else ',', dtype=None)
        for id_column in ('panel_id', 'chart_id', 'plot_id'):
            if id_column in table.columns:
                table = table[table[id_column].astype(str).eq(chart)]
        columns = [c['name'] for c in ref.get('columns', []) if c.get('name') in table.columns]
        for group_column in columns:
            grouped = table[group_column].astype(str)
            if set(grouped) != set(labels):
                continue
            for value_column in columns:
                if value_column == group_column:
                    continue
                try:
                    expected = [sample_signature(pd.to_numeric(table.loc[grouped.eq(label), value_column], errors='raise'))
                                for label in labels]
                except (ValueError, TypeError):
                    continue
                if not all(e['sha256'] for e in expected):
                    missing_values=True
                    continue
                comparable=True
                if all(e['sha256'] and e == actual for e, actual in zip(expected, groups)):
                    if extra_artists:
                        samples=[pd.to_numeric(table.loc[grouped.eq(label),value_column],errors='raise').to_numpy(float) for label in labels]
                        verified,error=_verify_iqr_connectors(extra_artists,call,samples)
                        if error:return stop(error)
                        result['statistic_overlays']=verified
                    result['matches'] = [{'path': path, 'group_column': group_column, 'value_column': value_column,
                                          'groups': [{'label': label, 'count': e['count']} for label, e in zip(labels, expected)]}]
                    if kind == 'boxplot':
                        result['warnings'].append('箱线图以中位数和四分位数展示原始分布；须线规则：'+str(call.get('whis'))+'。')
                        if not call.get('showfliers', True):
                            result['warnings'].append('此候选不显示离群点；原始样本仍全部参与箱线统计，CSV 未被删除。')
                    return {**result, 'status': 'pass', 'reason': '按用户明确要求转换图型；完整原始样本、分组标签与统计标注核对通过。'}
    if missing_values and not comparable:
        return stop('源分组含缺失值或非有限值；需要明确缺失值处理规则，未自动删除或填补样本。')
    if not comparable:
        return stop('没有找到可核对的完整 CSV/TSV 分组及数值列；请补充明确的数据引用，不能据此断言数据已被改动。')
    return stop('分布图样本未能与所引用 CSV 的完整分组逐值核对；请检查漏行、改值、分组或数据引用。', 'fail')


def verify_distribution(project, chart, context, proposal, report):
    """Verify every panel independently; unsupported mappings never bypass checks."""
    kind=requested_distribution(context.get('user_message',''))
    if not kind:
        return None
    before=(report.get('baseline_layout_signature') or {}).get('axes',[])
    after=(report.get('layout_signature') or {}).get('axes',[])
    if len(before)<=1 and len(after)<=1:
        return _verify_single_distribution(project,chart,context,proposal,report)
    def stop(reason,status='unverified'):
        return {'kind':kind,'status':status,'reason':reason,'warnings':[],'matches':[]}
    if len(before)!=len(after):
        return stop('转换前后子图数量变化，尚无法确认逐子图数据对应。')
    global_text=lambda signature:sorted(t['text'] for t in (signature or {}).get('texts',[]) if not t['key'].startswith('axes_'))
    if global_text(report.get('baseline_layout_signature'))!=global_text(report.get('layout_signature')):
        return stop('图级标题或标注发生变化，需要确认对应要求。')
    calls=report.get('distribution_inputs') or []
    baseline_calls=report.get('baseline_distribution_inputs') or []
    # Raw baseline samples anchor panel identity. Without this, matching any CSV
    # column could accidentally approve a swap between same-label panels.
    if len(calls)!=len(before) or len(baseline_calls)!=len(before):
        return stop('多子图转换需要每个子图的原始分布样本锚点；当前缺少完整对应，未使用形状差异代替数据核对。')
    results=[]
    for axis in range(len(before)):
        current=[c for c in calls if c.get('axis')==axis]
        prior=[c for c in baseline_calls if c.get('axis')==axis]
        if len(current)!=1 or len(prior)!=1:
            return stop('同一子图多次分布绘制尚无法唯一确定分组对应。')
        if prior[0]['groups']!=current[0]['groups'] or prior[0]['labels']!=current[0]['labels']:
            return stop(f'第 {axis+1} 个子图的完整样本或分组发生变化。','fail')
        scoped={**report,'distribution_inputs':current,
            'baseline_layout_signature':{'axes':[before[axis]],'texts':[t for t in (report.get('baseline_layout_signature') or {}).get('texts',[]) if t['key'].startswith(f'axes_{axis}.')]},
            'layout_signature':{'axes':[after[axis]],'texts':[t for t in (report.get('layout_signature') or {}).get('texts',[]) if t['key'].startswith(f'axes_{axis}.')]},
            'candidate_artists':[a for a in report.get('candidate_artists',[]) if a['key'].startswith(f'axes_{axis}.')],
            'distribution_overlays':[o for o in report.get('distribution_overlays',[]) if o['axis']==axis]}
        checked=_verify_single_distribution(project,chart,context,proposal,scoped)
        if checked['status']!='pass':
            return {**checked,'reason':f'第 {axis+1} 个子图：'+checked['reason']}
        results.append(checked)
    return {'kind':kind,'status':'pass','reason':'逐子图完整样本、分组和源数据核对通过。',
            'warnings':list(dict.fromkeys(w for r in results for w in r['warnings'])),
            'matches':[{**m,'axis':axis} for axis,r in enumerate(results) for m in r['matches']]}
