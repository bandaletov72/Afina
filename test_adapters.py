import copy
import io
import json
import socket
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit, urlencode
from network_adapter import FixedHTTPS, ReportsTransport, Response, ENDPOINT, TOKEN_ENDPOINT
from oauth_prepare import begin, finish
from report_core import InvalidReport, build_request

ARGS={'dateFrom':'2026-11-09','dateTo':'2026-11-15'}
FAKE_TOKEN='SYNTHETIC_NOT_A_REAL_TOKEN'

class FakeHTTP:
    def __init__(self,*responses):self.responses=list(responses);self.calls=[]
    def post(self,*args):
        self.calls.append(args)
        return self.responses.pop(0)

class NetworkTests(unittest.TestCase):
    def test_live_disabled(self):
        with self.assertRaisesRegex(InvalidReport,'LIVE_ACCESS_DISABLED'):
            FixedHTTPS().post(ENDPOINT,{},b'{}',100,1)
    def test_wrong_endpoint(self):
        with self.assertRaises(InvalidReport):
            FixedHTTPS(live_enabled=True).post('https://attacker.invalid',{},b'{}',100,1)
    def test_success_fixed_request(self):
        f=FakeHTTP(Response(200,{'requestid':'test-id'},b'synthetic'))
        t=ReportsTransport(lambda:FAKE_TOKEN,http=f)
        self.assertEqual(t.fetch(build_request(ARGS)),b'synthetic')
        url,headers,body,limit,timeout=f.calls[0]
        self.assertEqual(url,ENDPOINT)
        self.assertEqual(headers['Authorization'],'Bearer '+FAKE_TOKEN)
        self.assertEqual(json.loads(body)['params']['IncludeVAT'],'YES')
        self.assertEqual(t.last_request_id,'test-id')
    def test_modified_endpoint_or_body_rejected(self):
        for modifier in ('endpoint','vat','method','header'):
            f=FakeHTTP();r=build_request(ARGS)
            if modifier=='endpoint':r['endpoint']='https://attacker.invalid'
            if modifier=='vat':r['body']['params']['IncludeVAT']='NO'
            if modifier=='method':r['body']['method']='delete'
            if modifier=='header':r['headers']['Authorization']='attacker'
            with self.assertRaises(InvalidReport):ReportsTransport(lambda:FAKE_TOKEN,http=f).fetch(r)
            self.assertEqual(f.calls,[])
    def test_missing_bad_token(self):
        for token in [None,'', 'x\r\nInjected: true']:
            f=FakeHTTP()
            with self.assertRaises(InvalidReport):ReportsTransport(lambda:token,http=f).fetch(build_request(ARGS))
            self.assertEqual(f.calls,[])
    def test_queued_polling(self):
        f=FakeHTTP(Response(201,{'retryin':'1'},b''),Response(202,{'retryin':'2'},b''),Response(200,{},b'ok'))
        waits=[]
        self.assertEqual(ReportsTransport(lambda:FAKE_TOKEN,http=f,sleep=waits.append).fetch(build_request(ARGS)),b'ok')
        self.assertEqual(waits,[1,2])
        self.assertEqual(len(f.calls),3)
    def test_poll_limit(self):
        f=FakeHTTP(*[Response(202,{'retryin':'1'},b'')]*3)
        with self.assertRaisesRegex(InvalidReport,'still queued'):
            ReportsTransport(lambda:FAKE_TOKEN,http=f,sleep=lambda _:None).fetch(build_request(ARGS))
        self.assertEqual(len(f.calls),3)
    def test_invalid_retryin(self):
        for delay in ['0','-1','1000','abc','16']:
            f=FakeHTTP(Response(202,{'retryin':delay},b''))
            with self.assertRaises(InvalidReport):ReportsTransport(lambda:FAKE_TOKEN,http=f).fetch(build_request(ARGS))
    def test_http_errors_never_echo_body(self):
        for status in [301,400,401,403,429,500,503]:
            f=FakeHTTP(Response(status,{},FAKE_TOKEN.encode()))
            with self.assertRaises(InvalidReport) as error:
                ReportsTransport(lambda:FAKE_TOKEN,http=f).fetch(build_request(ARGS))
            self.assertNotIn(FAKE_TOKEN,str(error.exception))
    def test_login_crlf_rejected(self):
        with self.assertRaises(InvalidReport):ReportsTransport(lambda:FAKE_TOKEN,client_login='test\nInjected: value')

