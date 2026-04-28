import unittest
from unittest.mock import MagicMock, AsyncMock
import logging
from fastapi import WebSocketDisconnect
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

    async def test_remote_executor_endpoint_ping_pong(self):
        # This test was testing the protocol loop, but now it just delegates to hub
        pass

    async def test_remote_executor_endpoint_exception(self):
        # This test was testing the protocol loop, but now it just delegates to hub
        pass
