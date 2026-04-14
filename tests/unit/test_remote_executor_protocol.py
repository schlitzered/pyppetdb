import asyncio
import json
import unittest
from unittest.mock import MagicMock, AsyncMock, patch
import logging
from pyppetdb.controller.api.v1.remote_executor_protocol import RemoteExecutorProtocol


class TestRemoteExecutorProtocolUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_ws = AsyncMock()
        self.mock_crud_nodes = MagicMock()
        self.mock_crud_jobs = MagicMock()
        self.mock_crud_job_definitions = MagicMock()
        self.mock_crud_node_jobs = MagicMock()
        self.mock_crud_log_blobs = MagicMock()
        self.mock_redactor = MagicMock()
        
        self.protocol = RemoteExecutorProtocol(
            log=self.log,
            node_id="node1",
            websocket=self.mock_ws,
            crud_nodes=self.mock_crud_nodes,
            crud_jobs=self.mock_crud_jobs,
            crud_job_definitions=self.mock_crud_job_definitions,
            crud_node_jobs=self.mock_crud_node_jobs,
            crud_log_blobs=self.mock_crud_log_blobs,
            redactor=self.mock_redactor,
        )

    async def test_handle_ack(self):
        # Setup a pending ACK
        event = asyncio.Event()
        self.protocol._pending_acks[123] = event
        
        msg = {
            "msg_type": "ack",
            "msg_body": {"acked_ids": [123]}
        }
        await self.protocol._handle_message(json.dumps(msg))
        
        self.assertTrue(event.is_set())
        self.assertNotIn(123, self.protocol._pending_acks)

    async def test_handle_log_message(self):
        self.protocol._current_job_id = "job1"
        self.mock_redactor.redact.side_effect = lambda x: x
        
        msg_body = {
            "logs": [{"line_nr": 1, "msg": "test log"}]
        }
        await self.protocol._handle_log_message(msg_body)
        
        self.assertEqual(len(self.protocol._log_buffer), 1)
        self.assertEqual(self.protocol._log_buffer[0]["msg"], "test log")

    async def test_handle_finish(self):
        self.protocol._current_job_id = "job1"
        self.protocol._busy = True
        self.mock_crud_node_jobs.update_status = AsyncMock()
        self.mock_crud_nodes.update_remote_agent_busy = AsyncMock()
        
        body = {"exit_code": 0}
        await self.protocol._handle_finish(body)
        
        self.mock_crud_node_jobs.update_status.assert_called_once_with(
            job_id="job1",
            node_id="node1",
            status="success",
        )
        self.mock_crud_nodes.update_remote_agent_busy.assert_called_once_with(
            node_id="node1",
            busy=False,
            current_job_id=None,
        )
        self.assertFalse(self.protocol._busy)
        self.assertIsNone(self.protocol._current_job_id)

    async def test_poll_and_start_job(self):
        # Mock finding a job
        mock_node_job = MagicMock()
        mock_node_job.job_id = "job1"
        self.mock_crud_node_jobs.get_oldest_scheduled = AsyncMock(return_value=mock_node_job)
        
        # Mock job and definition
        mock_job = MagicMock()
        mock_job.definition_id = "def1"
        mock_job.parameters = {}
        mock_job.env_vars = {}
        self.mock_crud_jobs.get = AsyncMock(return_value=mock_job)
        
        mock_def = MagicMock()
        mock_def.executable = "/bin/ls"
        self.mock_crud_job_definitions.get = AsyncMock(return_value=mock_def)
        
        self.mock_crud_nodes.update_remote_agent_busy = AsyncMock()
        self.mock_crud_node_jobs.update_status = AsyncMock()
        
        # Mock _send_message to avoid actual network IO and ACK waiting
        self.protocol._send_message = AsyncMock()
        
        # Run one iteration of polling logic manually
        await self.protocol._poll_for_jobs()
        
        self.mock_crud_node_jobs.get_oldest_scheduled.assert_called()
        self.protocol._send_message.assert_called_once()
        args = self.protocol._send_message.call_args[1]
        self.assertEqual(args["msg_type"], "start_job")
        self.assertEqual(args["body"]["job_id"], "job1")
        
    @patch('pyppetdb.controller.api.v1.remote_executor_protocol.asyncio.sleep', return_value=None)
    async def test_run_disconnect(self, mock_sleep):
        self.mock_ws.receive_text.side_effect = WebSocketDisconnect()
        # Mock _poll_for_jobs to return immediately
        self.protocol._poll_for_jobs = AsyncMock()
        
        await self.protocol.run()
        
        self.assertFalse(self.protocol._running)
