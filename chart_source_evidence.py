"""Distinguish a missing drawing observation from missing source samples."""
import hashlib
from pathlib import Path


def inspect_source_samples(project, chart, context, references=()):
    import pandas as pd
    project=Path(project).resolve()
    found=[];summaries=[];unresolved=[]
    for item in context.get('plot_data',[]):
        path=item.get('path','')
        if not path.lower().endswith(('.csv','.tsv')):
            continue
        target=(project/path).resolve()
        if not target.is_relative_to(project) or not target.is_file():
            continue
        raw=target.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=item.get('sha256','').removeprefix('sha256:'):
            return {'status':'changed','reason':'原始数据文件在本轮期间发生变化，需要重新读取。','sources':[]}
        try:
            table=pd.read_csv(target,sep='\t' if path.lower().endswith('.tsv') else ',')
        except (ValueError,UnicodeError):
            unresolved.append(path);continue
        for column in ('panel_id','chart_id','plot_id'):
            if column in table.columns:
                table=table[table[column].astype(str).eq(chart)]
        if table.empty:
            continue
        declared=[column['name'] for ref in references if ref.get('path')==path for column in ref.get('columns',[])
                  if column.get('role','').lower() in ('group','grouping','condition') and column.get('name') in table.columns]
        group_columns=declared+[column for column in table.columns if column.lower() in ('group','condition','treatment','组别','分组') and column not in declared]
        if not group_columns:
            unresolved.append(path);continue
        group=group_columns[0]
        counts=table.groupby(group,dropna=False).size()
        aggregate_columns={'mean','sem','sd','std','median','ci','ci_lower','ci_upper','均值','标准误','标准差'}
        excluded=set(group_columns)|{'panel_id','chart_id','plot_id','subject_id','sample_id','trial_id'}
        numeric=[column for column in table.columns if column not in excluded and pd.to_numeric(table[column],errors='coerce').notna().any()]
        detail={'path':path,'group_column':group,'value_columns':numeric,
                'groups':[{'label':str(label),'count':int(count)} for label,count in counts.items()]}
        if numeric and all(column.lower() in aggregate_columns for column in numeric) and int(counts.max())<=1:
            summaries.append(detail)
        elif numeric:
            found.append(detail)
        else:
            unresolved.append(path)
    if found:
        return {'status':'available','reason':'已在项目中找到分组数值数据；需要进一步确认候选图实际使用了这些完整数据。','sources':found[:5]}
    if summaries:
        return {'status':'summary_only','reason':'已找到数据文件，但每组只有一行均值/误差等汇总统计，不能据此还原组内分布；需要每组逐条观测值。','sources':summaries[:5]}
    return {'status':'unresolved','reason':'尚未定位到可核对的逐条分组样本；这不代表项目没有数据。数据可能嵌入代码、Bundle 或使用了未识别的列名，需要定位其来源。',
            'sources':[], 'unresolved_files':unresolved[:5]}
