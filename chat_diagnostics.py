"""Explain existing decisions without changing acceptance or data policies."""


def explain_draft(draft):
    status = draft.get('status')
    if status in ('preview_ready', 'applied', 'discarded', 'already_compliant'):
        return []
    transform = draft.get('chart_transform') or {}
    source=transform.get('source_evidence') or {}
    data = draft.get('data_report') or {}
    reason = draft.get('reason') or ''
    if status in ('cannot_complete','agent_failed','needs_shared_module'):
        options=[
            ('429','model_rate_limit','模型服务限流','稍后重试，或检查服务端额度和并发限制。'),
            ('截断','model_truncated','模型输出被截断','检查模型实际输出上限，缩小本轮任务；不要反复提交同一大请求。'),
            ('连接','model_connection','模型连接失败','检查网络、VPN 和模型服务地址。'),
            ('密钥','model_configuration','模型配置未完成','打开 API 配置，保存并测试个人配置。'),
            ('JSON','model_format','模型返回格式不完整','查看输出是否完整；格式修复仍受三次调用总额度限制。'),
            ('CSV column','data_reference','数据列引用不匹配','核对实际数据列名和列用途。'),
        ]
        for keyword,code,title,action in options:
            if keyword in reason:
                return [{'code':code,'title':title,'category':'service' if code.startswith('model_') else 'review',
                         'reason':reason,'next_action':action,'evidence':[]}]
    if status == 'validation_failed' and (transform.get('status') == 'unverified'
            or (not transform and '无法捕获目标图型的原始样本' in reason)):
        code, title, category, action = (
            'transform_unverified', '图型转换尚无法核对', 'unverified',
            '查看缺少的核对条件；确认是否使用完整原始样本、支持的绘图接口及明确分组。无法核对不等于已发现数据错误。')
        if source.get('status')=='available':
            title='原数据已找到，候选使用情况未确认'
            action='可使用已有数据继续修复本轮候选；若重试后仍失败，请反馈检查信息，无需重复上传相同数据。'
        elif source.get('status')=='summary_only':
            title='现有汇总数据不足以还原分布'
            action='请补充每组逐条观测值；均值和误差不能还原组内分布，不会自动编造样本。'
        elif source.get('status')=='insufficient_samples':
            title='部分组的样本数量不足'
            action='请补充这些组的逐条样本，或选择适合现有样本量的图型；不会通过复制样本来凑数。'
        elif source.get('status')=='unresolved':
            title='需要定位原始样本来源'
            action='请说明逐条样本所在文件或数据列；如果数据在代码或 Bundle 中，需要补充其位置，未要求重新上传整个项目。'
    elif status == 'validation_failed' and transform.get('status') == 'fail':
        code, title, category, action = (
            'transform_mismatch', '图型转换核对不一致', 'mismatch',
            '对照具体原因检查样本、组名、单位和标注；这可能是映射变化，也可能是当前匹配规则无法识别，需要进一步核查。')
    elif status == 'validation_failed':
        code, title, category, action = (
            'data_mapping_difference', '绘图数据或映射出现差异', 'mismatch',
            '检查下方变化对象。绘图几何差异不直接证明 CSV 被改；图型转换需核对原始样本，普通样式修改应保留数据映射。')
    else:
        choices = {
            'layout_conflict': ('layout_conflict', '布局存在重叠或裁切', 'presentation', '可基于此候选继续修复；审阅所列冲突后也可明确接受布局例外。'),
            'font_unverified': ('font_unverified', '字体效果未确认', 'unverified', '查看实际字体、替代字体或缺字信息，可继续调整字体。'),
            'manual_review': ('manual_review', '需人工审阅', 'unverified', '对照当前图人工核对要求；模型的完成判断尚未获得自动验证。'),
            'intent_unmet': ('intent_unmet', '本轮要求未实现', 'mismatch', '查看需求验收的目标值和导出值，可基于候选继续修复。'),
            'intent_unverified': ('intent_unverified', '本轮要求无法自动确认', 'unverified', '查看缺少的目标或测量信息，明确目标后继续修改。'),
            'axis_unmet': ('axis_unmet', '坐标轴要求尚未实现', 'mismatch', '检查范围、端点刻度和轴线；进一步说明需要调整哪条轴。'),
            'no_visible_change': ('no_visible_change', '图片变化未达到要求', 'mismatch', '核对上一版是否已满足要求；若未满足，检查参数是否真正作用于输出图。'),
            'render_failed': ('render_failed', '候选未能成功出图', 'execution', '查看运行错误，检查代码、数据路径、依赖或超时。'),
            'revision_conflict': ('revision_conflict', '正式版本已经变化', 'conflict', '从最新正式版本重试，避免覆盖较新的代码或数据。'),
        }
        code, title, category, action = choices.get(draft.get('review_blocker') or status,
            ('review_required', '需要核对修改方案', 'review', '查看具体原因，补充缺少的信息或调整要求后重试。'))
    details = []
    if status == 'validation_failed' and transform.get('status') != 'pass':
        for field, label in (('changed', '数值或几何变化'), ('removed', '移除对象'), ('added', '新增对象')):
            items = data.get(field) or []
            if items:
                details.append({'kind': field, 'label': label, 'count': len(items),
                                'objects': [str(item.get('key', item.get('kind', '未知对象'))) for item in items[:12]]})
    return [{'code': code, 'title': title, 'category': category, 'reason': reason,
             'next_action': action, 'evidence': details}]


