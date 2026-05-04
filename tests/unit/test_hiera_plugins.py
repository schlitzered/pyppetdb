import unittest
from unittest.mock import MagicMock, patch
import logging
from pyppetdb.config import ConfigAppHiera
from pyppetdb.hiera import PyHiera


class TestHieraPlugins(unittest.TestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_crud = MagicMock()

    @patch("importlib.import_module")
    @patch("pyppetdb.hiera.PyHieraAsync")
    def test_load_plugins_basic(self, mock_pyhiera_async_cls, mock_import_module):
        mock_hiera_instance = mock_pyhiera_async_cls.return_value
        mock_hiera_instance.keyModels = {}

        # Mock plugin module
        mock_module = MagicMock()
        mock_module.key_models = {"key1": MagicMock(), "key2": MagicMock()}
        mock_import_module.return_value = mock_module

        hiera_config = ConfigAppHiera(keyModels=["dummy"])

        PyHiera(
            log=self.log,
            crud_hiera_level_data=self.mock_crud,
            hiera_level_ids=["level1"],
            hiera_config=hiera_config,
        )

        mock_import_module.assert_called_with("pyppetdb_dummy")
        # Check if keys were added with prefix
        mock_hiera_instance.key_model_add.assert_any_call(
            "static:dummy:key1", mock_module.key_models["key1"]
        )
        mock_hiera_instance.key_model_add.assert_any_call(
            "static:dummy:key2", mock_module.key_models["key2"]
        )

    @patch("importlib.import_module")
    @patch("pyppetdb.hiera.PyHieraAsync")
    def test_load_plugins_filtered(self, mock_pyhiera_async_cls, mock_import_module):
        mock_hiera_instance = mock_pyhiera_async_cls.return_value
        mock_hiera_instance.keyModels = {}

        # Mock plugin module
        mock_module = MagicMock()
        mock_module.key_models = {"key1": "type1", "key2": "type2", "key3": "type3"}
        mock_import_module.return_value = mock_module

        hiera_config = ConfigAppHiera(keyModels=["dummy:key1,key3"])

        PyHiera(
            log=self.log,
            crud_hiera_level_data=self.mock_crud,
            hiera_level_ids=["level1"],
            hiera_config=hiera_config,
        )

        mock_import_module.assert_called_with("pyppetdb_dummy")
        # Check if only filtered keys were added
        mock_hiera_instance.key_model_add.assert_any_call("static:dummy:key1", "type1")
        mock_hiera_instance.key_model_add.assert_any_call("static:dummy:key3", "type3")

        # Ensure key2 was NOT added
        calls = [
            call[0][0] for call in mock_hiera_instance.key_model_add.call_args_list
        ]
        self.assertNotIn("static:dummy:key2", calls)

    @patch("importlib.import_module")
    @patch("pyppetdb.hiera.PyHieraAsync")
    def test_load_plugins_import_error(
        self, mock_pyhiera_async_cls, mock_import_module
    ):
        mock_hiera_instance = mock_pyhiera_async_cls.return_value
        mock_hiera_instance.keyModels = {}

        mock_import_module.side_effect = ImportError("Module not found")

        hiera_config = ConfigAppHiera(keyModels=["missing"])

        # Should not raise exception, but log a warning
        with self.assertLogs("test", level="WARNING") as cm:
            PyHiera(
                log=self.log,
                crud_hiera_level_data=self.mock_crud,
                hiera_level_ids=["level1"],
                hiera_config=hiera_config,
            )

        self.assertIn(
            "Failed to load Hiera plugin module: pyppetdb_missing", cm.output[0]
        )

    @patch("importlib.import_module")
    @patch("pyppetdb.hiera.PyHieraAsync")
    def test_load_plugins_missing_attribute(
        self, mock_pyhiera_async_cls, mock_import_module
    ):
        mock_hiera_instance = mock_pyhiera_async_cls.return_value
        mock_hiera_instance.keyModels = {}

        # Mock plugin module without key_models
        mock_module = MagicMock(spec=[])
        del mock_module.key_models
        mock_import_module.return_value = mock_module

        hiera_config = ConfigAppHiera(keyModels=["dummy"])

        with self.assertLogs("test", level="WARNING") as cm:
            PyHiera(
                log=self.log,
                crud_hiera_level_data=self.mock_crud,
                hiera_level_ids=["level1"],
                hiera_config=hiera_config,
            )

        self.assertIn(
            "Hiera plugin module pyppetdb_dummy does not contain 'key_models'",
            cm.output[0],
        )
