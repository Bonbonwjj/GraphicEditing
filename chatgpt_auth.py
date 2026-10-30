"""Official ChatGPT plan OAuth. Tokens never enter the browser or project tree."""
import base64
import hashlib
import json
import secrets
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlencode, urlparse, parse_qs
from urllib import request, error

import keyring

AUTH = 'https://auth.openai.com'
RESOURCE = 'https://api.openai.com/v1'
SCOPE = 'openid profile email offline_access resource.invoke chatgpt.tokens.use.direct'
SERVICE = 'Plot Forge ChatGPT OAuth'
LOCK = threading.RLock()
_record = None
_storage = 'session'
_pending = None
_status = ''
_retry_registration = None  # Issued client ID only; never an unverified identity/token.


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('为保护凭据，已阻止模型服务重定向。')


def secure_open(req, timeout=30):
    return request.build_opener(NoRedirect()).open(req, timeout=timeout)


def _account():
    from model_config import CONFIG_PATH
    return hashlib.sha256(str(CONFIG_PATH.resolve().parent).encode()).hexdigest()


def _vault():
    """Do not accept keyrings.alt/plaintext or arbitrary fallback backends."""
    backend = keyring.get_keyring()
    allowed = {'keyring.backends.secretservice', 'keyring.backends.macos',
               'keyring.backends.os_x', 'keyring.backends.windows', 'keyring.backends.libsecret'}
    candidates = backend.backends if type(backend).__module__.lower() == 'keyring.backends.chainer' else [backend]
    for candidate in candidates:
        if type(candidate).__module__.lower() in allowed:
            return candidate
    raise ValueError('No approved operating-system credential vault is available')


def read_record():
    global _record, _storage
    if _record is None:
        try:
            from model_config import CONFIG_PATH
            tombstone = CONFIG_PATH.with_name('.chatgpt-disconnected')
            value = None if tombstone.exists() else _vault().get_password(SERVICE, _account())
            _record = json.loads(value) if value else {}
            _storage = 'keyring'
        except Exception:
            _record, _storage = {}, 'session'
    return dict(_record)


def save_record(value):
    global _record, _storage
    # Memory remains authoritative if the vault becomes unavailable. No plaintext fallback.
    _record = dict(value)
    from model_config import CONFIG_PATH
    tombstone = CONFIG_PATH.with_name('.chatgpt-disconnected')
    try:
        _vault().set_password(SERVICE, _account(), json.dumps(value))
        _storage = 'keyring'
        tombstone.unlink(missing_ok=True)
    except Exception:
        _storage = 'session'
        # Never resurrect a stale vault token after logout/rotation failure.
        tombstone.touch(mode=0o600, exist_ok=True)


def host_id():
    from model_config import CONFIG_PATH
    path = CONFIG_PATH.with_name('.chatgpt-host.json')
    if path.is_symlink():
        raise ValueError('ChatGPT 主机标识文件不能为符号链接')
    if path.exists():
        value = json.loads(path.read_text())['host_id']
        uuid.UUID(value.removeprefix('urn:uuid:'))
        return value
    value = 'urn:uuid:' + str(uuid.uuid4())
    with path.open('x', encoding='utf-8') as stream:
        import os
        if hasattr(os, 'fchmod'):
            os.fchmod(stream.fileno(), 0o600)
        json.dump({'host_id': value}, stream)
    return value


def public():
    with LOCK:
        record = read_record()
        email = record.get('email', '')
        label = email[:1] + '***@' + email.split('@')[-1] if '@' in email else 'ChatGPT 账户'
        connected = bool(record.get('access_token'))
        return {'connected': connected, 'sharing': connected and 'chatgpt.tokens.use.direct' in record.get('scope', '').split(),
                'account_label': label if record.get('sub') else '', 'storage': _storage,
                'pending': bool(_pending), 'message': _status}


def _form(url, fields, empty_ok=False):
    if urlparse(url).scheme != 'https' or urlparse(url).netloc != 'auth.openai.com':
        raise ValueError('拒绝向非 OpenAI 登录服务发送凭据')
    req = request.Request(url, data=urlencode(fields).encode(),
                          headers={'Content-Type': 'application/x-www-form-urlencoded'}, method='POST')
    try:
        with secure_open(req) as response:
            data = response.read(1_000_000)
            return {} if not data and empty_ok else json.loads(data)
    except error.HTTPError as exc:
        # Never display provider bodies: they can echo credentials or user information.
        raise ValueError(f'ChatGPT 授权请求失败（HTTP {exc.code}），请重新登录或检查账户权限。') from None
    except (OSError, ValueError) as exc:
        if isinstance(exc, ValueError) and str(exc).startswith('ChatGPT'):
            raise
        raise ValueError('ChatGPT 授权服务暂时不可用，请稍后重试。') from None


