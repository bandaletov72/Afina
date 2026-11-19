import socket
import unittest
from unittest.mock import patch
from metrica_core import *
PERIOD={'dateFrom':'2026-11-09','dateTo':'2026-11-15'}
COUNTER={'id':123,'name':'Synthetic','site':'example.invalid'}
def response(users=0,**extra):
    obj={'query':{'ids':[123],'date1':'2026-11-09','date2':'2026-11-15','timezone':'+03:00','metrics':['ym:s:users']},'totals':[users],'sampled':False,'sample_share':1,'data_lag':120}
    obj.update(extra);return obj
class FakeHTTP:
    def __init__(self,objects):self.objects=iter(objects);self.calls=[]
    def get(self,path,params,token):
        self.calls.append((path,params))
        item=next(self.objects)
        if isinstance(item,Exception):raise item
        return item
class Tests(unittest.TestCase):
    def setUp(self):
        guard=patch.object(socket,'socket',side_effect=AssertionError('No live sockets'));guard.start();self.addCleanup(guard.stop)
    def test_ids(self):self.assertEqual(parse_counter_ids('1, 0002;123456789012345\n1 3'),['1','2','123456789012345','3'])
    def test_bad_ids(self):
        for text in ('','0','-1','1.2','1x','1/2','1\x00','１２','1 '*9000):
            with self.subTest(text=text[:20]),self.assertRaises(MetricaError):parse_counter_ids(text)
    def test_many_ids(self):
        with self.assertRaises(MetricaError):parse_counter_ids(' '.join(str(x) for x in range(1,502)))
    def test_list_pagination(self):
        first=[dict(COUNTER,id=x) for x in range(1,101)];second=[dict(COUNTER,id=101)]
        http=FakeHTTP([{'rows':101,'counters':first},{'rows':101,'counters':second}])
        self.assertEqual(len(list_counters(lambda:'synthetic',http)),101);self.assertEqual(http.calls[1][1]['offset'],101)
    def test_empty_list(self):self.assertEqual(list_counters(lambda:'fake',FakeHTTP([{'rows':0,'counters':[]}])),[])
    def test_broken_pagination(self):
        for pages in ([{'rows':1,'counters':[]}],[{'rows':2,'counters':[COUNTER]},{'rows':2,'counters':[COUNTER]}]):
            with self.assertRaises(MetricaError):list_counters(lambda:'fake',FakeHTTP(pages))
    def test_zero_exact_distinct_missing(self):
        http=FakeHTTP([{'counter':COUNTER},response(0)])
        result=weekly_report(lambda:'fake',http,'123',PERIOD)
        self.assertEqual(result['users'],0);self.assertTrue(result['exact']);self.assertEqual(result['status'],'ok');self.assertEqual(result['dataLag'],120)
        self.assertEqual(http.calls[-1][1]['timezone'],'+03:00');self.assertEqual(http.calls[-1][1]['accuracy'],'full')
        missing=weekly_report(lambda:'fake',FakeHTTP([MetricaError('HTTP_403')]),'123',PERIOD)
        self.assertIsNone(missing['users']);self.assertEqual(missing['errorCode'],'HTTP_403')
    def test_sampling(self):
        result=parse_users(response(12.5,sampled=True,sample_share=.1),dict(period_params(PERIOD),ids='123'));self.assertFalse(result['exact']);self.assertEqual(result['users'],12.5)
        obj=response();del obj['sampled'];self.assertFalse(parse_users(obj,dict(period_params(PERIOD),ids='123'))['exact'])
    def test_reject_bad_stats(self):
        objects=[response(float('nan')),response(-1),response(True),response(1,sample_share=2),response(1,data_lag=-1),response(1,sampled='false'),response(1,totals=[]),response(1.5)]
        bad=response();bad['query']['metrics']=['ym:s:visits'];objects.append(bad)
        for obj in objects:
            with self.assertRaises(MetricaError):parse_users(obj,dict(period_params(PERIOD),ids='123'))
    def test_untrusted_error_never_exposed(self):
        result=weekly_report(lambda:'fake',FakeHTTP([ValueError('secret echo')]),'123',PERIOD)
        self.assertNotIn('secret',str(result));self.assertIsNone(result['users'])
    def test_counter_mismatch(self):
        result=weekly_report(lambda:'fake',FakeHTTP([{'counter':dict(COUNTER,id=124)}]),'123',PERIOD)
        self.assertEqual(result['status'],'error')
    def test_counter_allowlist(self):
        self.assertEqual(set(safe_counter(dict(COUNTER,owner_login='private',secret='private'))),{'id','name','site'})
    def test_period_invalid(self):
        with self.assertRaises(MetricaError):period_params({'dateFrom':'2026-11-10','dateTo':'2026-11-16'})

class Corrections(unittest.TestCase):
    def test_very_long_id_without_int_conversion(self):
        value='9'*5000
        self.assertEqual(parse_counter_ids('000'+value+';'+value),[value])
    def test_total_limit_still_enforced(self):
        with self.assertRaises(MetricaError):parse_counter_ids('9'*16385)
    def test_query_ids_must_match(self):
        for ids in ([124],[],[123,124],None,['123x']):
            obj=response();obj['query']['ids']=ids
            with self.assertRaises(MetricaError):parse_users(obj,dict(period_params(PERIOD),ids='123'))
    def test_query_id_normalized(self):
        obj=response();obj['query']['ids']=['000123']
        self.assertEqual(parse_users(obj,dict(period_params(PERIOD),ids='123'))['users'],0)
    def test_error_message_safe_and_readable(self):
        obj=weekly_report(lambda:'fake',FakeHTTP([MetricaError('HTTP_403')]),'123',PERIOD)
        self.assertEqual(obj['errorCode'],'HTTP_403');self.assertIn('нет доступа',obj['error']);self.assertEqual(obj['error'],obj['errorMessage'])
