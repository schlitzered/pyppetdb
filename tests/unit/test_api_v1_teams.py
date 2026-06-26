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
from pyppetdb.controller.api.v1.teams import ControllerApiV1Teams
from pyppetdb.model.teams import TeamPost, TeamPut, TeamGet
from pyppetdb.errors import QueryParamValidationError, ResourceNotFound
from pyppetdb.authorize import (
    PERM_HIERA_KEY_MODELS_DYNAMIC_CREATE,
    PERM_HIERA_KEY_MODELS_DYNAMIC_DELETE,
    PERM_HIERA_KEYS_CREATE,
    PERM_HIERA_KEYS_UPDATE,
    PERM_HIERA_KEYS_DELETE,
    PERM_HIERA_LEVELS_CREATE,
    PERM_HIERA_LEVELS_UPDATE,
    PERM_HIERA_LEVELS_DELETE,
    PERM_HIERA_LEVEL_DATA_CREATE,
    PERM_HIERA_LEVEL_DATA_UPDATE,
    PERM_HIERA_LEVEL_DATA_DELETE,
    PERM_HIERA_LEVEL_DATA_CREATE_DYNAMIC,
    PERM_HIERA_LEVEL_DATA_UPDATE_DYNAMIC,
    PERM_HIERA_LEVEL_DATA_DELETE_DYNAMIC,
    PERM_NODES_SECRETS_REDACTOR_CREATE,
    PERM_NODES_SECRETS_REDACTOR_DELETE,
    PERM_NODES_CREATE,
    PERM_NODES_UPDATE,
    PERM_NODES_DELETE,
    PERM_NODES_CATALOG_CACHE_DELETE,
    PERM_NODES_GROUPS_CREATE,
    PERM_NODES_GROUPS_UPDATE,
    PERM_NODES_GROUPS_DELETE,
    PERM_NODES_GROUPS_GET,
    PERM_PYPPETDB_NODES_GET,
    PERM_PYPPETDB_NODES_DELETE,
    PERM_TEAMS_CREATE,
    PERM_TEAMS_UPDATE,
    PERM_TEAMS_DELETE,
    PERM_TEAMS_GET,
    PERM_USERS_CREATE,
    PERM_USERS_UPDATE,
    PERM_USERS_DELETE,
    PERM_USERS_GET,
    PERM_USERS_CREDENTIALS_CREATE,
    PERM_USERS_CREDENTIALS_UPDATE,
    PERM_USERS_CREDENTIALS_DELETE,
    PERM_USERS_CREDENTIALS_GET,
    PERM_JOBS_JOB_CREATE,
    PERM_JOBS_JOB_CREATE_DYNAMIC,
    PERM_JOBS_DEFINITION_CREATE,
    PERM_JOBS_DEFINITION_UPDATE,
    PERM_JOBS_DEFINITION_DELETE,
    PERM_CA_SPACES_CREATE,
    PERM_CA_AUTHORITIES_UPDATE,
    PERM_CA_AUTHORITIES_CERTS_UPDATE,
    PERM_CA_SPACES_CERTS_UPDATE,
)