def check_results(draft, transform, font_issue, axis_issue, visual_issue, remaining, view_issue=False, addition_issue=False):
    """A checklist of observed evidence, independent of the first blocking reason."""
    data=draft.get('data_report') or {}
    transformed=bool(transform and transform['status']=='pass' and data.get('status') not in ('fail','changed','conflict'))
    changed=bool(data.get('changed') or data.get('removed') or data.get('status') in ('fail','changed','conflict'))
    layout=draft.get('layout') or {}
    return [
        {'name':'实际出图','status':'pass','reason':'候选图片和运行报告已生成。'},
        {'name':'图型转换样本','status':transform['status'] if transform else 'not_requested',
         'reason':transform.get('reason','以转换核对明细为准。') if transform else '本轮没有明确的受支持分布图转换要求。'},
        {'name':'原有绘图数据/几何','status':'explained' if transformed else 'mismatch' if changed else 'pass' if data else 'unverified',
         'reason':'图型转换的形状变化已由完整样本核对解释。' if transformed else '观察到原有对象数值、映射或移除差异。' if changed else '检测范围内未发现原有绘图数值变化。' if data else '缺少运行比较结果。'},
        {'name':'布局','status':'conflict' if remaining and layout.get('status')=='conflict' else 'accepted' if layout.get('issues') and not remaining else layout.get('status','unverified'),
         'reason':f'发现 {len(remaining)} 项未接受的布局问题。' if remaining else '以布局明细及检测覆盖范围为准。'},
        {'name':'显示范围与可见性授权','status':'unmet' if view_issue else 'no_blocker','reason':'显示范围或可见性变化缺少明确要求。' if view_issue else '未发现未授权的显示范围变化。'},
        {'name':'新增图元授权','status':'unmet' if addition_issue else 'no_blocker','reason':'新增对象缺少对应的用户要求。' if addition_issue else '未发现未授权的新增对象；新增元素仍需审阅。'},
        {'name':'字体效果','status':'unverified' if font_issue else 'no_blocker','reason':font_issue or '未发现字体要求阻断项；实际字体请看导出字体报告。'},
        {'name':'坐标轴要求','status':'unmet' if axis_issue else 'no_blocker','reason':axis_issue or '本轮可识别的坐标范围要求未发现不满足项。'},
        {'name':'本轮需求验收','status':(draft.get('edit_contract') or {}).get('status','not_requested'),'reason':'以逐项需求的目标值和最终导出值为准；未覆盖要求需人工审阅。'},
        {'name':'实际图像效果','status':'unmet' if visual_issue else 'no_blocker','reason':visual_issue or '本轮图像效果检查未发现阻断项。'},
    ]
