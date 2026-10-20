"""Verify supported user requirements against final-save measurements, not agent claims."""
import math
import re
from chat_parameters import parse_requests

_KEYS={'set_xlabel':'xlabel_fontsize','set_ylabel':'ylabel_fontsize','legend':'legend_loc','plot':'line_color','set_xlim':'xlim','set_ylim':'ylim'}
_LOC={'upper right':1,'upper left':2,'lower left':3,'lower right':4,'upper center':9,'lower center':8}


def _near(actual,expected):
    if isinstance(expected,dict):
        return isinstance(actual,dict) and set(actual)==set(expected) and all(_near(actual[k],v) for k,v in expected.items())
    if isinstance(expected,(list,tuple)):
        return isinstance(actual,(list,tuple)) and len(actual)==len(expected) and all(_near(a,b) for a,b in zip(actual,expected))
    if isinstance(expected,(float,int)) and not isinstance(expected,bool):
        return isinstance(actual,(float,int)) and math.isclose(actual,expected,rel_tol=1e-5,abs_tol=1e-6)
    return actual==expected



def equal_tick_spacing(axis,name):
    """Return observed linear numeric tick spacing; category/log axes are out of scope."""
    if axis.get(name+'scale')!='linear' or not axis.get('numeric_'+name+'ticks'):
        return None
    ticks=axis.get('major_'+name+'ticks') or []
    gaps=[float(b)-float(a) for a,b in zip(ticks,ticks[1:])]
    return {'ticks':[float(f'{v:.12g}') for v in ticks],'intervals':[float(f'{v:.12g}') for v in gaps],'equal':bool(gaps) and gaps[0]>0 and all(math.isclose(g,gaps[0],rel_tol=1e-6,abs_tol=max(abs(gaps[0])*1e-8,1e-12)) for g in gaps)}


