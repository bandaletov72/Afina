import unittest,socket,copy
from unittest.mock import patch
from ads_catalog import *
BASE={'Id':1,'CampaignId':2,'AdGroupId':3,'Type':'TEXT_AD','Subtype':'NONE','State':'ON','Status':'ACCEPTED','TextAd':{'Title':'Test','AdImageHash':'abc','Href':'https://example.com'}}
IMAGE={'AdImageHash':'abc','Name':'Test','Type':'REGULAR','Subtype':'NONE','PreviewUrl':'https://example.com/a.png','OriginalUrl':None}
class HTTP:
    def __init__(self,*values):self.values=iter(values);self.calls=[]
    def get(self,service,params,token):
        self.calls.append((service,params));value=next(self.values)
        if isinstance(value,Exception):raise value
        return value
class Tests(unittest.TestCase):
    def setUp(self):
        self.guard=patch.object(socket,'socket',side_effect=AssertionError('No live network'));self.guard.start();self.addCleanup(self.guard.stop)
    def test_ids(self):self.assertEqual(campaign_ids('2, 3;2\n0004'),['2','3','4'])
    def test_bad_input(self):
        for value in ('','0','-1','x','9'*5000,[]):
            with self.assertRaises(CatalogError):campaign_ids(value)
    def test_basic_catalog(self):
        h=HTTP({'result':{'Ads':[BASE]}},{'result':{'AdImages':[IMAGE]}});r=catalog(lambda:'fake',h,['2'])
        self.assertTrue(r['complete']);self.assertEqual(r['ads'][0]['images'],['abc']);self.assertEqual(r['images'][0]['hash'],'abc');self.assertEqual(len(h.calls),2)
    def test_responsive(self):
        obj=dict(BASE,Type='RESPONSIVE_AD',ResponsiveAd={'Titles':[{'Title':'Title'}],'AdImages':{'Items':[{'ImageHash':'abc'}]},'Href':None})
        self.assertEqual(normalize_ad(obj)['images'],['abc'])
    def test_unknown_explicit(self):
        result=normalize_ad(dict(BASE,Type='NEW_TYPE'));self.assertFalse(result['supported']);self.assertEqual(result['images'],[])
    def test_creative(self):
        obj=dict(BASE,Type='IMAGE_AD',Subtype='TEXT_AD_BUILDER_AD',TextAdBuilderAd={'Creative':{'CreativeId':9},'Href':None})
        self.assertEqual(normalize_ad(obj)['creativeIds'],['9'])
    def test_image_type(self):
        obj=dict(BASE,Type='IMAGE_AD',Subtype='TEXT_IMAGE_AD',TextImageAd={'AdImageHash':'abc','Href':None});self.assertTrue(normalize_ad(obj)['supported'])
    def test_urls(self):
        for value in ('http://example.com','javascript:alert(1)','https://localhost/a','https://127.0.0.1/a','https://x:y@example.com','https://example.com:81/a','https://example.com\\evil'):
            self.assertIsNone(safe_url(value))
        self.assertEqual(safe_url('https://example.com/a'),'https://example.com/a')
    def test_pagination_failure_atomic(self):
        h=HTTP({'result':{'Ads':[BASE],'LimitedBy':1}},RuntimeError('secret echoed'))
        with self.assertRaises(CatalogError) as e:catalog(lambda:'fake',h,['2'])
        self.assertNotIn('secret',str(e.exception))
    def test_duplicate_pagination(self):
        h=HTTP({'result':{'Ads':[BASE],'LimitedBy':1}},{'result':{'Ads':[BASE]}})
        with self.assertRaises(CatalogError):catalog(lambda:'fake',h,['2'])
    def test_missing_image_not_complete(self):
        with self.assertRaises(CatalogError):catalog(lambda:'fake',HTTP({'result':{'Ads':[BASE]}},{'result':{'AdImages':[]}}),['2'])
    def test_wrong_campaign(self):
        with self.assertRaises(CatalogError):catalog(lambda:'fake',HTTP({'result':{'Ads':[BASE]}}),['99'])
    def test_empty_complete(self):self.assertTrue(catalog(lambda:'fake',HTTP({'result':{'Ads':[]}}),['2'])['complete'])
    def test_bad_limitedby(self):
        for limit in (0,True,10):
            with self.assertRaises(CatalogError):catalog(lambda:'fake',HTTP({'result':{'Ads':[BASE],'LimitedBy':limit}}),['2'])
