import unittest
from unittest.mock import MagicMock, AsyncMock, patch
import logging
from datetime import datetime, timedelta, UTC
from pyppetdb.crud.nodes import CrudNodes, NodePutInternal

class TestCrudNodesUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_coll = MagicMock()
        self.mock_config = MagicMock()
        # Setup basic config structure if needed
        self.mock_config.app.main.facts.index = []
        self.crud = CrudNodes(self.log, self.mock_config, self.mock_coll)

    async def test_delete(self):
        self.crud._delete = AsyncMock()
        await self.crud.delete(_id="node1")
        self.crud._delete.assert_called_once_with(query={"id": "node1"})

    async def test_delete_node_group_from_all(self):
        self.mock_coll.update_many = AsyncMock()
        await self.crud.delete_node_group_from_all(node_group_id="group1")
        self.mock_coll.update_many.assert_called_once()
        call_args = self.mock_coll.update_many.call_args[1]
        self.assertEqual(call_args["filter"], {"node_groups": "group1"})
        self.assertEqual(call_args["update"], {"$pull": {"node_groups": "group1"}})

    async def test_get(self):
        self.crud._get = AsyncMock(return_value={"id": "node1"})
        await self.crud.get(_id="node1", fields=[], user_node_groups=["g1"])
        self.crud._get.assert_called_once()
        query = self.crud._get.call_args[1]["query"]
        self.assertEqual(query["id"], "node1")
        self.assertEqual(query["node_groups"], {"$in": ["g1"]})

    async def test_search(self):
        # Mock aggregation for status counts
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[
            {"_id": "changed", "count": 5},
            {"_id": "unchanged", "count": 10}
        ])
        self.mock_coll.aggregate.return_value = mock_cursor
        
        # Mock count_documents for outdated nodes
        self.mock_coll.count_documents = AsyncMock(return_value=2)
        
        # Mock _search from CrudMongo
        self.crud._search = AsyncMock(return_value={
            "result": [{"id": "node1"}],
            "meta": {"result_size": 1}
        })
        
        result = await self.crud.search(_id="node1", disabled=False)
        
        self.assertEqual(result.meta.result_size, 1)
        self.assertEqual(result.meta.status_changed, 5)
        self.assertEqual(result.meta.status_unchanged, 10)
        self.assertEqual(result.meta.status_outdated, 2)

    async def test_update(self):
        self.crud._update = AsyncMock(return_value={"id": "node1"})
        payload = NodePutInternal(disabled=True)
        await self.crud.update(_id="node1", payload=payload, fields=[])
        self.crud._update.assert_called_once()

    async def test_update_nodegroup(self):
        self.mock_coll.update_many = AsyncMock()
        await self.crud.update_nodegroup(node_group_id="g1", nodes=["node1", "node2"])
        # Should be called twice: once for $pull (remove others) and once for $addToSet (add these)
        self.assertEqual(self.mock_coll.update_many.call_count, 2)

    async def test_distinct_fact_values(self):
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[
            {"_id": "RedHat", "count": 5},
            {"_id": "Debian", "count": 3}
        ])
        self.mock_coll.aggregate.return_value = mock_cursor
        
        result = await self.crud.distinct_fact_values(fact_id="osfamily")
        
        self.assertEqual(len(result.result), 2)
        self.assertEqual(result.result[0].value, "RedHat")
        self.assertEqual(result.result[0].count, 5)

    async def test_exported_resources(self):
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[
            {"results": [{"type": "File", "title": "/tmp/test", "tags": [], "exported": True, "parameters": {}}]}
        ])
        self.mock_coll.aggregate.return_value = mock_cursor
        
        result = await self.crud.exported_resources(resource_type="File")
        
        self.assertEqual(len(result.result), 1)
        self.assertEqual(result.result[0].type, "File")
