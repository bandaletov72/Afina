import unittest,json
from unittest.mock import Mock
from verify_direct import identity,report,PERIOD
from network_adapter import Response,CLIENTS_ENDPOINT,CLIENTS_BODY,FixedHTTPS
from report_core import InvalidReport
TOKEN='SYNTHETIC_NOT_A_REAL_TOKEN'
class Tests(unittest.TestCase):
    def fake(self,data,status=200):
        h=Mock();h.post.return_value=Response(status,{},json.dumps(data).encode());return h
    def test_identity_fixed_query(self):
        h=self.fake({'result':{'Clients':[{'ClientId':123,'Login':'synthetic-user','Currency':'RUB','Extra':'ignored'}]}})
        r=identity(lambda:TOKEN,h)
        self.assertEqual(r,{'clientId':'123','login':'synthetic-user','currency':'RUB'})
        args=h.post.call_args.args
        self.assertEqual(args[0],CLIENTS_ENDPOINT);self.assertEqual(json.loads(args[2]),CLIENTS_BODY)
        self.assertNotIn('Client-Login',args[1]);self.assertNotIn(TOKEN,str(r))
    def test_bad_identity_rejected(self):
        for data in [{'error':{'message':TOKEN}}, {'result':{'Clients':[]}},
                     {'result':{'Clients':[{'ClientId':1,'Login':'bad\n','Currency':'RUB'}]}},
                     {'result':{'Clients':[{'ClientId':1,'Login':'ok','Currency':None}]}}]:
            with self.assertRaises(InvalidReport) as c:identity(lambda:TOKEN,self.fake(data))
            self.assertNotIn(TOKEN,str(c.exception))
    def test_http_failure(self):
        with self.assertRaises(InvalidReport):identity(lambda:TOKEN,self.fake({},403))
    def test_report_period_vat(self):
        h=Mock();h.post.return_value=Response(200,{},b'CampaignId\tCampaignName\tClicks\tCost\n1\tSynthetic\t2\t100.90\n')
        r=report(lambda:TOKEN,h,{'currency':'RUB'})
        self.assertEqual(r['period'],PERIOD);self.assertEqual(r['totals']['costExact'],'100.90')
        self.assertTrue(r['vatIncluded']);self.assertEqual(r['currency'],'RUB');self.assertNotIn('offline',r['provenance'])
        body=json.loads(h.post.call_args.args[2])
        self.assertEqual(body['params']['IncludeVAT'],'YES')
    def test_clients_write_forbidden(self):
        with self.assertRaises(InvalidReport):
            FixedHTTPS(live_enabled=True).post(CLIENTS_ENDPOINT,{},b'{"method":"update"}',100,1)

class SavedAuthTests(unittest.TestCase):
    def test_available_local_only(self):
        from verify_direct import stored_authorization_available,KNOWN_CLIENT_ID
        factory=Mock();factory.return_value.access_token.return_value=TOKEN
        self.assertIs(stored_authorization_available(KNOWN_CLIENT_ID,factory),True)
        factory.assert_called_once_with(KNOWN_CLIENT_ID)
        self.assertNotEqual(stored_authorization_available(KNOWN_CLIENT_ID,factory),TOKEN)
    def test_unavailable_redacted(self):
        from verify_direct import stored_authorization_available,KNOWN_CLIENT_ID
        factory=Mock();factory.return_value.access_token.side_effect=RuntimeError(TOKEN)
        self.assertIs(stored_authorization_available(KNOWN_CLIENT_ID,factory),False)

