import unittest
from unittest.mock import MagicMock, AsyncMock
import logging
from pyppetdb.crud.hiera_keys import CrudHieraKeysAdapter
from pyppetdb.crud.hiera_key_models_dynamic import CrudHieraModelsDynamicAdapter
from pyhiera.keys import PyHieraKeyBase

class TestPyHieraAdaptersUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_coll = MagicMock()
        self.mock_pyhiera = MagicMock()
        self.mock_pyhiera.hiera = MagicMock()

    def test_hiera_keys_adapter_add_key(self):
        adapter = CrudHieraKeysAdapter(self.log, self.mock_coll, self.mock_pyhiera)
        
        # Mock key model existence
        self.mock_pyhiera.hiera.key_models = {"model1": MagicMock()}
        
        adapter._add_or_update_key("key1", "model1")
        self.mock_pyhiera.hiera.key_add.assert_called_once_with("key1", "model1")

    def test_hiera_keys_adapter_add_key_missing_model(self):
        adapter = CrudHieraKeysAdapter(self.log, self.mock_coll, self.mock_pyhiera)
        self.mock_pyhiera.hiera.key_models = {}
        
        adapter._add_or_update_key("key1", "model1")
        self.mock_pyhiera.hiera.key_add.assert_not_called()

    def test_hiera_dynamic_models_adapter_build_class(self):
        adapter = CrudHieraModelsDynamicAdapter(self.log, self.mock_coll, self.mock_pyhiera)
        
        schema = {
            "type": "object",
            "properties": {
                "foo": {"type": "string"}
            }
        }
        
        model_cls = adapter._build_key_model_class("dynamic:test", schema, "desc")
        self.assertTrue(issubclass(model_cls, PyHieraKeyBase))
        
        # Test validation logic inside the dynamic model
        instance = model_cls()
        validated = instance.validate({"foo": "bar"})
        self.assertEqual(validated.data, {"foo": "bar"})
        
        with self.assertRaises(Exception):
            instance.validate({"foo": 123}) # Should fail validation (foo is string)

    def test_hiera_dynamic_models_adapter_register(self):
        adapter = CrudHieraModelsDynamicAdapter(self.log, self.mock_coll, self.mock_pyhiera)
        schema = {"properties": {"a": {"type": "int"}}}
        
        adapter.model_register("dynamic:m1", schema, "desc")
        
        self.assertEqual(self.mock_pyhiera.hiera.key_model_add.call_count, 1)
        args = self.mock_pyhiera.hiera.key_model_add.call_args[0]
        self.assertEqual(args[0], "dynamic:m1")
        self.assertTrue(issubclass(args[1], PyHieraKeyBase))

    async def test_hiera_keys_adapter_handle_change_insert(self):
        adapter = CrudHieraKeysAdapter(self.log, self.mock_coll, self.mock_pyhiera)
        self.mock_pyhiera.hiera.key_models = {"model1": MagicMock()}
        
        change = {
            "operationType": "insert",
            "documentKey": {"_id": "doc1"},
            "fullDocument": {"id": "key1", "key_model_id": "model1"}
        }
        
        await adapter._handle_change(change)
        self.mock_pyhiera.hiera.key_add.assert_called_once_with("key1", "model1")
        self.assertEqual(adapter._doc_to_key["doc1"], "key1")

    async def test_hiera_keys_adapter_handle_change_delete(self):
        adapter = CrudHieraKeysAdapter(self.log, self.mock_coll, self.mock_pyhiera)
        adapter._doc_to_key["doc1"] = "key1"
        
        change = {
            "operationType": "delete",
            "documentKey": {"_id": "doc1"}
        }
        
        await adapter._handle_change(change)
        self.mock_pyhiera.hiera.key_delete.assert_called_once_with("key1")
        self.assertNotIn("doc1", adapter._doc_to_key)
