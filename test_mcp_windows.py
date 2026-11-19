import io,json,unittest,subprocess,os,sys
from unittest.mock import Mock
from mcp_windows import WindowsReportService,create_server
from network_adapter import Response
from report_core import InvalidReport
from server import main
TOKEN='SYNTHETIC_NOT_A_REAL_TOKEN'
class Tests(unittest.TestCase):
    def service(self,login='synthetic'):
        h=Mock();h.post.side_effect=[
            Response(200,{},json.dumps({'result':{'Clients':[{'ClientId':123,'Login':login,'Currency':'RUB'}]}}).encode()),
            Response(200,{},b'CampaignId\tCampaignName\tClicks\tCost\n1\tSynthetic\t2\t100.90\n')]
        p=Mock(return_value=TOKEN)
        return WindowsReportService('123','synthetic',provider=p,http=h),p,h
    def test_success_pinned_no_secrets(self):
        s,p,h=self.service()
        r=s.run({'dateFrom':'2026-11-09','dateTo':'2026-11-15'})
        p.assert_called_once();self.assertTrue(r['vatIncluded']);self.assertNotIn(TOKEN,json.dumps(r))
        self.assertEqual(h.post.call_count,2)
    def test_wrong_account_stops_report(self):
        s,p,h=self.service('other')
        with self.assertRaises(InvalidReport):s.run({'dateFrom':'2026-11-09','dateTo':'2026-11-15'})
        self.assertEqual(h.post.call_count,1)
    def test_invalid_args_no_credentials(self):
        s,p,h=self.service()
        with self.assertRaises(InvalidReport):s.run({'url':'evil'})
        p.assert_not_called();h.post.assert_not_called()
    def test_error_redaction(self):
        s,p,h=self.service();p.side_effect=RuntimeError(TOKEN)
        with self.assertRaises(InvalidReport) as e:s.run({'dateFrom':'2026-11-09','dateTo':'2026-11-15'})
        self.assertNotIn(TOKEN,str(e.exception))
    def test_missing_binding(self):
        with self.assertRaises(InvalidReport):create_server({})
    def test_handshake_no_credential_access(self):
        env={'AFINA_DIRECT_ADVERTISER_ID':'123','AFINA_DIRECT_LOGIN':'synthetic'}
        s=create_server(env)
        frames=[{'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-11-25'}},
                {'jsonrpc':'2.0','method':'notifications/initialized'},
                {'jsonrpc':'2.0','id':2,'method':'tools/list'}]
        out=io.StringIO()
        main(io.BytesIO(('\n'.join(map(json.dumps,frames))+'\n').encode()),out,server=s)
        responses=[json.loads(x) for x in out.getvalue().splitlines()]
        self.assertEqual(len(responses),2)
        t=responses[1]['result']['tools']
        self.assertEqual(len(t),1);self.assertTrue(t[0]['annotations']['readOnlyHint'])
        self.assertIn('INCLUDING VAT',t[0]['description'])
    def test_actual_subprocess_handshake(self):
        env=dict(os.environ,AFINA_DIRECT_ADVERTISER_ID='123',AFINA_DIRECT_LOGIN='synthetic',AFINA_DIRECT_LIVE='0')
        req={'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-11-25'}}
        p=subprocess.run([sys.executable,'-E','-s','mcp_windows.py'],input=json.dumps(req)+'\n',text=True,capture_output=True,env=env,timeout=5)
        self.assertEqual(p.returncode,0);self.assertEqual(p.stderr,'')
        self.assertEqual(json.loads(p.stdout)['id'],1)