class SelectionTests(unittest.TestCase):
    def run_selection(self, action, available=True, other=None):
        from unittest.mock import patch
        from types import SimpleNamespace
        import verify_direct
        parent=Mock();window=Mock();buttons={}
        def button(*a,**kw):
            buttons[kw['text']]=kw
            return Mock()
        fake=SimpleNamespace(Toplevel=Mock(return_value=window),Label=Mock(),Button=button,PhotoImage=Mock())
        def waiting(w):
            if action: buttons[action]['command']()
        parent.wait_window.side_effect=waiting
        with patch.dict('sys.modules',{'tkinter':fake}), patch.object(verify_direct,'stored_authorization_available',return_value=available), patch.object(verify_direct,'ask_local_value',return_value=other):
            value=verify_direct.select_client_id(parent)
        return value,buttons
    def test_existing_selection(self):
        from verify_direct import KNOWN_CLIENT_ID
        value,_=self.run_selection('Использовать сохранённую авторизацию Афины')
        self.assertEqual(value,KNOWN_CLIENT_ID)
    def test_cancel(self):
        value,_=self.run_selection('Отмена')
        self.assertIsNone(value)
    def test_other(self):
        value,_=self.run_selection('Указать другой Client ID',other='b'*32)
        self.assertEqual(value,'b'*32)
    def test_absent_disabled(self):
        value,b=self.run_selection(None,available=False)
        self.assertIsNone(value)
        self.assertEqual(b['Использовать сохранённую авторизацию Афины']['state'],'disabled')

class ReauthorizeTests(unittest.TestCase):
    def test_cancel_id_no_action(self):
        from verify_direct import reauthorize_local
        confirm=Mock();auth=Mock()
        self.assertIsNone(reauthorize_local(None,confirm_delete=lambda:True,delete_saved=lambda:None,prompt=lambda:None,confirm=confirm,authorize=auth))
        confirm.assert_not_called();auth.assert_not_called()
    def test_decline_replacement_no_action(self):
        from verify_direct import reauthorize_local
        auth=Mock()
        self.assertIsNone(reauthorize_local(None,confirm_delete=lambda:True,delete_saved=lambda:None,prompt=lambda:'a'*32,confirm=lambda:False,authorize=auth))
        auth.assert_not_called()
    def test_code_cancel_retains_old(self):
        from verify_direct import reauthorize_local
        auth=Mock(return_value=False)
        self.assertIsNone(reauthorize_local(None,confirm_delete=lambda:True,delete_saved=lambda:None,prompt=lambda:'a'*32,confirm=lambda:True,authorize=auth))
        auth.assert_called_once_with('a'*32)
    def test_confirm_success(self):
        from verify_direct import reauthorize_local
        auth=Mock(return_value=True)
        self.assertEqual(reauthorize_local(None,confirm_delete=lambda:True,delete_saved=lambda:None,prompt=lambda:'a'*32,confirm=lambda:True,authorize=auth),'a'*32)
    def test_cancel_keeps_existing_credential(self):
        from oauth_screen import authorize_local
        from windows_credentials import CredentialStore
        from oauth_prepare import TokenBundle
        from test_windows_credentials import FakeVault
        store=CredentialStore('a'*32,backend=FakeVault(),clock=lambda:100)
        store.save(TokenBundle(TOKEN,3600))
        http=Mock()
        self.assertFalse(authorize_local('a'*32,secure_store=store.save,http=http,
            browser_opener=lambda _:True,prompt=lambda:None))
        self.assertEqual(store.access_token(),TOKEN)
        http.post.assert_not_called()


class DeleteReauthTests(unittest.TestCase):
    def test_decline_delete_no_changes(self):
        from verify_direct import reauthorize_local
        delete=Mock();prompt=Mock();auth=Mock()
        self.assertIsNone(reauthorize_local(None,confirm_delete=lambda:False,
            delete_saved=delete,prompt=prompt,authorize=auth))
        delete.assert_not_called();prompt.assert_not_called();auth.assert_not_called()
    def test_delete_precedes_prompt_and_cancel(self):
        from verify_direct import reauthorize_local
        events=[]
        self.assertIsNone(reauthorize_local(None,confirm_delete=lambda:True,
            delete_saved=lambda:events.append('delete'),
            prompt=lambda:events.append('prompt')))
        self.assertEqual(events,['delete','prompt'])
    def test_delete_failure_stops_new_auth(self):
        from verify_direct import reauthorize_local
        prompt=Mock()
        with self.assertRaises(RuntimeError):
            reauthorize_local(None,confirm_delete=lambda:True,
                delete_saved=Mock(side_effect=RuntimeError('synthetic')),prompt=prompt)
        prompt.assert_not_called()
