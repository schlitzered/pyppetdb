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
from datetime import UTC
from datetime import datetime
from unittest.mock import MagicMock

from pyppetdb.controller.api.v1.status import ControllerApiV1Status


class TestApiV1StatusUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.coordinator = MagicMock()
        config = MagicMock()
        config.app.main.port = 8000
        self.controller = ControllerApiV1Status(
            log=logging.getLogger("test"),
            config=config,
            watcher_coordinator=self.coordinator,
        )

    async def test_reports_every_watcher(self):
        synced = datetime(2026, 1, 1, tzinfo=UTC)
        self.coordinator.status.return_value = [
            {"name": "nodes_groups", "state": "ready", "last_sync": synced, "last_error": None},
            {"name": "hiera_keys", "state": "error", "last_sync": synced, "last_error": "connection lost"},
        ]

        result = await self.controller.get()

        self.assertTrue(result.instance.endswith(":8000"))
        self.assertFalse(result.ready)
        self.assertEqual([watcher.name for watcher in result.watchers], ["nodes_groups", "hiera_keys"])
        self.assertEqual(result.watchers[1].last_error, "connection lost")

    async def test_ready_when_every_watcher_is_ready(self):
        self.coordinator.status.return_value = [
            {"name": "nodes_groups", "state": "ready", "last_sync": None, "last_error": None},
        ]

        result = await self.controller.get()

        self.assertTrue(result.ready)