def verify_identity(token, client_id, nonce=None):
    import jwt
    # Fetch JWKS with redirects disabled; do not trust jku or alg supplied by a JWT.
    with secure_open(request.Request(AUTH + '/.well-known/jwks.json')) as response:
        keys = json.loads(response.read(1_000_000))['keys']
    header = jwt.get_unverified_header(token)
    if header.get('alg') != 'RS256':
        raise ValueError('Unsupported ID token algorithm')
    matches = [key for key in keys if key.get('kid') == header.get('kid') and key.get('kty') == 'RSA']
    if len(matches) != 1:
        raise ValueError('Unknown signing key')
    identity = jwt.decode(token, jwt.PyJWK.from_dict(matches[0]).key, algorithms=['RS256'],
                          audience=client_id, issuer=AUTH,
                          options={'require': ['exp', 'iat', 'iss', 'aud', 'sub'] + (['nonce'] if nonce is not None else [])})
    if nonce is not None and not secrets.compare_digest(str(identity['nonce']), nonce):
        raise ValueError('Invalid nonce')
    return identity


def finish(query):
    global _pending, _status, _retry_registration
    with LOCK:
        pending = _pending
        values = parse_qs(query, keep_blank_values=True)
        if any(len(v) != 1 for v in values.values()):
            raise ValueError('登录回调参数重复')
        values = {k: v[0] for k, v in values.items()}
        if not pending or time.monotonic() > pending['expires'] or not secrets.compare_digest(values.get('state', ''), pending['state']):
            raise ValueError('登录回调已过期或校验失败，请回到 Plot Forge 重新登录。')
        _pending = None  # one-time consumption before network work
        try:
            if values.get('error'):
                raise ValueError('你取消了 ChatGPT 授权。')
            client_id = values.get('client_id') or pending.get('client_id')
            if not client_id or client_id == 'dynamic_agent_client' or len(client_id) > 256:
                raise ValueError('OpenAI 未返回有效的应用注册标识。')
            if pending.get('client_id') and client_id != pending['client_id']:
                raise ValueError('登录返回的应用标识不匹配。')
            if not values.get('code'):
                raise ValueError('登录回调缺少授权码。')
            if not pending.get('client_id'):
                _retry_registration = client_id
            tokens = _form(AUTH + '/api/accounts/oauth/token', {
                'grant_type': 'authorization_code', 'client_id': client_id, 'code': values['code'],
                'code_verifier': pending['verifier'], 'redirect_uri': pending['redirect_uri'], 'resource': RESOURCE})
            identity = verify_identity(tokens['id_token'], client_id, pending['nonce'])
            if pending.get('expected_sub') and identity['sub'] != pending['expected_sub']:
                raise ValueError('登录账户发生变化，请使用“连接其他账户”。')
            save_record({'client_id': client_id, 'sub': identity['sub'], 'email': identity.get('email', ''),
                         'access_token': tokens.get('access_token', ''), 'refresh_token': tokens.get('refresh_token', ''),
                         'id_token': tokens['id_token'], 'scope': tokens.get('scope', ''),
                         'expires_at': time.time() + float(tokens.get('expires_in', 300))})
            _retry_registration = None
            _status = '登录完成。请返回 Plot Forge 选择模型并设置代码发送权限。'
        except Exception:
            _status = '登录未完成或身份验证失败，请回到 Plot Forge 重试；原连接保持不变。'
            raise ValueError(_status) from None
        finally:
            pending['timer'].cancel()
            threading.Thread(target=pending['server'].shutdown, daemon=True).start()
        return _status


