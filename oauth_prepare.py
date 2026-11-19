"""Explicit own-app PKCE helper. No default third-party client, browser launch or storage."""
import base64
from dataclasses import dataclass, field
import hashlib
import json
import re
import secrets
import time
from urllib.parse import urlencode, urlsplit, parse_qs
from network_adapter import FixedHTTPS, TOKEN_ENDPOINT, valid_token
from report_core import InvalidReport

@dataclass(repr=False)
class Pending:
    client_id: str
    redirect_uri: str
    verifier: str = field(repr=False)
    state: str = field(repr=False)
    created_at: float
    consumed: bool = False

@dataclass(repr=False)
class TokenBundle:
    access_token: str = field(repr=False)
    expires_in: int
    refresh_token: str | None = field(default=None, repr=False)


def begin(client_id, redirect_uri, *, clock=time.monotonic):
    if type(client_id) is not str or not re.fullmatch(r'[a-fA-F0-9]{32}', client_id):
        raise InvalidReport('Supply the client ID of a reviewed, API-approved own application.')
    uri = urlsplit(redirect_uri)
    if uri.scheme != 'http' or uri.hostname != '127.0.0.1' or uri.username or uri.password or uri.query or uri.fragment or uri.path != '/callback':
        raise InvalidReport('Only an exactly registered loopback http://127.0.0.1[:port]/callback is permitted.')
    try:
        if uri.port is not None and not 1024 <= uri.port <= 65535:
            raise InvalidReport('Invalid callback port.')
    except ValueError:
        raise InvalidReport('Invalid callback port.') from None
    verifier = secrets.token_urlsafe(48)
    state = secrets.token_urlsafe(32)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    pending = Pending(client_id, redirect_uri, verifier, state, clock())
    url = 'https://oauth.yandex.ru/authorize?' + urlencode({
        'response_type':'code', 'client_id':client_id, 'redirect_uri':redirect_uri,
        'scope':'direct:api', 'force_confirm':'yes', 'state':state,
        'code_challenge':challenge, 'code_challenge_method':'S256'})
    return pending, url


def finish(pending, callback_url, *, http=None, clock=time.monotonic):
    if not isinstance(pending, Pending) or pending.consumed or not 0 <= clock()-pending.created_at < 600:
        raise InvalidReport('Authorization attempt missing, expired or already consumed.')
    if type(callback_url) is not str or len(callback_url) > 8192:
        raise InvalidReport('Invalid callback.')
    got, expected = urlsplit(callback_url), urlsplit(pending.redirect_uri)
    if got._replace(query='') != expected:
        raise InvalidReport('Callback destination mismatch.')
    query = parse_qs(got.query, keep_blank_values=True, strict_parsing=True)
    if set(query) != {'code','state'} or any(len(v) != 1 for v in query.values()):
        raise InvalidReport('Callback parameters invalid or authorization denied.')
    if not secrets.compare_digest(query['state'][0], pending.state):
        raise InvalidReport('OAuth state mismatch.')
    code = query['code'][0]
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,512}', code):
        raise InvalidReport('Invalid authorization code.')
    return _exchange(pending, code, http=http)


def _exchange(pending, code, *, http=None, expected_scope="direct:api"):
    if expected_scope not in ("direct:api", "metrika:read"):
        raise InvalidReport("Unsupported OAuth scope.")
    # Consume before exchange; no replay even after an uncertain network outcome.
    pending.consumed = True
    form = {'grant_type':'authorization_code','code':code,'client_id':pending.client_id,
            'code_verifier':pending.verifier}
    response = (http or FixedHTTPS()).post(TOKEN_ENDPOINT,
                {'Content-Type':'application/x-www-form-urlencoded','Accept-Encoding':'identity'},
                urlencode(form).encode(), 16384, 15)
    if response.status != 200:
        raise InvalidReport(f'OAuth HTTP {response.status}; no token details exposed.')
    try:
        if len(response.body) > 16384:
            raise ValueError()
        data = json.loads(response.body)
        access, expires = data['access_token'], data['expires_in']
        refresh = data.get('refresh_token')
        if not valid_token(access) or type(expires) is not int or not 0 < expires <= 10*366*86400:
            raise ValueError()
        if refresh is not None and (type(refresh) is not str or not re.fullmatch(r'[A-Za-z0-9._~+/:=-]{10,4096}', refresh)):
            raise ValueError()
        if 'scope' in data and data['scope'] != expected_scope:
            raise ValueError()
    except (ValueError, KeyError, TypeError, RecursionError):
        raise InvalidReport('Invalid token response; no token details exposed.') from None
    return TokenBundle(access, expires, refresh)
