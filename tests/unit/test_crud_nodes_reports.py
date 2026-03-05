import unittest
from unittest.mock import MagicMock, AsyncMock
import logging
from datetime import datetime
from pyppetdb.crud.nodes_reports import CrudNodesReports

class TestCrudNodesReportsUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_coll = MagicMock()
        self.mock_config = MagicMock()
        self.mock_redactor = MagicMock()
        self.crud = CrudNodesReports(self.mock_config, self.log, self.mock_coll, self.mock_redactor)

    async def test_delete(self):
        now = datetime.now()
        self.crud._delete = AsyncMock()
        await self.crud.delete(_id=now, node_id="node1")
        self.crud._delete.assert_called_once_with(query={"id": now, "node_id": "node1"})

    async def test_delete_all_from_node(self):
        self.mock_coll.delete_many = AsyncMock()
        await self.crud.delete_all_from_node(node_id="node1")
        self.mock_coll.delete_many.assert_called_once_with(filter={"node_id": "node1"})

    async def test_create(self):
        now = datetime.now()
        self.crud._create = AsyncMock(return_value={"id": now})
        self.mock_redactor.redact.side_effect = lambda x: x
        
        from pyppetdb.model.nodes_reports import NodeReportPostInternal
        payload = NodeReportPostInternal(report={"status": "changed"})
        
        result = await self.crud.create(_id=now, node_id="node1", payload=payload, fields=[])
        self.assertEqual(result.id, now)
        self.mock_redactor.redact.assert_called_once()

    async def test_get(self):
        now = datetime.now()
        self.crud._get = AsyncMock(return_value={"id": now, "node_id": "node1"})
        await self.crud.get(_id=now, node_id="node1", fields=[])
        self.crud._get.assert_called_once()

    async def test_resource_exists(self):
        now = datetime.now()
        self.crud._resource_exists = AsyncMock(return_value=True)
        await self.crud.resource_exists(_id=now, node_id="node1")
        self.crud._resource_exists.assert_called_once()

    async def test_search(self):
        self.crud._search = AsyncMock(return_value={"result": [], "meta": {"result_size": 0}})
        await self.crud.search(node_id="node1")
        self.crud._search.assert_called_once()
