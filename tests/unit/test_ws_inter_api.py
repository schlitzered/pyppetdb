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
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
import logging

from pyppetdb.ws.inter_api import WsInterAPI


class TestWsInterAPIUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")

        # Mock Config
        self.mock_config = MagicMock()
        self.mock_config.app.main.port = 8000
        self.mock_config.app.main.ssl.cert = "dummy.cert"
        self.mock_config.app.main.ssl.key = "dummy.key"
        self.mock_config.app.main.ssl.ca = "dummy.ca"
        self.mock_config.app.main.interApiIdleTimeout = 10  # Short timeout for testing

        # Mock Hub
        self.mock_hub = MagicMock()
        self.mock_hub.job_run_id_to_via = {}

        self.mock_authorize_client_cert = MagicMock()
        self.mock_crud_pyppetdb_nodes = MagicMock()

        self.inter_api = WsInterAPI(
            log=self.log,
            config=self.mock_config,
            hub=self.mock_hub,
            authorize_client_cert=self.mock_authorize_client_cert,
            crud_pyppetdb_nodes=self.mock_crud_pyppetdb_nodes,
        )

    @patch("pyppetdb.ws.inter_api.ssl.create_default_context")
    @patch("pyppetdb.ws.inter_api.websockets.connect")
    async def test_remote_api_client_idle_disconnect(
        self, mock_ws_connect, mock_ssl_context
    ):
        self.mock_config.app.main.interApiIdleTimeout = -1

        mock_ws = AsyncMock()
        mock_ws.recv.side_effect = asyncio.TimeoutError()

        mock_ws_context = AsyncMock()
        mock_ws_context.__aenter__.return_value = mock_ws
        mock_ws_connect.return_value = mock_ws_context

        via = "remote-node"
        try:
            await asyncio.wait_for(
                self.inter_api._remote_api_client(via), timeout=1.0
            )
        except asyncio.TimeoutError:
            self.fail(
                "The inter-API client task did not exit proactively upon idle timeout."
            )

        mock_ws_connect.assert_called_once()
        mock_ws.close.assert_called_once()
        self.assertNotIn(via, self.inter_api._remote_conns)

    async def test_authenticate_success(self):
        from datetime import datetime
        mock_node = MagicMock()
        mock_node.heartbeat = datetime.now()
        self.mock_crud_pyppetdb_nodes.get = AsyncMock(return_value=mock_node)

        result = await self.inter_api._authenticate("node1")
        self.assertTrue(result)

    async def test_authenticate_port_success(self):
        from datetime import datetime
        self.mock_crud_pyppetdb_nodes.get = AsyncMock(side_effect=Exception("not found"))

        mock_node = MagicMock()
        mock_node.heartbeat = datetime.now()
        mock_search_res = MagicMock()
        mock_search_res.result = [mock_node]
        self.mock_crud_pyppetdb_nodes.search = AsyncMock(return_value=mock_search_res)

        result = await self.inter_api._authenticate("node1")
        self.assertTrue(result)
        self.mock_crud_pyppetdb_nodes.search.assert_called_once_with(
            _id="^node1(:|$)",
            fields=["id", "heartbeat"],
        )
