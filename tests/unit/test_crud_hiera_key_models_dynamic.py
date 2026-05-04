import unittest
from unittest.mock import MagicMock, AsyncMock, patch
import logging
from pyppetdb.crud.hiera_key_models_dynamic import (
    CrudHieraKeyModelsDynamic,
    HieraKeyModelDynamicPost,
)
from pyppetdb.errors import QueryParamValidationError
from pyhiera.keys import PyHieraKeyBase


class TestCrudHieraKeyModelsDynamicUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_coll = MagicMock()
        self.mock_config = MagicMock()
        self.mock_pyhiera = MagicMock()

        with patch(
            "pyppetdb.crud.hiera_key_models_dynamic.CrudHieraModelsDynamicAdapter"
        ) as mock_adapter_class:
            self.mock_adapter = mock_adapter_class.return_value
            self.crud = CrudHieraKeyModelsDynamic(
                self.mock_config, self.log, self.mock_coll, self.mock_pyhiera
            )

    async def test_create_success(self):
        valid_model = {
            "title": "StringModel",
            "type": "object",
            "required": ["data"],
            "properties": {"data": {"type": "string"}},
        }
        self.crud._create = AsyncMock(
            return_value={
                "id": "dynamic:test",
                "model": valid_model,
                "description": "desc",
            }
        )
        payload = HieraKeyModelDynamicPost(model=valid_model, description="desc")
        result = await self.crud.create(_id="dynamic:test", payload=payload, fields=[])

        self.assertEqual(result.id, "dynamic:test")
        self.mock_adapter.model_register.assert_called_once_with(
            "dynamic:test", valid_model, "desc"
        )

    async def test_create_invalid_prefix(self):
        valid_model = {
            "title": "StringModel",
            "type": "object",
            "required": ["data"],
            "properties": {"data": {"type": "string"}},
        }
        payload = HieraKeyModelDynamicPost(model=valid_model)
        with self.assertRaises(QueryParamValidationError):
            await self.crud.create(_id="static:test", payload=payload, fields=[])

    async def test_delete(self):
        self.crud._delete = AsyncMock()
        await self.crud.delete(_id="dynamic:test")
        self.crud._delete.assert_called_once_with(query={"id": "dynamic:test"})
        self.mock_adapter.model_unregister.assert_called_once_with("dynamic:test")

    async def test_get(self):
        self.crud._get = AsyncMock(return_value={"id": "dynamic:test", "model": {}})
        await self.crud.get(_id="dynamic:test", fields=[])
        self.crud._get.assert_called_once_with(query={"id": "dynamic:test"}, fields=[])

    async def test_search(self):
        self.crud._search = AsyncMock(
            return_value={"result": [], "meta": {"result_size": 0}}
        )
        await self.crud.search(_id="dynamic:test")
        call_args = self.crud._search.call_args[1]
        self.assertEqual(call_args["query"]["id"], {"$regex": "dynamic:test"})


class TestCrudHieraModelsDynamicAdapterUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_coll = MagicMock()
        self.mock_pyhiera = MagicMock()
        from pyppetdb.crud.hiera_key_models_dynamic import CrudHieraModelsDynamicAdapter

        self.adapter = CrudHieraModelsDynamicAdapter(
            self.log, self.mock_coll, self.mock_pyhiera
        )

    async def test_handle_change_insert(self):
        valid_model = {
            "title": "StringModel",
            "type": "object",
            "required": ["data"],
            "properties": {"data": {"type": "string"}},
        }
        change = {
            "operationType": "insert",
            "documentKey": {"_id": "doc1"},
            "fullDocument": {
                "id": "dynamic:test",
                "model": valid_model,
                "description": "desc",
            },
        }
        # Mock model_register to avoid pydantic complex mocking
        self.adapter.model_register = MagicMock()
        await self.adapter._handle_change(change)
        self.adapter.model_register.assert_called_once_with(
            "dynamic:test", valid_model, "desc"
        )
        self.assertEqual(self.adapter._doc_to_model_id["doc1"], "dynamic:test")

    async def test_handle_change_delete(self):
        self.adapter._doc_to_model_id["doc1"] = "dynamic:test"
        change = {"operationType": "delete", "documentKey": {"_id": "doc1"}}
        self.adapter.model_unregister = MagicMock()
        await self.adapter._handle_change(change)
        self.adapter.model_unregister.assert_called_once_with("dynamic:test")
        self.assertNotIn("doc1", self.adapter._doc_to_model_id)

    async def test_load_initial_data(self):
        valid_model = {
            "title": "StringModel",
            "type": "object",
            "required": ["data"],
            "properties": {"data": {"type": "string"}},
        }
        mock_cursor = MagicMock()
        mock_cursor.__aiter__.return_value = iter(
            [
                {
                    "_id": "d1",
                    "id": "dynamic:m1",
                    "model": valid_model,
                    "description": "desc1",
                }
            ]
        )
        self.mock_coll.find.return_value = mock_cursor
        self.adapter.model_register = MagicMock()

        await self.adapter._load_initial_data()
        self.assertEqual(self.adapter._doc_to_model_id["d1"], "dynamic:m1")
        self.adapter.model_register.assert_called_once()

    def test_build_key_model_class(self):
        # Update the test schema to follow the required 'wrapped' pattern
        schema = {
            "type": "object",
            "required": ["data"],
            "properties": {
                "data": {"type": "object", "properties": {"foo": {"type": "string"}}}
            },
        }
        model_class = self.adapter._build_key_model_class("dynamic:m1", schema, "desc")
        self.assertTrue(issubclass(model_class, PyHieraKeyBase))
        instance = model_class()

        # We pass the 'value' of the key, which is the dict {"foo": "bar"}
        res = instance.validate({"foo": "bar"})
        self.assertEqual(res.data["data"], {"foo": "bar"})

    def test_build_key_model_class_wrapped_dict(self):
        # Test the case reported by user: Wrapped style schema with dict value
        schema = {
            "type": "object",
            "required": ["data"],
            "properties": {
                "data": {
                    "type": "object",
                    "properties": {
                        "a": {"type": "string"},
                        "b": {"type": "string"},
                        "c": {"type": "string"},
                    },
                }
            },
        }
        model_class = self.adapter._build_key_model_class(
            "dynamic:complex2", schema, "desc"
        )
        instance = model_class()
        input_data = {"a": "asd", "b": "asd", "c": "asd"}

        # This should now succeed due to the fix
        res = instance.validate(input_data)
        self.assertEqual(res.data["data"], input_data)
