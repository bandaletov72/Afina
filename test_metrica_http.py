import io
import socket
import unittest
from unittest.mock import patch,MagicMock
from metrica_http import *
class Response(io.BytesIO):
    def __init__(self,body=b'{}',code=200,headers=None):super().__init__(body);self.code=code;self.headers=headers or {}
class Tests(unittest.TestCase):
    def setUp(self):
        guard=patch.object(socket,'socket',side_effect=AssertionError('No live sockets'));guard.start();self.addCleanup(guard.stop)
    def test_disabled_by_default(self):
        with self.assertRaisesRegex(MetricaError,'LIVE_DISABLED'):MetricaHTTP().get('/management/v1/counter/123',{},'synthetic-token')
    def run_get(self,response,path='/management/v1/counter/123',params=None):
        opener=MagicMock();opener.open.return_value=response
        with patch('urllib.request.build_opener',return_value=opener):
            value=MetricaHTTP(live_enabled=True).get(path,params or {},'synthetic-token')
        return value,opener.open.call_args.args[0]
    def test_get_fixed_host_oauth(self):
        value,request=self.run_get(Response(b'{"counter":{}}'))
        self.assertEqual(request.method,'GET');self.assertEqual(request.get_header('Authorization'),'OAuth synthetic-token');self.assertTrue(request.full_url.startswith(BASE+'/management/'))
    def test_timezone_encoded(self):
        params=period_params({'dateFrom':'2026-11-09','dateTo':'2026-11-15'});params['ids']='123'
        _,request=self.run_get(Response(),'/stat/v1/data',params)
        self.assertIn('timezone=%2B03%3A00',request.full_url)
    def test_forbidden(self):
        for path,params in [('https://evil.invalid',{}),('/management/v1/counter/123',{'field':'measurement_tokens'}),('/management/v1/counter/123/grants',{}),('/stat/v1/data',{'ids':'123'}),('/management/v1/counters',{'offset':0,'per_page':100})]:
            with self.assertRaisesRegex(MetricaError,'FORBIDDEN_REQUEST'):MetricaHTTP(live_enabled=True).get(path,params,'synthetic-token')
    def test_no_redirect(self):
        with self.assertRaisesRegex(MetricaError,'REDIRECT_REFUSED'):self.run_get(Response(code=302,headers={'Location':'https://evil.invalid'}))
    def test_safe_http_errors(self):
        for code in (401,403,404,429,500):
            with self.assertRaises(MetricaError) as got:self.run_get(Response(b'secret token echoed',code))
            self.assertNotIn('secret',str(got.exception))
    def test_size_and_truncation(self):
        for response in (Response(b'{}',headers={'Content-Length':str(MAX_BYTES+1)}),Response(b'{}',headers={'Content-Length':'10'}),Response(b'x'*(MAX_BYTES+1)),Response(headers={'Content-Encoding':'gzip'})):
            with self.assertRaises(MetricaError):self.run_get(response)
    def test_bad_json(self):
        for raw in (b'null',b'[]',b'{bad',b'{"errors":["secret"]}'):
            with self.assertRaises(MetricaError):self.run_get(Response(raw))
    def test_no_header_injection(self):
        with self.assertRaisesRegex(MetricaError,'INVALID_TOKEN'):MetricaHTTP(live_enabled=True).get('/management/v1/counter/123',{},'secret\nheader')

class IDCorrections(unittest.TestCase):
    def test_long_id_whitelist(self):
        validate_request('/management/v1/counter/'+'9'*5000,{})
        params=period_params({'dateFrom':'2026-11-09','dateTo':'2026-11-15'});params['ids']='9'*5000
        validate_request('/stat/v1/data',params)
    def test_url_bound(self):
        with self.assertRaises(MetricaError):validate_request('/management/v1/counter/'+'9'*32768,{})
    def test_get_only_path_whitelist_still_enforced(self):
        for suffix in ('/grants','?field=secret','#fragment','/../counters'):
            with self.assertRaises(MetricaError):validate_request('/management/v1/counter/123'+suffix,{})
