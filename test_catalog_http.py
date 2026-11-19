import unittest,socket,io,json,copy
from unittest.mock import patch,MagicMock
from catalog_http import *
class Response(io.BytesIO):
    def __init__(self,body=b'{"result":{}}',code=200,headers=None):super().__init__(body);self.code=code;self.headers=headers or {}
class Tests(unittest.TestCase):
    def setUp(self):
        p=patch.object(socket,'socket',side_effect=AssertionError('No live network'));p.start();self.addCleanup(p.stop)
        self.params=params_for('ads',{'CampaignIds':[2]})
    def test_default_disabled(self):
        with self.assertRaises(CatalogError):CatalogHTTP().get('ads',self.params,'synthetic-token')
    def test_only_get_wire(self):
        opener=MagicMock();opener.open.return_value=Response()
        with patch('urllib.request.build_opener',return_value=opener):CatalogHTTP(live_enabled=True).get('ads',self.params,'synthetic-token')
        request=opener.open.call_args.args[0];self.assertEqual(request.full_url,ENDPOINTS['ads']);self.assertEqual(json.loads(request.data)['method'],'get')
    def test_no_write_service(self):
        for service in ('Ads.update','adimages/add','https://evil.invalid','campaigns'):
            with self.assertRaises(CatalogError):validate(service,self.params)
    def test_extra_fields_filters_rejected(self):
        for key,value in [('Ads',[{'Id':1}]),('FieldNames',['Id']),('SelectionCriteria',{}),('method','update')]:
            p=copy.deepcopy(self.params);p[key]=value
            with self.assertRaises(CatalogError):validate('ads',p)
    def test_no_redirect_or_raw_errors(self):
        for code,body in [(302,b'secret'),(200,b'{"error":{"secret":"token"}}'),(403,b'secret')]:
            opener=MagicMock();opener.open.return_value=Response(body,code)
            with patch('urllib.request.build_opener',return_value=opener),self.assertRaises(CatalogError) as e:CatalogHTTP(live_enabled=True).get('ads',self.params,'synthetic-token')
            self.assertNotIn('secret',str(e.exception))
    def test_all_service_whitelists(self):
        validate('adimages',params_for('adimages',{'AdImageHashes':['abc']}));validate('creatives',params_for('creatives',{'Ids':[2]}))
    def test_truncated_oversize_invalid_json(self):
        for response in (Response(b'{}',headers={'Content-Length':'50'}),Response(b'{}',headers={'Content-Length':str(MAX_BYTES+1)}),Response(b'no json'),Response(headers={'Content-Encoding':'gzip'})):
            opener=MagicMock();opener.open.return_value=response
            with patch('urllib.request.build_opener',return_value=opener),self.assertRaises(CatalogError):CatalogHTTP(live_enabled=True).get('ads',self.params,'synthetic-token')
    def test_token_header_injection_rejected(self):
        with self.assertRaises(CatalogError):CatalogHTTP(live_enabled=True).get('ads',self.params,'token\nInjected: yes')
