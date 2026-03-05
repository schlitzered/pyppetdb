import unittest
import json
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
            ConfigAppPuppet(catalogCacheFacts='invalid-json')
