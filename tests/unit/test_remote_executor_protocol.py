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

import asyncio
import json
import unittest
from unittest.mock import MagicMock, AsyncMock, patch
import logging
from fastapi import WebSocketDisconnect
from pyppetdb.ws.remote_executor import RemoteExecutorProtocol
from pyppetdb.ws.remote_executor import IncompatibleAgentError


class TestRemoteExecutorProtocolUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_ws = AsyncMock()
        self.mock_crud_nodes = MagicMock()
        self.mock_crud_nodes.get = AsyncMock()
        self.mock_crud_nodes.update_remote_agent_current_job_id = AsyncMock()

        self.mock_crud_jobs = MagicMock()
        self.mock_crud_jobs.get = AsyncMock()

        self.mock_crud_job_definitions = MagicMock()
        self.mock_crud_job_definitions.get = AsyncMock()

        self.mock_crud_node_jobs = MagicMock()
        self.mock_crud_node_jobs.get = AsyncMock()
        self.mock_crud_node_jobs.update_status = AsyncMock()
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
        acked = asyncio.Event()
        other = asyncio.Event()
        self.protocol._pending_acks[123] = acked
        self.protocol._pending_acks[456] = other

        msg_dict = {
            "msg_id": 1,
            "msg_type": "ack",
            "msg_body": {"acked_ids": [123]},
        }
        await self.protocol._handle_message(json.dumps(msg_dict))

        self.assertTrue(acked.is_set())
        self.assertFalse(other.is_set())

    async def test_handle_log_message(self):
        self.mock_redactor.redact.side_effect = lambda text: text

        mock_log_entry_1 = MagicMock()
        mock_log_entry_1.model_dump.return_value = {"line_nr": 1, "msg": "test log 1"}
        mock_log_entry_2 = MagicMock()
        mock_log_entry_2.model_dump.return_value = {"line_nr": 2, "msg": "test log 2"}

        mock_body = MagicMock()
        mock_body.job_id = "job1"
        mock_body.logs = [mock_log_entry_1, mock_log_entry_2]

        await asyncio.wait_for(
            self.protocol._log_handler.handle_log_message(
                body=mock_body,
            ),
            timeout=1.0,
        )

        # The whole batch must be forwarded in a single broadcast call.
        self.mock_manager.broadcast_local_log.assert_called_once()
        _, kwargs = self.mock_manager.broadcast_local_log.call_args
        self.assertEqual(
            kwargs["log_entries"],
            [
                {"line_nr": 1, "msg": "test log 1"},
                {"line_nr": 2, "msg": "test log 2"},
            ],
        )

    async def test_handle_finish(self):
        body = MagicMock()
        body.job_id = "job1"
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
        self.mock_crud_nodes.update_remote_agent_current_job_id.assert_called_once()
        self.mock_manager.job_finished.assert_called_once()

    async def test_dispatch_job(self):
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

        await self.protocol.dispatch_job(job_id="job1")

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
        self.protocol.dispatch_job = AsyncMock()

        self.mock_crud_nodes.get.return_value = MagicMock(remote_agent=None)

        try:
            await asyncio.wait_for(self.protocol.run(), timeout=1.0)
        except WebSocketDisconnect:
            pass

        # run() no longer bulk-dispatches on connect; filling is driven by the
        # first heartbeat, so nothing is dispatched here.
        self.protocol.dispatch_job.assert_not_called()
        self.assertFalse(self.protocol._running)

    async def test_fill_slots_dispatches_up_to_capacity(self):
        self.protocol._job_manager._max_jobs = 2
        self.protocol._job_manager.active_job_ids = set()

        counter = {"n": 0}

        async def fake_oldest(node_id):
            counter["n"] += 1
            return MagicMock(job_id=f"job{counter['n']}")

        self.mock_crud_node_jobs.get_oldest_scheduled = AsyncMock(
            side_effect=fake_oldest
        )

        dispatched = []

        async def fake_dispatch(job_id):
            dispatched.append(job_id)
            self.protocol._job_manager.active_job_ids.add(job_id)

        self.protocol.dispatch_job = AsyncMock(side_effect=fake_dispatch)

        await asyncio.wait_for(self.protocol.fill_slots(), timeout=1.0)

        self.assertEqual(dispatched, ["job1", "job2"])

    async def test_fill_slots_no_dispatch_when_full(self):
        self.protocol._job_manager._max_jobs = 1
        self.protocol._job_manager.active_job_ids = {"existing"}
        self.mock_crud_node_jobs.get_oldest_scheduled = AsyncMock()
        self.protocol.dispatch_job = AsyncMock()

        await asyncio.wait_for(self.protocol.fill_slots(), timeout=1.0)

        self.protocol.dispatch_job.assert_not_called()
        self.mock_crud_node_jobs.get_oldest_scheduled.assert_not_called()

    async def test_fill_slots_no_dispatch_when_capacity_unknown(self):
        self.protocol._job_manager._max_jobs = None
        self.mock_crud_node_jobs.get_oldest_scheduled = AsyncMock()
        self.protocol.dispatch_job = AsyncMock()

        await asyncio.wait_for(self.protocol.fill_slots(), timeout=1.0)

        self.protocol.dispatch_job.assert_not_called()
        self.mock_crud_node_jobs.get_oldest_scheduled.assert_not_called()

    async def test_fill_slots_stops_when_no_scheduled(self):
        self.protocol._job_manager._max_jobs = 5
        self.protocol._job_manager.active_job_ids = set()
        self.mock_crud_node_jobs.get_oldest_scheduled = AsyncMock(return_value=None)
        self.protocol.dispatch_job = AsyncMock()

        await asyncio.wait_for(self.protocol.fill_slots(), timeout=1.0)

        self.protocol.dispatch_job.assert_not_called()

    async def test_incompatible_message_triggers_shutdown_and_raises(self):
        self.protocol.send_shutdown = AsyncMock()
        bad = json.dumps(
            {
                "msg_id": 1,
                "msg_type": "heartbeat",
                "msg_body": {"running_job_ids": []},
            }
        )

        with self.assertRaises(IncompatibleAgentError):
            await asyncio.wait_for(
                self.protocol._handle_message(bad),
                timeout=1.0,
            )

        self.protocol.send_shutdown.assert_awaited_once()

    async def test_send_shutdown_sends_shutdown_frame(self):
        await asyncio.wait_for(
            self.protocol.send_shutdown(reason="please upgrade"),
            timeout=1.0,
        )

        self.mock_ws.send_text.assert_awaited_once()
        sent = json.loads(self.mock_ws.send_text.call_args[1]["data"])
        self.assertEqual(sent["msg_type"], "shutdown")
        self.assertEqual(sent["msg_body"]["reason"], "please upgrade")

    async def test_fill_slots_after_finish_dispatches_next(self):
        self.protocol._job_manager._max_jobs = 1
        self.protocol._job_manager.active_job_ids = set()
        self.mock_crud_node_jobs.get_oldest_scheduled = AsyncMock(
            return_value=MagicMock(job_id="next_job")
        )

        dispatched = []

        async def fake_dispatch(job_id):
            dispatched.append(job_id)
            self.protocol._job_manager.active_job_ids.add(job_id)

        self.protocol.dispatch_job = AsyncMock(side_effect=fake_dispatch)

        await asyncio.wait_for(self.protocol.fill_slots(), timeout=1.0)

        self.assertEqual(dispatched, ["next_job"])
