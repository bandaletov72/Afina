import contextlib
import io
import json
import socket
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from network_adapter import Response,TOKEN_ENDPOINT
from oauth_screen import *

FAKE_CODE='1234567'
FAKE_TOKEN='SYNTHETIC_NOT_A_REAL_TOKEN'
class FakeHTTP:
    def __init__(self):self.calls=[]
    def post(self,*args):
        self.calls.append(args)
        return Response(200,{},json.dumps({'access_token':FAKE_TOKEN,'expires_in':3600,'refresh_token':'1:SYNTHETIC_REFRESH_TOKEN'}).encode())
class Tests(unittest.TestCase):
    def setUp(self):self.p,self.url=begin_screen('a'*32,clock=lambda:0)
    def test_redirect_exact(self):
        q=parse_qs(urlsplit(self.url).query)
        self.assertEqual(q['redirect_uri'],[REDIRECT_URI])
        self.assertEqual(q['response_type'],['code'])
        self.assertEqual(q['scope'],['direct:api'])
    def test_pkce_secret_not_in_url(self):
        self.assertNotIn(self.p.verifier,self.url)
        self.assertEqual(parse_qs(urlsplit(self.url).query)['code_challenge_method'],['S256'])
    def test_no_fake_state_guarantee(self):
        self.assertNotIn('state',parse_qs(urlsplit(self.url).query))
    def test_exchange_fixed_endpoint(self):
        http=FakeHTTP();r=finish_screen(self.p,FAKE_CODE,http=http,clock=lambda:1)
        self.assertEqual(r.access_token,FAKE_TOKEN)
        url,headers,body,*_=http.calls[0]
        self.assertEqual(url,TOKEN_ENDPOINT)
        q=parse_qs(body.decode());self.assertEqual(q['code'],[FAKE_CODE])
        self.assertEqual(q['code_verifier'],[self.p.verifier]);self.assertNotIn('client_secret',q)
    def test_opaque_code_exchange_preserved(self):
        http=FakeHTTP()
        code='AbCdEf0123456789+/='
        finish_screen(self.p,'  '+code+'\n',http=http,clock=lambda:1)
        body=http.calls[0][2]
        self.assertEqual(parse_qs(body.decode())['code'],[code])
    def test_replay(self):
        finish_screen(self.p,FAKE_CODE,http=FakeHTTP(),clock=lambda:1)
        with self.assertRaises(InvalidReport):finish_screen(self.p,FAKE_CODE,http=FakeHTTP(),clock=lambda:2)
    def test_expiry(self):
        with self.assertRaises(InvalidReport):finish_screen(self.p,FAKE_CODE,http=FakeHTTP(),clock=lambda:600)
    def test_tokens_urls_unicode_or_wrong_length_rejected(self):
        for v in [None,'','https://oauth.yandex.ru/verification_code','x'*513,'123\n4567','abc def','abc\x00def']:
            with self.assertRaises(InvalidReport):finish_screen(self.p,v,http=FakeHTTP(),clock=lambda:1)
    def test_wrong_flow_rejected(self):
        self.p.redirect_uri='http://127.0.0.1:8765/callback'
        with self.assertRaises(InvalidReport):finish_screen(self.p,FAKE_CODE,http=FakeHTTP(),clock=lambda:1)
    def test_default_network_disabled(self):
        with self.assertRaisesRegex(InvalidReport,'LIVE_ACCESS_DISABLED'):finish_screen(self.p,FAKE_CODE,clock=lambda:1)
    def test_storage_required_before_browser(self):
        opened=[]
        with self.assertRaises(InvalidReport):authorize_local('a'*32,browser_opener=lambda u:opened.append(u))
        self.assertEqual(opened,[])
    def test_cancel_no_exchange_or_storage(self):
        http=FakeHTTP();stored=[]
        self.assertFalse(authorize_local('a'*32,secure_store=stored.append,http=http,browser_opener=lambda _:True,prompt=lambda:None))
        self.assertEqual(http.calls,[]);self.assertEqual(stored,[])
    def test_browser_failure_no_prompt(self):
        def forbidden():raise AssertionError('must not prompt')
        with self.assertRaises(InvalidReport):authorize_local('a'*32,secure_store=lambda _:None,browser_opener=lambda _:False,prompt=forbidden)
    def test_no_code_token_output(self):
        out,err,stored=io.StringIO(),io.StringIO(),[]
        with contextlib.redirect_stdout(out),contextlib.redirect_stderr(err):
            r=authorize_local('a'*32,secure_store=stored.append,http=FakeHTTP(),browser_opener=lambda _:True,prompt=lambda:FAKE_CODE)
        self.assertIs(r,True);self.assertEqual(len(stored),1)
        self.assertEqual(out.getvalue()+err.getvalue(),'')
    def test_storage_exception_sanitized(self):
        def broken(_):raise RuntimeError(FAKE_TOKEN+' '+FAKE_CODE)
        with self.assertRaises(InvalidReport) as result:
            authorize_local('a'*32,secure_store=broken,http=FakeHTTP(),browser_opener=lambda _:True,prompt=lambda:FAKE_CODE)
        self.assertNotIn(FAKE_TOKEN,str(result.exception));self.assertNotIn(FAKE_CODE,str(result.exception))
    def test_no_gui_no_stdin_fallback(self):
        with patch.dict('sys.modules',{'tkinter':None}):
            with self.assertRaisesRegex(InvalidReport,'no console/chat fallback'):prompt_local_code()
if __name__=='__main__':
    with patch.object(socket,'socket',side_effect=AssertionError('NETWORK FORBIDDEN')):
        unittest.main(verbosity=2)
