"""API-only Yandex verification-code + PKCE flow; local hidden UI, no MCP login tool.
No CLI is provided and no browser/network runs on import. Storage must be supplied.
"""
import base64
import hashlib
import re
import secrets
import time
import webbrowser
from urllib.parse import urlencode
from oauth_prepare import Pending, _exchange
from report_core import InvalidReport
from local_input import normalize_code

REDIRECT_URI = 'https://oauth.yandex.ru/verification_code'


def begin_screen(client_id, *, clock=time.monotonic):
    if type(client_id) is not str or not re.fullmatch(r'[a-fA-F0-9]{32}', client_id):
        raise InvalidReport('Own reviewed OAuth client ID required.')
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    # There is no callback/state to verify in manual-code mode. PKCE binds the code
    # exchange to this process; never pretend the state check of loopback mode applies.
    pending = Pending(client_id, REDIRECT_URI, verifier, '', clock())
    url = 'https://oauth.yandex.ru/authorize?' + urlencode({
        'response_type':'code', 'client_id':client_id, 'redirect_uri':REDIRECT_URI,
        'scope':'direct:api', 'force_confirm':'yes', 'code_challenge':challenge,
        'code_challenge_method':'S256'})
    return pending, url


def finish_screen(pending, code, *, http=None, clock=time.monotonic):
    if not isinstance(pending, Pending) or pending.redirect_uri != REDIRECT_URI or pending.consumed or not 0 <= clock()-pending.created_at < 600:
        raise InvalidReport('Authorization attempt missing, expired or consumed.')
    try:
        code = normalize_code(code)
    except ValueError:
        raise InvalidReport('Enter the complete confirmation code shown by Yandex, not a URL.') from None
    return _exchange(pending, code, http=http)


def prompt_local_code():
    """Mask entry in local GUI; fail closed if GUI unavailable. Never stdin/chat fallback."""
    try:
        import tkinter
        from local_input import ask_local_value
        root = tkinter.Tk()
        root.withdraw()
        try:
            return ask_local_value(root, code=True)
        finally:
            root.destroy()
    except Exception:
        raise InvalidReport('Local protected input unavailable; no console/chat fallback.') from None


def authorize_local(client_id, *, secure_store=None, http=None,
                    browser_opener=webbrowser.open, prompt=prompt_local_code,
                    clock=time.monotonic):
    """Prepared orchestration. Caller must supply an approved secure-store backend.
    Returns a boolean only. No access token or verification code returned/logged.
    """
    if not callable(secure_store):
        raise InvalidReport('Secure credential storage is not configured; authorization not started.')
    pending, url = begin_screen(client_id, clock=clock)
    code = tokens = None
    try:
        if not browser_opener(url):
            raise InvalidReport('Browser did not open; authorization stopped.')
        code = prompt()
        if code is None:
            return False
        tokens = finish_screen(pending, code, http=http, clock=clock)
        try:
            secure_store(tokens)
        except Exception:
            raise InvalidReport('Secure storage failed; token was not confirmed saved.') from None
        return True
    except InvalidReport:
        raise
    except Exception:
        raise InvalidReport('Local authorization/storage failed; no sensitive details exposed.') from None
    finally:
        pending.consumed = True
        pending.verifier = ''
        code = tokens = None
        # Python immutable strings cannot be reliably wiped from process memory.
        # This avoids persistent copies, but is not a secure-memory guarantee.


def authorize_windows(client_id, *, http=None):
    """Explicit local entry point; Windows store checked before opening browser.
    Network stays disabled unless caller supplies an explicitly enabled transport.
    No CLI args, stdout, config-file secrets or token-returning login tool.
    """
    from windows_credentials import CredentialStore
    store = CredentialStore(client_id)
    return authorize_local(client_id, secure_store=store.save, http=http)
