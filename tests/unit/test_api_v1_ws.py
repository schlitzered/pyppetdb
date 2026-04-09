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
        self.mock_crud_nodes = MagicMock()
        self.controller = ControllerApiV1Ws(
            log=self.log,
            authorize=self.mock_authorize,
            authorize_client_cert=self.mock_authorize_client_cert,
            crud_nodes=self.mock_crud_nodes,
        )

    async def test_remote_executor_endpoint_connect_disconnect(self):
        mock_ws = AsyncMock()
        # Mock receive_text to raise WebSocketDisconnect on first call to simulate disconnect
        mock_ws.receive_text.side_effect = WebSocketDisconnect()

        self.mock_authorize_client_cert.require_cn_match = AsyncMock()
        self.mock_crud_nodes.update_remote_agent_status = AsyncMock()

        await self.controller.remote_executor_endpoint(
            websocket=mock_ws, node_id="node1"
        )

        mock_ws.accept.assert_called_once()
        self.mock_authorize_client_cert.require_cn_match.assert_called_once()

        # Should be called twice: once for connect (True), once for disconnect (False)
        self.assertEqual(self.mock_crud_nodes.update_remote_agent_status.call_count, 2)

        # First call: connect
        args1 = self.mock_crud_nodes.update_remote_agent_status.call_args_list[0][1]
        self.assertEqual(args1["node_id"], "node1")
        self.assertEqual(args1["connected"], True)
        self.assertIsNotNone(args1["via"])

        # Second call: disconnect
        args2 = self.mock_crud_nodes.update_remote_agent_status.call_args_list[1][1]
        self.assertEqual(args2["node_id"], "node1")
        self.assertEqual(args2["connected"], False)
        self.assertIsNone(args2["via"])

    async def test_remote_executor_endpoint_ping_pong(self):
        mock_ws = AsyncMock()
        # Return "ping", then raise disconnect
        mock_ws.receive_text.side_effect = ["ping", WebSocketDisconnect()]

        self.mock_authorize_client_cert.require_cn_match = AsyncMock()
        self.mock_crud_nodes.update_remote_agent_status = AsyncMock()

        await self.controller.remote_executor_endpoint(
            websocket=mock_ws, node_id="node1"
        )

        mock_ws.send_text.assert_called_once_with("pong")

    async def test_remote_executor_endpoint_exception(self):
        mock_ws = AsyncMock()
        # Mock receive_text to raise Exception
        mock_ws.receive_text.side_effect = Exception("error")

        self.mock_authorize_client_cert.require_cn_match = AsyncMock()
        self.mock_crud_nodes.update_remote_agent_status = AsyncMock()

        await self.controller.remote_executor_endpoint(
            websocket=mock_ws, node_id="node1"
        )

        # Should be called twice: once for connect (True), once for error (False)
        self.assertEqual(self.mock_crud_nodes.update_remote_agent_status.call_count, 2)
        mock_ws.close.assert_called_once_with(code=4003)
