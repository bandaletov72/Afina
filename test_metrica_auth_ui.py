import json
import socket
import unittest
from unittest.mock import patch,MagicMock
from urllib.parse import urlsplit,parse_qs
from network_adapter import Response
from oauth_prepare import TokenBundle
from metrica_auth import begin,finish,MetricaStore
from metrica_ui import export_results,MetricaView

class MetricaAuthTests(unittest.TestCase):
    def setUp(self):
        self.network=patch.object(socket,'socket',side_effect=AssertionError('No real network'));self.network.start();self.addCleanup(self.network.stop)
    def test_minimal_scope_and_pkce(self):
        pending,url=begin('a'*32,store_factory=MagicMock())
        q=parse_qs(urlsplit(url).query)
        self.assertEqual(q['scope'],['metrika:read']);self.assertEqual(q['code_challenge_method'],['S256'])
        self.assertNotIn('direct:api',url)
    def test_backend_before_prepare(self):
        with patch('metrica_auth.begin_screen') as prepare:
            with self.assertRaises(OSError):begin('a'*32,store_factory=MagicMock(side_effect=OSError()))
            prepare.assert_not_called()
    def test_isolated_credential_key(self):
        backend=MagicMock();store=MetricaStore('a'*32,backend=backend)
        self.assertEqual(store.target,'Afina/YandexMetrica/'+'a'*32)
        backend.read.assert_not_called();store.delete();backend.delete.assert_called_once_with(store.target)
    def test_read_scope_exchange(self):
        pending,_=begin('a'*32,store_factory=MagicMock())
        http=MagicMock();http.post.return_value=Response(200,{},json.dumps({'access_token':'synthetic-token-value','expires_in':3600,'scope':'metrika:read'}).encode())
        result=finish(pending,'sixteencharacters',http)
        self.assertIsInstance(result,TokenBundle);self.assertTrue(pending.consumed);self.assertEqual(pending.verifier,'')
    def test_extra_scope_rejected(self):
        pending,_=begin('a'*32,store_factory=MagicMock());http=MagicMock()
        http.post.return_value=Response(200,{},json.dumps({'access_token':'synthetic-token-value','expires_in':3600,'scope':'metrika:read metrika:write'}).encode())
        with self.assertRaises(ValueError):finish(pending,'synthetic-code',http)
        self.assertTrue(pending.consumed);self.assertEqual(pending.verifier,'')

class MetricaUITests(unittest.TestCase):
    def test_export_missing_is_not_zero(self):
        rows=[{'id':'1','period':{'dateFrom':'2026-11-09','dateTo':'2026-11-15'},'error':'Нет доступа'}]
        text=export_results(rows)
        self.assertIn('Нет доступа',text);self.assertNotIn(';0;',text)
    def test_export_formula_escape_and_metadata(self):
        rows=[{'id':'1','period':{'dateFrom':'2026-11-09','dateTo':'2026-11-15'},'result':{'counter':{'name':'=CMD()','site':'example.com'},'users':12,'exact':False,'sampleShare':0.5,'dataLag':120,'secret':'do-not-copy'}}]
        text=export_results(rows);self.assertIn("'=CMD()",text);self.assertIn('0.5;120',text);self.assertNotIn('do-not-copy',text)
    def test_busy_export_copy_noop(self):
        view=MetricaView.__new__(MetricaView);view.busy=True;view.results=[1];view.panel_text=MagicMock();view.root=MagicMock()
        view.copy();view.export();view.panel_text.assert_not_called();view.root.clipboard_clear.assert_not_called()
    def test_cancel_wipes_pending(self):
        view=MetricaView.__new__(MetricaView);view.pending=MagicMock();p=view.pending;view.clear_panel=MagicMock();view.set_busy=MagicMock();view.status=MagicMock()
        view.cancel_auth();self.assertEqual(p.verifier,'');self.assertTrue(p.consumed);self.assertIsNone(view.pending)
    def test_demo_constructs_without_access(self):
        import metrica_ui
        def widget(*a,**kw):
            obj=MagicMock();obj.winfo_children.return_value=[];return obj
        patches=[patch.object(metrica_ui.tk,n,side_effect=widget) for n in ('Frame','Label','StringVar','Text','Listbox')]
        patches += [patch.object(metrica_ui.ttk,n,side_effect=widget) for n in ('Button','Entry','Treeview','Scrollbar')]
        for p in patches:p.start();self.addCleanup(p.stop)
        with patch.object(socket,'socket',side_effect=AssertionError('No real network')),patch('metrica_auth.MetricaStore',side_effect=AssertionError('No credentials')),patch('metrica_ui.load_client_id',side_effect=AssertionError('No settings read')):
            app=MagicMock();app.demo=True;view=MetricaView(app);view.show();view.hide();view.close()
            self.assertTrue(view.closed);view.auth_button.configure.assert_called_with(state='disabled')

