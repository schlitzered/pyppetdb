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
from pyppetdb.controller.api.v1.users_credentials import ControllerApiV1UsersCredentials
from pyppetdb.model.credentials import CredentialPost, CredentialPut
from pyppetdb.errors import ResourceNotFound
from pyppetdb.authorize import (
    PERM_USERS_CREDENTIALS_CREATE,
    PERM_USERS_CREDENTIALS_DELETE,
    PERM_USERS_CREDENTIALS_GET,
    PERM_USERS_CREDENTIALS_UPDATE,
)


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
        self.mock_authorize.require_perm = AsyncMock()

        # Mocking CRUD
        self.mock_crud_users.resource_exists = AsyncMock()
        self.mock_crud_creds.create = AsyncMock()

        payload = CredentialPost(description="desc")
        mock_request = MagicMock()

        await self.controller.create(
            data=payload, user_id="other-user", request=mock_request
        )

        self.mock_authorize.require_perm.assert_called_once_with(
            request=mock_request, permission=PERM_USERS_CREDENTIALS_CREATE
        )
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
        self.mock_authorize.require_perm = AsyncMock()
        self.mock_crud_creds.delete = AsyncMock()

        mock_request = MagicMock()
        await self.controller.delete(
            user_id="other", credential_id="cred1", request=mock_request
        )

        self.mock_authorize.require_perm.assert_called_once_with(
            request=mock_request, permission=PERM_USERS_CREDENTIALS_DELETE
        )
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

    async def test_create_credential_unknown_user_raises_404(self):
        # non-_self create for a user that does not exist -> ResourceNotFound,
        # and the credential must NOT be created
        self.mock_authorize.require_perm = AsyncMock()
        self.mock_crud_users.resource_exists = AsyncMock(side_effect=ResourceNotFound())
        self.mock_crud_creds.create = AsyncMock()

        with self.assertRaises(ResourceNotFound):
            await self.controller.create(
                data=CredentialPost(description="d"),
                user_id="ghost",
                request=MagicMock(),
            )
        self.mock_crud_creds.create.assert_not_called()

    async def test_get_credential_other_user_requires_perm(self):
        self.mock_authorize.require_perm = AsyncMock()
        self.mock_authorize.get_user = AsyncMock()
        self.mock_crud_creds.get = AsyncMock()

        mock_request = MagicMock()
        await self.controller.get(
            request=mock_request,
            user_id="alice",
            credential_id="cred1",
            fields=set(),
        )

        self.mock_authorize.require_perm.assert_called_once_with(
            request=mock_request, permission=PERM_USERS_CREDENTIALS_GET
        )
        self.mock_authorize.get_user.assert_not_called()
        self.mock_crud_creds.get.assert_called_once_with(
            owner="alice", _id="cred1", fields=[]
        )

    async def test_search_credentials_other_user_requires_perm(self):
        self.mock_authorize.require_perm = AsyncMock()
        self.mock_authorize.get_user = AsyncMock()
        self.mock_crud_creds.search = AsyncMock()

        mock_request = MagicMock()
        await self.controller.search(
            request=mock_request,
            user_id="alice",
            fields=set(),
            sort="id",
            sort_order="ascending",
            page=0,
            limit=10,
        )

        self.mock_authorize.require_perm.assert_called_once_with(
            request=mock_request, permission=PERM_USERS_CREDENTIALS_GET
        )
        self.mock_authorize.get_user.assert_not_called()
        _, kwargs = self.mock_crud_creds.search.call_args
        self.assertEqual(kwargs["owner"], "alice")

    async def test_update_credential_other_user_requires_perm(self):
        self.mock_authorize.require_perm = AsyncMock()
        self.mock_authorize.get_user = AsyncMock()
        self.mock_crud_creds.update = AsyncMock()

        mock_request = MagicMock()
        await self.controller.update(
            request=mock_request,
            user_id="alice",
            credential_id="cred1",
            data=CredentialPut(description="new"),
            fields=set(),
        )

        self.mock_authorize.require_perm.assert_called_once_with(
            request=mock_request, permission=PERM_USERS_CREDENTIALS_UPDATE
        )
        self.mock_authorize.get_user.assert_not_called()
        self.mock_crud_creds.update.assert_called_once()
        _, kwargs = self.mock_crud_creds.update.call_args
        self.assertEqual(kwargs["owner"], "alice")
        self.assertEqual(kwargs["_id"], "cred1")
