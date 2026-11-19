import unittest
from unittest.mock import patch, MagicMock
from datetime import date
from decimal import Decimal
import queue
import socket
from desktop import previous_week,period_from_start,number,cpc,csv_text,Dashboard
from report_core import parse_report

class DesktopTests(unittest.TestCase):
    def setUp(self):
        self.net=patch.object(socket,'socket',side_effect=AssertionError('No networking in offline tests'));self.net.start();self.addCleanup(self.net.stop)
        self.account={'clientId':'1','login':'test','currency':'RUB'}
        self.result=parse_report(b'CampaignId\tCampaignName\tClicks\tCost\n1\t=test\t3\t10.99\n2\tSafe\t2\t10.99\n')
        self.result.update(period=period_from_start('2026-11-09'),currency='RUB',secret='must-not-copy')
    def test_previous_week_cross_year(self):
        self.assertEqual(previous_week(date(2026,1,1)),{'dateFrom':'2025-12-22','dateTo':'2025-12-28'})
    def test_monday_sunday(self):
        self.assertEqual(period_from_start('2026-11-09')['dateTo'],'2026-11-15')
        with self.assertRaises(ValueError):period_from_start('2026-11-10')
    def test_formats(self):
        self.assertEqual(number('123456.78',2),'123 456,78');self.assertEqual(cpc(self.result),Decimal('4.396'))
        self.result['totals']['clicks']=0;self.assertIsNone(cpc(self.result))
    def test_export_safe(self):
        text=csv_text(self.account,self.result)
        self.assertIn("'=test",text);self.assertNotIn('must-not-copy',text);self.assertIn('21.98;21',text)
        self.assertIn('\t',csv_text(self.account,self.result,delimiter='\t'))
    def test_export_rejects_partial(self):
        self.result['complete']=False
        with self.assertRaises(ValueError):csv_text(self.account,self.result)
    def app(self):
        app=Dashboard.__new__(Dashboard);app.root=MagicMock();app.closed=False;app.generation=1;app.events=queue.Queue();app.set_busy=MagicMock();app.status=MagicMock();app.confirm_inline=MagicMock();app.background=MagicMock();app.pending_period=period_from_start('2026-11-09');app.result=self.result;return app
    def test_late_result_ignored(self):
        app=self.app();app.events.put((0,'report',(self.account,self.result)));app.display=MagicMock();app.poll();app.display.assert_not_called()
    def test_identity_cancel_no_report(self):
        app=self.app();app.events.put((1,'identity',(self.account,lambda:'synthetic')));app.poll();app.confirm_inline.call_args.args[2]();app.background.assert_not_called();app.set_busy.assert_called_with(False)
    def test_error_keeps_last_report(self):
        app=self.app();app.events.put((1,'error',None));app.poll();self.assertIs(app.result,self.result);app.set_busy.assert_called_with(False)
    def test_repeated_fetch_ignored(self):
        app=self.app();app.busy=True;app.fetch();app.background.assert_not_called()
    def test_close_invalidates_events(self):
        app=self.app();app.close();self.assertTrue(app.closed);self.assertEqual(app.generation,2);app.root.destroy.assert_called_once()
    def test_authorized_updates_id(self):
        app=self.app();app.events.put((1,'authorized','public-id'));app.poll();self.assertEqual(app.client_id,'public-id');self.assertIsNone(app.pending_auth)
    def test_no_popup_dialogs(self):
        from pathlib import Path
        source=Path(__file__).with_name('desktop.py').read_text()
        self.assertNotIn('messagebox',source);self.assertNotIn('Toplevel',source);self.assertNotIn('filedialog',source)

if __name__=='__main__':unittest.main()

class ReviewRegressionTests(unittest.TestCase):
    def test_busy_disables_export_and_copy(self):
        app=Dashboard.__new__(Dashboard);app.result={}
        for name in ('auth','load','prev','entry','export','copy'):setattr(app,name,MagicMock())
        app.set_busy(True)
        app.export.configure.assert_called_with(state='disabled')
        app.copy.configure.assert_called_with(state='disabled')
        app.set_busy(False)
        app.export.configure.assert_called_with(state='normal')
    def test_busy_export_cannot_replace_confirmation(self):
        app=Dashboard.__new__(Dashboard);app.busy=True;app.result={};app.panel_text=MagicMock()
        app.save();app.panel_text.assert_not_called()
    def test_cancel_wipes_pending_verifier(self):
        from oauth_prepare import Pending
        app=Dashboard.__new__(Dashboard);pending=Pending('a'*32,'unused','synthetic-verifier','',0)
        app.pending_auth=pending;app.clear_panel=MagicMock();app.set_busy=MagicMock();app.status=MagicMock()
        app.cancel_authorization()
        self.assertIsNone(app.pending_auth);self.assertTrue(pending.consumed);self.assertEqual(pending.verifier,'')
        app.set_busy.assert_called_with(False)

class CredentialSnapshotTests(unittest.TestCase):
    def test_account_and_report_use_one_snapshot(self):
        app=Dashboard.__new__(Dashboard)
        app.busy=False;app.demo=False;app.client_id='a'*32;app.start=MagicMock();app.start.get.return_value='2026-11-09'
        app.set_busy=MagicMock();app.status=MagicMock();app.background=MagicMock()
        app.root=MagicMock();app.closed=False;app.generation=1;app.events=queue.Queue();app.confirm_inline=MagicMock()
        account={'clientId':'1','login':'original','currency':'RUB'}
        store=MagicMock();store.access_token.side_effect=['original-token','replacement-token']
        with patch('windows_credentials.CredentialStore',return_value=store),patch('verify_direct.identity',side_effect=lambda provider,http: account if provider()=='original-token' else None):
            app.fetch();identity_fn=app.background.call_args.args[1]
            returned=identity_fn();self.assertEqual(returned[0],account)
            app.events.put((1,'identity',returned));app.poll()
            class Transport:
                def __init__(self,provider,**kwargs):self.provider=provider
                def fetch(self,request):
                    assert self.provider()=='original-token'
                    return b'CampaignId\tCampaignName\tClicks\tCost\n1\tOriginal\t1\t1.00\n'
            with patch('network_adapter.ReportsTransport',Transport),patch.object(socket,'socket',side_effect=AssertionError('network forbidden')):
                app.confirm_inline.call_args.args[1]()
                report_fn=app.background.call_args.args[1]
                result=report_fn()
            self.assertEqual(result[0]['login'],'original');store.access_token.assert_called_once()
            app.display=MagicMock();app.events.put((1,'report',result));app.poll();self.assertIsNone(app.session_provider)

class EarlyCredentialTests(unittest.TestCase):
    def test_storage_checked_before_oauth_prepare(self):
        from desktop import prepare_authorization
        with patch('oauth_screen.begin_screen') as begin:
            with self.assertRaises(OSError):prepare_authorization('a'*32,store_factory=MagicMock(side_effect=OSError('blocked')))
            begin.assert_not_called()
    def test_credential_error_is_actionable(self):
        app=Dashboard.__new__(Dashboard);app.closed=False;app.generation=1;app.events=queue.Queue();app.root=MagicMock();app.set_busy=MagicMock();app.status=MagicMock()
        app.events.put((1,'credential_error',None));app.poll()
        self.assertIn('истекла',app.status.set.call_args.args[0]);self.assertIsNone(app.session_provider)
