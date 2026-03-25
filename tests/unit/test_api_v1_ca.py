import unittest
from unittest.mock import MagicMock, AsyncMock
import logging
from pyppetdb.controller.api.v1.ca_authorities import ControllerApiV1CAAuthorities
from pyppetdb.controller.api.v1.ca_spaces import ControllerApiV1CASpaces
from pyppetdb.model.ca_authorities import CAAuthorityPost, CAAuthorityPut
from pyppetdb.model.ca_spaces import CASpacePost, CASpacePut

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
            ca_service=self.mock_ca_service
        )

    async def test_update_authority_permission(self):
        self.mock_authorize.require_perm = AsyncMock()
        self.mock_ca_service.revoke_authority = AsyncMock()
        
        mock_request = MagicMock()
        data = CAAuthorityPut(status="revoked")
        
        await self.controller.update(request=mock_request, ca_id="ca1", data=data)
        
        self.mock_authorize.require_perm.assert_called_once_with(
            request=mock_request, permission="CA:AUTHORITIES:UPDATE"
        )
        self.mock_ca_service.revoke_authority.assert_called_once_with("ca1")

    async def test_delete_authority_permission(self):
        self.mock_authorize.require_perm = AsyncMock()
        self.mock_ca_service.delete_authority = AsyncMock()
        self.mock_crud_teams.drop_permissions_by_pattern = AsyncMock()
        
        mock_request = MagicMock()
        await self.controller.delete(request=mock_request, ca_id="ca1")
        
        self.mock_authorize.require_perm.assert_called_once_with(
            request=mock_request, permission="CA:AUTHORITIES:DELETE"
        )
        self.mock_ca_service.delete_authority.assert_called_once_with("ca1")
        self.mock_crud_teams.drop_permissions_by_pattern.assert_called_once_with("^CA:AUTHORITIES:ca1:")

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
            ca_service=self.mock_ca_service
        )

    async def test_create_space_permission(self):
        self.mock_authorize.require_perm = AsyncMock()
        self.mock_crud_ca_spaces.create = AsyncMock()
        
        mock_request = MagicMock()
        data = CASpacePost(ca_id="ca1")
        
        await self.controller.create(request=mock_request, space_id="space1", data=data, fields=set())
        
        self.mock_authorize.require_perm.assert_called_once_with(
            request=mock_request, permission="CA:SPACES:CREATE"
        )

    async def test_delete_space_permission(self):
        self.mock_authorize.require_perm = AsyncMock()
        self.mock_crud_ca_certificates.count = AsyncMock(return_value=0)
        self.mock_crud_ca_spaces.delete = AsyncMock()
        self.mock_crud_teams.drop_permissions_by_pattern = AsyncMock()
        
        mock_request = MagicMock()
        await self.controller.delete(request=mock_request, space_id="space1")
        
        self.mock_authorize.require_perm.assert_called_once_with(
            request=mock_request, permission="CA:SPACES:DELETE"
        )
        self.mock_crud_teams.drop_permissions_by_pattern.assert_called_once_with("^CA:SPACES:space1:")
