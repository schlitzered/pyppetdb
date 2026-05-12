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
from pyppetdb.controller.api.v1.ca_authorities import ControllerApiV1CAAuthorities
from pyppetdb.controller.api.v1.ca_spaces import ControllerApiV1CASpaces
from pyppetdb.model.ca_authorities import CAAuthorityPut
from pyppetdb.model.ca_spaces import CASpacePost
from pyppetdb.authorize import PERM_CA_AUTHORITIES_UPDATE
from pyppetdb.authorize import PERM_CA_AUTHORITIES_DELETE
from pyppetdb.authorize import PATTERN_CA_AUTHORITIES
from pyppetdb.authorize import PERM_CA_GET
from pyppetdb.authorize import PERM_CA_SPACES_CREATE
from pyppetdb.authorize import PERM_CA_SPACES_DELETE
from pyppetdb.authorize import PATTERN_CA_SPACES


class TestApiV1CAAuthoritiesUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_authorize = MagicMock()
        self.mock_crud_authorities = MagicMock()
        self.mock_crud_teams = MagicMock()
        self.mock_ca_service = MagicMock()

        self.controller = ControllerApiV1CAAuthorities(
            log=self.log,
            authorize=self.mock_authorize,
            crud_authorities=self.mock_crud_authorities,
            crud_teams=self.mock_crud_teams,
            ca_service=self.mock_ca_service,
        )

    async def test_update_authority_permission(self):
        self.mock_authorize.require_perm = AsyncMock()
        self.mock_ca_service.update_authority = AsyncMock()
        self.mock_ca_service.revoke_authority = AsyncMock()

        mock_request = MagicMock()
        data = CAAuthorityPut(status="revoked")

        await self.controller.update(
            request=mock_request, ca_id="ca1", data=data, fields=set()
        )

        self.mock_authorize.require_perm.assert_called_once_with(
            request=mock_request,
            permission=PERM_CA_AUTHORITIES_UPDATE,
        )
        self.mock_ca_service.update_authority.assert_called_once_with(
            ca_id="ca1", payload=data, fields=[]
        )

    async def test_delete_authority_permission(self):
        self.mock_authorize.require_perm = AsyncMock()
        self.mock_ca_service.delete_authority = AsyncMock()
        self.mock_crud_teams.drop_permissions_by_pattern = AsyncMock()

        mock_request = MagicMock()
        await self.controller.delete(request=mock_request, ca_id="ca1")

        self.mock_authorize.require_perm.assert_called_once_with(
            request=mock_request,
            permission=PERM_CA_AUTHORITIES_DELETE,
        )
        self.mock_ca_service.delete_authority.assert_called_once_with("ca1")
        self.mock_crud_teams.drop_permissions_by_pattern.assert_called_once_with(
            PATTERN_CA_AUTHORITIES.format(ca_id="ca1"),
        )

    async def test_get_authority_permission(self):
        self.mock_authorize.require_perm = AsyncMock()
        self.mock_crud_authorities.get = AsyncMock()

        mock_request = MagicMock()
        await self.controller.get(request=mock_request, ca_id="ca1", fields=set())

        self.mock_authorize.require_perm.assert_called_once_with(
            request=mock_request,
            permission=PERM_CA_GET,
        )
        self.mock_crud_authorities.get.assert_called_once()

    async def test_search_authorities_permission(self):
        self.mock_authorize.require_perm = AsyncMock()
        self.mock_crud_authorities.search = AsyncMock()

        mock_request = MagicMock()
        await self.controller.search(request=mock_request, fields=set())

        self.mock_authorize.require_perm.assert_called_once_with(
            request=mock_request,
            permission=PERM_CA_GET,
        )
        self.mock_crud_authorities.search.assert_called_once()


class TestApiV1CASpacesUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_authorize = MagicMock()
        self.mock_crud_ca_spaces = MagicMock()
        self.mock_crud_ca_authorities = MagicMock()
        self.mock_crud_ca_certificates = MagicMock()
        self.mock_crud_teams = MagicMock()
        self.mock_ca_service = MagicMock()

        self.controller = ControllerApiV1CASpaces(
            log=self.log,
            authorize=self.mock_authorize,
            crud_ca_spaces=self.mock_crud_ca_spaces,
            crud_ca_authorities=self.mock_crud_ca_authorities,
            crud_ca_certificates=self.mock_crud_ca_certificates,
            crud_teams=self.mock_crud_teams,
            ca_service=self.mock_ca_service,
        )

    async def test_create_space_permission(self):
        self.mock_authorize.require_perm = AsyncMock()
        self.mock_ca_service.create_space = AsyncMock()

        mock_request = MagicMock()
        data = CASpacePost(ca_id="ca1")

        await self.controller.create(
            request=mock_request, space_id="space1", data=data, fields=set()
        )

        self.mock_authorize.require_perm.assert_called_once_with(
            request=mock_request,
            permission=PERM_CA_SPACES_CREATE,
        )
        self.mock_ca_service.create_space.assert_called_once()

    async def test_delete_space_permission(self):
        self.mock_authorize.require_perm = AsyncMock()
        self.mock_crud_ca_certificates.count = AsyncMock(return_value=0)
        self.mock_ca_service.delete_space = AsyncMock()
        self.mock_crud_teams.drop_permissions_by_pattern = AsyncMock()

        mock_request = MagicMock()
        await self.controller.delete(request=mock_request, space_id="space1")

        self.mock_authorize.require_perm.assert_called_once_with(
            request=mock_request,
            permission=PERM_CA_SPACES_DELETE,
        )
        self.mock_ca_service.delete_space.assert_called_once_with(_id="space1")
        self.mock_crud_teams.drop_permissions_by_pattern.assert_called_once_with(
            PATTERN_CA_SPACES.format(space_id="space1"),
        )

    async def test_get_space_permission(self):
        self.mock_authorize.require_perm = AsyncMock()
        self.mock_crud_ca_spaces.get = AsyncMock()

        mock_request = MagicMock()
        await self.controller.get(request=mock_request, space_id="space1", fields=set())

        self.mock_authorize.require_perm.assert_called_once_with(
            request=mock_request,
            permission=PERM_CA_GET,
        )
        self.mock_crud_ca_spaces.get.assert_called_once()

    async def test_search_spaces_permission(self):
        self.mock_authorize.require_perm = AsyncMock()
        self.mock_crud_ca_spaces.search = AsyncMock()

        mock_request = MagicMock()
        await self.controller.search(request=mock_request, fields=set())

        self.mock_authorize.require_perm.assert_called_once_with(
            request=mock_request,
            permission=PERM_CA_GET,
        )
        self.mock_crud_ca_spaces.search.assert_called_once()
