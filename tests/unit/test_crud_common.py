import unittest
from unittest.mock import MagicMock, AsyncMock
import logging
import pymongo.errors
from pyppetdb.crud.common import CrudMongo
from pyppetdb.errors import DuplicateResource, ResourceNotFound, BackendError

class TestCrudCommon(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_config = MagicMock()
        self.mock_coll = MagicMock()
        self.mock_coll.name = "test_coll"
        self.crud = CrudMongo(self.mock_config, self.log, self.mock_coll)

    async def test_create_success(self):
        self.mock_coll.insert_one = AsyncMock(return_value=MagicMock(inserted_id="obj1"))
        self.crud._get_by_obj_id = AsyncMock(return_value={"id": "r1"})
        
        result = await self.crud._create({"id": "r1"})
        self.assertEqual(result, {"id": "r1"})
        self.mock_coll.insert_one.assert_called_once()

    async def test_create_duplicate(self):
        self.mock_coll.insert_one = AsyncMock(side_effect=pymongo.errors.DuplicateKeyError("msg"))
        with self.assertRaises(DuplicateResource):
            await self.crud._create({"id": "r1"})

    async def test_create_backend_error(self):
        self.mock_coll.insert_one = AsyncMock(side_effect=pymongo.errors.ConnectionFailure("msg"))
        with self.assertRaises(BackendError):
            await self.crud._create({"id": "r1"})

    async def test_delete_success(self):
        self.mock_coll.delete_one = AsyncMock(return_value=MagicMock(deleted_count=1))
        result = await self.crud._delete({"id": "r1"})
        self.assertEqual(result, {})

    async def test_delete_not_found(self):
        self.mock_coll.delete_one = AsyncMock(return_value=MagicMock(deleted_count=0))
        with self.assertRaises(ResourceNotFound):
            await self.crud._delete({"id": "r1"})

    async def test_get_success(self):
        self.mock_coll.find_one = AsyncMock(return_value={"_id": "obj1", "id": "r1"})
        result = await self.crud._get({"id": "r1"}, fields=["id"])
        self.assertEqual(result, {"id": "r1"})

    async def test_get_not_found(self):
        self.mock_coll.find_one = AsyncMock(return_value=None)
        with self.assertRaises(ResourceNotFound):
            await self.crud._get({"id": "r1"}, fields=[])

    async def test_search_success(self):
        self.mock_coll.count_documents = AsyncMock(return_value=1)
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[{"_id": "obj1", "id": "r1"}])
        self.mock_coll.find.return_value = mock_cursor
        
        result = await self.crud._search({"id": "r1"}, sort="id", sort_order="ascending", page=1, limit=10)
        self.assertEqual(result["meta"]["result_size"], 1)
        self.assertEqual(result["result"][0]["id"], "r1")

    async def test_update_success(self):
        self.mock_coll.find_one_and_update = AsyncMock(return_value={"_id": "obj1", "id": "r1", "val": "new"})
        result = await self.crud._update({"id": "r1"}, {"val": "new"}, fields=[])
        self.assertEqual(result["val"], "new")

    async def test_update_not_found(self):
        self.mock_coll.find_one_and_update = AsyncMock(return_value=None)
        with self.assertRaises(ResourceNotFound):
            await self.crud._update({"id": "r1"}, {"val": "new"}, fields=[])

    async def test_create_ttl_index(self):
        self.mock_coll.list_indexes.return_value.to_list = AsyncMock(return_value=[])
        self.mock_coll.create_index = AsyncMock()
        
        await self.crud._create_ttl_index("field1", 3600, "idx1")
        self.mock_coll.create_index.assert_called_once()

    async def test_create_ttl_index_exists_matching(self):
        self.mock_coll.list_indexes.return_value.to_list = AsyncMock(return_value=[
            {"name": "idx1", "expireAfterSeconds": 3600, "key": {"field1": 1}}
        ])
        self.mock_coll.create_index = AsyncMock()
        
        await self.crud._create_ttl_index("field1", 3600, "idx1")
        self.mock_coll.create_index.assert_not_called()

    async def test_create_ttl_index_exists_mismatch(self):
        self.mock_coll.list_indexes.return_value.to_list = AsyncMock(return_value=[
            {"name": "idx1", "expireAfterSeconds": 1800, "key": {"field1": 1}}
        ])
        self.mock_coll.drop_index = AsyncMock()
        self.mock_coll.create_index = AsyncMock()
        
        await self.crud._create_ttl_index("field1", 3600, "idx1")
        self.mock_coll.drop_index.assert_called_once_with("idx1")
        self.mock_coll.create_index.assert_called_once()
