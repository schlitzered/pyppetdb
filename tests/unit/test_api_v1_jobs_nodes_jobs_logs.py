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

import logging
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, AsyncMock

from fastapi import HTTPException

from pyppetdb.authorize import PERM_JOBS_GET
from pyppetdb.controller.api.v1.jobs_nodes_jobs_logs import (
    ControllerApiV1JobsNodesJobsLogs,
)


class TestApiV1JobsNodesJobsLogsUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_authorize = MagicMock()
        self.mock_authorize.require_perm = AsyncMock()
        self.mock_manager = MagicMock()

        self.controller = ControllerApiV1JobsNodesJobsLogs(
            log=self.log,
            authorize=self.mock_authorize,
            manager=self.mock_manager,
        )

    async def test_get_success(self):
        log_entry = {
            "line_nr": 1,
            "timestamp": datetime.now(timezone.utc),
            "msg": "hello",
        }
        self.mock_manager.get_log_chunk = AsyncMock(return_value=[log_entry])

        mock_request = MagicMock()
        result = await self.controller.get(
            request=mock_request, log_id="job1:node1:5"
        )

        self.mock_authorize.require_perm.assert_called_once_with(
            request=mock_request, permission=PERM_JOBS_GET
        )
        # rsplit(":", 1) -> job_run_id keeps everything before the last colon
        self.mock_manager.get_log_chunk.assert_called_once_with(
            job_run_id="job1:node1", chunk_id="5"
        )
        self.assertEqual(result.id, "job1:node1:5")
        self.assertEqual(len(result.data), 1)
        self.assertEqual(result.data[0].msg, "hello")

    async def test_get_invalid_log_id_format(self):
        self.mock_manager.get_log_chunk = AsyncMock()

        with self.assertRaises(HTTPException) as ctx:
            await self.controller.get(request=MagicMock(), log_id="no-colon-here")

        self.assertEqual(ctx.exception.status_code, 400)
        self.mock_manager.get_log_chunk.assert_not_called()

    async def test_get_chunk_not_found(self):
        self.mock_manager.get_log_chunk = AsyncMock(return_value=None)

        with self.assertRaises(HTTPException) as ctx:
            await self.controller.get(request=MagicMock(), log_id="job1:node1:5")

        self.assertEqual(ctx.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
