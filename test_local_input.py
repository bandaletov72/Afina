import unittest
from unittest.mock import Mock
from types import SimpleNamespace
from local_input import install_paste
class Tests(unittest.TestCase):
    def setUp(self):
        self.entry=Mock(); self.paste=install_paste(self.entry)
        self.bindings=dict(c.args for c in self.entry.bind.call_args_list)
    def test_button(self):
        self.assertEqual(self.paste(),'break')
        self.entry.event_generate.assert_called_once_with('<<Paste>>')
        self.entry.clipboard_get.assert_not_called()
    def test_russian_key(self):
        r=self.bindings['<Control-KeyPress>'](SimpleNamespace(keycode=86,keysym='Cyrillic_em'))
        self.assertEqual(r,'break');self.entry.event_generate.assert_called_once_with('<<Paste>>')
    def test_english(self):
        self.assertEqual(self.bindings['<Control-KeyPress>'](SimpleNamespace(keycode=86,keysym='v')),'break')
    def test_other_control_unchanged(self):
        self.assertIsNone(self.bindings['<Control-KeyPress>'](SimpleNamespace(keycode=67,keysym='c')))
        self.entry.event_generate.assert_not_called()
    def test_shift_insert(self):
        self.assertEqual(self.bindings['<Shift-Insert>'](None),'break')

class CodeTests(unittest.TestCase):
    def test_opaque_code(self):
        from local_input import normalize_code
        for value in ['AbCdEf0123456789','1234567','abc_-+/=.:!','кодABC','１２３４５６７','a'*512]:
            self.assertEqual(normalize_code(value),value)
    def test_trim_edges(self):
        from local_input import normalize_code
        self.assertEqual(normalize_code(' \nAbCdEf0123456789\r\n '),'AbCdEf0123456789')
    def test_reject_unsafe_or_empty(self):
        from local_input import normalize_code
        for value in [None,'',' '*3,'x'*513,'a b','a\nb','a\x00b','a\u202eb','https://example.test']:
            with self.assertRaises(ValueError):normalize_code(value)
