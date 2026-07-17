# Copyright 2026 Stephan Schultchen
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import unittest
from unittest.mock import MagicMock, AsyncMock
import logging
from pyppetdb.authorize import (
    PERM_NODES_CREATE,
    PERM_NODES_UPDATE,
    PERM_NODES_DELETE,
    PERM_NODES_CATALOG_CACHE_DELETE,
)
from pyppetdb.controller.api.v1.nodes import ControllerApiV1Nodes
from pyppetdb.model.nodes import NodePut


class TestApiV1NodesUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_authorize = MagicMock()
        self.mock_crud_nodes = MagicMock()
        self.mock_crud_nodes.get_placement = AsyncMock(return_value={})
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
        await self.controller.get(
            node_id="node1", request=mock_request, fields=set(), outdated_threshold=None
        )

        self.mock_authorize.require_user.assert_called_once_with(request=mock_request)
        self.mock_crud_nodes.get.assert_called_once_with(
            _id="node1", user_node_groups=[], fields=[], outdated_threshold=None
        )

    async def test_delete_node_cascades(self):
        self.mock_authorize.require_perm = AsyncMock()
        self.mock_ca_service.update_certificate_status = AsyncMock()
        self.mock_crud_groups.delete_node_from_nodes_groups = AsyncMock()
        self.mock_crud_catalogs.delete_all_from_node = AsyncMock()
        self.mock_crud_reports.delete_all_from_node = AsyncMock()
        self.mock_crud_jobs.remove_node_from_jobs = AsyncMock()
        self.mock_crud_node_jobs.delete_by_node = AsyncMock()
        self.mock_crud_nodes.delete = AsyncMock()

        mock_request = MagicMock()
        await self.controller.delete(node_id="node1", request=mock_request)

        self.mock_authorize.require_perm.assert_called_once_with(
            request=mock_request, permission=PERM_NODES_DELETE
        )
        self.mock_ca_service.update_certificate_status.assert_called_once()
        self.mock_crud_groups.delete_node_from_nodes_groups.assert_called_once_with(
            node_id="node1"
        )
        self.mock_crud_catalogs.delete_all_from_node.assert_called_once_with(
            node_id="node1",
            placement={},
        )
        self.mock_crud_reports.delete_all_from_node.assert_called_once_with(
            node_id="node1",
            placement={},
        )
        self.mock_crud_jobs.remove_node_from_jobs.assert_called_once_with(
            node_id="node1"
        )
        self.mock_crud_node_jobs.delete_by_node.assert_called_once_with(node_id="node1")
        self.mock_crud_nodes.delete.assert_called_once_with(_id="node1")

    async def test_update_node_perm_required(self):
        self.mock_authorize.require_perm = AsyncMock()
        self.mock_crud_nodes.update = AsyncMock()

        data = NodePut(disabled=True)
        mock_request = MagicMock()
        await self.controller.update(
            node_id="node1", request=mock_request, data=data, fields=set()
        )

        self.mock_authorize.require_perm.assert_called_once_with(
            request=mock_request, permission=PERM_NODES_UPDATE
        )
        self.mock_crud_nodes.update.assert_called_once()
        args = self.mock_crud_nodes.update.call_args[1]
        self.assertEqual(args["_id"], "node1")
        self.assertEqual(args["payload"].disabled, True)

    async def test_create_node_perm_required(self):
        self.mock_authorize.require_perm = AsyncMock()
        self.mock_crud_nodes.create = AsyncMock()

        data = NodePut(disabled=True)
        mock_request = MagicMock()
        await self.controller.create(
            node_id="node2", request=mock_request, data=data, fields=set()
        )

        self.mock_authorize.require_perm.assert_called_once_with(
            request=mock_request, permission=PERM_NODES_CREATE
        )
        self.mock_crud_nodes.create.assert_called_once()
        args = self.mock_crud_nodes.create.call_args[1]
        self.assertEqual(args["_id"], "node2")
        self.assertEqual(args["payload"].disabled, True)

    async def test_catalog_cache_wipe_perm_required(self):
        self.mock_authorize.require_perm = AsyncMock()
        self.mock_crud_catalog_cache.delete_many_by_filter = AsyncMock()

        mock_request = MagicMock()
        await self.controller.catalog_cache_wipe(
            request=mock_request, node_id="node1", environment="prod", fact=set()
        )

        self.mock_authorize.require_perm.assert_called_once_with(
            request=mock_request, permission=PERM_NODES_CATALOG_CACHE_DELETE
        )
        self.mock_crud_catalog_cache.delete_many_by_filter.assert_called_once_with(
            node_id="node1", environment="prod", fact=set()
        )
