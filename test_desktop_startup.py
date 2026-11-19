"""Widget-level startup smoke tests without a display. Not a screenshot test."""
import unittest
from unittest.mock import MagicMock,patch
import socket
import desktop

class StartupTests(unittest.TestCase):
    def test_single_window_demo_no_credentials_or_network(self):
        widgets=[]
        def factory(*a,**kw):
            obj=MagicMock();obj.winfo_width.return_value=1000;obj.get_children.return_value=();obj.winfo_children.return_value=[]
            widgets.append(obj);return obj
        patches=[patch.object(desktop.tk,n,side_effect=factory) for n in ('Frame','Label','PhotoImage','StringVar','Canvas')]
        patches += [patch.object(desktop.ttk,n,side_effect=factory) for n in ('Style','Button','Entry','Treeview','Scrollbar')]
        for p in patches:p.start();self.addCleanup(p.stop)
        with patch.object(socket,'socket',side_effect=AssertionError('network forbidden')),patch('windows_credentials.CredentialStore',side_effect=AssertionError('credentials forbidden')):
            root=MagicMock();app=desktop.Dashboard(root,demo=True)
            self.assertTrue(app.demo);self.assertEqual(app.result['totals']['costExact'],'16000.75')
            self.assertEqual(app.tree.insert.call_count,2)
            app.auth.configure.assert_called_with(state='disabled')
            self.assertEqual(app.metrics[0].configure.call_args.kwargs['text'],'16 000 ₽')
            root.mainloop.assert_not_called()

if __name__=='__main__':unittest.main()
