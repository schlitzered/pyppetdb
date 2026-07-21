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

from pyppetdb.ws.remote_executor import RemoteExecutorJobManager


class TestRemoteExecutorJobManager(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.crud_nodes = MagicMock()
        self.crud_nodes.update_remote_agent_current_job_id = AsyncMock()
        self.crud_node_jobs = MagicMock()
        self.crud_node_jobs.search = AsyncMock()
        self.crud_node_jobs.update_status = AsyncMock()
        self.manager = MagicMock()
        self.manager.job_finished = AsyncMock()

        self.jm = RemoteExecutorJobManager(
            log=MagicMock(),
            node_id="node1",
            crud_nodes=self.crud_nodes,
            crud_jobs=MagicMock(),
            crud_job_definitions=MagicMock(),
            crud_node_jobs=self.crud_node_jobs,
            manager=self.manager,
        )

    async def test_handle_finish_success(self):
        self.jm.active_job_ids = {"job1"}

        await self.jm.handle_finish(MagicMock(job_id="job1", exit_code=0))

        self.crud_node_jobs.update_status.assert_awaited_once_with(
            job_id="job1", node_id="node1", status="success"
        )
        self.assertEqual(self.manager.job_finished.call_args[1]["status"], "success")
        self.assertNotIn("job1", self.jm.active_job_ids)
        self.crud_nodes.update_remote_agent_current_job_id.assert_awaited()

    async def test_handle_finish_non_zero_exit_is_failed(self):
        self.jm.active_job_ids = {"job1"}

        await self.jm.handle_finish(MagicMock(job_id="job1", exit_code=3))

        self.crud_node_jobs.update_status.assert_awaited_once_with(
            job_id="job1", node_id="node1", status="failed"
        )
        kwargs = self.manager.job_finished.call_args[1]
        self.assertEqual(kwargs["status"], "failed")
        self.assertEqual(kwargs["exit_code"], 3)
        self.assertNotIn("job1", self.jm.active_job_ids)

    async def test_handle_heartbeat_syncs_active_jobs(self):
        await self.jm.handle_heartbeat(MagicMock(running_job_ids=["a", "b"]))

        self.assertEqual(self.jm.active_job_ids, {"a", "b"})
        args = self.crud_nodes.update_remote_agent_current_job_id.call_args[1]
        self.assertEqual(args["node_id"], "node1")
        self.assertEqual(set(args["current_job_id"]), {"a", "b"})

    async def test_mark_job_failed(self):
        self.jm.active_job_ids = {"job1", "job2"}

        await self.jm.mark_job_failed(job_id="job1", reason="boom")

        self.crud_node_jobs.update_status.assert_awaited_once_with(
            job_id="job1", node_id="node1", status="failed"
        )
        kwargs = self.manager.job_finished.call_args[1]
        self.assertEqual(kwargs["status"], "failed")
        self.assertEqual(kwargs["exit_code"], 1)
        self.assertNotIn("job1", self.jm.active_job_ids)
        self.assertIn("job2", self.jm.active_job_ids)

    async def test_mark_all_jobs_failed(self):
        self.jm.active_job_ids = {"job1", "job2"}

        await self.jm.mark_all_jobs_failed(reason="disconnect")

        self.assertEqual(self.crud_node_jobs.update_status.await_count, 2)
        self.assertEqual(self.manager.job_finished.await_count, 2)
        self.assertEqual(self.jm.active_job_ids, set())

    async def test_initialize_marks_stale_running_jobs_failed(self):
        self.crud_node_jobs.search = AsyncMock(
            return_value=MagicMock(result=[MagicMock(job_id="jobX")])
        )

        await self.jm.initialize()

        self.crud_node_jobs.search.assert_awaited_once_with(
            node_id="node1", status="running"
        )
        self.crud_node_jobs.update_status.assert_awaited_once_with(
            job_id="jobX", node_id="node1", status="failed"
        )
        self.manager.job_finished.assert_awaited_once()

    async def test_initialize_without_stale_jobs_is_noop(self):
        self.crud_node_jobs.search = AsyncMock(return_value=MagicMock(result=[]))

        await self.jm.initialize()

        self.crud_node_jobs.update_status.assert_not_called()
        self.manager.job_finished.assert_not_called()


if __name__ == "__main__":
    unittest.main()