def verify_requirements(message,report):
    requests=parse_requests(message)
    result={'version':1,'scope':'最终 PNG 保存时的 Matplotlib 属性；不包含任意复杂图元或科学语义的完整视觉判断。','requirements':[]}
    rows=result['requirements']
    if not requests:
        rows.append({'request':message,'status':'unverified','reason':'此要求未被完整解析为受支持的参数目标；需对照候选人工审阅。','blocking':False})
    else:
        before=report.get('baseline_layout_signature') or {};after=report.get('layout_signature') or {}
        old=before.get('axes') or [];new=after.get('axes') or []
        for clause,intent in requests:
            key=intent.get('setting') or _KEYS.get(intent.get('method'))
            row={'request':clause,'property':key,'status':'unverified','blocking':True,'expected':intent['value'],'actual':None}
            rows.append(row)
            if len(old)!=1 or len(new)!=1:
                row['reason']='需要唯一的目标坐标轴及前后测量结果，当前无法自动确认。';continue
            a,b=old[0],new[0];value=intent['value'];expected=actual=None
            if key in ('spine_scale','xspine_scale','yspine_scale'):
                names={'bottom','top'} if key=='xspine_scale' else {'left','right'} if key=='yspine_scale' else {'bottom','top','left','right'}
                widths=a.get('spine_linewidths',{});current=b.get('spine_linewidths',{})
                names=names&set(widths)
                if names:expected={n:widths[n]*value for n in sorted(names)};actual={n:current.get(n) for n in sorted(names)}
            elif key in ('xlabel_fontsize','ylabel_fontsize','xlabel_scale','ylabel_scale'):
                index=0 if key.startswith('x') else 1
                sizes=a.get('label_fontsizes',[]);current=b.get('label_fontsizes',[])
                if len(sizes)==len(current)==2 and a.get('labels',['',''])[index]:
                    expected=sizes[index]*value if key.endswith('_scale') else value;actual=current[index]
            elif key=='tick_fontsize':
                sizes=b.get('tick_fontsizes',[])
                if sizes and any(sizes):expected=[[value for _ in axis] for axis in sizes];actual=sizes
            elif key=='text_scale':
                texts={t['key']:t for t in before.get('texts',[]) if t.get('text','').strip()};current={t['key']:t for t in after.get('texts',[]) if t.get('text','').strip()}
                if texts and all('fontsize' in t for t in texts.values()):
                    expected={k:t['fontsize']*value for k,t in texts.items()};actual={k:current.get(k,{}).get('fontsize') for k in texts}
            elif key in ('legend_loc','legend_fontsize'):
                legend=b.get('legend') or {}
                if legend.get('labels'):
                    expected=_LOC.get(value) if key=='legend_loc' else [value]*len(legend['labels']);actual=legend.get('loc') if key=='legend_loc' else legend.get('fontsizes')
            elif key=='line_color':
                from matplotlib.colors import to_hex
                colors=b.get('line_colors') or []
                if len(a.get('line_colors') or [])==len(colors)==1:expected=to_hex(value,keep_alpha=True);actual=colors[0]
            elif key in ('xlim','ylim'):
                axes=report.get('axis_details') or []
                if len(axes)==1:
                    axis=axes[0];name=key[0];spine='bottom' if name=='x' else 'left'
                    expected={'limits':list(value),'spine_bounds':list(value),'continuous':True,'visible':True}
                    actual={'limits':axis.get(key),'spine_bounds':axis.get(spine+'_spine_bounds'),'continuous':axis.get(spine+'_spine_continuous'),'visible':axis.get(spine+'_spine_visible')}
                    spacing=equal_tick_spacing(axis,name)
                    if spacing is not None:
                        expected['equally_spaced_ticks']=True;actual['equally_spaced_ticks']=spacing['equal']
                        row['tick_spacing']=spacing
            row.update(expected=expected if expected is not None else value,actual=actual)
            if expected is None or actual is None:
                row['reason']='缺少适用的目标元素或最终属性测量，不能确认已实现。'
            else:
                row['status']='pass' if _near(actual,expected) else 'fail'
                row['reason']='最终导出属性符合本轮要求。' if row['status']=='pass' else '最终导出属性与要求不一致；参数可能被后续绘图或标准化覆盖。'
    # An explicit preservation request has its own observed acceptance result.
    # Compare stable style attributes, not positions/bounding boxes that naturally
    # move when text, legend location or limits change.
    if requests and re.search(r'(?:其他|其余)(?:内容)?(?:保持)?不变',message) and len(old)==len(new)==1:
        allowed={i.get('setting') or _KEYS.get(i.get('method')) for _,i in requests}
        a,b=old[0],new[0];checks={}
        for name in ('labels','line_colors','label_fontsizes','spine_linewidths','legend'):
            if name not in a or name not in b:continue
            expected=a[name];actual=b[name]
            if name=='line_colors' and 'line_color' in allowed:continue
            if name=='label_fontsizes':
                indices=[j for j,prefix in enumerate(('x','y')) if not allowed&{'text_scale',prefix+'label_scale',prefix+'label_fontsize'}]
                expected=[a[name][j] for j in indices];actual=[b[name][j] for j in indices]
            if name=='spine_linewidths':
                if 'spine_scale' in allowed:continue
                keys=set(expected)
                if 'xspine_scale' in allowed:keys-={'bottom','top'}
                if 'yspine_scale' in allowed:keys-={'left','right'}
                expected={k:expected[k] for k in sorted(keys)};actual={k:actual.get(k) for k in sorted(keys)}
            if name=='legend' and expected and actual:
                keys={'loc','fontsizes','labels'}
                if 'legend_loc' in allowed:keys.discard('loc')
                if allowed&{'legend_fontsize','text_scale'}:keys.discard('fontsizes')
                expected={k:expected[k] for k in sorted(keys)};actual={k:actual.get(k) for k in sorted(keys)}
            if not _near(actual,expected):checks[name]={'expected':expected,'actual':actual}
        baseline_axes=report.get('baseline_axis_details') or [];candidate_axes=report.get('axis_details') or []
        if len(baseline_axes)==len(candidate_axes)==1:
            for name in ('xlim','ylim'):
                if name not in allowed and not _near(candidate_axes[0].get(name),baseline_axes[0].get(name)):
                    checks[name]={'expected':baseline_axes[0].get(name),'actual':candidate_axes[0].get(name)}
        rows.append({'request':'其他内容保持不变（已测量的标签、线色、字号、轴线宽及图例属性）',
                     'status':'fail' if checks else 'pass','blocking':True,
                     'expected':'未请求修改的已测量样式属性保持不变','actual':checks or '未发现差异',
                     'reason':'发现额外样式变化。' if checks else '检测范围内未发现额外样式变化；数据与布局另行检查。'})
    result['status']='fail' if any(r['status']=='fail' for r in rows) else 'unverified' if any(r['status']=='unverified' for r in rows) else 'pass'
    result['blocking']=any(r.get('blocking') and r['status']!='pass' for r in rows)
    return result


def finish_summary(draft):
    """Visible completion text comes from checks, with model prose kept for auditing."""
    draft.setdefault('proposal_summary',draft.get('summary',''))
    contract=draft.get('edit_contract') or {}
    if draft['status']=='preview_ready':
        draft['summary']=(f"已生成候选；{len(contract.get('requirements',[]))} 项参数要求通过最终导出核对，请审阅后应用。" if contract.get('status')=='pass' else '已生成候选；部分要求需对照图片人工审阅，请审阅后应用。')
    elif draft['status']=='already_compliant':draft['summary']=draft.get('reason','当前图已满足要求。')
    else:draft['summary']='候选尚未通过检查，未替换正式图。'+draft.get('reason','')
