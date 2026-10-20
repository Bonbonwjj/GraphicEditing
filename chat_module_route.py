"""Route explicit shared-edit requests to review, never write shared code in Chat."""


def module_handoff(context, response):
    requested = response.get('shared_module_path')
    if not requested:
        return None
    path = str(requested).removeprefix('lib/')
    module = next((m for m in context.get('shared_module_catalog', []) if m['path'] == path), None)
    if not module:
        raise ValueError('模型要求修改的共享模块不在本项目可编辑目录中。')
    if response.get('status') == 'candidate':
        raise ValueError('共享模块修改需单独生成共享候选，不能与单图候选混合应用。')
    charts = [item['chart'] for item in context.get('project_chart_catalog', [])]
    return {'module_id':module['id'], 'path':module['path'], 'chart':context['allowed_write_paths'][0].split('/')[-1][:-3],
            'prompt':context['user_message'], 'affected_charts':charts,
            'scope':'conservative_all', 'force_all':True,
            'notice':'共享函数可能影响下列全部项目图表。此为保守范围，尚未修改文件；进入模块编辑后须验证并单独应用。'}
