import asyncio
import json
import unittest
from unittest.mock import MagicMock, AsyncMock, patch
import logging
from fastapi import WebSocketDisconnect
from pyppetdb.ws.remote_executor import RemoteExecutorProtocol


class TestRemoteExecutorProtocolUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_ws = AsyncMock()
        self.mock_crud_nodes = MagicMock()
        self.mock_crud_nodes.get = AsyncMock()
        self.mock_crud_nodes.update_remote_agent_busy = AsyncMock()

        self.mock_crud_jobs = MagicMock()
        self.mock_crud_jobs.get = AsyncMock()

        self.mock_crud_job_definitions = MagicMock()
        self.mock_crud_job_definitions.get = AsyncMock()

        self.mock_crud_node_jobs = MagicMock()
        self.mock_crud_node_jobs.update_status = AsyncMock()
        self.mock_crud_node_jobs.get_oldest_scheduled = AsyncMock()
        self.mock_crud_node_jobs.search = AsyncMock()
        self.mock_crud_node_jobs.search.return_value = MagicMock(result=[])

        self.mock_redactor = MagicMock()
        self.mock_manager = MagicMock()
        self.mock_manager.broadcast_local_log = AsyncMock()
        self.mock_manager.job_finished = AsyncMock()

        self.protocol = RemoteExecutorProtocol(
            log=self.log,
            node_id="node1",
            websocket=self.mock_ws,
            crud_nodes=self.mock_crud_nodes,
            crud_jobs=self.mock_crud_jobs,
            crud_job_definitions=self.mock_crud_job_definitions,
            crud_node_jobs=self.mock_crud_node_jobs,
            redactor=self.mock_redactor,
            manager=self.mock_manager,
        )

    async def test_handle_ack(self):
        # Setup a pending ACK
        event = asyncio.Event()
        self.protocol._pending_acks[123] = event

        msg_dict = {
            "msg_id": 1,
            "msg_type": "ack",
            "msg_body": {"acked_ids": [123]},
        }
        await self.protocol._handle_message(json.dumps(msg_dict))

        self.assertTrue(event.is_set())
        self.assertIn(123, self.protocol._pending_acks)

    async def test_handle_log_message(self):
        self.protocol._job_manager.current_job_id = "job1"
        self.mock_redactor.redact.side_effect = lambda text: text

        mock_log_entry = MagicMock()
        mock_log_entry.model_dump.return_value = {"line_nr": 1, "msg": "test log"}

        mock_body = MagicMock()
        mock_body.logs = [mock_log_entry]

        await asyncio.wait_for(
            self.protocol._log_handler.handle_log_message(
                body=mock_body,
                current_job_id="job1",
            ),
            timeout=1.0,
        )

        self.mock_manager.broadcast_local_log.assert_called_once()

    async def test_handle_finish(self):
        self.protocol._job_manager.current_job_id = "job1"
        self.protocol._job_manager.busy = True

        body = MagicMock()
        body.exit_code = 0
        await asyncio.wait_for(
            self.protocol._job_manager.handle_finish(body),
            timeout=1.0,
        )

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
        self.mock_manager.job_finished.assert_called_once()
        self.assertFalse(self.protocol._job_manager.busy)
        self.assertIsNone(self.protocol._job_manager.current_job_id)

    async def test_trigger_job_check(self):
        # Mock finding a job
        mock_node_job = MagicMock()
        mock_node_job.job_id = "job1"

        self.mock_crud_node_jobs.get_oldest_scheduled.return_value = mock_node_job

        # Mock job and definition
        mock_job = MagicMock()
        mock_job.definition_id = "def1"
        mock_job.parameters = {}
        mock_job.env_vars = {}
        self.mock_crud_jobs.get.return_value = mock_job

        mock_def = MagicMock()
        mock_def.id = "def1"
        mock_def.executable = "/bin/ls"
        mock_def.params_template = []
        mock_def.user = "root"
        mock_def.group = "root"
        self.mock_crud_job_definitions.get.return_value = mock_def

        self.protocol._send_message = AsyncMock()

        await self.protocol.trigger_job_check()

        self.mock_crud_node_jobs.get_oldest_scheduled.assert_called_with(
            node_id="node1"
        )
        self.protocol._send_message.assert_called_once()
        args = self.protocol._send_message.call_args[1]
        self.assertEqual(args["msg_type"], "start_job")
        self.assertEqual(args["body"].job_id, "job1")
        self.assertEqual(args["body"].job_definition_id, "def1")

    @patch(
        "pyppetdb.ws.remote_executor.asyncio.sleep",
        return_value=None,
    )
    async def test_run_disconnect(self, mock_sleep):
        self.mock_ws.receive_text.side_effect = WebSocketDisconnect()
        self.protocol.trigger_job_check = AsyncMock()
        self.protocol._heartbeat = AsyncMock()

        self.mock_crud_nodes.get.return_value = MagicMock(remote_agent=None)

        try:
            await asyncio.wait_for(self.protocol.run(), timeout=1.0)
        except WebSocketDisconnect:
            pass

        self.assertFalse(self.protocol._running)
