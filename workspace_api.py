"""Local project preparation and official ChatGPT login HTTP endpoints."""
import json
import os
import subprocess
import sys


def handle(handler, path, projects, preview_lock=None):
    if not path.startswith(('/api/workspace/', '/api/chatgpt/')):
        return False
    method = handler.command
    body = {}
    if method == 'POST':
        handler.check_local_json()
        body = handler.body_json()
        if not isinstance(body, dict):
            raise ValueError('请求必须为 JSON 对象')
    if path.startswith('/api/chatgpt/'):
        import chatgpt_auth
        if path == '/api/chatgpt/status' and method == 'GET':
            handler.json_response(chatgpt_auth.public())
        elif path == '/api/chatgpt/connect' and method == 'POST':
            handler.json_response(chatgpt_auth.begin(body.get('new_account') is True))
        elif path == '/api/chatgpt/disconnect' and method == 'POST':
            handler.json_response(chatgpt_auth.disconnect())
        elif path == '/api/chatgpt/models' and method == 'GET':
            from model_transport import models
            handler.json_response({'models': models()})
        else:
            handler.json_response({'error': 'Unknown ChatGPT route'}, 404)
        return True
    import project_preparation as prep
    if path == '/api/workspace/projects' and method == 'GET':
        from private_projects import names
        private = names(projects.parent)
        handler.json_response({'projects': [{**prep.status(p), 'private': p.name in private}
            for p in sorted(projects.iterdir()) if not p.name.startswith('.') and (p/'project.json').is_file()]})
    elif path == '/api/workspace/pick-folder' and method == 'POST':
        from folder_picker import choose_folder
        handler.json_response({'path': choose_folder()})
    elif path == '/api/workspace/inspect' and method == 'POST':
        handler.json_response(prep.inspect(body.get('source', '')))
    elif path == '/api/workspace/open' and method == 'POST':
        handler.json_response(prep.open_project(projects, body.get('source', ''), body.get('name', ''), body.get('allow_local_execution') is True))
    else:
        parts = path.split('/')
        if len(parts) != 6 or parts[3] != 'projects':
            handler.json_response({'error':'Unknown workspace route'}, 404)
            return True
        project = prep.project_path(projects, parts[4])
        action = parts[5]
        if method == 'GET' and action == 'status':
            handler.json_response(prep.status(project))
        elif method == 'POST' and action == 'rename':
            handler.json_response(prep.rename_project(project, body.get('name')))
        elif method == 'GET' and action == 'analysis-options':
            from analysis_scope import options
            handler.json_response(options(project))
        elif method == 'POST' and action == 'analysis-preview':
            from analysis_scope import build, public
            handler.json_response(public(build(project, body.get('scope', ''))))
        elif method == 'POST' and action == 'batch-preview':
            from project_batch import plan, public_plan
            handler.json_response(public_plan(plan(project)))
        elif method == 'POST' and action == 'native-prepare':
            from native_project import start
            handler.json_response(start(project, body.get('consent') is True, body.get('environment_mode','default')))
        elif method == 'POST' and action == 'universal-prepare':
            from universal_project import start
            handler.json_response(start(project, body.get('consent') is True))
        elif method == 'POST' and action == 'batch-analyze':
            from project_batch import start
            handler.json_response(start(project, body.get('consent') is True, body.get('confirmation_token')))
        elif method == 'POST' and action == 'batch-finalize':
            from project_batch import start_finalize
            handler.json_response(start_finalize(project, body.get('bundle_root', ''), body.get('consent') is True))
        elif method == 'GET' and action == 'batch.zip':
            from project_batch import archive
            from chat_harness import lock
            with prep.LOCK, lock(project):
                if str(project) in prep.RUNNING:
                    raise ValueError('工程任务正在运行，完成后可下载全部批次方案')
                handler.bytes_response(archive(project), 'application/zip', 'batch.zip')
        elif method == 'GET' and action == 'delete-preview':
            from project_deletion import deletion_info
            handler.json_response(deletion_info(projects, parts[4]))
        elif method == 'POST' and action == 'delete':
            from project_deletion import delete_project
            handler.json_response(delete_project(projects, parts[4], body.get('confirm_name'),
                                                 body.get('confirmation_token'), preview_lock))
        elif method == 'POST' and action == 'analyze':
            handler.json_response(prep.start_analysis(project, body.get('consent') is True,
                                                     body.get('scope'), body.get('confirmation_token')))
        elif method == 'POST' and action == 'finalize':
            handler.json_response(prep.start_finalize(project, body.get('bundle', ''), body.get('allow_local_execution') is True))
        elif method == 'GET' and action in ('prepare.zip', 'backup.zip'):
            from chat_harness import lock
            with lock(project):
                handler.bytes_response(prep.archive(project, action == 'prepare.zip'), 'application/zip', action)
        else:
            handler.json_response({'error':'Unknown workspace action'}, 404)
    return True
