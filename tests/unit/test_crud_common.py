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
import pymongo
import pymongo.errors
from pyppetdb.crud.common import CrudMongo
from pyppetdb.errors import DuplicateResource
from pyppetdb.errors import ResourceNotFound
from pyppetdb.errors import BackendError


class TestCrudCommon(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_config = MagicMock()
        self.mock_coll = MagicMock()
        self.mock_coll.name = "test_coll"
        self.crud = CrudMongo(self.mock_config, self.log, self.mock_coll)

    async def test_create_success(self):
        self.mock_coll.insert_one = AsyncMock(
            return_value=MagicMock(inserted_id="obj1")
        )
        self.crud._get_by_obj_id = AsyncMock(return_value={"id": "r1"})

        result = await self.crud._create(
            payload={"id": "r1"},
            fields=["id"],
        )
        self.assertEqual(result, {"id": "r1"})
        self.mock_coll.insert_one.assert_called_once()

    async def test_create_duplicate(self):
        self.mock_coll.insert_one = AsyncMock(
            side_effect=pymongo.errors.DuplicateKeyError("msg")
        )
        with self.assertRaises(DuplicateResource):
            await self.crud._create(
                payload={"id": "r1"},
                fields=["id"],
            )

    async def test_create_backend_error(self):
        self.mock_coll.insert_one = AsyncMock(
            side_effect=pymongo.errors.ConnectionFailure("msg")
        )
        with self.assertRaises(BackendError):
            await self.crud._create(
                payload={"id": "r1"},
                fields=["id"],
            )

    async def test_sync_index_replaces_every_conflicting_index(self):
        index = pymongo.IndexModel([("a", 1), ("b", 1)], name="idx_a")
        conflict = pymongo.errors.OperationFailure("conflict", code=86)
        self.mock_coll.create_indexes = AsyncMock(side_effect=[conflict, None])
        self.mock_coll.drop_index = AsyncMock()
        self.mock_coll.list_indexes = MagicMock(
            return_value=MagicMock(
                to_list=AsyncMock(
                    return_value=[
                        {"name": "_id_", "key": {"_id": 1}},
                        {"name": "idx_a", "key": {"a": 1}},
                        {"name": "idx_other", "key": {"a": 1, "b": 1}},
                    ]
                )
            )
        )
        await self.crud._sync_index(index)
        dropped = [call.args[0] for call in self.mock_coll.drop_index.call_args_list]
        self.assertEqual(dropped, ["idx_a", "idx_other"])
        self.assertEqual(self.mock_coll.create_indexes.call_count, 2)

    async def test_sync_index_compares_key_order(self):
        index = pymongo.IndexModel([("a", 1), ("b", 1)], name="idx_a")
        conflict = pymongo.errors.OperationFailure("conflict", code=86)
        self.mock_coll.create_indexes = AsyncMock(side_effect=[conflict, None])
        self.mock_coll.drop_index = AsyncMock()
        self.mock_coll.list_indexes = MagicMock(
            return_value=MagicMock(
                to_list=AsyncMock(
                    return_value=[
                        {"name": "idx_a", "key": {"b": 1, "a": 1}},
                        {"name": "idx_reversed", "key": {"b": 1, "a": 1}},
                    ]
                )
            )
        )
        await self.crud._sync_index(index)
        dropped = [call.args[0] for call in self.mock_coll.drop_index.call_args_list]
        self.assertEqual(dropped, ["idx_a"])

    async def test_sync_index_replaces_an_index_whose_options_changed(self):
        index = pymongo.IndexModel(
            [("disabled", 1)], name="idx_disabled", partialFilterExpression={"disabled": True}
        )
        conflict = pymongo.errors.OperationFailure("conflict", code=85)
        self.mock_coll.create_indexes = AsyncMock(side_effect=[conflict, None])
        self.mock_coll.drop_index = AsyncMock()
        self.mock_coll.list_indexes = MagicMock(
            return_value=MagicMock(
                to_list=AsyncMock(
                    return_value=[{"name": "idx_disabled", "key": {"disabled": 1}}]
                )
            )
        )
        await self.crud._sync_index(index)
        dropped = [call.args[0] for call in self.mock_coll.drop_index.call_args_list]
        self.assertEqual(dropped, ["idx_disabled"])
        self.assertEqual(self.mock_coll.create_indexes.call_count, 2)

    async def test_sync_index_raises_other_failures(self):
        index = pymongo.IndexModel([("a", 1)], name="idx_a")
        self.mock_coll.create_indexes = AsyncMock(
            side_effect=pymongo.errors.OperationFailure("nope", code=13)
        )
        with self.assertRaises(pymongo.errors.OperationFailure):
            await self.crud._sync_index(index)

    async def test_delete_success(self):
        self.mock_coll.delete_one = AsyncMock(return_value=MagicMock(deleted_count=1))
        result = await self.crud._delete({"id": "r1"})
        self.assertEqual(result, {})

    async def test_delete_not_found(self):
        self.mock_coll.delete_one = AsyncMock(return_value=MagicMock(deleted_count=0))
        with self.assertRaises(ResourceNotFound):
            await self.crud._delete({"id": "r1"})

    async def test_get_success(self):
        self.mock_coll.find_one = AsyncMock(return_value={"_id": "obj1", "id": "r1"})
        result = await self.crud._get({"id": "r1"}, fields=["id"])
        self.assertEqual(result, {"id": "r1"})

    async def test_get_not_found(self):
        self.mock_coll.find_one = AsyncMock(return_value=None)
        with self.assertRaises(ResourceNotFound):
            await self.crud._get({"id": "r1"}, fields=[])

    async def test_search_success(self):
        self.mock_coll.count_documents = AsyncMock(return_value=1)
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[{"_id": "obj1", "id": "r1"}])
        self.mock_coll.find.return_value = mock_cursor

        result = await self.crud._search(
            {"id": "r1"}, sort="id", sort_order="ascending", page=1, limit=10
        )
        self.assertEqual(result["meta"]["result_size"], 1)
        self.assertEqual(result["result"][0]["id"], "r1")
        mock_cursor.sort.assert_called_once_with([("id", pymongo.ASCENDING)])
        mock_cursor.skip.assert_called_once_with(10)
        mock_cursor.limit.assert_called_once_with(10)
        mock_cursor.hint.assert_not_called()
        self.mock_coll.count_documents.assert_awaited_once_with(filter={"id": "r1"})

    async def test_search_without_limit_does_not_limit_cursor(self):
        self.mock_coll.count_documents = AsyncMock(return_value=0)
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[])
        self.mock_coll.find.return_value = mock_cursor

        await self.crud._search({})

        mock_cursor.limit.assert_not_called()
        mock_cursor.skip.assert_not_called()
        mock_cursor.sort.assert_not_called()

    async def test_search_hints_scoped_sort_index(self):
        self.crud._indices.append(
            pymongo.IndexModel([("space_id", 1), ("id", 1)], name="idx_space_id")
        )
        self.mock_coll.count_documents = AsyncMock(return_value=0)
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[])
        self.mock_coll.find.return_value = mock_cursor

        await self.crud._search(
            {"space_id": "s1", "cn": {"$regex": "x"}},
            sort="id",
            sort_order="descending",
            page=0,
            limit=10,
        )

        mock_cursor.hint.assert_called_once_with("idx_space_id")

    async def test_search_retries_without_hint_on_failure(self):
        self.crud._indices.append(
            pymongo.IndexModel([("space_id", 1), ("id", 1)], name="idx_space_id")
        )
        self.mock_coll.count_documents = AsyncMock(return_value=1)
        hinted = MagicMock()
        hinted.to_list = AsyncMock(
            side_effect=pymongo.errors.OperationFailure("bad hint", code=2)
        )
        plain = MagicMock()
        plain.to_list = AsyncMock(return_value=[{"id": "r1"}])
        self.mock_coll.find.side_effect = [hinted, plain]

        result = await self.crud._search(
            {"space_id": "s1"}, sort="id", sort_order="ascending", limit=10
        )

        self.assertEqual(result["result"], [{"id": "r1"}])
        hinted.hint.assert_called_once_with("idx_space_id")
        plain.hint.assert_not_called()

    async def test_search_backend_error(self):
        self.mock_coll.count_documents = AsyncMock(
            side_effect=pymongo.errors.ConnectionFailure("msg")
        )
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[])
        self.mock_coll.find.return_value = mock_cursor

        with self.assertRaises(BackendError):
            await self.crud._search({})

    def test_sort_hint_prefers_longest_pinned_scope(self):
        self.crud._indices.extend(
            [
                pymongo.IndexModel([("space_id", 1), ("cn", 1)], name="idx_a"),
                pymongo.IndexModel(
                    [("space_id", 1), ("status", 1), ("cn", 1)], name="idx_b"
                ),
            ]
        )
        self.assertEqual(
            self.crud._sort_hint({"space_id": "s", "status": "signed"}, "cn"),
            "idx_b",
        )
        self.assertEqual(self.crud._sort_hint({"space_id": "s"}, "cn"), "idx_a")

    def test_sort_hint_requires_equality_on_whole_scope(self):
        self.crud._indices.append(
            pymongo.IndexModel([("space_id", 1), ("id", 1)], name="idx_space_id")
        )
        self.assertIsNone(self.crud._sort_hint({}, "id"))
        self.assertIsNone(self.crud._sort_hint({"space_id": {"$regex": "s"}}, "id"))
        self.assertIsNone(self.crud._sort_hint({"space_id": {"$in": ["a"]}}, "id"))
        self.assertIsNone(self.crud._sort_hint({"space_id": ["a"]}, "id"))
        self.assertIsNone(self.crud._sort_hint({"space_id": "s"}, "cn"))
        self.assertEqual(
            self.crud._sort_hint({"space_id": {"$eq": "s", "$in": ["s"]}}, "id"),
            "idx_space_id",
        )
        self.assertEqual(
            self.crud._sort_hint({"space_id": {"a": "b"}}, "id"), "idx_space_id"
        )

    def test_sort_hint_skips_unscoped_sparse_and_partial_indexes(self):
        self.crud._indices.extend(
            [
                pymongo.IndexModel([("id", 1)], name="idx_id"),
                pymongo.IndexModel(
                    [("space_id", 1), ("cn", 1)], sparse=True, name="idx_sparse"
                ),
                pymongo.IndexModel(
                    [("space_id", 1), ("not_after", 1)],
                    partialFilterExpression={"status": "signed"},
                    name="idx_partial",
                ),
            ]
        )
        self.assertIsNone(self.crud._sort_hint({"space_id": "s"}, "id"))
        self.assertIsNone(self.crud._sort_hint({"space_id": "s"}, "cn"))
        self.assertIsNone(self.crud._sort_hint({"space_id": "s"}, "not_after"))

    async def test_update_success(self):
        self.mock_coll.find_one_and_update = AsyncMock(
            return_value={"_id": "obj1", "id": "r1", "val": "new"}
        )
        result = await self.crud._update({"id": "r1"}, {"val": "new"}, fields=[])
        self.assertEqual(result["val"], "new")

    async def test_update_not_found(self):
        self.mock_coll.find_one_and_update = AsyncMock(return_value=None)
        with self.assertRaises(ResourceNotFound):
            await self.crud._update({"id": "r1"}, {"val": "new"}, fields=[])

    async def test_create_ttl_index(self):
        self.mock_coll.list_indexes.return_value.to_list = AsyncMock(return_value=[])
        self.mock_coll.create_index = AsyncMock()

        await self.crud._create_ttl_index("field1", 3600, "idx1")
        self.mock_coll.create_index.assert_called_once()

    async def test_create_ttl_index_exists_matching(self):
        self.mock_coll.list_indexes.return_value.to_list = AsyncMock(
            return_value=[
                {"name": "idx1", "expireAfterSeconds": 3600, "key": {"field1": 1}}
            ]
        )
        self.mock_coll.create_index = AsyncMock()

        await self.crud._create_ttl_index("field1", 3600, "idx1")
        self.mock_coll.create_index.assert_not_called()

    async def test_create_ttl_index_exists_mismatch(self):
        self.mock_coll.list_indexes.return_value.to_list = AsyncMock(
            return_value=[
                {"name": "idx1", "expireAfterSeconds": 1800, "key": {"field1": 1}}
            ]
        )
        self.mock_coll.drop_index = AsyncMock()
        self.mock_coll.create_index = AsyncMock()

        await self.crud._create_ttl_index("field1", 3600, "idx1")
        self.mock_coll.drop_index.assert_called_once_with("idx1")
        self.mock_coll.create_index.assert_called_once()
