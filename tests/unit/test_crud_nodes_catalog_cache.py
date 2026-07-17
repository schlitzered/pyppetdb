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
from pyppetdb.crud.nodes_catalog_cache import CrudNodesCatalogCache
from pyppetdb.errors import ResourceNotFound


class TestCrudNodesCatalogCacheUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_config = MagicMock()
        self.mock_config.mongodb = MagicMock()
        self.mock_config.mongodb.placementFacts = []
        self.mock_coll = MagicMock()
        self.mock_protector = MagicMock()
        self.crud = CrudNodesCatalogCache(
            config=self.mock_config,
            log=self.log,
            coll=self.mock_coll,
            protector=self.mock_protector,
        )



    async def test_get_success(self):
        self.mock_coll.find_one = AsyncMock(return_value={"catalog": "encrypted_data"})
        self.mock_protector.decrypt_obj.return_value = {"resources": []}

        catalog = await self.crud.get(
            node_id="node1",
            placement={},
        )
        self.assertEqual(catalog, {"resources": []})
        self.mock_protector.decrypt_obj.assert_called_once_with("encrypted_data")

    async def test_get_none(self):
        self.mock_coll.find_one = AsyncMock(return_value=None)
        catalog = await self.crud.get(
            node_id="node1",
            placement={},
        )
        self.assertIsNone(catalog)

    async def test_upsert(self):
        self.mock_config.app.puppet.catalogCacheTTL = 3600
        self.mock_config.mongodb.placementFacts = ["provider"]
        self.mock_protector.encrypt_obj.return_value = "encrypted"
        self.mock_coll.update_one = AsyncMock()

        await self.crud.upsert("node1", {"provider": "aws"}, {"res": []})
        self.mock_coll.update_one.assert_called_once()
        call_args = self.mock_coll.update_one.call_args[1]
        self.assertEqual(call_args["filter"], {"id": "node1"})
        self.assertEqual(call_args["update"]["$set"]["catalog"], "encrypted")
        self.assertEqual(call_args["update"]["$set"]["placement"], {"provider": "aws"})

    async def test_get_cached_node_ids(self):
        mock_cursor = MagicMock()
        mock_cursor.__aiter__.return_value = [{"id": "n1"}, {"id": "n2"}]
        self.mock_coll.find.return_value = mock_cursor

        ids = await self.crud.get_cached_node_ids(["n1", "n2", "n3"])
        self.assertEqual(ids, {"n1", "n2"})

    async def test_delete_many_by_filter(self):
        self.mock_coll.delete_many = AsyncMock(return_value=MagicMock(deleted_count=5))
        count = await self.crud.delete_many_by_filter(node_id="node.*")
        self.assertEqual(count, 5)
        self.mock_coll.delete_many.assert_called_once()
