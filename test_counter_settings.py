import json
import os
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch,MagicMock
from counter_settings import load_counter_list,save_counter_list,HISTORICAL_IDS
from metrica_ui import MetricaView

class CounterSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'counters.json'
        self.guard=patch.object(socket,'socket',side_effect=AssertionError('No network'));self.guard.start();self.addCleanup(self.guard.stop)
    def test_first_start_only_defaults_no_write(self):
        self.assertEqual(load_counter_list(self.path)['ids'],HISTORICAL_IDS);self.assertFalse(self.path.exists())
    def test_save_restart_edit_restart(self):
        self.assertEqual(save_counter_list('001;2\n1',self.path),['1','2'])
        self.assertEqual(load_counter_list(self.path)['ids'],['1','2'])
        save_counter_list('3 4',self.path);self.assertEqual(load_counter_list(self.path)['ids'],['3','4'])
    def test_clear_survives_restart(self):
        save_counter_list('1',self.path);save_counter_list(' \n',self.path)
        loaded=load_counter_list(self.path);self.assertEqual(loaded['ids'],[]);self.assertEqual(loaded['source'],'saved')
    def test_invalid_edit_preserves_saved(self):
        save_counter_list('1',self.path)
        with self.assertRaises(ValueError):save_counter_list('2 nope',self.path)
        self.assertEqual(load_counter_list(self.path)['ids'],['1'])
    def test_atomic_failure_preserves_saved(self):
        save_counter_list('1',self.path)
        with patch('counter_settings.os.replace',side_effect=OSError('denied')):
            with self.assertRaises(OSError):save_counter_list('2',self.path)
        self.assertEqual(load_counter_list(self.path)['ids'],['1']);self.assertEqual(list(self.path.parent.glob('*.tmp')),[])
    def test_corruption_not_replaced_by_defaults(self):
        self.path.write_text('{bad');loaded=load_counter_list(self.path)
        self.assertEqual(loaded['source'],'error');self.assertEqual(loaded['ids'],[]);self.assertEqual(self.path.read_text(),'{bad')
    def test_only_ids_schema(self):
        save_counter_list('1 2',self.path);obj=json.loads(self.path.read_text())
        self.assertEqual(obj,{'version':1,'ids':['1','2']})
    def test_ui_save_and_clear_in_both_modes(self):
        with patch.dict(os.environ,{'LOCALAPPDATA':self.temp.name}):
            for demo in (True,False):
                view=MetricaView.__new__(MetricaView);view.busy=False;view.demo=demo;view.ids=MagicMock();view.ids_note=MagicMock();view.status=MagicMock()
                view.counter_revision=load_counter_list()['revision'];view.ids.get.return_value='7\n8';view.save_ids();self.assertEqual(load_counter_list()['ids'],['7','8'])
                self.assertIn('Сохранено',view.status.set.call_args.args[0])
                view.ids.get.return_value='';view.save_ids();self.assertEqual(load_counter_list()['ids'],[])
                self.assertIn('Пустой',view.status.set.call_args.args[0])
    def test_startup_loads_saved_in_both_modes(self):
        import metrica_ui
        def widget(*a,**kw):
            obj=MagicMock();obj.winfo_children.return_value=[];return obj
        patches=[patch.object(metrica_ui.tk,n,side_effect=widget) for n in ('Frame','Label','StringVar','Text','Listbox')]
        patches += [patch.object(metrica_ui.ttk,n,side_effect=widget) for n in ('Button','Entry','Treeview','Scrollbar')]
        for p in patches:p.start();self.addCleanup(p.stop)
        with patch.dict(os.environ,{'LOCALAPPDATA':self.temp.name}),patch('metrica_ui.load_client_id',return_value=''),patch('metrica_auth.MetricaStore',side_effect=AssertionError('No credentials')):
            save_counter_list('7 8')
            for demo in (True,False):
                app=MagicMock();app.demo=demo;view=MetricaView(app)
                view.ids.insert.assert_called_with('1.0','7\n8');view.close()

if __name__=='__main__':unittest.main()

class CounterConflictTests(unittest.TestCase):
    def test_stale_revision_cannot_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'ids.json';old=load_counter_list(path)['revision']
            save_counter_list('1',path,expected_revision=old)
            with self.assertRaises(ValueError):save_counter_list('2',path,expected_revision=old)
            self.assertEqual(load_counter_list(path)['ids'],['1'])
    def test_refresh_then_save(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'ids.json';save_counter_list('1',path)
            revision=load_counter_list(path)['revision'];save_counter_list('2',path,expected_revision=revision)
            self.assertEqual(load_counter_list(path)['ids'],['2'])
    def test_other_process_lock_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'ids.json';save_counter_list('1',path);path.with_name('ids.json.lock').write_text('')
            with self.assertRaises(ValueError):save_counter_list('2',path)
            self.assertEqual(load_counter_list(path)['ids'],['1'])
