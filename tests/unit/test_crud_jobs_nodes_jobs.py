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
import logging

from pyppetdb.crud.jobs_nodes_jobs import CrudJobsNodeJobs


class TestCrudJobsNodeJobsUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_coll = MagicMock()
        self.mock_config = MagicMock()
        self.crud = CrudJobsNodeJobs(
            config=self.mock_config,
            log=self.log,
            coll=self.mock_coll,
        )

    async def test_update_status_transitions_non_terminal(self):
        self.mock_coll.find_one_and_update = AsyncMock(
            return_value={"status": "running"}
        )

        result = await self.crud.update_status(
            job_id="job1", node_id="node1", status="running"
        )

        self.assertEqual(result, "running")
        query = self.mock_coll.find_one_and_update.call_args[1]["filter"]
        self.assertEqual(query["job_id"], "job1")
        self.assertEqual(query["node_id"], "node1")
        self.assertEqual(
            query["status"], {"$nin": ["success", "failed", "canceled"]}
        )

    async def test_update_status_does_not_overwrite_terminal(self):
        self.mock_coll.find_one_and_update = AsyncMock(return_value=None)
        self.mock_coll.find_one = AsyncMock(return_value={"status": "canceled"})

        result = await self.crud.update_status(
            job_id="job1", node_id="node1", status="running"
        )

        self.assertEqual(result, "canceled")

    async def test_update_status_returns_none_for_missing_job(self):
        self.mock_coll.find_one_and_update = AsyncMock(return_value=None)
        self.mock_coll.find_one = AsyncMock(return_value=None)

        result = await self.crud.update_status(
            job_id="job1", node_id="node1", status="failed"
        )

        self.assertIsNone(result)

    async def test_cancel_node_jobs_cancels_scheduled_and_running(self):
        self.mock_coll.update_many = AsyncMock()

        await self.crud.cancel_node_jobs(job_id="job1")

        call_args = self.mock_coll.update_many.call_args[1]
        self.assertEqual(
            call_args["filter"],
            {"job_id": "job1", "status": {"$in": ["scheduled", "running"]}},
        )
        self.assertEqual(
            call_args["update"], {"$set": {"status": "canceled"}}
        )
