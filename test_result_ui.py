import unittest,json
from unittest.mock import Mock
from types import SimpleNamespace
from result_ui import report_text,install_copy
class Tests(unittest.TestCase):
    def result(self):
        from report_core import parse_report
        r=parse_report(b'CampaignId\tCampaignName\tClicks\tCost\n1\tSynthetic\t2\t100.90\n')
        r['period']={'dateFrom':'2026-11-09','dateTo':'2026-11-15'}
        return r
    def test_extra_secrets_omitted(self):
        r=self.result();r['access_token']='SYNTHETIC_SECRET';r['error']='SYNTHETIC_SECRET'
        r['rows'][0]['debug']='SYNTHETIC_SECRET'
        a={'clientId':'1','login':'synthetic','currency':'RUB','refresh_token':'SYNTHETIC_SECRET'}
        text=report_text(a,r)
        self.assertNotIn('SYNTHETIC_SECRET',text);self.assertTrue(json.loads(text)['vatIncluded'])
    def test_incomplete_or_no_vat_rejected(self):
        for k in ['complete','vatIncluded']:
            r=self.result();r[k]=False
            with self.assertRaises(ValueError):report_text({},r)
    def setup_copy(self):
        window,text,status=Mock(),Mock(),Mock()
        copy=install_copy(window,text,'safe-report',status)
        return window,text,status,copy,text.bind.call_args.args[1]
    def test_button(self):
        w,t,s,copy,key=self.setup_copy();copy()
        w.clipboard_append.assert_called_once_with('safe-report')
    def test_russian_ctrl_c_selection(self):
        w,t,s,copy,key=self.setup_copy();t.get.return_value='selected'
        self.assertEqual(key(SimpleNamespace(keycode=67,keysym='Cyrillic_es')),'break')
        w.clipboard_append.assert_called_once_with('selected')
    def test_no_selection_copies_report(self):
        w,t,s,copy,key=self.setup_copy();t.get.side_effect=Exception()
        key(SimpleNamespace(keycode=67,keysym='c'))
        w.clipboard_append.assert_called_once_with('safe-report')
    def test_ctrl_a(self):
        w,t,s,copy,key=self.setup_copy()
        self.assertEqual(key(SimpleNamespace(keycode=65,keysym='Cyrillic_ef')),'break')
        t.tag_add.assert_called_once_with('sel','1.0','end-1c')
    def test_clipboard_error_safe(self):
        w,t,s,copy,key=self.setup_copy();w.clipboard_append.side_effect=Exception('SYNTHETIC_SECRET')
        copy();self.assertNotIn('SYNTHETIC_SECRET',str(s.configure.call_args))
