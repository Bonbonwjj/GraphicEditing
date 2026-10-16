"""Local model settings; the API key lives in the system credential store."""
import json
import ipaddress
import os
from pathlib import Path
import tempfile
import time
from urllib.parse import urlparse
from urllib import request, error

import keyring

CONFIG_PATH = Path(__file__).resolve().parent / '.model-api.json'
KEYRING_SERVICE = 'Plot Forge model API'
KEYRING_ACCOUNT = 'local workspace'
DEFAULT_URL = 'http://10.254.1.138:8080/api/v1/chat/completions'
DEFAULT_MODEL = 'glm-5.3'
INTRANET_URL = os.environ.get('PLOT_FORGE_INTRANET_API_URL', '').strip()
INTRANET_MODEL = os.environ.get('PLOT_FORGE_INTRANET_MODEL', '').strip()
DEFAULT_MAX_OUTPUT_TOKENS = 16384
MAX_OUTPUT_TOKENS_LIMIT = 65536
_session_secret = None


def _encrypted_path():
    return CONFIG_PATH.with_name('.model-api-key.dpapi')


def _secret():
    if _session_secret:
        return _session_secret, 'session', False
    path = _encrypted_path()
    if path.is_symlink():
        raise ValueError('密钥文件不能是符号链接')
    if path.exists():
        if not path.stat().st_size:
            return None, 'none', False  # Cleared while the credential store was inaccessible.
        from windows_secret import transform
        try:
            return transform(path.read_bytes(), decrypt=True).decode('utf-8'), 'windows_encrypted', False
        except Exception as exc:
            raise ValueError('无法解密本机密钥，请在当前 Windows 用户下重新输入 API Key 保存') from exc
    try:
        return keyring.get_password(KEYRING_SERVICE, KEYRING_ACCOUNT), 'keychain', True
    except Exception:
        # Some Windows backends raise pywintypes.error instead of KeyringError.
        return None, 'none', False


def _store_secret(secret):
    global _session_secret
    if not _encrypted_path().exists():
        try:
            keyring.set_password(KEYRING_SERVICE, KEYRING_ACCOUNT, secret)
            _session_secret = None
            return
        except Exception as exc:
            if os.name != 'nt':
                raise ValueError('无法将 API Key 保存到系统钥匙串，请检查钥匙串是否解锁') from exc
    from windows_secret import transform
    try:
        encrypted = transform(secret.encode('utf-8'))
        descriptor, temporary = tempfile.mkstemp(prefix='.model-api-key-', suffix='.tmp', dir=CONFIG_PATH.parent)
        try:
            with os.fdopen(descriptor, 'wb') as output:
                output.write(encrypted)
            Path(temporary).replace(_encrypted_path())
            _session_secret = None
        finally:
            Path(temporary).unlink(missing_ok=True)
    except Exception:
        # Restricted Windows sessions may have neither a credential vault nor DPAPI.
        # Never fall back to a plaintext file.
        _session_secret = secret


def validate_max_output_tokens(value):
    if isinstance(value, bool) or not isinstance(value, int) or not 1024 <= value <= MAX_OUTPUT_TOKENS_LIMIT:
        raise ValueError('最大输出 token 须为 1024～65536 的整数；请按所选模型的实际支持上限填写')
    return value