class OAuthTests(unittest.TestCase):
    def setUp(self):
        self.p,self.url=begin('a'*32,'http://127.0.0.1:8765/callback',clock=lambda:0)
    def callback(self,**changes):
        q={'code':'SYNTHETIC_CODE','state':self.p.state};q.update(changes)
        return self.p.redirect_uri+'?'+urlencode(q)
    def success_http(self):
        return FakeHTTP(Response(200,{},json.dumps({'access_token':FAKE_TOKEN,'expires_in':3600}).encode()))
    def test_pkce_url_and_minimal_scope(self):
        q=parse_qs(urlsplit(self.url).query)
        self.assertEqual(q['scope'],['direct:api'])
        self.assertEqual(q['code_challenge_method'],['S256'])
        self.assertNotIn(self.p.verifier,self.url)
        self.assertNotIn(self.p.verifier,repr(self.p))
    def test_no_third_party_app_default(self):
        for cid in ['',None,'x']:
            with self.assertRaises((InvalidReport,TypeError)):begin(cid,self.p.redirect_uri)
    def test_non_loopback_redirect_rejected(self):
        for url in ['https://attacker.invalid/callback','http://localhost:8765/callback','http://127.0.0.1:80/callback']:
            with self.assertRaises(InvalidReport):begin('a'*32,url)
    def test_state_mismatch_before_http(self):
        f=FakeHTTP()
        with self.assertRaisesRegex(InvalidReport,'state mismatch'):finish(self.p,self.callback(state='wrong'),http=f,clock=lambda:1)
        self.assertEqual(f.calls,[])
    def test_callback_destination_mismatch(self):
        with self.assertRaises(InvalidReport):finish(self.p,self.callback().replace('8765','8766'),http=FakeHTTP(),clock=lambda:1)
    def test_expiry_before_http(self):
        with self.assertRaises(InvalidReport):finish(self.p,self.callback(),http=FakeHTTP(),clock=lambda:600)
    def test_exchange_and_no_token_repr(self):
        f=self.success_http();tokens=finish(self.p,self.callback(),http=f,clock=lambda:1)
        self.assertEqual(tokens.access_token,FAKE_TOKEN)
        self.assertNotIn(FAKE_TOKEN,repr(tokens))
        self.assertEqual(f.calls[0][0],TOKEN_ENDPOINT)
        self.assertIn('code_verifier=',f.calls[0][2].decode())
        self.assertNotIn('client_secret',f.calls[0][2].decode())
    def test_code_replay_rejected(self):
        finish(self.p,self.callback(),http=self.success_http(),clock=lambda:1)
        with self.assertRaises(InvalidReport):finish(self.p,self.callback(),http=FakeHTTP(),clock=lambda:2)
    def test_default_no_network(self):
        with self.assertRaisesRegex(InvalidReport,'LIVE_ACCESS_DISABLED'):finish(self.p,self.callback(),clock=lambda:1)
    def test_token_error_sanitized(self):
        with self.assertRaises(InvalidReport) as error:
            finish(self.p,self.callback(),http=FakeHTTP(Response(400,{},FAKE_TOKEN.encode())),clock=lambda:1)
        self.assertNotIn(FAKE_TOKEN,str(error.exception))
    def test_extra_scope_rejected(self):
        data={'access_token':FAKE_TOKEN,'expires_in':3600,'scope':'direct:api login:info'}
        with self.assertRaises(InvalidReport):finish(self.p,self.callback(),http=FakeHTTP(Response(200,{},json.dumps(data).encode())),clock=lambda:1)

if __name__=='__main__':
    with patch.object(socket,'socket',side_effect=AssertionError('NETWORK FORBIDDEN')):
        unittest.main(verbosity=2)
