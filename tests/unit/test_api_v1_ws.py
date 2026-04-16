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
        self.mock_crud_pyppetdb_nodes = MagicMock()
        self.mock_redactor = MagicMock()

        self.controller = ControllerApiV1Ws(
            log=self.log,
            config=self.mock_config,
            authorize=self.mock_authorize,
            authorize_client_cert=self.mock_authorize_client_cert,
            crud_nodes=self.mock_crud_nodes,
            crud_jobs=self.mock_crud_jobs,
            crud_job_definitions=self.mock_crud_job_definitions,
            crud_node_jobs=self.mock_crud_node_jobs,
            crud_pyppetdb_nodes=self.mock_crud_pyppetdb_nodes,
            redactor=self.mock_redactor,
        )

    async def test_remote_executor_endpoint_connect_disconnect(self):
        mock_ws = AsyncMock()
        mock_ws.receive_text.side_effect = WebSocketDisconnect()

        await self.controller.remote_executor_endpoint(
            websocket=mock_ws, node_id="node1"
        )

        mock_ws.accept.assert_called_once()
        self.mock_authorize_client_cert.require_cn_match.assert_called_once()
        self.assertEqual(self.mock_crud_nodes.update_remote_agent_status.call_count, 2)

    async def test_remote_executor_endpoint_ping_pong(self):
        mock_ws = AsyncMock()
        # In the new protocol, we expect valid JSON or it disconnects
        mock_ws.receive_text.side_effect = ["{}", WebSocketDisconnect()]

        await self.controller.remote_executor_endpoint(
            websocket=mock_ws, node_id="node1"
        )
        # Should not crash
        pass

    async def test_remote_executor_endpoint_exception(self):
        mock_ws = AsyncMock()
        mock_ws.receive_text.side_effect = Exception("error")

        await self.controller.remote_executor_endpoint(
            websocket=mock_ws, node_id="node1"
        )

        self.assertEqual(self.mock_crud_nodes.update_remote_agent_status.call_count, 2)
        mock_ws.close.assert_called_once_with(code=4003)
