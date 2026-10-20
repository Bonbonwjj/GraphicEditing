"""Shared, cached API health; HEAD heartbeats do not request model inference."""
import hashlib
import json
import threading
import time
from urllib import request,error

INTERVAL=20
FUNCTIONAL_TTL=120


def _identity(settings):
    return hashlib.sha256(json.dumps([settings.get('api_url'),settings.get('model'),settings.get('api_key')]).encode()).hexdigest()


def _transport(settings):
    req=request.Request(settings['api_url'],method='HEAD',headers={'Authorization':'Bearer '+settings['api_key']})
    try:
        with request.urlopen(req,timeout=5):pass
    except error.HTTPError as exc:
        # HEAD need not be supported by a chat-completions route.
        if exc.code in (401,403,429) or exc.code>=500:
            messages={401:'API密钥未通过鉴权',403:'API访问被拒绝',429:'API额度或请求频率受限'}
            return False,messages.get(exc.code,'模型服务暂不可用')+f'（HTTP {exc.code}）'
    except (OSError,TimeoutError):
        return False,'无法连接模型服务，请检查网络、VPN或服务地址。'
    return True,''


class ConnectionMonitor:
    def __init__(self,clock=time.time):
        self.clock=clock;self.lock=threading.Lock();self.key=None;self.token=None
        self.value={};self.next_check=0;self.observed_at=0;self.needs_functional=True;self.event_version=0

    def reset(self,settings):
        key=_identity(settings)
        if self.key!=key:
            self.key=key;self.token=None;self.next_check=0;self.observed_at=0;self.needs_functional=True;self.event_version=0
            self.value={'status':'unknown','checked_at':None,'functional_checked_at':None,'message':'尚未检测连接'}
        return key

    def report(self,settings,connected,message=''):
        with self.lock:
            self.reset(settings);now=self.clock();self.observed_at=now;self.event_version+=1
            self.value.update(status='connected' if connected else 'error',message='模型请求成功' if connected else message,
                              checked_at=now,functional_checked_at=now if connected else None)
            self.next_check=now+INTERVAL;self.needs_functional=False

    def status(self,settings):
        with self.lock:
            key=self.reset(settings)
            if not settings.get('api_key'):
                return {'status':'unconfigured','checking':False,'message':'尚未配置API Key','checked_at':None,'functional_checked_at':None,'interval_seconds':INTERVAL}
            now=self.clock()
            if now>=self.next_check and self.token is None:
                token=object();self.token=token;self.next_check=now+INTERVAL
                threading.Thread(target=self._check,args=(dict(settings),key,token,now),daemon=True).start()
            result=dict(self.value,checking=self.token is not None,interval_seconds=INTERVAL)
            if result['status']=='connected' and now-(result['functional_checked_at'] or 0)>FUNCTIONAL_TTL:
                result.update(status='reachable',message='服务可达；最近一次模型功能验证已超过2分钟，可手动重新测试。')
            if result['status']=='unknown' and result['checking']:result['status']='checking'
            if result.get('checked_at') and now-result['checked_at']>INTERVAL+15:
                result.update(status='stale',message='连接状态已过期，正在重新检测。')
            return result

    def _check(self,settings,key,token,started):
        try:
            with self.lock:
                if self.key!=key or self.token is not token:return
                version=self.event_version
            reachable,message=_transport(settings)
            with self.lock:
                if self.key!=key or self.token is not token or version!=self.event_version:return
                previous=self.value['status'];functional=self.value.get('functional_checked_at');needs_functional=self.needs_functional
            # One actual tiny request on first check or recovery. Regular HEAD
            # polls never generate text or send chart/project content.
            if reachable and needs_functional:
                from model_config import test_connection
                try:test_connection()
                except (ValueError,OSError):pass # test_connection records a sanitized failure
            else:
                with self.lock:
                    if self.key!=key or self.token is not token or version!=self.event_version:return
                    if not reachable:
                        self.needs_functional=True
                        self.value.update(status='error',message=message,functional_checked_at=None)
                    elif previous!='error':
                        self.value.update(status='connected' if functional and self.clock()-functional<=FUNCTIONAL_TTL else 'reachable',message='服务可达')
                    self.value['checked_at']=self.clock()
        except Exception:
            with self.lock:
                if self.key==key and self.token is token and self.observed_at<=started:
                    self.value.update(status='error',message='连接检测未完成，请重新测试。',checked_at=self.clock())
        finally:
            with self.lock:
                if self.key==key and self.token is token:
                    self.token=None;self.next_check=self.clock()+INTERVAL


_monitor=ConnectionMonitor()


def connection_status():
    from model_config import effective
    return _monitor.status(effective())


def report_result(settings,connected,message=''):
    # Ignore late results for superseded credentials/configuration.
    try:
        from model_config import effective
        if _identity(settings)!=_identity(effective()):return
        _monitor.report(settings,connected,message)
    except Exception:
        pass # Status reporting must never break a real model request.
