import unittest
from unittest.mock import MagicMock, AsyncMock, patch
import logging
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
        self.mock_authorize.require_admin = AsyncMock()
        self.controller._upsert_data = AsyncMock(return_value=MagicMock())
        self.mock_crud_groups.create = AsyncMock()

        data = NodeGroupUpdate(teams=["team1"])
        mock_request = MagicMock()
        await self.controller.create(
            node_group_id="group1", request=mock_request, data=data, fields=set()
        )

        self.mock_authorize.require_admin.assert_called_once_with(request=mock_request)
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
        self.mock_authorize.require_admin = AsyncMock()
        self.mock_crud_nodes.delete_node_group_from_all = AsyncMock()
        self.mock_crud_groups.delete = AsyncMock()

        mock_request = MagicMock()
        await self.controller.delete(node_group_id="group1", request=mock_request)

        self.mock_authorize.require_admin.assert_called_once_with(request=mock_request)
        self.mock_crud_nodes.delete_node_group_from_all.assert_called_once_with(
            node_group_id="group1"
        )
        self.mock_crud_groups.delete.assert_called_once_with(_id="group1")

    async def test_get_group(self):
        self.mock_authorize.require_admin = AsyncMock()
        self.mock_crud_groups.get = AsyncMock()

        mock_request = MagicMock()
        await self.controller.get(
            node_group_id="group1", request=mock_request, fields=set()
        )
        self.mock_crud_groups.get.assert_called_once()

    async def test_search_groups(self):
        self.mock_authorize.require_admin = AsyncMock()
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
        self.mock_crud_groups.search.assert_called_once()

    async def test_update_group(self):
        self.mock_authorize.require_admin = AsyncMock()
        self.controller._upsert_data = AsyncMock()
        self.mock_crud_groups.update = AsyncMock()

        data = NodeGroupUpdate(teams=["team1"])
        mock_request = MagicMock()
        await self.controller.update(
            node_group_id="group1", request=mock_request, data=data, fields=set()
        )
        self.mock_crud_groups.update.assert_called_once()