class TestApiV1TeamsUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_authorize = MagicMock()
        self.mock_crud_nodes_groups = MagicMock()
        self.mock_crud_teams = MagicMock()
        self.mock_crud_ldap = MagicMock()
        self.mock_crud_ca_spaces = MagicMock()
        self.mock_crud_ca_authorities = MagicMock()
        self.mock_crud_jobs_definitions = MagicMock()
        self.mock_crud_hiera_keys = MagicMock()

        self.controller = ControllerApiV1Teams(
            log=self.log,
            authorize=self.mock_authorize,
            crud_nodes_groups=self.mock_crud_nodes_groups,
            crud_teams=self.mock_crud_teams,
            crud_ldap=self.mock_crud_ldap,
            crud_ca_spaces=self.mock_crud_ca_spaces,
            crud_ca_authorities=self.mock_crud_ca_authorities,
            crud_jobs_definitions=self.mock_crud_jobs_definitions,
            crud_hiera_keys=self.mock_crud_hiera_keys,
        )

    async def test_validate_permissions_hiera_success(self):
        # Test simple Hiera permissions
        await self.controller._validate_permissions(
            [
                PERM_HIERA_KEY_MODELS_DYNAMIC_CREATE,
                PERM_HIERA_KEY_MODELS_DYNAMIC_DELETE,
                PERM_HIERA_KEYS_CREATE,
                PERM_HIERA_KEYS_UPDATE,
                PERM_HIERA_KEYS_DELETE,
                PERM_HIERA_LEVELS_CREATE,
                PERM_HIERA_LEVELS_UPDATE,
                PERM_HIERA_LEVELS_DELETE,
                PERM_HIERA_LEVEL_DATA_CREATE,
                PERM_HIERA_LEVEL_DATA_UPDATE,
                PERM_HIERA_LEVEL_DATA_DELETE,
            ]
        )

        # Test granular Hiera permission with lookup
        self.mock_crud_hiera_keys.resource_exists = AsyncMock(return_value="key1")
        await self.controller._validate_permissions(
            [
                PERM_HIERA_LEVEL_DATA_CREATE_DYNAMIC.format(key_id="key1"),
                PERM_HIERA_LEVEL_DATA_UPDATE_DYNAMIC.format(key_id="key1"),
                PERM_HIERA_LEVEL_DATA_DELETE_DYNAMIC.format(key_id="key1"),
            ]
        )
        self.assertEqual(self.mock_crud_hiera_keys.resource_exists.call_count, 3)
        self.mock_crud_hiera_keys.resource_exists.assert_called_with("key1")

    async def test_validate_permissions_nodes_secrets_redactor_success(self):
        await self.controller._validate_permissions(
            [
                PERM_NODES_SECRETS_REDACTOR_CREATE,
                PERM_NODES_SECRETS_REDACTOR_DELETE,
                PERM_NODES_CREATE,
                PERM_NODES_UPDATE,
                PERM_NODES_DELETE,
                PERM_NODES_CATALOG_CACHE_DELETE,
                PERM_NODES_GROUPS_CREATE,
                PERM_NODES_GROUPS_UPDATE,
                PERM_NODES_GROUPS_DELETE,
                PERM_NODES_GROUPS_GET,
                PERM_PYPPETDB_NODES_GET,
                PERM_PYPPETDB_NODES_DELETE,
            ]
        )

    async def test_validate_permissions_teams_users_success(self):
        await self.controller._validate_permissions(
            [
                PERM_TEAMS_CREATE,
                PERM_TEAMS_UPDATE,
                PERM_TEAMS_DELETE,
                PERM_TEAMS_GET,
                PERM_USERS_CREATE,
                PERM_USERS_UPDATE,
                PERM_USERS_DELETE,
                PERM_USERS_GET,
                PERM_USERS_CREDENTIALS_CREATE,
                PERM_USERS_CREDENTIALS_UPDATE,
                PERM_USERS_CREDENTIALS_DELETE,
                PERM_USERS_CREDENTIALS_GET,
            ]
        )

    async def test_validate_permissions_jobs_success(self):
        # Test simple job permissions
        await self.controller._validate_permissions(
            [
                PERM_JOBS_JOB_CREATE,
                PERM_JOBS_DEFINITION_CREATE,
                PERM_JOBS_DEFINITION_UPDATE,
                PERM_JOBS_DEFINITION_DELETE,
            ]
        )

        # Test granular job permission with lookup
        self.mock_crud_jobs_definitions.resource_exists = AsyncMock(return_value="job1")
        await self.controller._validate_permissions(
            [PERM_JOBS_JOB_CREATE_DYNAMIC.format(definition_id="job1")]
        )
        self.mock_crud_jobs_definitions.resource_exists.assert_called_once_with("job1")

    async def test_create_team_with_ldap(self):
        self.mock_authorize.require_perm = AsyncMock()
        self.mock_crud_ldap.get_logins_from_group = AsyncMock(
            return_value=["user1", "user2"]
        )
        self.mock_crud_teams.create = AsyncMock()

        data = TeamPost(ldap_group="engineers", permissions=[])
        mock_request = MagicMock()

        await self.controller.create(
            team_id="team1", request=mock_request, data=data, fields=set()
        )

        self.mock_authorize.require_perm.assert_called_once_with(
            request=mock_request, permission=PERM_TEAMS_CREATE
        )
        self.mock_crud_ldap.get_logins_from_group.assert_called_once_with(
            group="engineers"
        )
        self.assertEqual(data.users, ["user1", "user2"])
        self.mock_crud_teams.create.assert_called_once_with(
            _id="team1", payload=data, fields=[]
        )

    async def test_create_team_no_ldap(self):
        self.mock_authorize.require_perm = AsyncMock()
        self.mock_crud_teams.create = AsyncMock()

        data = TeamPost(ldap_group="", users=["manual-user"], permissions=[])
        mock_request = MagicMock()

        await self.controller.create(
            team_id="team1", request=mock_request, data=data, fields=set()
        )

        self.mock_authorize.require_perm.assert_called_once_with(
            request=mock_request, permission=PERM_TEAMS_CREATE
        )
        self.mock_crud_ldap.get_logins_from_group.assert_not_called()
        self.assertEqual(data.users, ["manual-user"])

    async def test_delete_team(self):
        self.mock_authorize.require_perm = AsyncMock()
        self.mock_crud_nodes_groups.delete_team_from_nodes_groups = AsyncMock()
        self.mock_crud_teams.delete = AsyncMock()

        mock_request = MagicMock()
        await self.controller.delete(team_id="team1", request=mock_request)

        self.mock_authorize.require_perm.assert_called_once_with(
            request=mock_request, permission=PERM_TEAMS_DELETE
        )
        self.mock_crud_nodes_groups.delete_team_from_nodes_groups.assert_called_once_with(
            team_id="team1"
        )
        self.mock_crud_teams.delete.assert_called_once_with(_id="team1")

    async def test_get_team(self):
        self.mock_authorize.require_perm = AsyncMock()
        self.mock_crud_teams.get = AsyncMock()

        mock_request = MagicMock()
        await self.controller.get(team_id="team1", request=mock_request, fields=set())

        self.mock_authorize.require_perm.assert_called_once_with(
            request=mock_request, permission=PERM_TEAMS_GET
        )
        self.mock_crud_teams.get.assert_called_once_with(_id="team1", fields=[])

    async def test_search_teams(self):
        self.mock_authorize.require_perm = AsyncMock()
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

        self.mock_authorize.require_perm.assert_called_once_with(
            request=mock_request, permission=PERM_TEAMS_GET
        )
        self.mock_crud_teams.search.assert_called_once()

    async def test_update_team(self):
        self.mock_authorize.require_perm = AsyncMock()
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

        self.mock_authorize.require_perm.assert_called_once_with(
            request=mock_request, permission=PERM_TEAMS_UPDATE
        )
        self.assertEqual(data.users, ["u1"])
        self.mock_crud_teams.update.assert_called_once()

    async def test_validate_permissions_success(self):
        # Test simple permissions
        await self.controller._validate_permissions(
            [PERM_CA_SPACES_CREATE, PERM_CA_AUTHORITIES_UPDATE]
        )

        # Test granular permissions with resource lookup
        self.mock_crud_ca_spaces.resource_exists = AsyncMock(return_value="space1")
        self.mock_crud_ca_authorities.resource_exists = AsyncMock(return_value="auth1")

        await self.controller._validate_permissions(
            [
                PERM_CA_SPACES_CERTS_UPDATE.format(space_id="space1"),
                PERM_CA_AUTHORITIES_CERTS_UPDATE.format(ca_id="auth1"),
            ]
        )

        self.mock_crud_ca_spaces.resource_exists.assert_called_once_with("space1")
        self.mock_crud_ca_authorities.resource_exists.assert_called_once_with("auth1")

    async def test_validate_permissions_invalid_format(self):
        with self.assertRaises(QueryParamValidationError) as cm:
            await self.controller._validate_permissions(
                ["CA:SPACES:VIEW"]
            )  # VIEW is now invalid
        self.assertIn("Invalid permission format", str(cm.exception.detail))

    async def test_validate_permissions_resource_not_found(self):
        self.mock_crud_ca_spaces.resource_exists = AsyncMock(
            side_effect=ResourceNotFound("space1")
        )
        with self.assertRaises(QueryParamValidationError) as cm:
            await self.controller._validate_permissions(
                [PERM_CA_SPACES_CERTS_UPDATE.format(space_id="space1")]
            )
        self.assertIn("CA Space 'space1' does not exist", str(cm.exception.detail))

        self.mock_crud_ca_authorities.resource_exists = AsyncMock(
            side_effect=ResourceNotFound("auth1")
        )
        with self.assertRaises(QueryParamValidationError) as cm:
            await self.controller._validate_permissions(
                [PERM_CA_AUTHORITIES_CERTS_UPDATE.format(ca_id="auth1")]
            )
        self.assertIn("CA Authority 'auth1' does not exist", str(cm.exception.detail))