if __name__=='__main__':unittest.main()

class MetricaBatchTests(unittest.TestCase):
    def make_view(self):
        import queue,threading
        view=MetricaView.__new__(MetricaView);view.busy=False;view.demo=False;view.closed=False;view.client_id=MagicMock(return_value='a'*32)
        view.ids=MagicMock();view.ids.get.return_value='1,2,3';view.start=MagicMock();view.start.get.return_value='2026-11-09'
        view.period_display=MagicMock();view.clear_panel=MagicMock();view.set_busy=MagicMock();view.cancel_button=MagicMock();view.tree=MagicMock();view.tree.get_children.return_value=[]
        view.status=MagicMock();view.stop=threading.Event();view.events=queue.Queue();view.background=MagicMock();return view
    def test_separate_results_one_credential_snapshot(self):
        view=self.make_view();store=MagicMock();store.access_token.return_value='synthetic-token';view.fetch()
        def report(provider,http,cid,period):
            self.assertEqual(provider(),'synthetic-token')
            if cid=='2':return {'status':'error','error':'Нет доступа','users':None}
            return {'status':'ok','users':10,'counter':{'id':cid,'name':'test','site':'example.test'}}
        with patch.object(socket,'socket',side_effect=AssertionError('No network')),patch('metrica_auth.MetricaStore',return_value=store),patch('metrica_http.MetricaHTTP'),patch('metrica_core.weekly_report',side_effect=report):
            view.background.call_args.args[1]()
        rows=[view.events.get_nowait()[1] for _ in range(3)]
        self.assertEqual([r['id'] for r in rows],['1','2','3']);self.assertNotIn('result',rows[1]);self.assertEqual(rows[1]['error'],'Нет доступа');store.access_token.assert_called_once()
    def test_stop_marks_remaining_not_zero(self):
        view=self.make_view();view.fetch();view.stop.set();store=MagicMock();store.access_token.return_value='synthetic-token'
        with patch.object(socket,'socket',side_effect=AssertionError('No network')),patch('metrica_auth.MetricaStore',return_value=store),patch('metrica_http.MetricaHTTP'),patch('metrica_core.weekly_report') as report:
            view.background.call_args.args[1]();report.assert_not_called()
        for _ in range(3):
            item=view.events.get_nowait()[1];self.assertNotIn('result',item);self.assertIn('остановлено',item['error'])

class MetricaCloseTests(unittest.TestCase):
    def view(self):
        import threading
        view=MetricaView.__new__(MetricaView);view.auth_lock=threading.Lock();view.closed=False;view.auth_in_flight=False;view.stop=threading.Event();view.pending=MagicMock();return view
    def test_close_wipes_waiting_code_attempt(self):
        view=self.view();pending=view.pending;view.close();self.assertTrue(view.closed);self.assertEqual(pending.verifier,'');self.assertIsNone(view.pending)
    def test_close_during_exchange_prevents_save(self):
        view=self.view();view.auth_in_flight=True;pending=view.pending;factory=MagicMock()
        def finish_then_close(*args):view.close();return TokenBundle('synthetic-token',3600)
        with patch.object(socket,'socket',side_effect=AssertionError('No network')),patch('metrica_auth.finish',side_effect=finish_then_close):
            result=view.complete_authorization(pending,'synthetic-code','a'*32,http=MagicMock(),store_factory=factory)
        self.assertIsNone(result);factory.assert_not_called();self.assertEqual(pending.verifier,'');self.assertFalse(view.auth_in_flight)
