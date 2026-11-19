"""Metrica-only OAuth and isolated Windows credentials. No import-time OS access."""
from oauth_prepare import _exchange, Pending
from oauth_screen import begin_screen, REDIRECT_URI
from windows_credentials import CredentialStore
from local_input import normalize_code
from report_core import InvalidReport
import time
from urllib.parse import urlsplit,parse_qsl,urlencode,urlunsplit

SCOPE='metrika:read'
class MetricaStore(CredentialStore):
    def __init__(self,client_id,**kwargs):
        super().__init__(client_id,**kwargs)
        self.target='Afina/YandexMetrica/'+client_id.lower()

def begin(client_id,store_factory=MetricaStore):
    store_factory(client_id) # Backend availability checked before opening browser.
    pending,url=begin_screen(client_id)
    parts=urlsplit(url);query=dict(parse_qsl(parts.query));query['scope']=SCOPE
    return pending,urlunsplit((parts.scheme,parts.netloc,parts.path,urlencode(query),parts.fragment))

def finish(pending,code,http,clock=time.monotonic):
    if not isinstance(pending,Pending) or pending.redirect_uri!=REDIRECT_URI or pending.consumed or not 0<=clock()-pending.created_at<600:
        raise InvalidReport('METRICA_AUTH_EXPIRED')
    code=normalize_code(code)
    try:return _exchange(pending,code,http=http,expected_scope=SCOPE)
    finally:pending.consumed=True;pending.verifier=''
