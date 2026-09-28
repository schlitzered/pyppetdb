# Copyright 2024 Stephan Schultchen
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
from datetime import datetime
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

from pyppetdb.crud.nodes_events import CrudNodesEvents


class TestCrudNodesEvents(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.coll = MagicMock()
        self.coll.insert_many = AsyncMock()
        self.coll.update_many = AsyncMock()
        self.coll.delete_many = AsyncMock()
        self.crud = CrudNodesEvents(MagicMock(), logging.getLogger("test"), self.coll)

    def test_indexes_cover_the_paging_and_filter_columns(self):
        keys = {
            index.document["name"]: list(index.document["key"].items())
            for index in self.crud._indices
        }
        self.assertEqual(keys["idx_node_id_timestamp"], [("node_id", 1), ("timestamp", 1)])
        self.assertEqual(keys["idx_report_hash"], [("report_hash", 1)])
        self.assertEqual(keys["idx_status_timestamp"], [("status", 1), ("timestamp", 1)])
        self.assertEqual(keys["idx_latest_timestamp"], [("latest", 1), ("timestamp", 1)])
        self.assertEqual(
            keys["idx_latest_counts"],
            [
                ("latest", 1),
                ("status", 1),
                ("node_id", 1),
                ("resource_type", 1),
                ("resource_title", 1),
                ("containing_class", 1),
                ("corrective_change", 1),
            ],
        )

    async def test_insert_for_report_skips_empty_batches(self):
        await self.crud.insert_for_report([])
        self.coll.insert_many.assert_not_awaited()
        await self.crud.insert_for_report([{"node_id": "a"}])
        self.coll.insert_many.assert_awaited_once_with([{"node_id": "a"}], ordered=False)

    async def test_set_latest_only_touches_changed_documents(self):
        await self.crud.set_latest(node_id="a", latest=False)
        self.coll.update_many.assert_awaited_once_with(
            filter={"node_id": "a", "latest": {"$ne": False}},
            update={"$set": {"latest": False}},
        )

    async def test_delete_for_report(self):
        when = datetime(2026, 1, 1)
        await self.crud.delete_for_report(node_id="a", report_id=when)
        self.coll.delete_many.assert_awaited_once_with(
            filter={"node_id": "a", "report_id": when}
        )
