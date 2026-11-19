"""Read-only JSON get adapter; HTTP POST is required by Direct API protocol."""
import json
import ssl
import time
import urllib.request
import urllib.error
from ads_catalog import CatalogError,params_for,campaign_ids,ident,image_hash
from network_adapter import NoRedirect,valid_token
ENDPOINTS={name:'https://api.direct.yandex.com/json/v5/'+name for name in ('ads','adimages','creatives')}
MAX_BYTES=4*1024*1024

def validate(service,params):
    if service not in ENDPOINTS or type(params) is not dict:raise CatalogError('FORBIDDEN')
    try:
        selection=params['SelectionCriteria'];page=params['Page'];offset=page['Offset']
        if type(offset) is not int or not 0<=offset<100000:raise ValueError()
        if service=='ads':
            if type(selection) is not dict or set(selection)!={'CampaignIds'}:raise ValueError()
            ids=selection['CampaignIds'];canonical={'CampaignIds':[int(x) for x in campaign_ids(ids)]}
            if any(type(x) is not int for x in ids):raise ValueError()
        elif service=='adimages':
            if type(selection) is not dict or set(selection)!={'AdImageHashes'}:raise ValueError()
            values=selection['AdImageHashes']
            if type(values) is not list or not 1<=len(values)<=1000:raise ValueError()
            canonical={'AdImageHashes':list(dict.fromkeys(image_hash(x) for x in values))}
        else:
            if type(selection) is not dict or set(selection)!={'Ids'}:raise ValueError()
            values=selection['Ids']
            if type(values) is not list or not 1<=len(values)<=1000 or any(type(x) is not int for x in values):raise ValueError()
            canonical={'Ids':list(dict.fromkeys(int(ident(x)) for x in values))}
        if params!=params_for(service,canonical,offset):raise ValueError()
    except Exception:raise CatalogError('FORBIDDEN') from None

class CatalogHTTP:
    def __init__(self,*,live_enabled=False):self.live_enabled=live_enabled
    def get(self,service,params,token):
        validate(service,params)
        if not self.live_enabled:raise CatalogError('DISABLED')
        if not valid_token(token):raise CatalogError('AUTH')
        body=json.dumps({'method':'get','params':params},separators=(',',':')).encode()
        if len(body)>1024*1024:raise CatalogError('LIMIT')
        request=urllib.request.Request(ENDPOINTS[service],data=body,method='POST',headers={'Authorization':'Bearer '+token,'Content-Type':'application/json; charset=utf-8','Accept-Encoding':'identity','Accept-Language':'en'})
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect(),urllib.request.HTTPSHandler(context=ssl.create_default_context()));deadline=time.monotonic()+20
        try:
            try:response=opener.open(request,timeout=15)
            except urllib.error.HTTPError as error:response=error
            with response:
                if response.code!=200:raise CatalogError('AUTH' if response.code in (401,403) else 'NETWORK')
                headers={k.lower():v for k,v in response.headers.items()};length=headers.get('content-length')
                if headers.get('content-encoding','identity').lower()!='identity':raise CatalogError()
                if length is not None and (not length.isdecimal() or int(length)>MAX_BYTES):raise CatalogError('LIMIT')
                chunks=[];size=0
                while True:
                    if time.monotonic()>deadline:raise CatalogError('NETWORK')
                    chunk=response.read(min(65536,MAX_BYTES+1-size))
                    if not chunk:break
                    size+=len(chunk);chunks.append(chunk)
                    if size>MAX_BYTES:raise CatalogError('LIMIT')
                if length is not None and size!=int(length):raise CatalogError()
                obj=json.loads(b''.join(chunks).decode('utf-8-sig'))
                if type(obj) is not dict or 'error' in obj or type(obj.get('result')) is not dict:raise CatalogError()
                return obj
        except CatalogError:raise
        except Exception:raise CatalogError('NETWORK') from None
