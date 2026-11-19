import unittest
from unittest.mock import patch, Mock
import start_oauth
class Tests(unittest.TestCase):
    def test_nonwindows_no_action(self):
        with patch.object(start_oauth.sys,'platform','linux'), patch.object(start_oauth,'CredentialStore') as store:
            self.assertEqual(start_oauth.main(),2);store.assert_not_called()
    def test_synthetic_roundtrip_cleanup(self):
        store=Mock();store.access_token.return_value='SYNTHETIC_STORAGE_PROBE_ONLY'
        with patch.object(start_oauth,'CredentialStore',return_value=store):
            start_oauth.storage_self_test()
        store.save.assert_called_once();store.delete.assert_called_once()
    def test_synthetic_failure_cleanup(self):
        store=Mock();store.save.side_effect=RuntimeError()
        with patch.object(start_oauth,'CredentialStore',return_value=store):
            with self.assertRaises(RuntimeError):start_oauth.storage_self_test()
        store.delete.assert_called_once()
