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
from datetime import datetime
from pyppetdb.crud.jobs_jobs import CrudJobs
from pyppetdb.model.jobs_jobs import JobPost


class TestCrudJobsUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_coll = MagicMock()
        self.mock_config = MagicMock()
        self.crud = CrudJobs(
            self.log,
            self.mock_config,
            self.mock_coll,
        )

    async def test_create_job(self):
        # Setup mocks
        self.crud._create = AsyncMock(
            return_value={
                "id": "job1",
                "definition_id": "def1",
                "parameters": {},
                "env_vars": {},
                "node_filter": ["kernel:eq:str:Linux"],
                "nodes": ["node1"],
                "created_by": "admin",
                "created_at": datetime.now(),
            }
        )

        payload = JobPost(definition_id="def1", node_filter={"kernel:eq:str:Linux"})

        result = await self.crud.create(
            payload=payload,
            node_ids=["node1"],
            created_by="admin",
            fields=[],
        )

        self.assertEqual(result.id, "job1")
        self.assertEqual(result.nodes, ["node1"])
