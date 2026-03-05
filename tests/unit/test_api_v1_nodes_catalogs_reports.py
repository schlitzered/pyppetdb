import unittest
from unittest.mock import MagicMock, AsyncMock
import logging
from datetime import datetime
from pyppetdb.controller.api.v1.nodes_catalogs import ControllerApiV1NodesCatalogs
from pyppetdb.controller.api.v1.nodes_reports import ControllerApiV1NodesReports

class TestApiV1NodesCatalogsReportsUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_authorize = MagicMock()
        self.mock_crud_nodes = MagicMock()
        self.mock_crud_catalogs = MagicMock()
        self.mock_crud_reports = MagicMock()
        
        self.catalogs_controller = ControllerApiV1NodesCatalogs(
            log=self.log,
            authorize=self.mock_authorize,
            crud_nodes=self.mock_crud_nodes,
            crud_nodes_catalogs=self.mock_crud_catalogs
        )
        
        self.reports_controller = ControllerApiV1NodesReports(
            log=self.log,
            authorize=self.mock_authorize,
            crud_nodes=self.mock_crud_nodes,
            crud_nodes_reports=self.mock_crud_reports
        )

    async def test_get_catalog(self):
        self.mock_authorize.require_user = AsyncMock()
        self.mock_authorize.get_user_node_groups = AsyncMock(return_value=[])
        self.mock_crud_nodes.resource_exists = AsyncMock()
        self.mock_crud_catalogs.get = AsyncMock()
        
        mock_request = MagicMock()
        await self.catalogs_controller.get(
            node_id="node1", catalog_id="cat1", request=mock_request, fields=set()
        )
        
        self.mock_crud_nodes.resource_exists.assert_called_once()
        self.mock_crud_catalogs.get.assert_called_once_with(
            _id="cat1", node_id="node1", fields=[]
        )

    async def test_get_report(self):
        self.mock_authorize.require_user = AsyncMock()
        self.mock_authorize.get_user_node_groups = AsyncMock(return_value=[])
        self.mock_crud_nodes.resource_exists = AsyncMock()
        self.mock_crud_reports.get = AsyncMock()
        
        now = datetime.now()
        mock_request = MagicMock()
        await self.reports_controller.get(
            node_id="node1", report_id=now, request=mock_request, fields=set()
        )
        
        self.mock_crud_nodes.resource_exists.assert_called_once()
        self.mock_crud_reports.get.assert_called_once_with(
            _id=now, node_id="node1", fields=[]
        )

    async def test_search_catalogs(self):
        self.mock_authorize.require_user = AsyncMock()
        self.mock_authorize.get_user_node_groups = AsyncMock(return_value=[])
        self.mock_crud_nodes.resource_exists = AsyncMock()
        self.mock_crud_catalogs.search = AsyncMock()
        
        mock_request = MagicMock()
        await self.catalogs_controller.search(
            node_id="node1", request=mock_request, fields=set(), sort="id", sort_order="ascending", page=0, limit=10
        )
        self.mock_crud_catalogs.search.assert_called_once()

    async def test_search_reports(self):
        self.mock_authorize.require_user = AsyncMock()
        self.mock_authorize.get_user_node_groups = AsyncMock(return_value=[])
        self.mock_crud_nodes.resource_exists = AsyncMock()
        self.mock_crud_reports.search = AsyncMock()
        
        mock_request = MagicMock()
        await self.reports_controller.search(
            node_id="node1", request=mock_request, fields=set(), sort="id", sort_order="ascending", page=0, limit=10
        )
        self.mock_crud_reports.search.assert_called_once()
