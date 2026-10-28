"""Keep existing workflow validation while adapting official ChatGPT Responses."""
import io
import json
import re
import time
from urllib import request, error

from chatgpt_auth import RESOURCE, secure_open


def guard_secrets(messages):
    def strings(value):
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for item in value.values():
                yield from strings(item)
        elif isinstance(value, (tuple, list)):
            for item in value:
                yield from strings(item)
    text = '\n'.join(strings(messages))
    patterns = (r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
                r'\bsk-[A-Za-z0-9_-]{24,}', r'\bgh[pousr]_[A-Za-z0-9]{25,}',
                r'(?i)(?:api[_-]?key|access[_-]?token|refresh[_-]?token|password)\s*[=:]\s*[\x22\x27][A-Za-z0-9_+/=-]{16,}')
    if any(re.search(pattern, text) for pattern in patterns):
        raise ValueError('发送内容疑似包含密钥或密码，已阻止发送。请先从代码中移除凭据。')


def _error(code):
    hints = {'subscription_sharing_usage_limit_exceeded': '订阅用量已达限制，请到 ChatGPT 设置 → Usage 查看。',
             'subscription_sharing_user_not_eligible': '当前账户或工作区尚无订阅共享权限。',
             'subscription_sharing_usage_unavailable': '暂时无法核对订阅额度，请稍后重试。',
             'subscription_sharing_unsupported_capability': '所选模型不支持本次请求的输入或功能。'}
    return hints.get(code, 'ChatGPT 请求未完成，请检查账户权限、网络或模型选择。')


def models():
    from chatgpt_auth import access_token
    req = request.Request(RESOURCE + '/models', headers={'Authorization': 'Bearer ' + access_token()})
    try:
        with secure_open(req) as response:
            value = json.loads(response.read(2_000_000))
        return [{'id': item['slug'], 'name': item.get('display_name', item['slug'])}
                for item in value.get('models', []) if item.get('visibility') == 'list' and isinstance(item.get('slug'), str)]
    except (OSError, ValueError, KeyError):
        raise ValueError('无法读取 ChatGPT 可用模型，请检查登录和订阅共享权限。') from None


def responses_payload(payload):
    instructions, inputs = [], []
    for message in payload['messages']:
        content = message.get('content', '')
        role = message.get('role', 'user')
        if role in ('system', 'developer'):
            instructions.append(content if isinstance(content, str) else json.dumps(content))
            continue
        if role not in ('user', 'assistant'):
            raise ValueError('不支持的对话消息类型')
        if isinstance(content, list):
            parts = []
            for part in content:
                if part.get('type') == 'text':
                    parts.append({'type': 'input_text' if role == 'user' else 'output_text', 'text': part['text']})
                elif part.get('type') == 'image_url' and role == 'user':
                    url = part['image_url']['url']
                    if not url.startswith('data:image/'):
                        raise ValueError('只允许发送已选中的本地图片')
                    parts.append({'type': 'input_image', 'image_url': url})
                else:
                    raise ValueError('不支持的消息内容')
            content = parts
        inputs.append({'role': role, 'content': content})
    return {'model': payload['model'], 'instructions': '\n\n'.join(instructions),
            'input': inputs, 'store': False, 'stream': True}


def read_responses(stream):
    chunks, size, received = [], 0, 0
    started = time.monotonic()
    while True:
        raw = stream.readline(2_000_001)
        if not raw:
            break
        received += len(raw)
        if len(raw) > 2_000_000 or received > 20_000_000 or time.monotonic() - started > 270:
            raise ValueError('ChatGPT 响应超出大小或时间限制。')
        if not raw.startswith(b'data:'):
            continue
        data = raw[5:].strip()
        if data == b'[DONE]':
            break
        event = json.loads(data)
        kind = event.get('type')
        if kind == 'response.output_text.delta':
            chunk = event.get('delta', '')
            size += len(chunk)
            if size > 1_000_000:
                raise ValueError('ChatGPT 输出过大，请缩小本轮任务。')
            chunks.append(chunk)
        elif kind == 'response.completed':
            if event.get('response', {}).get('status', 'completed') != 'completed':
                raise ValueError('ChatGPT 未完成响应')
            result = ''.join(chunks).strip()
            if not result:
                raise ValueError('ChatGPT 未返回可用内容。')
            return result
        elif kind in ('response.failed', 'response.incomplete', 'error'):
            detail = event.get('response', {}).get('error') or event.get('error') or {}
            raise ValueError(_error(detail.get('code') if isinstance(detail, dict) else None))
    raise ValueError('ChatGPT 流在完成前中断，未将半成品应用到工程。')


def open_completion(req, timeout, settings, probe=False):
    if settings.get('provider') != 'chatgpt':
        return request.urlopen(req, timeout=timeout)
    if not probe and not settings.get('allow_code_upload', False):
        raise ValueError('代码外发尚未授权。请在 API 配置中确认发送相关源码和绘图数据；需完全离线时请选择本地模型。')
    payload = json.loads(req.data)
    guard_secrets(payload['messages'])
    from chatgpt_auth import access_token
    outgoing = request.Request(RESOURCE + '/responses', data=json.dumps(responses_payload(payload)).encode(),
        headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + access_token()}, method='POST')
    try:
        with secure_open(outgoing, timeout=timeout) as stream:
            from chat_cancellation import watching
            with watching(stream):
                text = read_responses(stream)
    except error.HTTPError as exc:
        try:
            body = json.loads(exc.read(4096))
            code = (body.get('error') or {}).get('code')
        except Exception:
            code = None
        raise ValueError(f'ChatGPT HTTP {exc.code}：' + _error(code)) from None
    except (OSError, TimeoutError):
        raise ValueError('ChatGPT 连接中断或超时，本轮未应用修改。') from None
    if payload.get('stream'):
        event = {'choices': [{'delta': {'content': text}, 'finish_reason': 'stop'}]}
        return io.BytesIO(b'data: ' + json.dumps(event).encode() + b'\n\ndata: [DONE]\n\n')
    return io.BytesIO(json.dumps({'choices': [{'message': {'content': text}, 'finish_reason': 'stop'}]}).encode())
