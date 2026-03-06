import unittest
from unittest.mock import MagicMock, AsyncMock
import logging
from datetime import datetime
from pyppetdb.crud.nodes_catalog_cache import CrudNodesCatalogCache
from pyppetdb.errors import ResourceNotFound

class TestCrudNodesCatalogCacheUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_config = MagicMock()
        self.mock_coll = MagicMock()
        self.mock_protector = MagicMock()
        self.crud = CrudNodesCatalogCache(self.log, self.mock_config, self.mock_coll, self.mock_protector)

    async def test_get_cached(self):
        self.crud._get = AsyncMock(return_value={"id": "node1"})
        result = await self.crud.get("node1", fields=[])
        self.assertTrue(result.cached)
        self.assertEqual(result.id, "node1")

    async def test_get_not_cached(self):
        self.crud._get = AsyncMock(side_effect=ResourceNotFound)
        result = await self.crud.get("node1", fields=[])
        self.assertFalse(result.cached)
        self.assertEqual(result.id, "node1")

    async def test_get_catalog_success(self):
        self.mock_coll.find_one = AsyncMock(return_value={"catalog": "encrypted_data"})
        self.mock_protector.decrypt_obj.return_value = {"resources": []}
        
        catalog = await self.crud.get_catalog("node1")
        self.assertEqual(catalog, {"resources": []})
        self.mock_protector.decrypt_obj.assert_called_once_with("encrypted_data")

    async def test_get_catalog_none(self):
        self.mock_coll.find_one = AsyncMock(return_value=None)
        catalog = await self.crud.get_catalog("node1")
        self.assertIsNone(catalog)

    async def test_upsert(self):
        self.mock_config.app.puppet.catalogCacheTTL = 3600
        self.mock_config.mongodb.placement = "p1"
        self.mock_protector.encrypt_obj.return_value = "encrypted"
        self.mock_coll.update_one = AsyncMock()
        
        await self.crud.upsert("node1", {"os": "linux"}, {"res": []})
        self.mock_coll.update_one.assert_called_once()
        call_args = self.mock_coll.update_one.call_args[1]
        self.assertEqual(call_args["filter"], {"id": "node1"})
        self.assertEqual(call_args["update"]["$set"]["catalog"], "encrypted")

    async def test_get_cached_node_ids(self):
        mock_cursor = MagicMock()
        mock_cursor.__aiter__.return_value = [{"id": "n1"}, {"id": "n2"}]
        self.mock_coll.find.return_value = mock_cursor
        
        ids = await self.crud.get_cached_node_ids(["n1", "n2", "n3"])
        self.assertEqual(ids, {"n1", "n2"})

    async def test_delete_many_by_filter(self):
        self.mock_coll.delete_many = AsyncMock(return_value=MagicMock(deleted_count=5))
        count = await self.crud.delete_many_by_filter(node_id="node.*")
        self.assertEqual(count, 5)
        self.mock_coll.delete_many.assert_called_once()
