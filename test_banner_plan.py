import struct
import tempfile
from pathlib import Path
import unittest
from unittest.mock import MagicMock,patch
import socket
from banner_plan import inspect_image,make_plan,replacement_route
from ads_ui import AdsView

class BannerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.guard=patch.object(socket,'socket',side_effect=AssertionError('No network'));self.guard.start();self.addCleanup(self.guard.stop)
    def image(self):
        p=Path(self.tmp.name)/'test.png';p.write_bytes(b'\x89PNG\r\n\x1a\n'+b'\x00\x00\x00\rIHDR'+struct.pack('>II',320,180)+b'\x08\x02\x00\x00\x00'+b'0000');return inspect_image(p)
    def test_header_metadata_only_no_path_or_bytes(self):
        image=self.image();self.assertEqual((image['width'],image['height']),(320,180));self.assertEqual(len(image['sha256']),64);self.assertNotIn('path',image);self.assertNotIn('bytes',image)
    def test_draft_preserves_slots_and_not_sent(self):
        ad={'id':'1','campaignId':'2','adGroupId':'3','type':'RESPONSIVE_AD','subtype':'NONE','images':['old-a','old-b','old-c']}
        plan=make_plan({'clientId':'4','login':'test'},ad,self.image(),1)
        self.assertEqual(plan['replaceHash'],'old-b');self.assertEqual(plan['currentImages'],['old-a','old-b','old-c']);self.assertFalse(plan['sentToYandex']);self.assertEqual(plan['status'],'DRAFT_NOT_SENT')
    def test_creative_not_treated_as_jpg(self):
        ad={'type':'CPM_BANNER_AD','subtype':'NONE','images':['old']}
        with self.assertRaises(ValueError):make_plan({'clientId':'1','login':'test'},ad,self.image(),0)
    def test_invalid_slot(self):
        with self.assertRaises(ValueError):make_plan({'clientId':'1','login':'test'},{'type':'TEXT_AD','images':['a']},self.image(),1)
    def test_select_closes_old_draft_panel(self):
        view=AdsView.__new__(AdsView);view.busy=False;view.clear_panel=MagicMock();view.selected=MagicMock(return_value=None);view.save_button=MagicMock();view.select();view.clear_panel.assert_called_once();self.assertIsNone(view.plan)
    def test_demo_no_credentials(self):
        import ads_ui
        def widget(*a,**kw):
            obj=MagicMock();obj.winfo_children.return_value=[];obj.get_children.return_value=[];return obj
        patches=[patch.object(ads_ui.tk,n,side_effect=widget) for n in ('Frame','Label','StringVar')]
        patches += [patch.object(ads_ui.ttk,n,side_effect=widget) for n in ('Button','Entry','Treeview','Scrollbar','Combobox')]
        for p in patches:p.start();self.addCleanup(p.stop)
        with patch('windows_credentials.CredentialStore',side_effect=AssertionError('No credentials')):
            app=MagicMock();app.demo=True;app.result=None;view=AdsView(app);self.assertEqual(len(view.data['ads']),1);view.close()
