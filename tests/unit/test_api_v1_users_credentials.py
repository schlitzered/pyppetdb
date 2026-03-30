import unittest
from unittest.mock import MagicMock, AsyncMock
import logging
from pyppetdb.controller.api.v1.users_credentials import ControllerApiV1UsersCredentials
from pyppetdb.model.credentials import CredentialPost


class TestApiV1UsersCredentialsUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_authorize = MagicMock()
        self.mock_crud_users = MagicMock()
        self.mock_crud_creds = MagicMock()

        self.controller = ControllerApiV1UsersCredentials(
            log=self.log,
            authorize=self.mock_authorize,
            crud_users=self.mock_crud_users,
            crud_users_credentials=self.mock_crud_creds,
        )

    async def test_create_credential_self(self):
        # Mocking auth
        mock_user = MagicMock()
        mock_user.id = "real-user-id"
        self.mock_authorize.get_user = AsyncMock(return_value=mock_user)

        # Mocking CRUD
        self.mock_crud_users.resource_exists = AsyncMock()
        self.mock_crud_creds.create = AsyncMock()

        payload = CredentialPost(description="desc")
        mock_request = MagicMock()

        await self.controller.create(
            data=payload, user_id="_self", request=mock_request
        )

        self.mock_authorize.get_user.assert_called_once_with(request=mock_request)
        self.mock_crud_creds.create.assert_called_once_with(
            owner="real-user-id", payload=payload
        )

    async def test_create_credential_other_admin(self):
        # Mocking auth
        self.mock_authorize.require_admin = AsyncMock()

        # Mocking CRUD
        self.mock_crud_users.resource_exists = AsyncMock()
        self.mock_crud_creds.create = AsyncMock()

        payload = CredentialPost(description="desc")
        mock_request = MagicMock()

        await self.controller.create(
            data=payload, user_id="other-user", request=mock_request
        )

        self.mock_authorize.require_admin.assert_called_once_with(request=mock_request)
        self.mock_crud_creds.create.assert_called_once_with(
            owner="other-user", payload=payload
        )

    async def test_delete_credential_self(self):
        mock_user = MagicMock()
        mock_user.id = "my-id"
        self.mock_authorize.get_user = AsyncMock(return_value=mock_user)
        self.mock_crud_creds.delete = AsyncMock()

        mock_request = MagicMock()
        await self.controller.delete(
            user_id="_self", credential_id="cred1", request=mock_request
        )

        self.mock_crud_creds.delete.assert_called_once_with(_id="cred1", owner="my-id")

    async def test_delete_credential_other_admin(self):
        self.mock_authorize.require_admin = AsyncMock()
        self.mock_crud_creds.delete = AsyncMock()

        mock_request = MagicMock()
        await self.controller.delete(
            user_id="other", credential_id="cred1", request=mock_request
        )

        self.mock_authorize.require_admin.assert_called_once_with(request=mock_request)
        self.mock_crud_creds.delete.assert_called_once_with(_id="cred1", owner="other")

    async def test_get_credential_self(self):
        mock_user = MagicMock()
        mock_user.id = "my-id"
        self.mock_authorize.get_user = AsyncMock(return_value=mock_user)
        self.mock_crud_creds.get = AsyncMock()

        mock_request = MagicMock()
        await self.controller.get(
            user_id="_self", credential_id="cred1", request=mock_request, fields=set()
        )

        self.mock_crud_creds.get.assert_called_once_with(
            owner="my-id", _id="cred1", fields=[]
        )

    async def test_search_credentials_self(self):
        mock_user = MagicMock()
        mock_user.id = "my-id"
        self.mock_authorize.get_user = AsyncMock(return_value=mock_user)
        self.mock_crud_creds.search = AsyncMock()

        mock_request = MagicMock()
        await self.controller.search(
            user_id="_self",
            request=mock_request,
            fields=set(),
            sort="id",
            sort_order="ascending",
            page=0,
            limit=10,
        )

        self.mock_crud_creds.search.assert_called_once()

    async def test_update_credential_self(self):
        mock_user = MagicMock()
        mock_user.id = "my-id"
        self.mock_authorize.get_user = AsyncMock(return_value=mock_user)
        self.mock_crud_creds.update = AsyncMock()

        from pyppetdb.model.credentials import CredentialPut

        payload = CredentialPut(description="new desc")
        mock_request = MagicMock()

        await self.controller.update(
            user_id="_self",
            credential_id="cred1",
            data=payload,
            request=mock_request,
            fields=set(),
        )

        self.mock_crud_creds.update.assert_called_once_with(
            _id="cred1", owner="my-id", payload=payload, fields=[]
        )
