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
    pattern = (r'(?:改为|改成|转换为|转换成|转成|换成|换为|变成)\s*'
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


def requested_scatter(message):
    # Only an explicit conversion grants this exception; mentioning scatter is insufficient.
    pattern = (r'(?:改为|改成|转换为|转换成|转成|换成|换为|变成)\s*'
               r'(?:一个|一张)?\s*(?:scatter(?:\s*plot)?|散点图)'
               r'|(?:change|convert|switch|turn)\b[^.!?。！？]{0,60}?\b(?:to|into)\s+(?:a\s+)?scatter(?:\s*plot)?')
    match = re.search(pattern, message, re.I)
    if not match:
        return False
    clause = re.split(r'[,;，；。.!?！？]', message[:match.start()])[-1]
    return not re.search(r'不要|不想|无需|别|不改|do\s+not|don.t|never|\bnot\b', clause + match.group(), re.I)


def verify_scatter(context, report):
    return _verify_points(context,report,'scatter')


def requested_line(message):
    pattern=(r'(?:更改为|修改为|改为|改成|转换为|转换成|转成|换成|换为|变成)\s*'
             r'(?:一个|一张)?\s*(?:无节点标记的)?(?:折线图|折线|line\s*(?:plot|chart))'
             r'|(?:change|convert|switch|turn)\b[^.!?。！？]{0,60}?\b(?:to|into)\s+(?:a\s+)?line\s*(?:plot|chart)')
    match=re.search(pattern,message,re.I)
    if not match:return False
    clause=re.split(r'[,;，；。.!?！？]',message[:match.start()])[-1]
    return not re.search(r'不要|不想|无需|别|不改|do\s+not|don.t|never|\bnot\b',clause+match.group(),re.I)


def verify_line(context, report):
    return _verify_points(context,report,'line')


def _verify_points(context, report, target):
    """Verify either mark conversion using every ordered x/y pair, not samples."""
    predicate=requested_scatter if target=='scatter' else requested_line
    if not predicate(context.get('user_message', '')):
        return None
    source='line' if target=='scatter' else 'scatter'
    result = {'kind': target, 'status': 'unverified', 'warnings': [], 'matches': []}
    def stop(reason, status='fail'):
        return {**result, 'status': status, 'reason': reason}
    before, after = report.get('baseline_artists'), report.get('candidate_artists')
    if not before or not after or report.get('unsupported_artists'):
        return stop('缺少完整绘图元素记录或含不支持的元素，不能自动放行图型转换。', 'unverified')
    data = report.get('data_report') or {}
    ranges_only = all(isinstance(change.get('before'), dict) and isinstance(change.get('after'), dict)
                      and {k: v for k, v in change['before'].items() if k not in ('xlim', 'ylim')}
                      == {k: v for k, v in change['after'].items() if k not in ('xlim', 'ylim')}
                      for change in data.get('axes_changes', []))
    if data.get('status') in ('fail', 'changed', 'conflict') or not ranges_only:
        return stop('图型转换同时改变了坐标范围、轴尺度或数据，未放行。')
    def annotations(signature):
        return sorted((t['key'], t['text']) for t in (signature or {}).get('texts', [])
                      if not re.search(r'\.[xy](?:tick_|offset)', t['key']))
    if annotations(report.get('baseline_layout_signature')) != annotations(report.get('layout_signature')):
        return stop('图型转换改变了标题、轴标签、组名或标注，请保留原有科学含义。')
    remaining = list(after)
    for old in before:
        # First preserve unrelated artists, including existing error bars/annotations.
        same = [a for a in remaining if all(a.get(k) == old.get(k)
                for k in ('key', 'kind', 'label', 'data_hash', 'visibility', 'point_signature'))]
        if len(same) == 1:
            remaining.remove(same[0])
            continue
        label = old.get('label') or ''
        axis = old['key'].split('.')[0]
        targets = [a for a in remaining if a.get('kind') == target and a.get('label') == label
                   and a['key'].split('.')[0] == axis]
        if (old.get('kind') != source or old.get('semantic_role') != 'data_artist'
                or not label or label.startswith('_') or len(targets) != 1
                or sum(a.get('label') == label and a['key'].split('.')[0] == axis for a in before) != 1):
            return stop('转换前后的数据组无法唯一对应，或删除/修改了其他绘图元素。')
        new = targets[0]
        left, right = old.get('point_signature'), new.get('point_signature')
        if not left or not right:
            return stop('无法核对全部坐标：存在缺失值、自定义变换、隐藏点或旧版记录。', 'unverified')
        if (left.get('shape') != right.get('shape') or not left.get('sha256')
                or left['sha256'] != right.get('sha256') or old.get('visibility') != new.get('visibility')):
            return stop('散点与原折线的完整坐标、点数、顺序或可见性不一致；未放行。')
        result['matches'].append({'axis': axis, 'label': label, 'count': left['shape'][0],
                                  'sha256': left['sha256']})
        remaining.remove(new)
    if remaining or not result['matches']:
        return stop('未检测到可核对的目标图型转换，或出现额外数据元素。')
    direction='折线→散点' if target=='scatter' else '散点→折线'
    return {**result, 'status': 'pass', 'reason': direction+'：各组全部坐标、点数、顺序、坐标轴和标注核对通过。'}


def verify_distribution(project, chart, context, proposal, report):
    """Return None for ordinary edits, otherwise a pass/fail/unverified report."""
    kind = requested_distribution(context.get('user_message', ''))
    if not kind:
        return None
    if report.get('baseline_distribution_inputs'):
        return _verify_recorded_distributions(context,report,kind)
    result = {'kind': kind, 'status': 'unverified', 'warnings': [], 'matches': []}
    def stop(reason, status='unverified'):
        return {**result, 'status': status, 'reason': reason}
    calls = report.get('distribution_inputs') or []
    if not calls or any(c.get('kind') != kind for c in calls):
        name='小提琴图' if kind=='violinplot' else '箱线图'
        return {**stop(f'未检测到目标{name}的样本绘制，候选可能仍是原图型；请真正转换图型后再检查。'),
                'required_api':'Axes.'+kind}
    before_axes = (report.get('baseline_layout_signature') or {}).get('axes', [])
    after_axes = (report.get('layout_signature') or {}).get('axes', [])
    if len(calls) != 1 or len(before_axes) != 1 or len(after_axes) != 1:
        return stop('多子图或多次分布绘制的分组对应关系尚无法自动核对。')
    call = calls[0]
    dimension = call['dimension']; labels = call['labels']; groups = call['groups']
    if not labels or len(labels) != len(groups) or len(set(labels)) != len(labels):
        return stop('箱线/小提琴图的每组样本需要有唯一且完整的组标签。')
    if before_axes[0]['tick_texts'][1-dimension] != labels:
        return stop('转换前后的组标签或顺序发生变化，请保留原组别对应关系。', 'fail')
    if before_axes[0].get('labels') != after_axes[0].get('labels'):
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
    for artist in artists:
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
            return stop('目标分布图之外还有无法核对的数据元素，不能自动放行。')
    import pandas as pd
    known = {item['path']: item for item in context.get('plot_data', [])}
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
                if all(e['sha256'] and e == actual for e, actual in zip(expected, groups)):
                    result['matches'] = [{'path': path, 'group_column': group_column, 'value_column': value_column,
                                          'groups': [{'label': label, 'count': e['count']} for label, e in zip(labels, expected)]}]
                    if kind == 'boxplot':
                        result['warnings'].append('箱线图以中位数和四分位数展示原始分布；须线规则：'+str(call.get('whis'))+'。')
                        if not call.get('showfliers', True):
                            result['warnings'].append('此候选不显示离群点；原始样本仍全部参与箱线统计，CSV 未被删除。')
                    return {**result, 'status': 'pass', 'reason': '按用户明确要求转换图型；完整原始样本、分组标签与统计标注核对通过。'}
    return stop('分布图样本未能与所引用 CSV 的完整分组逐值核对；请检查漏行、改值、分组或数据引用。', 'fail')


def _verify_recorded_distributions(context,report,kind):
    """Match complete observed input groups per axis; keep paired marks exact."""
    from collections import Counter
    source_kind='boxplot' if kind=='violinplot' else 'violinplot'
    source_type='box_statistics' if source_kind=='boxplot' else 'violin_statistics'
    target_type='violin_statistics' if kind=='violinplot' else 'box_statistics'
    result={'kind':kind,'status':'unverified','warnings':[],'matches':[]}
    def stop(reason,status='fail'):return {**result,'status':status,'reason':reason}
    before_signature=report.get('baseline_layout_signature') or {};after_signature=report.get('layout_signature') or {}
    before_axes=before_signature.get('axes',[]);after_axes=after_signature.get('axes',[])
    if not before_axes or len(before_axes)!=len(after_axes):return stop('图型转换改变了子图数量，无法保留原始子图映射。')
    selected=(context.get('selected_panel') or {}).get('axis_labels')
    eligible={i for i,axis in enumerate(before_axes) if not selected or axis.get('axis_label') in selected}
    old_calls=report.get('baseline_distribution_inputs',[]);new_calls=report.get('distribution_inputs',[])
    target_axes={call.get('axis') for call in new_calls if call.get('kind')==kind}
    converted={call['axis'] for call in old_calls if call['kind']==source_kind
               and call.get('axis') in eligible & target_axes}
    if not converted:return stop('目标子图未记录可转换的原始逐样本分布输入。','unverified')
    for i,(a,b) in enumerate(zip(before_axes,after_axes)):
        if a.get('axis_label')!=b.get('axis_label') or a.get('labels')!=b.get('labels'):
            return stop('转换改变了子图标识、轴标题或单位。')
        if i not in converted:
            old_range=(report.get('baseline_axis_details') or [])
            new_range=(report.get('axis_details') or [])
            if len(old_range)==len(before_axes) and len(new_range)==len(after_axes) and old_range[i]!=new_range[i]:
                return stop('转换改变了目标之外子图的坐标范围。')
    def groups(calls,wanted,axes):
        flattened=[]
        for call in calls:
            if call.get('kind')!=wanted or call.get('axis') not in axes:continue
            values=call.get('groups',[]);positions=call.get('positions',[]);labels=call.get('group_labels',[])
            if len(labels)!=len(values) and len(call.get('labels',[]))==len(values):labels=call['labels']
            if len(positions)!=len(values) or len(labels)!=len(values) or any(label is None or label=='' for label in labels):
                raise ValueError('原始分布的组位置和组名未能自动对应。')
            for position,label,value in zip(positions,labels,values):
                if not value.get('sha256') or value.get('count',0)==0:raise ValueError('原始分布包含无法完整核对的空组或非有限样本。')
                flattened.append((call['axis'],call['dimension'],float(position),label,value['count'],value['sha256']))
        return Counter(flattened)
    try:
        expected=groups(old_calls,source_kind,converted);actual=groups(new_calls,kind,converted)
    except ValueError as error:return stop(str(error),'unverified')
    if not expected or actual!=expected:return stop('转换前后完整样本、重复值数量、组别、组顺序或组位置不一致。')
    if any(re.match(r'axes_(\d+)\.',a.get('key',''))
           and int(re.match(r'axes_(\d+)\.',a['key'])[1]) in converted
           and (a.get('data',{}).get('supplied') or {}).get('type')==source_type
           for a in report.get('candidate_artists',[])):
        return stop('目标子图仍保留原图型的绘制，尚未完整完成图型转换。')
    other_axes=set(range(len(before_axes)))-converted
    try:
        for name in ('boxplot','violinplot'):
            if groups(old_calls,name,other_axes)!=groups(new_calls,name,other_axes):return stop('转换改变了其他子图的分布输入。')
    except ValueError as error:return stop(str(error),'unverified')
    def annotations(signature):
        return Counter((str(t['key']).split('.')[0],t['text']) for t in signature.get('texts',[])
                       if not re.search(r'\.[xy](?:tick_|offset)',t['key']))
    if annotations(before_signature)!=annotations(after_signature):return stop('转换改变了标题、统计显著性文字或其他原有标注。')
    def axis(artist):
        match=re.match(r'axes_(\d+)\.',artist.get('key',''));return int(match[1]) if match else -1
    def statistical(artist,typ):
        return artist.get('semantic_role')=='distribution_statistics' and (artist.get('data',{}).get('supplied') or {}).get('type')==typ
    old_artists=report.get('baseline_artists',[]);new_artists=report.get('candidate_artists',[])
    if not old_artists or not new_artists:return stop('缺少完整原版和候选的绘图元素记录。','unverified')
    target=[a for a in new_artists if axis(a) in converted and statistical(a,target_type)]
    if not target:return stop('未捕获到实际生成的目标分布图。')
    for artist in target:
        if artist.get('distribution_mutated'):return stop('分布生成后又改动了统计数值，无法确认科学含义保持不变。')
        visible=artist.get('visibility') or {}
        if visible.get('visible') is False or visible.get('alpha')==0:return stop('候选隐藏了目标分布的统计元素。')
    def marker(artist):
        label=artist.get('label') or ''
        return (axis(artist),artist.get('kind'),label if not label.startswith('_') else '',
                artist.get('data_hash'),json.dumps(artist.get('visibility'),sort_keys=True))
    def bracket(artist):
        data=artist.get('data') or {};x=data.get('x') or {};y=data.get('y') or {}
        return (axis(artist) in converted and artist.get('kind')=='line' and x.get('shape')==[4] and y.get('shape')==[4]
                and len(x.get('sample',[]))==3 and x['sample'][0]==x['sample'][1]
                and len(y.get('sample',[]))==3 and y['sample'][1]==y['sample'][2])
    remaining=[a for a in new_artists if not (axis(a) in converted and statistical(a,target_type))]
    for old in old_artists:
        if axis(old) in converted and statistical(old,source_type):continue
        match=next((a for a in remaining if marker(a)==marker(old)),None)
        if match is None and bracket(old):
            match=next((a for a in remaining if bracket(a) and axis(a)==axis(old)
                        and a['data']['x']==old['data']['x'] and a.get('visibility')==old.get('visibility')),None)
        if match is None:return stop('转换修改或删除了原有样本散点、配对连线、均值标记或其他非目标数据元素。')
        remaining.remove(match)
    if remaining:return stop('候选包含无法与原版核对的额外数据元素。')
    result['matches']=[{'axis':a,'dimension':d,'position':p,'label':label,'count':n,'sha256':sha}
                       for a,d,p,label,n,sha in sorted(expected)]
    return {**result,'status':'pass','reason':'已逐子图核对全部样本与分组；配对连线、原有数据元素和显著性标注保持一致。'}
