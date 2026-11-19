"""Prepared fixed-host HTTP adapter. Never used by default server; no credential storage."""
import json
import re
import ssl
import time
import urllib.request
import urllib.error
from dataclasses import dataclass
from report_core import ENDPOINT, InvalidReport, MAX_REPORT_BYTES, build_request

CLIENTS_ENDPOINT = 'https://api.direct.yandex.com/json/v5/clients'
CLIENTS_BODY = {'method':'get','params':{'FieldNames':['ClientId','Login','Currency','Type']}}

TOKEN_ENDPOINT = 'https://oauth.yandex.ru/token'

@dataclass(frozen=True)
class Response:
    status: int
    headers: dict
    body: bytes

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

class FixedHTTPS:
    """Explicit opt-in only. Ignores proxy env; validates TLS; never follows redirects."""
    def __init__(self, *, live_enabled=False):
        self.live_enabled = live_enabled

    def post(self, url, headers, body, max_bytes, timeout):
        if not self.live_enabled:
            raise InvalidReport('LIVE_ACCESS_DISABLED: explicit reviewed deployment is required.')
        if url not in (ENDPOINT, TOKEN_ENDPOINT, CLIENTS_ENDPOINT):
            raise InvalidReport('Forbidden endpoint.')
        if url == CLIENTS_ENDPOINT:
            try:
                if json.loads(body) != CLIENTS_BODY: raise ValueError()
            except Exception:
                raise InvalidReport('Only fixed Clients.get identity query allowed.') from None
        if type(body) is not bytes or len(body) > 16384:
            raise InvalidReport('Invalid request size.')
        if not 0 < timeout <= 20 or not 0 < max_bytes <= MAX_REPORT_BYTES:
            raise InvalidReport('Invalid network bounds.')
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect(),
                    urllib.request.HTTPSHandler(context=ssl.create_default_context()))
        request = urllib.request.Request(url, data=body, headers=headers, method='POST')
        deadline = time.monotonic() + timeout
        try:
            try:
                response = opener.open(request, timeout=timeout)
            except urllib.error.HTTPError as error:
                response = error
            with response:
                status = response.code
                safe_headers = {k.lower(): v for k, v in response.headers.items()}
                if 300 <= status < 400:
                    raise InvalidReport('Redirect refused.')
                if safe_headers.get('content-encoding', 'identity').lower() != 'identity':
                    raise InvalidReport('Unexpected content encoding.')
                length = safe_headers.get('content-length')
                if length is not None and (not length.isdecimal() or int(length) > max_bytes):
                    raise InvalidReport('Response too large or invalid Content-Length.')
                chunks, size = [], 0
                while True:
                    if time.monotonic() > deadline:
                        raise InvalidReport('Network deadline exceeded.')
                    chunk = response.read(min(65536, max_bytes + 1 - size))
                    if not chunk:
                        break
                    chunks.append(chunk); size += len(chunk)
                    if size > max_bytes:
                        raise InvalidReport('Response size limit exceeded.')
                raw = b''.join(chunks)
                if length is not None and len(raw) != int(length):
                    raise InvalidReport('Truncated response.')
                return Response(status, safe_headers, raw)
        except InvalidReport:
            raise
        except Exception:
            raise InvalidReport('HTTPS request failed; sensitive diagnostics suppressed.') from None


def valid_token(token):
    return type(token) is str and bool(re.fullmatch(r'[A-Za-z0-9._~+/-]{10,4096}=?', token))

class ReportsTransport:
    """Only fixed report requests; token provided by an external secret provider callback."""
    def __init__(self, token_provider, *, http=None, client_login=None, sleep=time.sleep, clock=time.monotonic):
        if client_login is not None and not re.fullmatch(r'[A-Za-z0-9_.@-]{1,100}', client_login):
            raise InvalidReport('Invalid client login.')
        self.token_provider = token_provider
        self.http = http or FixedHTTPS()  # live disabled even if a token accidentally exists
        self.client_login = client_login
        self.sleep, self.clock = sleep, clock
        self.last_request_id = None

    def fetch(self, request):
        try:
            selection = request['body']['params']['SelectionCriteria']
            expected = build_request({'dateFrom': selection['DateFrom'], 'dateTo': selection['DateTo']})
        except (KeyError, TypeError):
            raise InvalidReport('Malformed report request.') from None
        if request != expected:
            raise InvalidReport('Only the canonical weekly report request is permitted.')
        token = self.token_provider()
        if not valid_token(token):
            raise InvalidReport('Credential missing or invalid; no request sent.')
        headers = dict(expected['headers'])
        headers.update({'Authorization': 'Bearer ' + token, 'Accept-Encoding': 'identity'})
        if self.client_login:
            headers['Client-Login'] = self.client_login
        body = json.dumps(expected['body'], separators=(',', ':')).encode()
        deadline = self.clock() + 55
        self.last_request_id = None
        for attempt in range(3):
            remaining = deadline - self.clock()
            if remaining <= 0:
                raise InvalidReport('Report deadline exceeded; no partial totals returned.')
            response = self.http.post(ENDPOINT, headers, body, MAX_REPORT_BYTES, min(15, remaining))
            rid = response.headers.get('requestid', '')
            if re.fullmatch(r'[A-Za-z0-9_-]{1,128}', rid):
                self.last_request_id = rid
            if response.status == 200:
                if len(response.body) > MAX_REPORT_BYTES:
                    raise InvalidReport('Report too large.')
                return response.body
            if response.status not in (201, 202):
                # Never forward untrusted API bodies which might echo credentials or identifiers.
                raise InvalidReport(f'Reports HTTP {response.status}; no report returned.')
            if attempt == 2:
                break
            delay = response.headers.get('retryin', '5')
            if not re.fullmatch(r'[0-9]{1,3}', delay) or not 1 <= int(delay) <= 15:
                raise InvalidReport('Report queued; server wait is outside polling budget.')
            if self.clock() + int(delay) >= deadline:
                break
            self.sleep(int(delay))
        raise InvalidReport('Report still queued; bounded polling stopped, no partial totals returned.')
