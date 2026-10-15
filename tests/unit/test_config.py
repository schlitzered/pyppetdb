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
from pyppetdb.config import ConfigAppFacts
from pyppetdb.config import ConfigAppPuppet
from pyppetdb.config import ConfigAppStoreHistory
from pyppetdb.config import ConfigCA


class TestConfigUnit(unittest.TestCase):
    def test_ttls_must_be_positive(self):
        ttls = (
            (ConfigAppStoreHistory, "ttl", 7776000),
            (ConfigAppStoreHistory, "catalogNoReportTtl", 3600),
            (ConfigAppPuppet, "catalogCacheTTL", 86400),
            (ConfigCA, "certificateRequestTtlDays", 30),
            (ConfigCA, "verifyCertificateRegistrationCacheTtl", 300),
        )
        for model, field, default in ttls:
            self.assertEqual(getattr(model(), field), default, field)
            for value in (0, -1, None):
                with self.assertRaises(Exception, msg=f"{field}={value}"):
                    model(**{field: value})

    def test_parse_index_deny(self):
        config = ConfigAppFacts(indexDeny='["role", "stage"]')
        self.assertEqual(config.indexDeny, ["role", "stage"])

        config = ConfigAppFacts(indexDeny=["a", "b"])
        self.assertEqual(config.indexDeny, ["a", "b"])

    def test_removed_dedicated_fact_index_setting_is_ignored(self):
        config = ConfigAppFacts(index='["role"]')
        self.assertFalse(hasattr(config, "index"))

    def test_parse_catalog_cache_facts(self):
        json_str = '["fact1", "fact2"]'
        config = ConfigAppPuppet(catalogCacheFacts=json_str)
        self.assertEqual(config.catalogCacheFacts, ["fact1", "fact2"])

        # Test invalid JSON (should raise error)
        with self.assertRaises(Exception):
            ConfigAppPuppet(catalogCacheFacts="invalid-json")
