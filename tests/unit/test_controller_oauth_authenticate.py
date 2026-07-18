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

import logging
import unittest
from unittest.mock import MagicMock, AsyncMock

from fastapi import HTTPException
from starlette.responses import RedirectResponse

from pyppetdb.controller.oauth.authenticate import ControllerOauthAuthenticate
from pyppetdb.errors import AuthenticationError, ResourceNotFound


class TestControllerOauthAuthenticateUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_crud_users = MagicMock()
        self.mock_http = MagicMock()
        self.crud_oauth = {}

        self.controller = ControllerOauthAuthenticate(
            log=self.log,
            crud_users=self.mock_crud_users,
            http=self.mock_http,
            crud_oauth=self.crud_oauth,
        )

    def _make_provider(self, backend_override=False):
        provider = MagicMock()
        provider.backend_override = backend_override
        provider.oauth_login = AsyncMock(return_value=RedirectResponse(url="/login"))
        provider.oauth_auth = AsyncMock(return_value={"access_token": "tok"})
        provider.get_user_info = AsyncMock(
            return_value={
                "login": "alice",
                "email": "alice@example.com",
                "name": "Alice",
            }
        )
        return provider

    async def test_get_oauth_providers(self):
        self.crud_oauth["github"] = self._make_provider()
        self.crud_oauth["gitlab"] = self._make_provider()

        result = await self.controller.get_oauth_providers()

        self.assertEqual(result.meta.result_size, 2)
        ids = sorted(p.id for p in result.result)
        self.assertEqual(ids, ["github", "gitlab"])

    async def test_get_oauth_login_success(self):
        provider = self._make_provider()
        self.crud_oauth["github"] = provider
        mock_request = MagicMock()

        await self.controller.get_oauth_login(provider="github", request=mock_request)

        provider.oauth_login.assert_called_once_with(request=mock_request)

    async def test_get_oauth_login_provider_not_found(self):
        mock_request = MagicMock()
        with self.assertRaises(HTTPException) as ctx:
            await self.controller.get_oauth_login(
                provider="unknown", request=mock_request
            )
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_get_oauth_auth_provider_not_found(self):
        mock_request = MagicMock()
        with self.assertRaises(HTTPException) as ctx:
            await self.controller.get_oauth_auth(
                provider="unknown", request=mock_request
            )
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_get_oauth_auth_existing_user_matching_backend(self):
        provider = self._make_provider()
        self.crud_oauth["github"] = provider

        user = MagicMock()
        user.backend = "oauth:github"
        self.mock_crud_users.get = AsyncMock(return_value=user)
        self.mock_crud_users.update = AsyncMock()
        self.mock_crud_users.create_external = AsyncMock()

        mock_request = MagicMock()
        mock_request.session = {}

        result = await self.controller.get_oauth_auth(
            provider="github", request=mock_request
        )

        self.assertIsInstance(result, RedirectResponse)
        self.assertEqual(mock_request.session["username"], "alice")
        self.mock_crud_users.update.assert_not_called()
        self.mock_crud_users.create_external.assert_not_called()

    async def test_get_oauth_auth_backend_mismatch_with_override(self):
        provider = self._make_provider(backend_override=True)
        self.crud_oauth["github"] = provider

        user = MagicMock()
        user.backend = "internal"
        self.mock_crud_users.get = AsyncMock(return_value=user)
        self.mock_crud_users.update = AsyncMock()

        mock_request = MagicMock()
        mock_request.session = {}

        await self.controller.get_oauth_auth(provider="github", request=mock_request)

        self.mock_crud_users.update.assert_called_once()
        _, kwargs = self.mock_crud_users.update.call_args
        self.assertEqual(kwargs["_id"], "alice")
        self.assertEqual(kwargs["payload"].backend, "oauth:github")
        self.assertEqual(mock_request.session["username"], "alice")

    async def test_get_oauth_auth_backend_mismatch_without_override(self):
        provider = self._make_provider(backend_override=False)
        self.crud_oauth["github"] = provider

        user = MagicMock()
        user.backend = "internal"
        self.mock_crud_users.get = AsyncMock(return_value=user)
        self.mock_crud_users.update = AsyncMock()

        mock_request = MagicMock()
        mock_request.session = {}

        with self.assertRaises(AuthenticationError) as ctx:
            await self.controller.get_oauth_auth(
                provider="github", request=mock_request
            )
        self.assertEqual(ctx.exception.status_code, 401)
        self.mock_crud_users.update.assert_not_called()
        self.assertNotIn("username", mock_request.session)

    async def test_get_oauth_auth_new_user_created(self):
        provider = self._make_provider()
        self.crud_oauth["github"] = provider

        self.mock_crud_users.get = AsyncMock(side_effect=ResourceNotFound())
        self.mock_crud_users.create_external = AsyncMock()

        mock_request = MagicMock()
        mock_request.session = {}

        await self.controller.get_oauth_auth(provider="github", request=mock_request)

        self.mock_crud_users.create_external.assert_called_once()
        _, kwargs = self.mock_crud_users.create_external.call_args
        self.assertEqual(kwargs["_id"], "alice")
        self.assertEqual(kwargs["backend"], "oauth:github")
        self.assertEqual(kwargs["payload"].email, "alice@example.com")
        self.assertEqual(kwargs["payload"].name, "Alice")
        self.assertEqual(kwargs["payload"].admin, False)
        self.assertEqual(mock_request.session["username"], "alice")


if __name__ == "__main__":
    unittest.main()
