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
    PERM_NODES_GROUPS_CREATE,
    PERM_NODES_GROUPS_UPDATE,
    PERM_NODES_GROUPS_DELETE,
    PERM_NODES_GROUPS_GET,
)
from pyppetdb.controller.api.v1.nodes_groups import ControllerApiV1NodesGroups
from pyppetdb.model.nodes_groups import NodeGroupUpdate


class TestApiV1NodesGroupsUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_authorize = MagicMock()
        self.mock_crud_nodes = MagicMock()
        self.mock_crud_groups = MagicMock()
        self.mock_crud_teams = MagicMock()

        self.controller = ControllerApiV1NodesGroups(
            log=self.log,
            authorize=self.mock_authorize,
            crud_nodes=self.mock_crud_nodes,
            crud_nodes_groups=self.mock_crud_groups,
            crud_teams=self.mock_crud_teams,
        )

    async def test_create_group_calls_upsert(self):
        self.mock_authorize.require_perm = AsyncMock()
        self.controller._upsert_data = AsyncMock(return_value=MagicMock())
        self.mock_crud_groups.create = AsyncMock()

        data = NodeGroupUpdate(teams=["team1"])
        mock_request = MagicMock()
        await self.controller.create(
            node_group_id="group1", request=mock_request, data=data, fields=set()
        )

        self.mock_authorize.require_perm.assert_called_once_with(
            request=mock_request, permission=PERM_NODES_GROUPS_CREATE
        )
        self.controller._upsert_data.assert_called_once()
        self.mock_crud_groups.create.assert_called_once()

    async def test_upsert_data_logic(self):
        # Mocking sub-calls of _upsert_data
        self.controller.add_nodes_from_filter = AsyncMock()
        self.mock_crud_teams.resource_exists = AsyncMock()
        self.mock_crud_nodes.update_nodegroup = AsyncMock()

        data = NodeGroupUpdate(teams=["team1"], filters=[])

        await self.controller._upsert_data(node_group_id="group1", data=data)

        self.controller.add_nodes_from_filter.assert_called_once()
        self.mock_crud_teams.resource_exists.assert_called_once_with(_id="team1")
        self.mock_crud_nodes.update_nodegroup.assert_called_once()

    async def test_delete_group(self):
        self.mock_authorize.require_perm = AsyncMock()
        self.mock_crud_nodes.delete_node_group_from_all = AsyncMock()
        self.mock_crud_groups.delete = AsyncMock()

        mock_request = MagicMock()
        await self.controller.delete(node_group_id="group1", request=mock_request)

        self.mock_authorize.require_perm.assert_called_once_with(
            request=mock_request, permission=PERM_NODES_GROUPS_DELETE
        )
        self.mock_crud_nodes.delete_node_group_from_all.assert_called_once_with(
            node_group_id="group1"
        )
        self.mock_crud_groups.delete.assert_called_once_with(_id="group1")

    async def test_get_group(self):
        self.mock_authorize.require_perm = AsyncMock()
        self.mock_crud_groups.get = AsyncMock()

        mock_request = MagicMock()
        await self.controller.get(
            node_group_id="group1", request=mock_request, fields=set()
        )
        self.mock_authorize.require_perm.assert_called_once_with(
            request=mock_request, permission=PERM_NODES_GROUPS_GET
        )
        self.mock_crud_groups.get.assert_called_once()

    async def test_search_groups(self):
        self.mock_authorize.require_perm = AsyncMock()
        self.mock_authorize.get_user_teams = AsyncMock(return_value=[])
        self.mock_crud_groups.search = AsyncMock()

        mock_request = MagicMock()
        await self.controller.search(
            request=mock_request,
            node_group_id=None,
            nodes=None,
            teams=None,
            fields=set(),
            sort="id",
            sort_order="ascending",
            page=0,
            limit=10,
        )
        self.mock_authorize.require_perm.assert_called_once_with(
            request=mock_request, permission=PERM_NODES_GROUPS_GET
        )
        self.mock_crud_groups.search.assert_called_once()

    async def test_update_group(self):
        self.mock_authorize.require_perm = AsyncMock()
        self.controller._upsert_data = AsyncMock()
        self.mock_crud_groups.update = AsyncMock()

        data = NodeGroupUpdate(teams=["team1"])
        mock_request = MagicMock()
        await self.controller.update(
            node_group_id="group1", request=mock_request, data=data, fields=set()
        )
        self.mock_authorize.require_perm.assert_called_once_with(
            request=mock_request, permission=PERM_NODES_GROUPS_UPDATE
        )
        self.mock_crud_groups.update.assert_called_once()
