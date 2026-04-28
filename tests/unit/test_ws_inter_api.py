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
    async def test_remote_api_client_idle_disconnect(self, mock_ws_connect, mock_ssl_context):
        # Mock the websocket connection and its context manager
        mock_ws = AsyncMock()
        
        # Make recv() raise a TimeoutError immediately
        mock_ws.recv.side_effect = asyncio.TimeoutError()
        
        mock_ws_context = AsyncMock()
        mock_ws_context.__aenter__.return_value = mock_ws
        mock_ws_connect.return_value = mock_ws_context

        # Mock time progression.
        # We need three calls to time(): 
        # 1. last_activity = asyncio.get_event_loop().time() (initially 100.0)
        # 2. Inside the TimeoutError block: asyncio.get_event_loop().time() (now 115.0)
        mock_time = MagicMock()
        mock_time.side_effect = [100.0, 115.0]

        with patch("pyppetdb.ws.inter_api.asyncio.get_event_loop") as mock_get_event_loop:
            mock_loop = MagicMock()
            mock_loop.time = mock_time
            mock_get_event_loop.return_value = mock_loop
            
            # Start the client task
            via = "remote-node"
            task = asyncio.create_task(self.inter_api._remote_api_client(via))
            
            # Allow the task to execute
            # Wait until the task finishes (which it should when it breaks on idle)
            try:
                await asyncio.wait_for(task, timeout=1.0)
            except asyncio.TimeoutError:
                self.fail("The inter-API client task did not exit proactively upon idle timeout.")
            
            # Verify the connection was initiated
            mock_ws_connect.assert_called_once()
            
            # Verify that ws.close() was called due to the timeout condition
            mock_ws.close.assert_called_once()
            
            # Verify it was removed from the remote_conns dictionary
            self.assertNotIn(via, self.inter_api._remote_conns)
