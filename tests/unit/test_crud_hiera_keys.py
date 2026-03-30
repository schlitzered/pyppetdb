import unittest
from unittest.mock import MagicMock, AsyncMock, patch
import logging
from pyppetdb.crud.hiera_keys import CrudHieraKeys, HieraKeyPost, HieraKeyPut


class TestCrudHieraKeysUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_coll = MagicMock()
        self.mock_config = MagicMock()
        self.mock_pyhiera = MagicMock()

        # Patch CrudHieraKeysAdapter to avoid background tasks
        with patch(
            "pyppetdb.crud.hiera_keys.CrudHieraKeysAdapter"
        ) as mock_adapter_class:
            self.mock_adapter = mock_adapter_class.return_value
            self.crud = CrudHieraKeys(
                self.mock_config, self.log, self.mock_coll, self.mock_pyhiera
            )

    async def test_create(self):
        self.crud._create = AsyncMock(
            return_value={
                "id": "key1",
                "key_model_id": "static:test",
                "deprecated": False,
            }
        )
        payload = HieraKeyPost(key_model_id="static:test")
        result = await self.crud.create(_id="key1", payload=payload, fields=[])

        self.assertEqual(result.id, "key1")
        self.crud._create.assert_called_once()
        call_args = self.crud._create.call_args[1]["payload"]
        self.assertEqual(call_args["id"], "key1")

    async def test_delete(self):
        self.crud._delete = AsyncMock()
        await self.crud.delete(_id="key1")
        self.crud._delete.assert_called_once_with(query={"id": "key1"})

    async def test_get(self):
        self.crud._get = AsyncMock(
            return_value={"id": "key1", "key_model_id": "static:test"}
        )
        await self.crud.get(_id="key1", fields=[])
        self.crud._get.assert_called_once_with(query={"id": "key1"}, fields=[])

    async def test_resource_exists(self):
        self.crud._resource_exists = AsyncMock(return_value=MagicMock())
        await self.crud.resource_exists(_id="key1")
        self.crud._resource_exists.assert_called_once_with(query={"id": "key1"})

    async def test_search(self):
        self.crud._search = AsyncMock(
            return_value={"result": [], "meta": {"result_size": 0}}
        )
        await self.crud.search(_id="key1", model="static:test", deprecated=True)

        call_args = self.crud._search.call_args[1]
        self.assertEqual(call_args["query"]["id"], {"$regex": "key1"})
        self.assertEqual(call_args["query"]["key_model_id"], {"$regex": "static:test"})
        self.assertEqual(call_args["query"]["deprecated"], True)

    async def test_update(self):
        self.crud._update = AsyncMock(
            return_value={"id": "key1", "key_model_id": "static:new"}
        )
        payload = HieraKeyPut(key_model_id="static:new")
        await self.crud.update(_id="key1", payload=payload, fields=[])
        self.crud._update.assert_called_once_with(
            query={"id": "key1"},
            fields=[],
            payload={
                "key_model_id": "static:new",
                "description": None,
                "deprecated": None,
            },
        )


class TestCrudHieraKeysAdapterUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_coll = MagicMock()
        self.mock_pyhiera = MagicMock()
        from pyppetdb.crud.hiera_keys import CrudHieraKeysAdapter

        self.adapter = CrudHieraKeysAdapter(self.log, self.mock_coll, self.mock_pyhiera)

    async def test_handle_change_insert(self):
        change = {
            "operationType": "insert",
            "documentKey": {"_id": "doc1"},
            "fullDocument": {"id": "key1", "key_model_id": "static:test"},
        }
        self.mock_pyhiera.hiera.key_models = {"static:test": MagicMock()}
        await self.adapter._handle_change(change)
        self.mock_pyhiera.hiera.key_add.assert_called_once_with("key1", "static:test")
        self.assertEqual(self.adapter._doc_to_key["doc1"], "key1")

    async def test_handle_change_delete(self):
        self.adapter._doc_to_key["doc1"] = "key1"
        change = {"operationType": "delete", "documentKey": {"_id": "doc1"}}
        await self.adapter._handle_change(change)
        self.mock_pyhiera.hiera.key_delete.assert_called_once_with("key1")
        self.assertNotIn("doc1", self.adapter._doc_to_key)

    async def test_load_initial_data(self):
        mock_cursor = MagicMock()
        mock_cursor.__aiter__.return_value = iter(
            [
                {"_id": "d1", "id": "k1", "key_model_id": "m1"},
                {"_id": "d2", "id": "k2", "key_model_id": "m2"},
            ]
        )
        self.mock_coll.find.return_value = mock_cursor
        self.mock_pyhiera.hiera.key_models = {"m1": MagicMock(), "m2": MagicMock()}

        await self.adapter._load_initial_data()
        self.assertEqual(self.adapter._doc_to_key["d1"], "k1")
        self.assertEqual(self.adapter._doc_to_key["d2"], "k2")
        self.assertEqual(self.mock_pyhiera.hiera.key_add.call_count, 2)
