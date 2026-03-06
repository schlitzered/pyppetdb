import asyncio
import unittest
from unittest.mock import MagicMock, AsyncMock, patch
import logging
import orjson
import gzip
from datetime import datetime, UTC
from pyppetdb.controller.pdb.cmd.v1 import ControllerPdbCmdV1

class TestControllerPdbCmdV1Unit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_config = MagicMock()
        self.mock_config.mongodb.placement = "p1"
        self.mock_config.app.main.storeHistory.catalog = True
        self.mock_config.app.main.storeHistory.catalogUnchanged = True
        self.mock_config.app.puppetdb.serverurl = None
        
        self.mock_nodes = MagicMock()
        self.mock_catalogs = MagicMock()
        self.mock_groups = MagicMock()
        self.mock_reports = MagicMock()
        
        self.controller = ControllerPdbCmdV1(
            self.log, self.mock_config, self.mock_nodes, self.mock_catalogs, self.mock_groups, self.mock_reports
        )

    async def test_replace_facts(self):
        mock_request = MagicMock()
        data = {
            "certname": "node1",
            "environment": "prod",
            "values": {"os": "linux"},
            "producer_timestamp": "2026-03-06T00:00:00Z",
            "producer": "pm1"
        }
        mock_request.body = AsyncMock(return_value=orjson.dumps(data))
        mock_request.headers = {}
        
        self.mock_groups.reevaluate_node_membership = AsyncMock(return_value=["g1"])
        self.mock_nodes.update = AsyncMock()
        
        await self.controller.create(
            request=mock_request,
            certname="node1",
            command="replace_facts",
            producer_timestamp="2026-03-06T00:00:00Z",
            version=1
        )
        
        self.mock_groups.reevaluate_node_membership.assert_called_once()
        # Note: update is called via asyncio.create_task, so it might not be finished yet in a real run,
        # but in this unit test setUp it should be fine if we wait or if it's already triggered.
        # Actually, let's wait a bit to ensure tasks are triggered
        await asyncio.sleep(0.1)
        self.mock_nodes.update.assert_called_once()

    async def test_replace_catalog(self):
        mock_request = MagicMock()
        data = {
            "certname": "node1",
            "environment": "prod",
            "catalog_uuid": "uuid1",
            "resources": [{"type": "File", "title": "/t", "exported": True, "tags": [], "parameters": {}}]
        }
        mock_request.body = AsyncMock(return_value=orjson.dumps(data))
        mock_request.headers = {}
        
        self.mock_nodes.update = AsyncMock()
        self.mock_catalogs.create = AsyncMock()
        
        await self.controller.create(
            request=mock_request,
            certname="node1",
            command="replace_catalog",
            producer_timestamp="2026-03-06T00:00:00Z",
            version=1
        )
        await asyncio.sleep(0.1)
        self.mock_nodes.update.assert_called_once()
        self.mock_catalogs.create.assert_called_once()

    async def test_store_report(self):
        mock_request = MagicMock()
        data = {
            "certname": "node1",
            "environment": "prod",
            "catalog_uuid": "uuid1",
            "status": "changed",
            "noop": False,
            "noop_pending": False,
            "corrective_change": False,
            "logs": [],
            "metrics": [],
            "resources": [{"skipped": False, "timestamp": "now", "resource_type": "F", "resource_title": "t", "containment_path": [], "corrective_change": False, "events": [], "file": None, "line": None}]
        }
        mock_request.body = AsyncMock(return_value=orjson.dumps(data))
        mock_request.headers = {}
        
        self.mock_nodes.update = AsyncMock()
        self.mock_reports.create = AsyncMock()
        self.mock_catalogs.drop_created_no_report_ttl = AsyncMock()
        
        await self.controller.create(
            request=mock_request,
            certname="node1",
            command="store_report",
            producer_timestamp="2026-03-06T00:00:00Z",
            version=1
        )
        await asyncio.sleep(0.1)
        self.mock_nodes.update.assert_called_once()
        self.mock_reports.create.assert_called_once()
        self.mock_catalogs.drop_created_no_report_ttl.assert_called_once()

    async def test_create_gzip(self):
        mock_request = MagicMock()
        data = {"environment": "prod"}
        body = gzip.compress(orjson.dumps(data))
        mock_request.body = AsyncMock(return_value=body)
        mock_request.headers = {"content-encoding": "gzip"}
        
        await self.controller.create(
            request=mock_request,
            certname="node1",
            command="unknown",
            producer_timestamp="2026-03-06T00:00:00Z",
            version=1
        )
        # Should not raise
