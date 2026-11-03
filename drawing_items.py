"""User-added annotations; positions are relative to a chosen subplot."""
import math
import re


def validate_items(items):
    if not isinstance(items,dict) or len(items)>200: raise ValueError('新增对象过多或格式无效')
    for ident,spec in items.items():
        if not isinstance(ident,str) or not re.fullmatch(r'[a-f0-9]{8,32}',ident) or not isinstance(spec,dict): raise ValueError('新增对象标识无效')
        if set(spec)-{'kind','axis','text','x','y','x2','y2'}: raise ValueError('新增对象属性无效')
        if spec.get('kind') not in ('text','line') or isinstance(spec.get('axis'),bool) or not isinstance(spec.get('axis'),int) or not 0<=spec['axis']<500: raise ValueError('新增对象类型或子图无效')
        if not isinstance(spec.get('text',''),str) or len(spec.get('text',''))>1000: raise ValueError('文字过长')
        for field in ('x','y','x2','y2'):
            v=spec.get(field,.5)
            if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not -5<=v<=5: raise ValueError('新增对象位置无效')
    return items


def apply_items(figure,items):
    for ident,spec in validate_items(items).items():
        if spec['axis']>=len(figure.axes): continue
        axis=figure.axes[spec['axis']]
        if any(getattr(obj,'_plot_forge_added_id',None)==ident for obj in [*axis.texts,*axis.lines]): continue
        if spec['kind']=='text':
            obj=axis.text(spec.get('x',.5),spec.get('y',.5),spec.get('text','新建文本'),transform=axis.transAxes,
                          fontsize=12,ha='center',va='center',color='#111111',clip_on=False,zorder=20)
        else:
            obj,=axis.plot([spec.get('x',.25),spec.get('x2',.75)],[spec.get('y',.5),spec.get('y2',.5)],
                          transform=axis.transAxes,color='#111111',linewidth=2,clip_on=False,zorder=20)
        obj._plot_forge_added_id=ident
