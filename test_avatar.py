import unittest
from unittest.mock import Mock,patch
from types import SimpleNamespace
from pathlib import Path
import struct
class Tests(unittest.TestCase):
    def test_resource_dimensions(self):
        data=(Path(__file__).parent/'assets'/'afina_avatar.png').read_bytes()
        self.assertEqual(data[:8],b'\x89PNG\r\n\x1a\n')
        self.assertEqual(struct.unpack('>II',data[16:24]),(512,512))
    def test_display_scale_and_retention(self):
        from avatar_ui import add_avatar
        source=Mock();label=Mock();window=Mock()
        fake=SimpleNamespace(PhotoImage=Mock(return_value=source),Label=Mock(return_value=label))
        with patch.dict('sys.modules',{'tkinter':fake}):
            self.assertIs(add_avatar(window),label)
        source.subsample.assert_called_once_with(4,4)
        self.assertIs(window._afina_avatar,source.subsample.return_value)
        self.assertTrue(fake.PhotoImage.call_args.kwargs['file'].endswith('assets/afina_avatar.png'))
