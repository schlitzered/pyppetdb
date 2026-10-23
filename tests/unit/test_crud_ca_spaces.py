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
from pyppetdb.crud.ca_spaces import CrudCASpaces


class _AsyncCursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._docs:
            raise StopAsyncIteration
        return self._docs.pop(0)


class TestCrudCASpacesUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_config = MagicMock()
        self.mock_coll = MagicMock()
        self.mock_protector = MagicMock()

        self.crud = CrudCASpaces(
            config=self.mock_config,
            log=self.log,
            coll=self.mock_coll,
            protector=self.mock_protector,
        )

    async def test_delete_success(self):
        self.mock_coll.delete_one = AsyncMock(return_value=MagicMock(deleted_count=1))
        await self.crud.delete(_id="space1")
        self.mock_coll.delete_one.assert_called_once_with(filter={"id": "space1"})

    async def test_create(self):
        from pyppetdb.model.ca_spaces import CASpacePost

        self.crud._create = AsyncMock(
            return_value={"id": "space1", "ca_id": "ca1", "ca_id_history": []}
        )
        payload_dict = {"ca_id": "ca1"}
        payload = CASpacePost(**payload_dict)
        await self.crud.create(_id="space1", payload=payload, fields=["id"])

        self.crud._create.assert_called_once()

    async def test_update(self):
        from pyppetdb.model.ca_spaces import CASpacePutInternal

        self.crud._update = AsyncMock(
            return_value={"id": "space1", "ca_id": "ca2", "ca_id_history": ["ca1"]}
        )

        payload_dict = {"ca_id": "ca2", "ca_id_history": ["ca1"]}
        payload = CASpacePutInternal(**payload_dict)
        await self.crud.update(_id="space1", payload=payload, fields=["id"])

        self.crud._update.assert_called_once()

    async def test_search_by_ca(self):
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[{"id": "s1"}])
        self.mock_coll.find.return_value = mock_cursor

        res = await self.crud.search_by_ca("ca1")
        self.assertEqual(len(res), 1)
        self.mock_coll.find.assert_called_once()
        args = self.mock_coll.find.call_args[0][0]
        self.assertIn("$or", args)

    async def test_search_filters_on_exact_secret_ref(self):
        self.crud._search = AsyncMock(
            return_value={"result": [], "meta": {"result_size": 0}}
        )

        await self.crud.search(secret_ref="TOK", fields=["id"])

        query = self.crud._search.call_args.kwargs["query"]
        self.assertEqual(query, {"secret_refs": "TOK"})

    async def test_search_without_secret_ref_has_no_filter(self):
        self.crud._search = AsyncMock(
            return_value={"result": [], "meta": {"result_size": 0}}
        )

        await self.crud.search(fields=["id"])

        self.assertNotIn("secret_refs", self.crud._search.call_args.kwargs["query"])

    def test_secret_refs_index_is_declared(self):
        keys = {
            index.document["name"]: dict(index.document["key"])
            for index in self.crud._indices
        }
        self.assertEqual(keys["idx_secret_refs"], {"secret_refs": 1})

    def test_schema_version_and_migrations(self):
        self.assertEqual(self.crud.schema_version, 3)
        self.assertEqual(
            {version: m.__name__ for version, m in self.crud._migrations.items()},
            {1: "migrate_1", 2: "migrate_2", 3: "migrate_3"},
        )

    async def test_migrate_3_backfills_missing_secret_refs(self):
        config = {
            "san_validation": {
                "http_checks": [
                    {
                        "url": "https://check.example.com",
                        "headers": [{"name": "a", "value": "$secrets[B] $secrets[A]"}],
                    }
                ]
            }
        }
        self.mock_coll.find = MagicMock(
            return_value=_AsyncCursor(
                [{"_id": "o1", "validation_config": config}, {"_id": "o2"}]
            )
        )
        self.mock_coll.update_one = AsyncMock()

        await self.crud.migrate_3()

        self.assertEqual(
            self.mock_coll.find.call_args.args[0], {"secret_refs": {"$exists": False}}
        )
        self.mock_coll.update_one.assert_any_await(
            {"_id": "o1"}, {"$set": {"secret_refs": ["A", "B"]}}, session=None
        )
        self.mock_coll.update_one.assert_any_await(
            {"_id": "o2"}, {"$set": {"secret_refs": []}}, session=None
        )

    def _cached(self, **kwargs):
        from pyppetdb.model.ca_spaces import CASpaceGet

        self.crud.cache.cache["space1"] = CASpaceGet(id="space1", ca_id="ca1", **kwargs)

    async def test_cached_get_returns_only_requested_fields_as_copy(self):
        from pyppetdb.crud.watcher import STATE_READY

        self.crud.cache.watcher._state = STATE_READY
        self._cached(description="cached")
        self.crud._get = AsyncMock()

        result = await self.crud.get("space1", fields=["ca_id"])
        result.ca_id = "changed"

        self.assertEqual(result.model_fields_set, {"ca_id"})
        self.assertEqual(self.crud.cache.cache["space1"].ca_id, "ca1")
        self.crud._get.assert_not_called()

    async def test_get_reads_backend_while_watcher_not_ready(self):
        self._cached(description="stale")
        self.crud._get = AsyncMock(return_value={"id": "space1", "description": "fresh"})

        result = await self.crud.get("space1", fields=[])

        self.assertEqual(result.description, "fresh")
