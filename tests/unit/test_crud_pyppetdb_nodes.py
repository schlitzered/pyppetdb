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
from pyppetdb.crud.pyppetdb_nodes import CrudPyppetDBNodes


class TestCrudPyppetDBNodesUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_coll = MagicMock()
        self.mock_config = MagicMock()
        self.crud = CrudPyppetDBNodes(self.log, self.mock_config, self.mock_coll)

    async def test_heartbeat_update(self):
        self.mock_coll.update_one = AsyncMock()
        await self.crud.heartbeat_update(_id="instance1")

        self.mock_coll.update_one.assert_called_once()
        args, kwargs = self.mock_coll.update_one.call_args
        self.assertEqual(kwargs["filter"], {"id": "instance1"})
        self.assertTrue("heartbeat" in kwargs["update"]["$set"])
        self.assertIsInstance(kwargs["update"]["$set"]["heartbeat"], datetime)
        self.assertTrue("online_since" in kwargs["update"]["$setOnInsert"])
        self.assertIsInstance(
            kwargs["update"]["$setOnInsert"]["online_since"], datetime
        )
        self.assertEqual(kwargs["upsert"], True)

    async def test_delete(self):
        self.crud._delete = AsyncMock()
        await self.crud.delete(_id="instance1")
        self.crud._delete.assert_called_once_with(query={"id": "instance1"})

    async def test_get(self):
        self.crud._get = AsyncMock(
            return_value={"id": "instance1", "heartbeat": datetime.now()}
        )
        result = await self.crud.get(_id="instance1", fields=[])
        self.assertEqual(result.id, "instance1")
        self.crud._get.assert_called_once()

    async def test_search(self):
        self.crud._search = AsyncMock(
            return_value={
                "result": [{"id": "instance1", "heartbeat": datetime.now()}],
                "meta": {"result_size": 1},
            }
        )

        result = await self.crud.search(_id="instance1")
        self.assertEqual(len(result.result), 1)
        self.assertEqual(result.result[0].id, "instance1")
        self.crud._search.assert_called_once()
