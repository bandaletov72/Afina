"""Fixed-host GET-only Metrica adapter. No redirects, proxy env or live-by-default."""
import json
import re
import ssl
import time
import urllib.request
import urllib.error
from urllib.parse import urlencode
from metrica_core import MetricaError, counter_id, period_params
from network_adapter import valid_token, NoRedirect

MAX_BYTES=2*1024*1024
MAX_URL_BYTES=32768
BASE='https://api-metrika.yandex.net'

def validate_request(path,params):
    if type(params) is not dict:raise MetricaError('FORBIDDEN_REQUEST')
    if path=='/management/v1/counters':
        if set(params)!={'offset','per_page'} or type(params['offset']) is not int or not 1<=params['offset']<=100000 or type(params['per_page']) is not int or not 1<=params['per_page']<=1000:raise MetricaError('FORBIDDEN_REQUEST')
    elif type(path) is str and re.fullmatch(r'/management/v1/counter/[1-9][0-9]*',path):
        if params:raise MetricaError('FORBIDDEN_REQUEST')
    elif path=='/stat/v1/data':
        if set(params)!={'ids','date1','date2','metrics','accuracy','timezone'}:raise MetricaError('FORBIDDEN_REQUEST')
        try:
            expected=period_params({'dateFrom':params['date1'],'dateTo':params['date2']});expected['ids']=counter_id(params['ids'])
            if params!=expected:raise ValueError()
        except Exception:raise MetricaError('FORBIDDEN_REQUEST') from None
    else:raise MetricaError('FORBIDDEN_REQUEST')
    if len((BASE+path+('?' + urlencode(params) if params else '')).encode('utf-8'))>MAX_URL_BYTES:raise MetricaError('FORBIDDEN_REQUEST')

class MetricaHTTP:
    def __init__(self,*,live_enabled=False):self.live_enabled=live_enabled
    def get(self,path,params,token):
        validate_request(path,params)
        if not self.live_enabled:raise MetricaError('LIVE_DISABLED')
        if not valid_token(token):raise MetricaError('INVALID_TOKEN')
        request=urllib.request.Request(BASE+path+('?' + urlencode(params) if params else ''),headers={'Authorization':'OAuth '+token,'Accept':'application/json','Accept-Encoding':'identity'},method='GET')
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect(),urllib.request.HTTPSHandler(context=ssl.create_default_context()))
        deadline=time.monotonic()+20
        try:
            try:response=opener.open(request,timeout=15)
            except urllib.error.HTTPError as error:response=error
            with response:
                status=response.code
                if 300<=status<400:raise MetricaError('REDIRECT_REFUSED')
                if status!=200:raise MetricaError('HTTP_'+str(status) if status in (401,403,404,429) else 'HTTP_ERROR')
                headers={k.lower():v for k,v in response.headers.items()}
                if headers.get('content-encoding','identity').lower()!='identity':raise MetricaError()
                length=headers.get('content-length')
                if length is not None and (not length.isdecimal() or int(length)>MAX_BYTES):raise MetricaError('RESPONSE_LIMIT')
                chunks=[];size=0
                while True:
                    if time.monotonic()>deadline:raise MetricaError('NETWORK_ERROR')
                    chunk=response.read(min(65536,MAX_BYTES+1-size))
                    if not chunk:break
                    chunks.append(chunk);size+=len(chunk)
                    if size>MAX_BYTES:raise MetricaError('RESPONSE_LIMIT')
                if length is not None and size!=int(length):raise MetricaError()
                obj=json.loads(b''.join(chunks).decode('utf-8-sig'))
                if type(obj) is not dict or 'errors' in obj:raise MetricaError()
                return obj
        except MetricaError:raise
        except Exception:raise MetricaError('NETWORK_ERROR') from None
