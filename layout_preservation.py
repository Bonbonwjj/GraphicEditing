"""Keep canvas and panel rectangles stable unless the user requests layout work."""
import math
import re


def layout_requested(context):
    if context.get('normalization_skill'):return True
    for clause in re.split(r'[，,；;。\n]',context.get('user_message','')):
        if re.search(r'不要|不改变|不改动|保持|保留|不动|do not|unchanged|preserve',clause,re.I):continue
        action=re.search(r'调整|修改|改变|加宽|加高|缩窄|缩小|放大|移动|挪|重排|恢复|还原|解决|修复|change|resize|move|restore|fix|adjust',clause,re.I)
        target=re.search(r'布局|排版|画布|整图|全图|子图.*(?:位置|大小|间距)|(?:位置|大小|间距).*子图|相对位置|figsize|canvas|figure size|panel.*(?:position|size|spacing)|layout|overlap|重叠',clause,re.I)
        if action and target:return True
    return False


def reference(context,report):
    return context.get('_layout_reference') or {'signature':report.get('baseline_layout_signature') or {},
        'layout':report.get('baseline_layout') or {}}


def check_layout(context,report,normalizing=False):
    if normalizing:return {'status':'not_applicable','reason':'normalization'}
    before=reference(context,report)['signature'];after=report.get('layout_signature') or {}
    restore=bool(context.get('_layout_reference'))
    if not restore and layout_requested(context):return {'status':'authorized'}
    changes=[]
    def compare(kind,a,b,tolerance):
        if a is None:return
        if b is None or len(a)!=len(b) or any(not math.isclose(float(x),float(y),rel_tol=0,abs_tol=tolerance) for x,y in zip(a,b)):
            changes.append({'kind':kind,'before':a,'after':b})
    compare('canvas',before.get('size_inches'),after.get('size_inches'),1e-4)
    old_axes=before.get('axes');new_axes=after.get('axes')
    if old_axes is not None:
        if new_axes is None or len(old_axes)!=len(new_axes):changes.append({'kind':'panel_count'})
        else:
            for i,(a,b) in enumerate(zip(old_axes,new_axes)):
                compare('panel_'+str(i),a.get('position'),b.get('position'),2e-4)
    if changes:return {'status':'fail','changes':changes,'expected_signature':before,
        'reason':'这次修改额外改变了整图大小或子图位置，平台已拦截；需要保留原排版后重新生成。'}
    return {'status':'pass' if before.get('size_inches') else 'unverified','changes':[]}


def unchanged_spacing_issues(context,report):
    """Existing unchanged spacing warnings do not authorize global rearrangement."""
    if layout_requested(context) and not context.get('_layout_reference'):return []
    if check_layout(context,report).get('status')!='pass':return []
    def key(issue):return (issue.get('kind'),tuple(issue.get('elements',[])),issue.get('message'))
    old={key(i) for i in reference(context,report)['layout'].get('issues',[]) if i.get('kind')=='panel_spacing'}
    return [i for i in report.get('layout',{}).get('issues',[]) if key(i) in old]
