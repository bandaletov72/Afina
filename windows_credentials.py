"""Current-user Windows Credential Manager storage. No import-time OS calls.
Not an isolation boundary against other programs running as the same user.
"""
import ctypes as C
import json
import math
import re
import sys
import time
from oauth_prepare import TokenBundle
from network_adapter import valid_token
from report_core import InvalidReport

DWORD = C.c_uint32
BYTE = C.c_ubyte
class FILETIME(C.Structure):
    _fields_ = [('low', DWORD), ('high', DWORD)]
class CREDENTIALW(C.Structure):
    _fields_ = [('Flags',DWORD), ('Type',DWORD), ('TargetName',C.c_wchar_p),
                ('Comment',C.c_wchar_p), ('LastWritten',FILETIME),
                ('CredentialBlobSize',DWORD), ('CredentialBlob',C.POINTER(BYTE)),
                ('Persist',DWORD), ('AttributeCount',DWORD), ('Attributes',C.c_void_p),
                ('TargetAlias',C.c_wchar_p), ('UserName',C.c_wchar_p)]
PCREDENTIALW = C.POINTER(CREDENTIALW)
MAX_BLOB = 2560

class NativeVault:
    def __init__(self):
        if sys.platform != 'win32':
            raise InvalidReport('Windows Credential Manager is required; no file fallback.')
        self.api = C.WinDLL('Advapi32.dll', use_last_error=True)
        self.api.CredWriteW.argtypes = [PCREDENTIALW, DWORD]
        self.api.CredWriteW.restype = C.c_int
        self.api.CredReadW.argtypes = [C.c_wchar_p, DWORD, DWORD, C.POINTER(PCREDENTIALW)]
        self.api.CredReadW.restype = C.c_int
        self.api.CredDeleteW.argtypes = [C.c_wchar_p, DWORD, DWORD]
        self.api.CredDeleteW.restype = C.c_int
        self.api.CredFree.argtypes = [C.c_void_p]
        self.api.CredFree.restype = None

    def write(self, target, payload):
        if not 0 < len(payload) <= MAX_BLOB:
            raise InvalidReport('Credential exceeds storage limit.')
        buf = (BYTE * len(payload)).from_buffer_copy(payload)
        cred = CREDENTIALW()
        cred.Type, cred.TargetName, cred.Persist = 1, target, 2
        cred.CredentialBlobSize, cred.CredentialBlob = len(payload), buf
        cred.UserName = 'Afina Direct OAuth'
        try:
            if not self.api.CredWriteW(C.byref(cred), 0):
                raise InvalidReport('Windows credential write failed.')
        finally:
            C.memset(buf, 0, len(payload))

    def read(self, target):
        ptr = PCREDENTIALW()
        if not self.api.CredReadW(target, 1, 0, C.byref(ptr)):
            raise InvalidReport('Windows credential unavailable.')
        try:
            cred = ptr.contents
            if cred.Type != 1 or cred.TargetName != target or not 0 < cred.CredentialBlobSize <= MAX_BLOB or not cred.CredentialBlob:
                raise InvalidReport('Invalid Windows credential.')
            return C.string_at(cred.CredentialBlob, cred.CredentialBlobSize)
        finally:
            self.api.CredFree(ptr)

    def delete(self, target):
        if not self.api.CredDeleteW(target, 1, 0) and C.get_last_error() != 1168:
            raise InvalidReport('Windows credential deletion failed.')

class CredentialStore:
    def __init__(self, client_id, *, backend=None, clock=time.time):
        if type(client_id) is not str or not re.fullmatch('[a-fA-F0-9]{32}', client_id):
            raise InvalidReport('Own OAuth client ID required.')
        self.target = 'Afina/YandexDirect/' + client_id.lower()
        self.backend = NativeVault() if backend is None else backend
        self.clock = clock

    def save(self, bundle):
        try:
            if not isinstance(bundle, TokenBundle) or not valid_token(bundle.access_token):
                raise ValueError()
            if type(bundle.expires_in) is not int or bundle.expires_in <= 0:
                raise ValueError()
            if bundle.refresh_token is not None and (type(bundle.refresh_token) is not str or not re.fullmatch(r'[A-Za-z0-9._~+/:=-]{10,4096}', bundle.refresh_token)):
                raise ValueError()
            now = self.clock()
            if type(now) not in (int, float) or not math.isfinite(now): raise ValueError()
            expiry = now + bundle.expires_in
            if not math.isfinite(expiry): raise ValueError()
            payload = json.dumps({'version':1, 'access_token':bundle.access_token,
                                  'refresh_token':bundle.refresh_token,
                                  'expires_at':expiry}, separators=(',',':')).encode()
            if len(payload) > MAX_BLOB: raise ValueError()
            self.backend.write(self.target, payload)
            if self.backend.read(self.target) != payload:
                raise ValueError()
        except Exception:
            raise InvalidReport('Secure credential save/verification failed.') from None

    def access_token(self):
        try:
            raw = self.backend.read(self.target)
            if not isinstance(raw, bytes) or len(raw) > MAX_BLOB: raise ValueError()
            data = json.loads(raw)
            if set(data) != {'version','access_token','refresh_token','expires_at'} or data['version'] != 1:
                raise ValueError()
            expiry = data['expires_at']
            now = self.clock()
            if type(now) not in (int,float) or not math.isfinite(now): raise ValueError()
            if type(expiry) not in (int,float) or not math.isfinite(expiry) or expiry <= now + 60:
                raise ValueError()
            if not valid_token(data['access_token']): raise ValueError()
            return data['access_token']
        except Exception:
            raise InvalidReport('Stored credential unavailable, invalid or expired; authorize locally again.') from None

    def delete(self):
        try: self.backend.delete(self.target)
        except Exception:
            raise InvalidReport('Secure credential deletion failed.') from None