def begin(new_account=False):
    global _pending, _status
    with LOCK:
        # Fail before opening a browser if the verification dependency is missing.
        try:
            import jwt  # noqa: F401
        except ImportError:
            raise ValueError('请通过启动器安装更新后的依赖（PyJWT[crypto]），然后重试。') from None
        if _pending:
            raise ValueError('已有登录窗口等待完成，请先完成或等待五分钟后重试。')
        installation_id = host_id()
        old = {} if new_account else read_record()
        expected_sub = old.get('sub')
        if not old.get('client_id') and _retry_registration:
            old['client_id'] = _retry_registration
        verifier, nonce, state = secrets.token_urlsafe(48), secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        class Callback(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass  # OAuth codes, state, and query strings must never be logged.
            def do_GET(self):
                parsed = urlparse(self.path)
                if parsed.path != '/auth/callback' or self.headers.get('Host') != f'127.0.0.1:{self.server.server_port}':
                    self.send_error(404)
                    return
                try:
                    message = finish(parsed.query)
                    status = 200
                except Exception:
                    message, status = '登录未完成。请回到 Plot Forge 查看状态并重试。', 400
                body = message.encode('utf-8')
                self.send_response(status)
                self.send_header('Content-Type', 'text/plain; charset=utf-8')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Referrer-Policy', 'no-referrer')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        server = ThreadingHTTPServer(('127.0.0.1', 0), Callback)
        redirect = f'http://127.0.0.1:{server.server_port}/auth/callback'
        def expire():
            global _pending, _status
            with LOCK:
                if _pending and _pending['state'] == state:
                    _pending = None
                    _status = '登录已超时，请重新连接。'
            server.shutdown()
        timer = threading.Timer(300, expire)
        timer.daemon = True
        _pending = {'state': state, 'nonce': nonce, 'verifier': verifier, 'redirect_uri': redirect,
                    'expected_sub': expected_sub,
                    'expires': time.monotonic() + 300, 'client_id': old.get('client_id'), 'server': server, 'timer': timer}
        params = {'client_id': old.get('client_id') or 'dynamic_agent_client', 'ext_agent_host_id': installation_id,
                  'response_type': 'code', 'redirect_uri': redirect, 'scope': SCOPE, 'resource': RESOURCE,
                  'state': state, 'nonce': nonce, 'code_challenge_method': 'S256',
                  'code_challenge': base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()}
        if not old.get('client_id'):
            params['agent_name_hint'] = 'Plot Forge'
        # Do not expose id_token_hint to the app browser. Account chooser is intentional.
        _status = '请在 OpenAI 官方页面完成登录。'
        def serve():
            try:
                server.serve_forever(poll_interval=.2)
            finally:
                server.server_close()
        threading.Thread(target=serve, daemon=True).start()
        timer.start()
        return {'url': AUTH + '/api/accounts/authorize?' + urlencode(params)}


def access_token():
    with LOCK:
        record = read_record()
        if 'chatgpt.tokens.use.direct' not in record.get('scope', '').split() or not record.get('access_token'):
            raise ValueError('请先登录 ChatGPT 并授权使用订阅额度。')
        if record.get('expires_at', 0) < time.time() + 60:
            if not record.get('refresh_token'):
                raise ValueError('ChatGPT 登录已过期，请重新登录。')
            tokens = _form(AUTH + '/api/accounts/oauth/token', {'grant_type': 'refresh_token',
                'client_id': record['client_id'], 'refresh_token': record['refresh_token'], 'resource': RESOURCE})
            if tokens.get('id_token'):
                try:
                    identity = verify_identity(tokens['id_token'], record['client_id'])
                    if identity['sub'] != record['sub']:
                        raise ValueError('Different account')
                except Exception:
                    raise ValueError('刷新后的账户身份校验失败，请重新登录；未替换原凭据。') from None
            for key in ('access_token', 'refresh_token', 'id_token', 'scope'):
                if key in tokens:
                    record[key] = tokens[key]
            if not tokens.get('access_token'):
                raise ValueError('刷新未返回有效凭据，请重新登录。')
            record['expires_at'] = time.time() + float(tokens.get('expires_in', 300))
            save_record(record)
        if 'chatgpt.tokens.use.direct' not in record.get('scope', '').split():
            raise ValueError('当前连接未授权使用 ChatGPT 订阅额度。')
        return record['access_token']


def disconnect():
    global _status, _pending, _retry_registration
    with LOCK:
        _retry_registration = None
        if _pending:
            pending, _pending = _pending, None
            pending['timer'].cancel()
            threading.Thread(target=pending['server'].shutdown, daemon=True).start()
        record = read_record()
        revoked = not bool(record.get('refresh_token'))
        if record.get('refresh_token'):
            try:
                with secure_open(request.Request(AUTH + '/.well-known/openid-configuration')) as response:
                    endpoint = json.loads(response.read(1_000_000))['revocation_endpoint']
                _form(endpoint, {'token': record['refresh_token'], 'token_type_hint': 'refresh_token',
                                 'client_id': record['client_id']}, empty_ok=True)
                revoked = True
            except Exception:
                pass
        save_record({k: v for k, v in record.items() if k in ('sub', 'email', 'client_id')})
        _status = '已退出 ChatGPT。' if revoked else '本机已退出；远端撤销未确认，请到 ChatGPT 设置中断开 Plot Forge。'
        if _storage == 'session':
            _status += '系统凭据库不可用，请同时在 ChatGPT 设置中撤销连接。'
        return public()
