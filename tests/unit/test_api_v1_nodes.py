import unittest
from unittest.mock import MagicMock, AsyncMock
import logging
from pyppetdb.controller.api.v1.nodes import ControllerApiV1Nodes
from pyppetdb.model.nodes import NodePut


class TestApiV1NodesUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_authorize = MagicMock()
        self.mock_crud_nodes = MagicMock()
        self.mock_crud_catalog_cache = MagicMock()
        self.mock_crud_catalogs = MagicMock()
        self.mock_crud_groups = MagicMock()
        self.mock_crud_reports = MagicMock()
        self.mock_crud_teams = MagicMock()
        self.mock_crud_jobs = MagicMock()
        self.mock_crud_jobs.remove_node_from_jobs = AsyncMock()
        self.mock_crud_node_jobs = MagicMock()
        self.mock_crud_node_jobs.delete_by_node = AsyncMock()
        self.mock_ca_service = MagicMock()

        self.controller = ControllerApiV1Nodes(
            log=self.log,
            authorize=self.mock_authorize,
            crud_nodes=self.mock_crud_nodes,
            crud_nodes_catalog_cache=self.mock_crud_catalog_cache,
            crud_nodes_catalogs=self.mock_crud_catalogs,
            crud_nodes_groups=self.mock_crud_groups,
            crud_nodes_reports=self.mock_crud_reports,
            crud_teams=self.mock_crud_teams,
            crud_jobs=self.mock_crud_jobs,
            crud_node_jobs=self.mock_crud_node_jobs,
            ca_service=self.mock_ca_service,
        )

    async def test_get_node(self):
        self.mock_authorize.require_user = AsyncMock()
        self.mock_authorize.get_user_node_groups = AsyncMock(return_value=[])
        self.mock_crud_nodes.get = AsyncMock()

        mock_request = MagicMock()
        await self.controller.get(node_id="node1", request=mock_request, fields=set())

        self.mock_authorize.require_user.assert_called_once_with(request=mock_request)
        self.mock_crud_nodes.get.assert_called_once_with(
            _id="node1", user_node_groups=[], fields=[]
        )

    async def test_delete_node_cascades(self):
        self.mock_authorize.require_admin = AsyncMock()
        self.mock_ca_service.update_certificate_status = AsyncMock()
        self.mock_crud_groups.delete_node_from_nodes_groups = AsyncMock()
        self.mock_crud_catalogs.delete_all_from_node = AsyncMock()
        self.mock_crud_reports.delete_all_from_node = AsyncMock()
        self.mock_crud_jobs.remove_node_from_jobs = AsyncMock()
        self.mock_crud_node_jobs.delete_by_node = AsyncMock()
        self.mock_crud_nodes.delete = AsyncMock()

        mock_request = MagicMock()
        await self.controller.delete(node_id="node1", request=mock_request)

        self.mock_authorize.require_admin.assert_called_once_with(request=mock_request)
        self.mock_ca_service.update_certificate_status.assert_called_once()
        self.mock_crud_groups.delete_node_from_nodes_groups.assert_called_once_with(
            node_id="node1"
        )
        self.mock_crud_catalogs.delete_all_from_node.assert_called_once_with(
            node_id="node1"
        )
        self.mock_crud_reports.delete_all_from_node.assert_called_once_with(
            node_id="node1"
        )
        self.mock_crud_jobs.remove_node_from_jobs.assert_called_once_with(
            node_id="node1"
        )
        self.mock_crud_node_jobs.delete_by_node.assert_called_once_with(node_id="node1")
        self.mock_crud_nodes.delete.assert_called_once_with(_id="node1")

    async def test_update_node_admin_required(self):
        self.mock_authorize.require_admin = AsyncMock()
        self.mock_crud_nodes.update = AsyncMock()

        data = NodePut(disabled=True)
        mock_request = MagicMock()
        await self.controller.update(
            node_id="node1", request=mock_request, data=data, fields=set()
        )

        self.mock_authorize.require_admin.assert_called_once_with(request=mock_request)
        self.mock_crud_nodes.update.assert_called_once()
        args = self.mock_crud_nodes.update.call_args[1]
        self.assertEqual(args["_id"], "node1")
        self.assertEqual(args["payload"].disabled, True)

    async def test_create_node_admin_required(self):
        self.mock_authorize.require_admin = AsyncMock()
        self.mock_crud_nodes.create = AsyncMock()

        data = NodePut(disabled=True)
        mock_request = MagicMock()
        await self.controller.create(
            node_id="node2", request=mock_request, data=data, fields=set()
        )

        self.mock_authorize.require_admin.assert_called_once_with(request=mock_request)
        self.mock_crud_nodes.create.assert_called_once()
        args = self.mock_crud_nodes.create.call_args[1]
        self.assertEqual(args["_id"], "node2")
        self.assertEqual(args["payload"].disabled, True)
