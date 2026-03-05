import unittest
import logging
from pyppetdb.nodes_data_protector import NodesDataProtector

class TestNodesDataProtectorUnit(unittest.TestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.protector = NodesDataProtector("super-secret-key", self.log)

    def test_string_encryption(self):
        original = "hello world"
        encrypted = self.protector.encrypt_string(original)
        self.assertNotEqual(original, encrypted)
        
        decrypted = self.protector.decrypt_string(encrypted)
        self.assertEqual(original, decrypted)

    def test_object_encryption(self):
        original = {"foo": "bar", "list": [1, 2, 3], "nested": {"a": True}}
        encrypted = self.protector.encrypt_obj(original)
        self.assertIsInstance(encrypted, bytes)
        
        decrypted = self.protector.decrypt_obj(encrypted)
        self.assertEqual(original, decrypted)

    def test_encryption_different_keys(self):
        # Different keys should produce different ciphertexts and fail decryption
        protector2 = NodesDataProtector("other-key", self.log)
        
        original = "secret data"
        encrypted = self.protector.encrypt_string(original)
        
        with self.assertRaises(Exception):
            protector2.decrypt_string(encrypted)
