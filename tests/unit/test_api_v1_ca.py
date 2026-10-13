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
import re
from pyppetdb.controller.api.v1.ca_authorities import ControllerApiV1CAAuthorities
from pyppetdb.controller.api.v1.ca_spaces import ControllerApiV1CASpaces
from pyppetdb.errors import QueryParamValidationError
from pyppetdb.model.ca_authorities import CAAuthorityPost
from pyppetdb.model.ca_authorities import CAAuthorityPut
from pyppetdb.model.ca_spaces import CASpacePost
from pyppetdb.model.ca_spaces import CASpacePut
from pyppetdb.model.ca_validation import CAValidationConfig
from pyppetdb.authorize import PERM_CA_AUTHORITIES_UPDATE
from pyppetdb.authorize import PERM_CA_AUTHORITIES_DELETE
from pyppetdb.authorize import PATTERN_CA_AUTHORITIES
from pyppetdb.authorize import PERM_CA_GET
from pyppetdb.authorize import PERM_CA_SPACES_CREATE
from pyppetdb.authorize import PERM_CA_SPACES_DELETE
from pyppetdb.authorize import PATTERN_CA_SPACES


def _config_with_password(password):
    return CAValidationConfig(
        san_validation={
            "http_checks": [
                {
                    "url": "https://check.example.com",
                    "basic_auth_enabled": True,
                    "username": "user",
                    "password": password,
                }
            ]
        }
    )


class TestApiV1CAAuthoritiesUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_authorize = MagicMock()
        self.mock_crud_authorities = MagicMock()
        self.mock_crud_teams = MagicMock()
        self.mock_ca_service = MagicMock()

        self.mock_crud_secrets = MagicMock()
        self.mock_crud_secrets.existing_ids = AsyncMock(return_value=set())

        self.controller = ControllerApiV1CAAuthorities(
            log=self.log,
            authorize=self.mock_authorize,
            crud_authorities=self.mock_crud_authorities,
            crud_secrets=self.mock_crud_secrets,
            crud_teams=self.mock_crud_teams,
            ca_service=self.mock_ca_service,
        )

    async def test_update_authority_permission(self):
        self.mock_authorize.require_perm = AsyncMock()
        self.mock_ca_service.update_authority = AsyncMock()

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

    async def test_delete_authority_escapes_regex_metacharacters(self):
        self.mock_authorize.require_perm = AsyncMock()
        self.mock_ca_service.delete_authority = AsyncMock()
        self.mock_crud_teams.drop_permissions_by_pattern = AsyncMock()

        mock_request = MagicMock()
        await self.controller.delete(request=mock_request, ca_id=".*")

        pattern = self.mock_crud_teams.drop_permissions_by_pattern.call_args[0][0]
        self.assertEqual(
            pattern, PATTERN_CA_AUTHORITIES.format(ca_id=re.escape(".*"))
        )
        self.assertIn(r"\.\*", pattern)
        self.assertNotIn("^CA:AUTHORITIES:.*:", pattern)

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

    async def test_create_authority_rejects_unknown_secret_before_service(self):
        self.mock_authorize.require_perm = AsyncMock()
        self.mock_ca_service.create_authority = AsyncMock()
        data = CAAuthorityPost(
            cn="CA1", validation_config=_config_with_password("$secrets[MISSING]")
        )

        with self.assertRaises(QueryParamValidationError) as ctx:
            await self.controller.create(
                request=MagicMock(), ca_id="ca1", data=data, fields=set()
            )

        self.assertIn("unknown secret references: MISSING", ctx.exception.detail)
        self.mock_crud_secrets.existing_ids.assert_awaited_once_with({"MISSING"})
        self.mock_ca_service.create_authority.assert_not_called()

    async def test_create_authority_with_known_secret_reaches_service(self):
        self.mock_authorize.require_perm = AsyncMock()
        self.mock_ca_service.create_authority = AsyncMock()
        self.mock_crud_secrets.existing_ids.return_value = {"KNOWN"}
        data = CAAuthorityPost(
            cn="CA1", validation_config=_config_with_password("$secrets[KNOWN]")
        )

        await self.controller.create(
            request=MagicMock(), ca_id="ca1", data=data, fields=set()
        )

        self.mock_ca_service.create_authority.assert_awaited_once()

    async def test_update_authority_rejects_literal_password(self):
        self.mock_authorize.require_perm = AsyncMock()
        self.mock_ca_service.update_authority = AsyncMock()
        data = CAAuthorityPut(validation_config=_config_with_password("plain"))

        with self.assertRaises(QueryParamValidationError):
            await self.controller.update(
                request=MagicMock(), ca_id="ca1", data=data, fields=set()
            )

        self.mock_ca_service.update_authority.assert_not_called()


class TestApiV1CASpacesUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_authorize = MagicMock()
        self.mock_crud_ca_spaces = MagicMock()
        self.mock_crud_ca_authorities = MagicMock()
        self.mock_crud_teams = MagicMock()
        self.mock_ca_service = MagicMock()

        self.mock_crud_ca_secrets = MagicMock()
        self.mock_crud_ca_secrets.existing_ids = AsyncMock(return_value=set())

        self.controller = ControllerApiV1CASpaces(
            log=self.log,
            authorize=self.mock_authorize,
            crud_ca_spaces=self.mock_crud_ca_spaces,
            crud_ca_authorities=self.mock_crud_ca_authorities,
            crud_ca_secrets=self.mock_crud_ca_secrets,
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

    async def test_delete_space_escapes_regex_metacharacters(self):
        self.mock_authorize.require_perm = AsyncMock()
        self.mock_ca_service.delete_space = AsyncMock()
        self.mock_crud_teams.drop_permissions_by_pattern = AsyncMock()

        mock_request = MagicMock()
        await self.controller.delete(request=mock_request, space_id=".*")

        pattern = self.mock_crud_teams.drop_permissions_by_pattern.call_args[0][0]
        self.assertEqual(pattern, PATTERN_CA_SPACES.format(space_id=re.escape(".*")))
        self.assertIn(r"\.\*", pattern)
        self.assertNotIn("^CA:SPACES:.*:", pattern)

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

    async def test_create_space_rejects_unknown_secret_before_service(self):
        self.mock_authorize.require_perm = AsyncMock()
        self.mock_ca_service.create_space = AsyncMock()
        data = CASpacePost(
            ca_id="ca1", validation_config=_config_with_password("$secrets[MISSING]")
        )

        with self.assertRaises(QueryParamValidationError) as ctx:
            await self.controller.create(
                request=MagicMock(), space_id="space1", data=data, fields=set()
            )

        self.assertIn("unknown secret references: MISSING", ctx.exception.detail)
        self.mock_ca_service.create_space.assert_not_called()

    async def test_update_space_rejects_unknown_secret_before_service(self):
        self.mock_authorize.require_perm = AsyncMock()
        self.mock_crud_ca_authorities.get = AsyncMock()
        self.mock_ca_service.update_space = AsyncMock()
        data = CASpacePut(validation_config=_config_with_password("$secrets[MISSING]"))

        with self.assertRaises(QueryParamValidationError):
            await self.controller.update(
                request=MagicMock(), space_id="space1", data=data, fields=set()
            )

        self.mock_ca_service.update_space.assert_not_called()
