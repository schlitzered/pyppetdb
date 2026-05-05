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
import sys
import os
import logging
from unittest.mock import MagicMock
from pyppetdb.config import ConfigAppHiera
from pyppetdb.hiera import PyHiera


class TestDummyPluginLoading(unittest.TestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_crud = MagicMock()
        # Add the plugin directory to sys.path so it can be imported
        # Find the project root relative to this test file
        test_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(os.path.dirname(test_dir))
        self.plugin_path = os.path.join(project_root, "pyppetdb_dummy_plugin")
        sys.path.insert(0, self.plugin_path)

    def tearDown(self):
        # Remove the plugin directory from sys.path
        if self.plugin_path in sys.path:
            sys.path.remove(self.plugin_path)
        # Clean up imported module from sys.modules
        if "pyppetdb_dummy_plugin" in sys.modules:
            del sys.modules["pyppetdb_dummy_plugin"]

    def test_load_dummy_plugin(self):
        hiera_config = ConfigAppHiera(keyModels=["dummy_plugin"])

        pyhiera = PyHiera(
            log=self.log,
            crud_hiera_level_data=self.mock_crud,
            hiera_level_ids=["level1"],
            hiera_config=hiera_config,
        )

        # Check if the keys from the dummy plugin are registered in the internal PyHieraAsync instance
        key_models = pyhiera.hiera.key_models
        self.assertIn("static:dummy_plugin:server", key_models)
        self.assertIn("static:dummy_plugin:user", key_models)
        self.assertIn("static:dummy_plugin:storage", key_models)

        # Verify it's the correct class (checking by name)
        self.assertEqual(
            key_models["static:dummy_plugin:server"].__name__, "ServerKeyModel"
        )
        self.assertEqual(
            key_models["static:dummy_plugin:user"].__name__, "UserKeyModel"
        )
        self.assertEqual(
            key_models["static:dummy_plugin:storage"].__name__, "StorageKeyModel"
        )

    def test_load_dummy_plugin_partial(self):
        hiera_config = ConfigAppHiera(keyModels=["dummy_plugin:server,user"])

        pyhiera = PyHiera(
            log=self.log,
            crud_hiera_level_data=self.mock_crud,
            hiera_level_ids=["level1"],
            hiera_config=hiera_config,
        )

        key_models = pyhiera.hiera.key_models
        self.assertIn("static:dummy_plugin:server", key_models)
        self.assertIn("static:dummy_plugin:user", key_models)
        self.assertNotIn("static:dummy_plugin:storage", key_models)
