import unittest
from unittest.mock import MagicMock, AsyncMock
import logging
from pyppetdb.controller.api.v1.teams import ControllerApiV1Teams
from pyppetdb.model.teams import TeamPost, TeamPut, TeamGet
from pyppetdb.errors import QueryParamValidationError, ResourceNotFound


class TestApiV1TeamsUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_authorize = MagicMock()
        self.mock_crud_nodes_groups = MagicMock()
        self.mock_crud_teams = MagicMock()
        self.mock_crud_ldap = MagicMock()
        self.mock_crud_ca_spaces = MagicMock()
        self.mock_crud_ca_authorities = MagicMock()

        self.controller = ControllerApiV1Teams(
            log=self.log,
            authorize=self.mock_authorize,
            crud_nodes_groups=self.mock_crud_nodes_groups,
            crud_teams=self.mock_crud_teams,
            crud_ldap=self.mock_crud_ldap,
            crud_ca_spaces=self.mock_crud_ca_spaces,
            crud_ca_authorities=self.mock_crud_ca_authorities,
        )

    async def test_create_team_with_ldap(self):
        self.mock_authorize.require_admin = AsyncMock()
        self.mock_crud_ldap.get_logins_from_group = AsyncMock(
            return_value=["user1", "user2"]
        )
        self.mock_crud_teams.create = AsyncMock()

        data = TeamPost(ldap_group="engineers", permissions=[])
        mock_request = MagicMock()

        await self.controller.create(
            team_id="team1", request=mock_request, data=data, fields=set()
        )

        self.mock_authorize.require_admin.assert_called_once_with(request=mock_request)
        self.mock_crud_ldap.get_logins_from_group.assert_called_once_with(
            group="engineers"
        )
        self.assertEqual(data.users, ["user1", "user2"])
        self.mock_crud_teams.create.assert_called_once_with(
            _id="team1", payload=data, fields=[]
        )

    async def test_create_team_no_ldap(self):
        self.mock_authorize.require_admin = AsyncMock()
        self.mock_crud_teams.create = AsyncMock()

        data = TeamPost(ldap_group="", users=["manual-user"], permissions=[])
        mock_request = MagicMock()

        await self.controller.create(
            team_id="team1", request=mock_request, data=data, fields=set()
        )

        self.mock_crud_ldap.get_logins_from_group.assert_not_called()
        self.assertEqual(data.users, ["manual-user"])

    async def test_delete_team(self):
        self.mock_authorize.require_admin = AsyncMock()
        self.mock_crud_nodes_groups.delete_team_from_nodes_groups = AsyncMock()
        self.mock_crud_teams.delete = AsyncMock()

        mock_request = MagicMock()
        await self.controller.delete(team_id="team1", request=mock_request)

        self.mock_crud_nodes_groups.delete_team_from_nodes_groups.assert_called_once_with(
            team_id="team1"
        )
        self.mock_crud_teams.delete.assert_called_once_with(_id="team1")

    async def test_get_team(self):
        self.mock_authorize.require_admin = AsyncMock()
        self.mock_crud_teams.get = AsyncMock()

        mock_request = MagicMock()
        await self.controller.get(team_id="team1", request=mock_request, fields=set())

        self.mock_authorize.require_admin.assert_called_once_with(request=mock_request)
        self.mock_crud_teams.get.assert_called_once_with(_id="team1", fields=[])

    async def test_search_teams(self):
        self.mock_authorize.require_admin = AsyncMock()
        self.mock_crud_teams.search = AsyncMock()

        mock_request = MagicMock()
        await self.controller.search(
            request=mock_request,
            team_id=None,
            ldap_group=None,
            users=None,
            fields=set(),
            sort="id",
            sort_order="ascending",
            page=0,
            limit=10,
        )

        self.mock_authorize.require_admin.assert_called_once_with(request=mock_request)
        self.mock_crud_teams.search.assert_called_once()

    async def test_update_team(self):
        self.mock_authorize.require_admin = AsyncMock()
        self.mock_crud_teams.get = AsyncMock(
            return_value=TeamGet(id="team1", ldap_group="old")
        )
        self.mock_crud_ldap.get_logins_from_group = AsyncMock(return_value=["u1"])
        self.mock_crud_teams.update = AsyncMock()

        data = TeamPut(ldap_group="new-ldap")
        mock_request = MagicMock()
        await self.controller.update(
            team_id="team1", request=mock_request, data=data, fields=set()
        )

        self.assertEqual(data.users, ["u1"])
        self.mock_crud_teams.update.assert_called_once()

    async def test_validate_permissions_success(self):
        # Test simple permissions
        await self.controller._validate_permissions(
            ["CA:SPACES:CREATE", "CA:AUTHORITIES:UPDATE"]
        )

        # Test granular permissions with resource lookup
        self.mock_crud_ca_spaces.get = AsyncMock(return_value=MagicMock(id="space1"))
        self.mock_crud_ca_authorities.get = AsyncMock(
            return_value=MagicMock(id="auth1")
        )

        await self.controller._validate_permissions(
            ["CA:SPACES:space1:CERTS:UPDATE", "CA:AUTHORITIES:auth1:CERTS:UPDATE"]
        )

        self.mock_crud_ca_spaces.get.assert_called_once_with("space1", fields=["id"])
        self.mock_crud_ca_authorities.get.assert_called_once_with(
            "auth1", fields=["id"]
        )

    async def test_validate_permissions_invalid_format(self):
        with self.assertRaises(QueryParamValidationError) as cm:
            await self.controller._validate_permissions(
                ["CA:SPACES:VIEW"]
            )  # VIEW is now invalid
        self.assertIn("Invalid permission format", str(cm.exception.detail))

    async def test_validate_permissions_resource_not_found(self):
        self.mock_crud_ca_spaces.get = AsyncMock(side_effect=ResourceNotFound("space1"))
        with self.assertRaises(QueryParamValidationError) as cm:
            await self.controller._validate_permissions(
                ["CA:SPACES:space1:CERTS:UPDATE"]
            )
        self.assertIn("CA Space 'space1' does not exist", str(cm.exception.detail))

        self.mock_crud_ca_authorities.get = AsyncMock(
            side_effect=ResourceNotFound("auth1")
        )
        with self.assertRaises(QueryParamValidationError) as cm:
            await self.controller._validate_permissions(
                ["CA:AUTHORITIES:auth1:CERTS:UPDATE"]
            )
        self.assertIn("CA Authority 'auth1' does not exist", str(cm.exception.detail))
