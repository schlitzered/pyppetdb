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

from itsdangerous import URLSafeTimedSerializer

from pyppetdb.controller.api.v1.ws import ControllerApiV1Ws


class TestApiV1WsUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_authorize = MagicMock()
        self.mock_authorize_client_cert = MagicMock()
        self.mock_authorize_client_cert.require_cn_match = AsyncMock()

        self.mock_crud_nodes = MagicMock()
        self.mock_crud_nodes.update_remote_agent_status = AsyncMock()
        self.mock_crud_nodes.update_remote_agent_busy = AsyncMock()
        self.mock_crud_nodes.get = AsyncMock()
        self.mock_crud_nodes.get.return_value = MagicMock(remote_agent=None)

        self.mock_config = MagicMock()
        self.mock_config.app.secretkey = "unit-test-secret"
        self.mock_config.app.wssalt = "unit-test-salt"
        self.mock_crud_jobs = MagicMock()
        self.mock_crud_job_definitions = MagicMock()
        self.mock_crud_node_jobs = MagicMock()
        self.mock_crud_node_jobs.search = AsyncMock()
        self.mock_crud_node_jobs.search.return_value = MagicMock(result=[])
        self.mock_crud_node_jobs.coll = MagicMock()
        self.mock_crud_pyppetdb_nodes = MagicMock()
        self.mock_redactor = MagicMock()

        self.mock_ws_hub = MagicMock()
        self.mock_ws_hub.remote_executor = MagicMock()
        self.mock_ws_hub.remote_executor.endpoint = AsyncMock()
        self.mock_ws_hub.api = MagicMock()
        self.mock_ws_hub.api.endpoint = AsyncMock()
        self.mock_ws_hub.inter_api = MagicMock()
        self.mock_ws_hub.inter_api.endpoint = AsyncMock()

        self.controller = ControllerApiV1Ws(
            log=self.log,
            config=self.mock_config,
            authorize=self.mock_authorize,
            authorize_client_cert=self.mock_authorize_client_cert,
            ws_hub=self.mock_ws_hub,
        )

    async def test_remote_executor_endpoint_connect_disconnect(self):
        mock_ws = AsyncMock()
        await self.controller.remote_executor_endpoint(
            websocket=mock_ws, node_id="node1"
        )
        self.mock_ws_hub.remote_executor.endpoint.assert_called_once_with(
            websocket=mock_ws, node_id="node1"
        )

    async def test_logs_endpoint_delegates_to_hub(self):
        mock_ws = AsyncMock()
        await self.controller.logs_endpoint(websocket=mock_ws)
        self.mock_ws_hub.api.endpoint.assert_called_once_with(websocket=mock_ws)

    async def test_inter_api_endpoint_delegates_to_hub(self):
        mock_ws = AsyncMock()
        await self.controller.inter_api_endpoint(websocket=mock_ws)
        self.mock_ws_hub.inter_api.endpoint.assert_called_once_with(websocket=mock_ws)

    async def test_get_ws_token_requires_user_and_signs_user_id(self):
        user = MagicMock()
        user.id = "alice"
        self.mock_authorize.require_user = AsyncMock(return_value=user)

        mock_request = MagicMock()
        result = await self.controller.get_ws_token(request=mock_request)

        self.mock_authorize.require_user.assert_called_once_with(request=mock_request)
        self.assertIn("token", result)

        # the token must be a valid signed blob carrying the authenticated user id
        serializer = URLSafeTimedSerializer(
            secret_key="unit-test-secret",
            salt="unit-test-salt",
        )
        payload = serializer.loads(result["token"])
        self.assertEqual(payload, {"user_id": "alice"})

    async def test_get_ws_token_uses_configured_salt(self):
        user = MagicMock()
        user.id = "bob"
        self.mock_authorize.require_user = AsyncMock(return_value=user)

        result = await self.controller.get_ws_token(request=MagicMock())

        # a serializer with a different salt must NOT be able to load the token
        wrong = URLSafeTimedSerializer(
            secret_key="unit-test-secret",
            salt="wrong-salt",
        )
        from itsdangerous import BadSignature

        with self.assertRaises(BadSignature):
            wrong.loads(result["token"])
