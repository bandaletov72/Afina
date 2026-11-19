import json
import socket
import unittest
from unittest.mock import patch, Mock
from windows_credentials import *
from oauth_screen import authorize_local, prompt_local_code
from network_adapter import Response

TOKEN = 'SYNTHETIC_NOT_A_REAL_TOKEN'
class FakeVault:
    def __init__(self): self.data={}
    def write(self,k,v): self.data[k]=v
    def read(self,k): return self.data[k]
    def delete(self,k): self.data.pop(k,None)
class Tests(unittest.TestCase):
    def setUp(self):
        self.v=FakeVault(); self.s=CredentialStore('a'*32,backend=self.v,clock=lambda:100)
        self.b=TokenBundle(TOKEN,3600,'1:SYNTHETIC_REFRESH_TOKEN')
    def test_roundtrip(self):
        self.s.save(self.b); self.assertEqual(self.s.access_token(),TOKEN)
    def test_deleted(self):
        self.s.save(self.b);self.s.delete()
        with self.assertRaises(InvalidReport):self.s.access_token()
    def test_wrong_client(self):
        self.s.save(self.b)
        with self.assertRaises(InvalidReport):CredentialStore('b'*32,backend=self.v).access_token()
    def test_size_limit(self):
        with self.assertRaises(InvalidReport):self.s.save(TokenBundle('a'*3000,3600))
        self.assertEqual(self.v.data,{})
    def test_expiry(self):
        self.s.save(self.b);self.s.clock=lambda:3641
        with self.assertRaises(InvalidReport):self.s.access_token()
    def test_invalid_clock(self):
        self.s.save(self.b)
        for now in [float('nan'),float('inf'),True,None]:
            self.s.clock=lambda:now
            with self.assertRaises(InvalidReport): self.s.access_token()
            with self.assertRaises(InvalidReport): self.s.save(self.b)
    def test_corrupt(self):
        for raw in [b'{}',b'null',b'[]',b'bad',b'x'*3000]:
            self.v.data[self.s.target]=raw
            with self.assertRaises(InvalidReport):self.s.access_token()
    def test_readback_failure(self):
        self.v.read=lambda k:b'wrong'
        with self.assertRaises(InvalidReport):self.s.save(self.b)
    def test_invalid_bundle(self):
        for b in [None,TokenBundle(TOKEN,True),TokenBundle(TOKEN,-1),TokenBundle('bad\nsecret',3600)]:
            with self.assertRaises(InvalidReport):self.s.save(b)
    def test_errors_redacted(self):
        def fail(*a): raise RuntimeError(TOKEN)
        self.v.write=fail
        with self.assertRaises(InvalidReport) as caught:self.s.save(self.b)
        self.assertNotIn(TOKEN,str(caught.exception))
    def test_nonwindows_fails(self):
        with patch('windows_credentials.sys.platform','linux'):
            with self.assertRaises(InvalidReport):NativeVault()
    def test_layout_windows64(self):
        if C.sizeof(C.c_void_p)==8:
            self.assertEqual(C.sizeof(CREDENTIALW),80)
            self.assertEqual(CREDENTIALW.CredentialBlob.offset,40)
            self.assertEqual(CREDENTIALW.Persist.offset,48)
    def test_full_mock_ui_exchange_store(self):
        http=Mock()
        http.post.return_value=Response(200,{},json.dumps({'access_token':TOKEN,'expires_in':3600}).encode())
        self.assertTrue(authorize_local('a'*32,secure_store=self.s.save,http=http,
                         browser_opener=lambda _:True,prompt=lambda:'1234567'))
        self.assertEqual(self.s.access_token(),TOKEN)
    def test_gui_mask_and_cleanup(self):
        import sys, types
        root=Mock(); dialog=Mock(return_value=None)
        fake=types.ModuleType('tkinter');fake.Tk=Mock(return_value=root)
        fake.simpledialog=types.SimpleNamespace(askstring=dialog)
        with patch.dict(sys.modules,{'tkinter':fake}), patch('local_input.ask_local_value', dialog):
            self.assertIsNone(prompt_local_code())
        self.assertTrue(dialog.call_args.kwargs['code'])
        root.destroy.assert_called_once()
    def test_gui_failure_cleanup_no_fallback(self):
        import sys,types
        root=Mock();fake=types.ModuleType('tkinter');fake.Tk=lambda:root
        fake.simpledialog=types.SimpleNamespace(askstring=Mock(side_effect=RuntimeError(TOKEN)))
        with patch.dict(sys.modules,{'tkinter':fake}), patch('local_input.ask_local_value', side_effect=RuntimeError(TOKEN)):
            with self.assertRaises(InvalidReport) as caught:prompt_local_code()
        root.destroy.assert_called_once(); self.assertNotIn(TOKEN,str(caught.exception))

if __name__=='__main__':
    with patch.object(socket,'socket',side_effect=AssertionError('Network forbidden')):
        unittest.main()
