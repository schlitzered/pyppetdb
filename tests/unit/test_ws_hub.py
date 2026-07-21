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
import unittest
from unittest.mock import MagicMock, AsyncMock, patch

from pyppetdb.ws.hub import WsHub


def _log_entry():
    return {"line_nr": 1, "timestamp": "2026-01-01T00:00:00Z", "msg": "x"}


class TestWsHub(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.crud_nodes = MagicMock()
        self.hub = WsHub(
            log=MagicMock(),
            config=MagicMock(),
            crud_nodes=self.crud_nodes,
            crud_jobs=MagicMock(),
            crud_job_definitions=MagicMock(),
            crud_node_jobs=MagicMock(),
            crud_pyppetdb_nodes=MagicMock(),
            redactor=MagicMock(),
            authorize_client_cert=MagicMock(),
        )
        self.hub._via = "me:8000"
        self.hub.inter_api = AsyncMock()
        self.hub.remote_executor = MagicMock()

    async def test_get_lock_returns_stable_lock(self):
        first = await self.hub._get_lock("job1:node1")
        second = await self.hub._get_lock("job1:node1")
        self.assertIs(first, second)
        self.assertIsNot(first, await self.hub._get_lock("other"))

    async def test_broadcast_delivers_and_removes_dead_socket(self):
        job_run_id = "job1:node1"
        good = AsyncMock()
        dead = AsyncMock()
        dead.send_text.side_effect = Exception("boom")
        self.hub._subscriptions[job_run_id] = {good, dead}

        await self.hub.broadcast_local_log("node1", "job1", [_log_entry()])

        good.send_text.assert_awaited_once()
        self.assertIn(good, self.hub._subscriptions[job_run_id])
        self.assertNotIn(dead, self.hub._subscriptions[job_run_id])

    async def test_broadcast_without_subscribers_is_noop(self):
        await self.hub.broadcast_local_log("node1", "job1", [_log_entry()])
        self.assertNotIn("job1:node1", self.hub._subscriptions)

    async def test_job_finished_is_broadcast(self):
        job_run_id = "job1:node1"
        ws = AsyncMock()
        self.hub._subscriptions[job_run_id] = {ws}

        await self.hub.job_finished("node1", "job1", "success", 0)

        ws.send_text.assert_awaited_once()

    async def test_first_subscription_subscribes_local_agent(self):
        node = MagicMock()
        node.remote_agent.connected = True
        node.remote_agent.via = self.hub._via
        self.crud_nodes.get = AsyncMock(return_value=node)
        protocol = MagicMock()
        protocol._send_message = AsyncMock()
        self.hub.remote_executor.get_protocol = MagicMock(return_value=protocol)

        ws = AsyncMock()
        await self.hub.subscribe(ws, "job1:node1")

        self.assertIn(ws, self.hub._subscriptions["job1:node1"])
        protocol._send_message.assert_awaited_once()
        self.assertEqual(
            protocol._send_message.call_args[1]["msg_type"], "subscribe_logs"
        )
        self.assertNotIn("job1:node1", self.hub._job_run_id_to_via)

    async def test_first_subscription_routes_via_inter_api(self):
        node = MagicMock()
        node.remote_agent.connected = True
        node.remote_agent.via = "other:8000"
        self.crud_nodes.get = AsyncMock(return_value=node)

        ws = AsyncMock()
        await self.hub.subscribe(ws, "job1:node1")

        self.assertEqual(self.hub._job_run_id_to_via["job1:node1"], "other:8000")
        self.hub.inter_api.subscribe.assert_awaited_once()

    async def test_second_subscriber_does_not_re_trigger_upstream(self):
        job_run_id = "job1:node1"
        self.hub._subscriptions[job_run_id] = {AsyncMock()}
        self.crud_nodes.get = AsyncMock()

        await self.hub.subscribe(AsyncMock(), job_run_id)

        self.assertEqual(len(self.hub._subscriptions[job_run_id]), 2)
        self.crud_nodes.get.assert_not_called()

    async def test_last_unsubscribe_cleans_up_local_agent(self):
        job_run_id = "job1:node1"
        ws = AsyncMock()
        self.hub._subscriptions[job_run_id] = {ws}
        protocol = MagicMock()
        protocol._send_message = AsyncMock()
        self.hub.remote_executor.get_protocol = MagicMock(return_value=protocol)

        await self.hub.unsubscribe(ws, job_run_id)

        self.assertNotIn(job_run_id, self.hub._subscriptions)
        protocol._send_message.assert_awaited_once()
        self.assertEqual(
            protocol._send_message.call_args[1]["msg_type"], "unsubscribe_logs"
        )

    async def test_last_unsubscribe_cleans_up_inter_api(self):
        job_run_id = "job1:node1"
        ws = AsyncMock()
        self.hub._subscriptions[job_run_id] = {ws}
        self.hub._job_run_id_to_via[job_run_id] = "other:8000"

        await self.hub.unsubscribe(ws, job_run_id)

        self.assertNotIn(job_run_id, self.hub._subscriptions)
        self.assertNotIn(job_run_id, self.hub._job_run_id_to_via)
        self.hub.inter_api.unsubscribe.assert_awaited_once()

    async def test_unsubscribe_with_remaining_subscribers_keeps_upstream(self):
        job_run_id = "job1:node1"
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        self.hub._subscriptions[job_run_id] = {ws1, ws2}

        await self.hub.unsubscribe(ws1, job_run_id)

        self.assertIn(ws2, self.hub._subscriptions[job_run_id])
        self.hub.inter_api.unsubscribe.assert_not_called()

    async def test_get_log_chunks_returns_empty_when_not_connected(self):
        node = MagicMock()
        node.remote_agent = None
        self.crud_nodes.get = AsyncMock(return_value=node)

        self.assertEqual(await self.hub.get_log_chunks("job1:node1"), [])

    @patch(
        "pyppetdb.ws.hub.asyncio.wait_for",
        new_callable=AsyncMock,
        side_effect=asyncio.TimeoutError,
    )
    async def test_get_log_chunks_timeout_returns_empty_and_cleans_up(self, _):
        node = MagicMock()
        node.remote_agent.connected = True
        node.remote_agent.via = self.hub._via
        self.crud_nodes.get = AsyncMock(return_value=node)
        self.hub.remote_executor.get_log_chunks = AsyncMock()
        self.hub.remote_executor.cleanup_request = MagicMock()

        result = await self.hub.get_log_chunks("job1:node1")

        self.assertEqual(result, [])
        self.hub.remote_executor.cleanup_request.assert_called_once()

    @patch(
        "pyppetdb.ws.hub.asyncio.wait_for",
        new_callable=AsyncMock,
        side_effect=asyncio.TimeoutError,
    )
    async def test_get_log_chunk_timeout_returns_none(self, _):
        node = MagicMock()
        node.remote_agent.connected = True
        node.remote_agent.via = self.hub._via
        self.crud_nodes.get = AsyncMock(return_value=node)
        self.hub.remote_executor.get_log_chunk = AsyncMock()
        self.hub.remote_executor.cleanup_request = MagicMock()

        result = await self.hub.get_log_chunk("job1:node1", "chunk1")

        self.assertIsNone(result)
        self.hub.remote_executor.cleanup_request.assert_called_once()


if __name__ == "__main__":
    unittest.main()
