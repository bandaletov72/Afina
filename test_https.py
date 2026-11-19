import io
import socket
import unittest
from unittest.mock import patch
from network_adapter import FixedHTTPS,ENDPOINT
from report_core import InvalidReport
class FakeResponse(io.BytesIO):
    def __init__(self,body=b'ok',status=200,headers=None):
        super().__init__(body);self.code=status;self.headers=headers or {}
class FakeOpener:
    def __init__(self,response):self.response=response;self.request=None
    def open(self,request,timeout):self.request=request;return self.response
class Tests(unittest.TestCase):
    def invoke(self,response,max_bytes=100):
        opener=FakeOpener(response)
        with patch('urllib.request.build_opener',return_value=opener):
            result=FixedHTTPS(live_enabled=True).post(ENDPOINT,{},b'{}',max_bytes,1)
        self.assertEqual(opener.request.method,'POST')
        return result
    def test_read(self):self.assertEqual(self.invoke(FakeResponse(headers={'Content-Length':'2'})).body,b'ok')
    def test_redirect(self):
        with self.assertRaisesRegex(InvalidReport,'Redirect'):self.invoke(FakeResponse(status=302,headers={'Location':'https://evil.invalid'}))
    def test_encoding(self):
        with self.assertRaises(InvalidReport):self.invoke(FakeResponse(headers={'Content-Encoding':'gzip'}))
    def test_content_length_limit(self):
        with self.assertRaises(InvalidReport):self.invoke(FakeResponse(headers={'Content-Length':'9999'}))
    def test_body_limit(self):
        with self.assertRaises(InvalidReport):self.invoke(FakeResponse(b'x'*101))
    def test_truncation(self):
        with self.assertRaisesRegex(InvalidReport,'Truncated'):self.invoke(FakeResponse(headers={'Content-Length':'3'}))
    def test_generic_errors_sanitized(self):
        class BrokenOpener:
            def open(self,*args,**kwargs):raise RuntimeError('SYNTHETIC_SECRET')
        with patch('urllib.request.build_opener',return_value=BrokenOpener()):
            with self.assertRaises(InvalidReport) as result:
                FixedHTTPS(live_enabled=True).post(ENDPOINT,{},b'{}',100,1)
            self.assertNotIn('SYNTHETIC_SECRET',str(result.exception))
if __name__=='__main__':
    with patch.object(socket,'socket',side_effect=AssertionError('NETWORK FORBIDDEN')):
        unittest.main(verbosity=2)