def validate_url(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 2048:
        raise ValueError('请输入有效的 API 地址')
    value = value.strip()
    if any(char.isspace() for char in value):
        raise ValueError('API 地址不能包含空格或换行')
    try:
        parsed = urlparse(value)
        port = parsed.port
    except ValueError as exc:
        raise ValueError('API 地址格式或端口不正确') from exc
    if not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise ValueError('API 地址格式不正确')
    local_http = parsed.hostname.lower() == 'localhost'
    try:
        address = ipaddress.ip_address(parsed.hostname)
        local_http = address.is_loopback or any(address in network for network in (
            ipaddress.ip_network('10.0.0.0/8'), ipaddress.ip_network('172.16.0.0/12'),
            ipaddress.ip_network('192.168.0.0/16'), ipaddress.ip_network('fc00::/7')))
    except ValueError:
        pass
    if parsed.scheme != 'https' and not (parsed.scheme == 'http' and (local_http or value == INTRANET_URL)):
        raise ValueError('公网 API 地址需使用 HTTPS；本机及内网 IP 可直接使用 HTTP')
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
    secret, source, keyring_available = _secret()
    key = secret or os.environ.get('OPENAI_API_KEY', '')
    url = saved.get('api_url') or os.environ.get('LLM_API_URL') or DEFAULT_URL
    model = saved.get('model') or os.environ.get('LLM_MODEL') or DEFAULT_MODEL
    vision = saved.get('vision_enabled', os.environ.get('CHAT_MODEL_VISION') == '1')
    max_output_tokens = validate_max_output_tokens(saved.get('max_output_tokens', DEFAULT_MAX_OUTPUT_TOKENS))
    return {'api_key': key, 'api_url': url, 'model': model,
            'key_source': source if secret else 'environment' if key else 'none',
            'keyring_available': keyring_available, 'vision_enabled': bool(vision),
            'max_output_tokens': max_output_tokens}


def public():
    settings = effective()
    return {'api_url': settings['api_url'], 'model': settings['model'],
            'key_configured': bool(settings['api_key']), 'key_source': settings['key_source'],
            'storage': 'Windows 用户加密 (DPAPI)' if settings['key_source'] == 'windows_encrypted' else 'Windows Credential Manager' if os.name == 'nt' else 'macOS Keychain', 'keyring_available': settings['keyring_available'],
            'vision_enabled': settings['vision_enabled'],
            'max_output_tokens': settings['max_output_tokens'],
            'intranet_preset': {'api_url': INTRANET_URL or DEFAULT_URL,
                               'model': INTRANET_MODEL or DEFAULT_MODEL}}


def _write_preferences(api_url, model, vision_enabled, max_output_tokens):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='.model-api-', suffix='.tmp', dir=CONFIG_PATH.parent)
    try:
        if hasattr(os, "fchmod"):
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
        old_secret, _, _ = _secret()
    except ValueError:
        if not supplied:
            raise
        old_secret = None
    if not supplied and not old_secret:
        raise ValueError('首次保存时请输入 API Key')
    if supplied:
        _store_secret(supplied)
    try:
        _write_preferences(api_url, model, vision_enabled, max_output_tokens)
    except Exception:
        if supplied:
            if old_secret:
                _store_secret(old_secret)
            else:
                if _encrypted_path().exists():
                    _encrypted_path().unlink()
                else:
                    keyring.delete_password(KEYRING_SERVICE, KEYRING_ACCOUNT)
        raise
    return public()


def clear():
    global _session_secret
    try:
        if keyring.get_password(KEYRING_SERVICE, KEYRING_ACCOUNT):
            keyring.delete_password(KEYRING_SERVICE, KEYRING_ACCOUNT)
    except Exception as exc:
        if not _encrypted_path().exists() and not _session_secret:
            raise ValueError('系统凭据库暂不可用，尚未完成清除；请重试') from exc
        # Prevent a previous credential from reappearing when the store recovers.
        _encrypted_path().write_bytes(b'')
    else:
        _encrypted_path().unlink(missing_ok=True)
    _session_secret = None
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
        raw = exc.read(4096).decode('utf-8', errors='replace')
        try:
            detail = json.loads(raw)
            if isinstance(detail, dict):
                detail = detail.get('error') or detail.get('message') or detail.get('detail') or detail.get('reason') or detail
            if isinstance(detail, dict):
                detail = detail.get('message') or detail.get('detail') or detail
            detail = str(detail)
        except (ValueError, TypeError):
            detail = raw
        detail = ' '.join(detail.replace(settings['api_key'], '[已隐藏密钥]').split())[:400]
        hint = {401: '密钥未通过鉴权', 403: '当前密钥或网络没有访问权限',
                404: '接口或所填模型未找到（也可能未向当前密钥开放）',
                429: '调用额度或频率受限'}.get(exc.code, '模型服务返回错误')
        models = []
        if exc.code == 404 and url.endswith('/chat/completions'):
            models_request = request.Request(url[:-len('/chat/completions')] + '/models',
                headers={'Authorization': 'Bearer ' + settings['api_key']})
            try:
                with request.urlopen(models_request, timeout=10) as stream:
                    listing = json.load(stream)
                models = [item['id'] for item in listing.get('data', [])
                          if isinstance(item, dict) and isinstance(item.get('id'), str)][:20]
            except (OSError, ValueError, TypeError, AttributeError):
                pass
        suffix = ('；当前可见模型：' + ', '.join(models)) if models else ''
        raise ValueError(f'连接失败：HTTP {exc.code}，{hint}。服务端说明：{detail or "无"}{suffix}') from exc
    except (error.URLError, TimeoutError) as exc:
        raise ValueError('无法连接模型服务；请检查 API 地址和网络') from exc
    if not isinstance(result, dict) or not result.get('choices'):
        raise ValueError('模型服务未返回兼容的 Chat Completions 响应')
    return {'connected': True, 'model': settings['model'], 'elapsed_ms': round((time.monotonic()-started)*1000)}
