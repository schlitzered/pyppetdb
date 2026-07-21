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

from pyppetdb.jobs.service import JobService


class TestJobServiceExpiryWorker(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.config = MagicMock()
        self.config.app.main.port = 8000
        self.config.jobs.expireSeconds = 300
        self.crud_node_jobs = MagicMock()
        self.crud_pyppetdb_nodes = MagicMock()
        self.hub = MagicMock()
        self.hub.job_finished = AsyncMock()

        self.svc = JobService(
            log=MagicMock(),
            config=self.config,
            crud_node_jobs=self.crud_node_jobs,
            crud_pyppetdb_nodes=self.crud_pyppetdb_nodes,
            hub=self.hub,
        )
        self.svc._instance_id = "me:8000"

    @patch(
        "pyppetdb.jobs.service.asyncio.sleep",
        new_callable=AsyncMock,
        side_effect=asyncio.CancelledError,
    )
    async def test_leader_expires_jobs_and_notifies_hub(self, _):
        self.crud_pyppetdb_nodes.get_leader = AsyncMock(return_value="me:8000")
        self.crud_node_jobs.expire_scheduled_jobs = AsyncMock(
            return_value=[MagicMock(job_id="job1", node_id="node1")]
        )

        with self.assertRaises(asyncio.CancelledError):
            await self.svc.expire_scheduled_jobs_worker()

        self.crud_node_jobs.expire_scheduled_jobs.assert_awaited_once_with(
            timeout_seconds=300
        )
        self.hub.job_finished.assert_awaited_once_with(
            node_id="node1", job_id="job1", status="failed", exit_code=1
        )

    @patch(
        "pyppetdb.jobs.service.asyncio.sleep",
        new_callable=AsyncMock,
        side_effect=asyncio.CancelledError,
    )
    async def test_non_leader_skips_expiry(self, _):
        self.crud_pyppetdb_nodes.get_leader = AsyncMock(return_value="other:8000")
        self.crud_node_jobs.expire_scheduled_jobs = AsyncMock()

        with self.assertRaises(asyncio.CancelledError):
            await self.svc.expire_scheduled_jobs_worker()

        self.crud_node_jobs.expire_scheduled_jobs.assert_not_called()
        self.hub.job_finished.assert_not_called()

    @patch(
        "pyppetdb.jobs.service.asyncio.sleep",
        new_callable=AsyncMock,
        side_effect=asyncio.CancelledError,
    )
    async def test_backend_error_is_swallowed_and_loop_continues(self, _):
        self.crud_pyppetdb_nodes.get_leader = AsyncMock(
            side_effect=Exception("backend down")
        )

        with self.assertRaises(asyncio.CancelledError):
            await self.svc.expire_scheduled_jobs_worker()

        self.hub.job_finished.assert_not_called()


if __name__ == "__main__":
    unittest.main()
