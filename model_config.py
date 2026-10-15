"""Local model settings; the API key lives in the macOS Keychain."""
import json
import os
from pathlib import Path
import tempfile
import time
from urllib.parse import urlparse
from urllib import request, error

import keyring
from keyring.errors import KeyringError

CONFIG_PATH = Path(__file__).resolve().parent / '.model-api.json'
KEYRING_SERVICE = 'Plot Forge model API'
KEYRING_ACCOUNT = 'local workspace'
DEFAULT_URL = 'https://api.siliconflow.cn/v1/chat/completions'
DEFAULT_MODEL = 'Qwen/Qwen3.5-4B'
INTRANET_URL = os.environ.get('PLOT_FORGE_INTRANET_API_URL', '').strip()
INTRANET_MODEL = os.environ.get('PLOT_FORGE_INTRANET_MODEL', '').strip()
DEFAULT_MAX_OUTPUT_TOKENS = 16384
MAX_OUTPUT_TOKENS_LIMIT = 65536


def validate_max_output_tokens(value):
    if isinstance(value, bool) or not isinstance(value, int) or not 1024 <= value <= MAX_OUTPUT_TOKENS_LIMIT:
        raise ValueError('最大输出 token 须为 1024～65536 的整数；请按所选模型的实际支持上限填写')
    return value


def validate_url(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 2048:
        raise ValueError('请输入有效的 API 地址')
    value = value.strip()
    parsed = urlparse(value)
    saved_url = _preferences().get('api_url')
    if parsed.scheme != 'https' and not (parsed.scheme == 'http' and (parsed.hostname in ('127.0.0.1', 'localhost') or (INTRANET_URL and value == INTRANET_URL) or value == saved_url)):
        raise ValueError('API 地址需使用 HTTPS；内网 HTTP 地址请先设置 PLOT_FORGE_INTRANET_API_URL')
    if not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise ValueError('API 地址格式不正确')
    return value


def _preferences():
    if not CONFIG_PATH.exists():
        return {}
    if CONFIG_PATH.is_symlink():
        raise ValueError('模型配置文件不能是符号链接')
    value = json.loads(CONFIG_PATH.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError('模型配置文件格式不正确')
    return value


def effective():
    saved = _preferences()
    try:
        secret = keyring.get_password(KEYRING_SERVICE, KEYRING_ACCOUNT)
        keyring_available = True
    except KeyringError:
        secret = None
        keyring_available = False
    key = secret or os.environ.get('OPENAI_API_KEY', '')
    url = saved.get('api_url') or os.environ.get('LLM_API_URL') or DEFAULT_URL
    model = saved.get('model') or os.environ.get('LLM_MODEL') or DEFAULT_MODEL
    vision = saved.get('vision_enabled', os.environ.get('CHAT_MODEL_VISION') == '1')
    max_output_tokens = validate_max_output_tokens(saved.get('max_output_tokens', DEFAULT_MAX_OUTPUT_TOKENS))
    return {'api_key': key, 'api_url': url, 'model': model,
            'key_source': 'keychain' if secret else 'environment' if key else 'none',
            'keyring_available': keyring_available, 'vision_enabled': bool(vision),
            'max_output_tokens': max_output_tokens}


def public():
    settings = effective()
    return {'api_url': settings['api_url'], 'model': settings['model'],
            'key_configured': bool(settings['api_key']), 'key_source': settings['key_source'],
            'storage': 'macOS Keychain', 'keyring_available': settings['keyring_available'],
            'vision_enabled': settings['vision_enabled'],
            'max_output_tokens': settings['max_output_tokens'],
            'intranet_preset': {'api_url': INTRANET_URL, 'model': INTRANET_MODEL} if INTRANET_URL else None}


def _write_preferences(api_url, model, vision_enabled, max_output_tokens):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='.model-api-', suffix='.tmp', dir=CONFIG_PATH.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, 'w', encoding='utf-8') as output:
            json.dump({'api_url': api_url, 'model': model, 'vision_enabled': vision_enabled,
                       'max_output_tokens': max_output_tokens}, output, ensure_ascii=False)
        Path(temporary).replace(CONFIG_PATH)
    finally:
        Path(temporary).unlink(missing_ok=True)


def save(body):
    if not isinstance(body, dict):
        raise ValueError('模型配置格式不正确')
    api_url = validate_url(body.get('api_url'))
    model = body.get('model')
    if not isinstance(model, str) or not model.strip() or len(model) > 200:
        raise ValueError('请输入模型名称')
    model = model.strip()
    vision_enabled = body.get('vision_enabled', False)
    if not isinstance(vision_enabled, bool):
        raise ValueError('视觉功能配置格式不正确')
    max_output_tokens = validate_max_output_tokens(body.get('max_output_tokens', DEFAULT_MAX_OUTPUT_TOKENS))
    supplied = body.get('api_key', '')
    if not isinstance(supplied, str) or len(supplied) > 4096:
        raise ValueError('API Key 格式不正确')
    supplied = supplied.strip()
    try:
        old_secret = keyring.get_password(KEYRING_SERVICE, KEYRING_ACCOUNT)
    except KeyringError as exc:
        raise ValueError('本机钥匙串当前不可用；请从普通终端启动工作台后重试') from exc
    if not supplied and not old_secret:
        raise ValueError('首次保存时请输入 API Key')
    if supplied:
        try:
            keyring.set_password(KEYRING_SERVICE, KEYRING_ACCOUNT, supplied)
        except KeyringError as exc:
            raise ValueError('无法将 API Key 保存到本机钥匙串') from exc
    try:
        _write_preferences(api_url, model, vision_enabled, max_output_tokens)
    except Exception:
        if supplied:
            if old_secret:
                keyring.set_password(KEYRING_SERVICE, KEYRING_ACCOUNT, old_secret)
            else:
                keyring.delete_password(KEYRING_SERVICE, KEYRING_ACCOUNT)
        raise
    return public()


def clear():
    try:
        if keyring.get_password(KEYRING_SERVICE, KEYRING_ACCOUNT):
            keyring.delete_password(KEYRING_SERVICE, KEYRING_ACCOUNT)
    except KeyringError as exc:
        raise ValueError('本机钥匙串当前不可用，尚未清除密钥') from exc
    CONFIG_PATH.unlink(missing_ok=True)
    return public()


def test_connection():
    settings = effective()
    if not settings['api_key']:
        raise ValueError('请先保存 API Key')
    url = validate_url(settings['api_url'])
    payload = {'model': settings['model'], 'messages': [{'role': 'user', 'content': 'Reply OK.'}], 'max_tokens': 8}
    req = request.Request(url, data=json.dumps(payload).encode('utf-8'), method='POST', headers={
        'Authorization': 'Bearer ' + settings['api_key'], 'Content-Type': 'application/json'})
    started = time.monotonic()
    try:
        with request.urlopen(req, timeout=20) as stream:
            result = json.load(stream)
    except error.HTTPError as exc:
        raise ValueError(f'连接失败：HTTP {exc.code}；请检查 API Key、地址和模型名称') from exc
    except (error.URLError, TimeoutError) as exc:
        raise ValueError('无法连接模型服务；请检查 API 地址和网络') from exc
    if not isinstance(result, dict) or not result.get('choices'):
        raise ValueError('模型服务未返回兼容的 Chat Completions 响应')
    return {'connected': True, 'model': settings['model'], 'elapsed_ms': round((time.monotonic()-started)*1000)}
