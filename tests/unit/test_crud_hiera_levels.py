import unittest
from unittest.mock import MagicMock, AsyncMock, patch
import logging
from pyppetdb.crud.hiera_levels import CrudHieraLevels, HieraLevelPost, HieraLevelPut

class TestCrudHieraLevelsUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_coll = MagicMock()
        self.mock_config = MagicMock()
        
        with patch("pyppetdb.crud.hiera_levels.CrudHieraLevelsCache") as mock_cache_class:
            self.mock_cache = mock_cache_class.return_value
            self.crud = CrudHieraLevels(self.mock_config, self.log, self.mock_coll)

    async def test_create(self):
        self.crud._create = AsyncMock(return_value={
            "id": "level1",
            "priority": 10
        })
        payload = HieraLevelPost(priority=10)
        result = await self.crud.create(_id="level1", payload=payload, fields=[])
        
        self.assertEqual(result.id, "level1")
        self.crud._create.assert_called_once()

    async def test_delete(self):
        self.crud._delete = AsyncMock()
        await self.crud.delete(_id="level1")
        self.crud._delete.assert_called_once_with(query={"id": "level1"})

    async def test_get(self):
        self.crud._get = AsyncMock(return_value={
            "id": "level1",
            "priority": 10
        })
        await self.crud.get(_id="level1", fields=[])
        self.crud._get.assert_called_once_with(query={"id": "level1"}, fields=[])

    async def test_search(self):
        self.crud._search = AsyncMock(return_value={"result": [], "meta": {"result_size": 0}})
        await self.crud.search(_id="level1", priority=10)
        
        call_args = self.crud._search.call_args[1]
        self.assertEqual(call_args["query"]["id"], {"$regex": "level1"})
        self.assertEqual(call_args["query"]["priority"], 10)

    async def test_update(self):
        self.crud._update = AsyncMock(return_value={
            "id": "level1",
            "priority": 20
        })
        payload = HieraLevelPut(priority=20)
        await self.crud.update(_id="level1", payload=payload, fields=[])
        self.crud._update.assert_called_once_with(
            query={"id": "level1"}, fields=[], payload={"priority": 20, "description": None}
        )

class TestCrudHieraLevelsCacheUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_coll = MagicMock()
        from pyppetdb.crud.hiera_levels import CrudHieraLevelsCache
        self.cache = CrudHieraLevelsCache(self.log, self.mock_coll)

    async def test_handle_change_insert(self):
        change = {
            "operationType": "insert",
            "documentKey": {"_id": "doc1"},
            "fullDocument": {"id": "level1", "priority": 10}
        }
        await self.cache._handle_change(change)
        self.assertIn("level1", self.cache.level_ids)
        self.assertEqual(self.cache.cache["doc1"].id, "level1")

    async def test_handle_change_delete(self):
        # Setup initial state
        self.cache._level_ids = ["level1"]
        from pyppetdb.model.hiera_levels import HieraLevelGet
        self.cache._cache["doc1"] = HieraLevelGet(id="level1", priority=10)
        
        change = {
            "operationType": "delete",
            "documentKey": {"_id": "doc1"}
        }
        await self.cache._handle_change(change)
        self.assertNotIn("level1", self.cache.level_ids)
        self.assertNotIn("doc1", self.cache.cache)
