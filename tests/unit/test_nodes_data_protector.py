# Copyright 2026 Stephan Schultchen
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import unittest
import logging
from pyppetdb.crud.nodes_catalog_cache import NodesDataProtector


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
