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
from pyppetdb.config import ConfigAppFacts, ConfigAppPuppet


class TestConfigUnit(unittest.TestCase):
    def test_parse_index(self):
        # Test that JSON string is parsed into list
        json_str = '["role", "stage"]'
        config = ConfigAppFacts(index=json_str)
        self.assertEqual(config.index, ["role", "stage"])

        # Test that list remains list
        config = ConfigAppFacts(index=["a", "b"])
        self.assertEqual(config.index, ["a", "b"])

    def test_parse_catalog_cache_facts(self):
        json_str = '["fact1", "fact2"]'
        config = ConfigAppPuppet(catalogCacheFacts=json_str)
        self.assertEqual(config.catalogCacheFacts, ["fact1", "fact2"])

        # Test invalid JSON (should raise error)
        with self.assertRaises(Exception):
            ConfigAppPuppet(catalogCacheFacts="invalid-json")
