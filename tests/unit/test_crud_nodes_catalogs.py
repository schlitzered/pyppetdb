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
from unittest.mock import MagicMock
from unittest.mock import AsyncMock
import logging
from pyppetdb.crud.nodes_catalog_cache import NodesDataProtector
from pyppetdb.crud.nodes_catalogs import CrudNodesCatalogs


class TestCrudNodesCatalogsUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_coll = MagicMock()
        self.mock_config = MagicMock()
        self.mock_redactor = MagicMock()
        self.mock_redactor.redact.side_effect = lambda x: x
        self.protector = NodesDataProtector("unit-test-key", self.log)
        self.crud = CrudNodesCatalogs(
            self.mock_config, self.log, self.mock_coll, self.mock_redactor, self.protector
        )

    async def test_delete_all_from_node(self):
        self.mock_coll.delete_many = AsyncMock()
        await self.crud.delete_all_from_node(
            node_id="node1",
            placement={},
        )
        self.mock_coll.delete_many.assert_called_once_with(filter={"node_id": "node1"})

    async def test_create(self):
        from datetime import datetime

        now = datetime.now()
        self.crud._create = AsyncMock(return_value={"id": now})
        self.mock_redactor.redact.side_effect = lambda x: x

        from pyppetdb.model.nodes_catalogs import NodeCatalogPostInternal

        payload = NodeCatalogPostInternal(catalog={"resources": []})

        content = self.crud.encode_content(
            {"catalog_uuid": "u", "resources": [{"type": "File"}], "edges": []}
        )
        result = await self.crud.create(
            _id=now, node_id="node1", payload=payload, fields=[], content=content
        )
        self.assertEqual(result.id, now)
        stored = self.crud._create.call_args.kwargs["payload"]
        self.assertEqual(stored["catalog_content"], content)
        self.assertEqual(
            self.protector.decrypt_obj(stored["catalog_content"]),
            {"resources": [{"type": "File"}], "edges": []},
        )

    async def test_get_inflates_the_content_and_redacts(self):
        content = self.crud.encode_content(
            {
                "resources": [
                    {"type": "File", "title": "x", "exported": False, "tags": [], "parameters": {"a": "s"}}
                ],
                "edges": [],
            }
        )
        self.crud._get = AsyncMock(
            return_value={
                "id": "cat1",
                "node_id": "node1",
                "catalog": {"catalog_uuid": "cat1", "num_resources": 1},
                "catalog_content": content,
            }
        )
        seen = []
        self.mock_redactor.redact.side_effect = lambda x: seen.append(x) or x
        result = await self.crud.get(
            _id="cat1", node_id="node1", placement={}, fields=["id", "catalog"]
        )
        self.assertEqual(
            self.crud._get.call_args.kwargs["fields"], ["id", "catalog", "catalog_content"]
        )
        self.assertEqual(result.catalog.resources[0].title, "x")
        self.assertEqual(result.catalog.num_resources, 1)
        self.assertNotIn("catalog_content", seen[0])
        self.assertEqual(seen[0]["catalog"]["resources"][0]["parameters"], {"a": "s"})

    async def test_get_without_catalog_field_skips_the_content(self):
        self.crud._get = AsyncMock(return_value={"id": "cat1", "node_id": "node1"})
        await self.crud.get(_id="cat1", node_id="node1", placement={}, fields=["id"])
        self.assertEqual(self.crud._get.call_args.kwargs["fields"], ["id"])

    async def test_get(self):
        self.crud._get = AsyncMock(return_value={"id": "cat1", "node_id": "node1"})
        await self.crud.get(
            _id="cat1",
            node_id="node1",
            placement={},
            fields=[],
        )
        self.crud._get.assert_called_once()

    async def test_resource_exists(self):
        self.crud._resource_exists = AsyncMock(return_value=True)
        await self.crud.resource_exists(
            _id="cat1",
            node_id="node1",
            placement={},
        )
        self.crud._resource_exists.assert_called_once()

    async def test_drop_created_no_report_ttl(self):
        self.mock_coll.update_one = AsyncMock()
        await self.crud.drop_created_no_report_ttl(
            _id="cat1",
            node_id="node1",
            placement={},
        )
        self.mock_coll.update_one.assert_called_once()

    async def test_search(self):
        self.crud._search = AsyncMock(
            return_value={"result": [], "meta": {"result_size": 0}}
        )
        await self.crud.search(
            node_id="node1",
            placement={},
        )
        self.crud._search.assert_called_once()
