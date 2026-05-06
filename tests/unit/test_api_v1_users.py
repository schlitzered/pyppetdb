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
from pyppetdb.controller.api.v1.users import ControllerApiV1Users
from pyppetdb.model.users import UserPost, UserPut, UserGet
from pyppetdb.authorize import (
    PERM_USERS_CREATE,
    PERM_USERS_DELETE,
    PERM_USERS_GET,
    PERM_USERS_UPDATE,
)


class TestApiV1UsersUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_authorize = MagicMock()
        self.mock_crud_teams = MagicMock()
        self.mock_crud_users = MagicMock()
        self.mock_crud_creds = MagicMock()

        self.controller = ControllerApiV1Users(
            log=self.log,
            authorize=self.mock_authorize,
            crud_teams=self.mock_crud_teams,
            crud_users=self.mock_crud_users,
            crud_users_credentials=self.mock_crud_creds,
        )

    async def test_get_user_self(self):
        mock_user = MagicMock()
        mock_user.id = "real-id"
        self.mock_authorize.get_user = AsyncMock(return_value=mock_user)
        self.mock_crud_users.get = AsyncMock(
            return_value=UserGet(id="real-id", name="Real User")
        )
        self.mock_crud_teams.search = AsyncMock(
            return_value=MagicMock(
                result=[
                    MagicMock(permissions=["P1", "P2"]),
                    MagicMock(permissions=["P2", "P3"]),
                ]
            )
        )

        mock_request = MagicMock()
        result = await self.controller.get(
            user_id="_self", request=mock_request, fields=set()
        )

        self.mock_authorize.get_user.assert_called_once_with(request=mock_request)
        self.mock_crud_users.get.assert_called_once_with(_id="real-id", fields=[])
        self.mock_crud_teams.search.assert_called_once_with(
            users="^real-id$", fields=["permissions"]
        )
        self.assertEqual(result.permissions, ["P1", "P2", "P3"])

    async def test_get_user_other_admin(self):
        self.mock_authorize.require_perm = AsyncMock()
        self.mock_crud_users.get = AsyncMock(
            return_value=UserGet(id="other", name="Other User")
        )
        self.mock_crud_teams.search = AsyncMock(
            return_value=MagicMock(result=[MagicMock(permissions=["P4"])])
        )

        mock_request = MagicMock()
        result = await self.controller.get(
            user_id="other", request=mock_request, fields=set()
        )

        self.mock_authorize.require_perm.assert_called_once_with(
            request=mock_request, permission=PERM_USERS_GET
        )
        self.mock_crud_users.get.assert_called_once_with(_id="other", fields=[])
        self.assertEqual(result.permissions, ["P4"])

    async def test_update_user_self_no_admin_change(self):
        mock_user = MagicMock()
        mock_user.id = "my-id"
        self.mock_authorize.get_user = AsyncMock(return_value=mock_user)
        self.mock_crud_users.update = AsyncMock()

        data = UserPut(
            name="New Name", admin=True
        )  # User tries to make themselves admin
        mock_request = MagicMock()

        await self.controller.update(
            user_id="_self", request=mock_request, data=data, fields=set()
        )

        # Verify data.admin was set to None for _self update
        self.assertIsNone(data.admin)
        self.mock_crud_users.update.assert_called_once_with(
            _id="my-id", payload=data, fields=[]
        )

    async def test_create_user_admin_required(self):
        self.mock_authorize.require_perm = AsyncMock()
        self.mock_crud_users.create = AsyncMock()

        data = UserPost(name="New User", email="test@ex.com", password="pwd")
        mock_request = MagicMock()
        await self.controller.create(
            user_id="newuser", request=mock_request, data=data, fields=set()
        )

        self.mock_authorize.require_perm.assert_called_once_with(
            request=mock_request, permission=PERM_USERS_CREATE
        )
        self.mock_crud_users.create.assert_called_once_with(
            _id="newuser", payload=data, fields=[]
        )

    async def test_delete_user(self):
        self.mock_authorize.require_perm = AsyncMock()
        self.mock_crud_users.delete = AsyncMock()
        self.mock_crud_creds.delete_all_from_owner = AsyncMock()
        self.mock_crud_teams.delete_user_from_teams = AsyncMock()

        mock_request = MagicMock()
        await self.controller.delete(user_id="user1", request=mock_request)

        self.mock_authorize.require_perm.assert_called_once_with(
            request=mock_request, permission=PERM_USERS_DELETE
        )
        self.mock_crud_users.delete.assert_called_once_with(_id="user1")
        self.mock_crud_creds.delete_all_from_owner.assert_called_once_with(
            owner="user1"
        )
        self.mock_crud_teams.delete_user_from_teams.assert_called_once_with(
            user_id="user1"
        )

    async def test_search_users(self):
        self.mock_authorize.require_perm = AsyncMock()
        self.mock_crud_users.search = AsyncMock()

        mock_request = MagicMock()
        await self.controller.search(
            request=mock_request,
            user_id=None,
            fields=set(),
            sort="id",
            sort_order="ascending",
            page=0,
            limit=10,
        )

        self.mock_authorize.require_perm.assert_called_once_with(
            request=mock_request, permission=PERM_USERS_GET
        )
        self.mock_crud_users.search.assert_called_once()

    async def test_update_user_admin(self):
        self.mock_authorize.require_perm = AsyncMock()
        self.mock_crud_users.update = AsyncMock()

        data = UserPut(admin=True)
        mock_request = MagicMock()
        await self.controller.update(
            user_id="user1", request=mock_request, data=data, fields=set()
        )

        self.mock_authorize.require_perm.assert_called_once_with(
            request=mock_request, permission=PERM_USERS_UPDATE
        )
        self.mock_crud_users.update.assert_called_once_with(
            _id="user1", payload=data, fields=[]
        )
