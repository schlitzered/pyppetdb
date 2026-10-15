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

    async def test_create_without_fetch_returns_none(self):
        self.mock_coll.insert_one = AsyncMock(
            return_value=MagicMock(inserted_id="obj1")
        )
        self.crud._get_by_obj_id = AsyncMock()

        result = await self.crud._create(
            payload={"id": "r1"}, fields=["id"], fetch=False
        )

        self.assertIsNone(result)
        self.mock_coll.insert_one.assert_awaited_once_with({"id": "r1", "_version": 0})
        self.crud._get_by_obj_id.assert_not_awaited()

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
        self.mock_coll.count_documents = AsyncMock(return_value=5)
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

    async def test_search_with_index_counts_before_reading_the_page(self):
        calls = []
        self.crud._indices.append(
            pymongo.IndexModel([("space_id", 1), ("id", 1)], name="idx_space_id")
        )

        async def count_documents(**kwargs):
            calls.append("count")
            return 30

        async def to_list(length):
            calls.append("page")
            return []

        self.mock_coll.count_documents = AsyncMock(side_effect=count_documents)
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(side_effect=to_list)
        self.mock_coll.find.return_value = mock_cursor

        await self.crud._search(
            {"space_id": "s1"}, sort="id", sort_order="ascending", page=1, limit=10
        )

        self.assertEqual(calls, ["count", "page"])
        mock_cursor.sort.assert_called_once_with([("id", pymongo.ASCENDING)])
        mock_cursor.skip.assert_called_once_with(10)

    async def test_search_with_index_and_no_matches_skips_the_page(self):
        self.crud._indices.append(
            pymongo.IndexModel([("space_id", 1), ("id", 1)], name="idx_space_id")
        )
        self.mock_coll.count_documents = AsyncMock(return_value=0)

        result = await self.crud._search(
            {"space_id": "s1"}, sort="id", sort_order="ascending", page=0, limit=10
        )

        self.assertEqual(result["result"], [])
        self.assertEqual(result["meta"]["result_size"], 0)
        self.mock_coll.find.assert_not_called()

    async def test_search_shallow_page_from_the_end(self):
        mock_cursor = self._scoped_search_setup(15, [{"id": "b"}, {"id": "a"}])

        result = await self.crud._search(
            {"space_id": "s"}, sort="id", sort_order="ascending", page=1, limit=10
        )

        self.assertEqual(result["result"], [{"id": "a"}, {"id": "b"}])
        mock_cursor.sort.assert_called_once_with([("id", pymongo.DESCENDING)])
        mock_cursor.skip.assert_not_called()
        mock_cursor.limit.assert_called_once_with(5)

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

    def _scoped_search_setup(self, count, rows):
        self.crud._indices.append(
            pymongo.IndexModel([("space_id", 1), ("id", 1)], name="idx_space_id")
        )
        self.mock_coll.count_documents = AsyncMock(return_value=count)
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=rows)
        self.mock_coll.find.return_value = mock_cursor
        return mock_cursor

    async def test_search_deep_page_reads_from_the_end(self):
        mock_cursor = self._scoped_search_setup(100000, [{"id": "b"}, {"id": "a"}])

        result = await self.crud._search(
            {"space_id": "s"}, sort="id", sort_order="ascending", page=9000, limit=10
        )

        self.assertEqual(result["result"], [{"id": "a"}, {"id": "b"}])
        self.assertEqual(result["meta"]["result_size"], 100000)
        mock_cursor.sort.assert_called_once_with([("id", pymongo.DESCENDING)])
        mock_cursor.skip.assert_called_once_with(9990)
        mock_cursor.limit.assert_called_once_with(10)
        mock_cursor.hint.assert_called_once_with("idx_space_id")

    async def test_search_partial_last_page_from_the_end(self):
        mock_cursor = self._scoped_search_setup(100005, [{"id": "a"}])

        await self.crud._search(
            {"space_id": "s"}, sort="id", sort_order="descending", page=10000, limit=10
        )

        mock_cursor.sort.assert_called_once_with([("id", pymongo.ASCENDING)])
        mock_cursor.skip.assert_not_called()
        mock_cursor.limit.assert_called_once_with(5)

    async def test_search_page_beyond_end_skips_find(self):
        self._scoped_search_setup(50000, [])

        result = await self.crud._search(
            {"space_id": "s"}, sort="id", sort_order="ascending", page=6000, limit=10
        )

        self.assertEqual(result["result"], [])
        self.assertEqual(result["meta"]["result_size"], 50000)
        self.mock_coll.find.assert_not_called()

    async def test_search_first_half_reads_forward(self):
        mock_cursor = self._scoped_search_setup(100000, [])

        await self.crud._search(
            {"space_id": "s"}, sort="id", sort_order="ascending", page=4000, limit=10
        )

        mock_cursor.sort.assert_called_once_with([("id", pymongo.ASCENDING)])
        mock_cursor.skip.assert_called_once_with(40000)

    async def test_search_deep_page_without_hint_reads_forward(self):
        mock_cursor = self._scoped_search_setup(100000, [])

        await self.crud._search(
            {"space_id": {"$regex": "s"}},
            sort="id",
            sort_order="ascending",
            page=9000,
            limit=10,
        )

        mock_cursor.sort.assert_called_once_with([("id", pymongo.ASCENDING)])
        mock_cursor.skip.assert_called_once_with(90000)
        mock_cursor.hint.assert_not_called()

    async def test_search_backend_error(self):
        self.mock_coll.count_documents = AsyncMock(
            side_effect=pymongo.errors.ConnectionFailure("msg")
        )
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[])
        self.mock_coll.find.return_value = mock_cursor

        with self.assertRaises(BackendError):
            await self.crud._search({}, limit=10)

    async def test_search_without_limit_counts_the_rows(self):
        self.mock_coll.count_documents = AsyncMock(return_value=99)
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[{"id": "a"}, {"id": "b"}])
        self.mock_coll.find.return_value = mock_cursor

        result = await self.crud._search({"x": 1}, page=3)

        self.assertEqual(result["meta"]["result_size"], 2)
        self.mock_coll.count_documents.assert_not_called()
        mock_cursor.skip.assert_not_called()

    async def test_search_uses_custom_count(self):
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[])
        self.mock_coll.find.return_value = mock_cursor
        count = AsyncMock(return_value=42)

        result = await self.crud._search({"x": 1}, limit=10, count=count)

        self.assertEqual(result["meta"]["result_size"], 42)
        count.assert_awaited_once_with({"x": 1})

    def _index_name(self, query, sort):
        index = self.crud._sort_index(query, sort)
        return index["name"] if index else None

    def test_sort_index_prefers_longest_pinned_scope(self):
        self.crud._indices.extend(
            [
                pymongo.IndexModel([("space_id", 1), ("cn", 1)], name="idx_a"),
                pymongo.IndexModel(
                    [("space_id", 1), ("status", 1), ("cn", 1)], name="idx_b"
                ),
            ]
        )
        self.assertEqual(
            self._index_name({"space_id": "s", "status": "signed"}, "cn"), "idx_b"
        )
        self.assertEqual(self._index_name({"space_id": "s"}, "cn"), "idx_a")

    def test_sort_index_requires_equality_on_whole_scope(self):
        self.crud._indices.append(
            pymongo.IndexModel([("space_id", 1), ("id", 1)], name="idx_space_id")
        )
        self.assertIsNone(self._index_name({}, "id"))
        self.assertIsNone(self._index_name({"space_id": {"$regex": "s"}}, "id"))
        self.assertIsNone(self._index_name({"space_id": {"$in": ["a"]}}, "id"))
        self.assertIsNone(self._index_name({"space_id": ["a"]}, "id"))
        self.assertIsNone(self._index_name({"space_id": "s"}, "cn"))
        self.assertEqual(
            self._index_name({"space_id": {"$eq": "s", "$in": ["s"]}}, "id"),
            "idx_space_id",
        )
        self.assertEqual(self._index_name({"space_id": {"a": "b"}}, "id"), "idx_space_id")

    def test_sort_index_unscoped_only_for_unfiltered_queries(self):
        self.crud._indices.append(pymongo.IndexModel([("id", 1)], name="idx_id"))
        self.assertEqual(self._index_name({}, "id"), "idx_id")
        self.assertIsNone(self._index_name({"space_id": "s"}, "id"))
        self.assertIsNone(self._index_name({"cn": {"$regex": "x"}}, "id"))

    def test_sort_index_skips_sparse_partial_and_special_indexes(self):
        self.crud._indices.extend(
            [
                pymongo.IndexModel(
                    [("space_id", 1), ("cn", 1)], sparse=True, name="idx_sparse"
                ),
                pymongo.IndexModel(
                    [("space_id", 1), ("not_after", 1)],
                    partialFilterExpression={"status": "signed"},
                    name="idx_partial",
                ),
                pymongo.IndexModel(
                    [("space_id", 1), ("text", "text")], name="idx_text"
                ),
            ]
        )
        self.assertIsNone(self._index_name({"space_id": "s"}, "cn"))
        self.assertIsNone(self._index_name({"space_id": "s"}, "not_after"))
        self.assertIsNone(self._index_name({"space_id": "s"}, "text"))

    def test_sort_index_accepts_trailing_tiebreaker(self):
        self.crud._indices.append(
            pymongo.IndexModel(
                [("node_id", 1), ("created", -1), ("id", 1)], name="idx_node_created"
            )
        )
        self.assertEqual(
            self._index_name({"node_id": "n"}, "created"), "idx_node_created"
        )
        self.assertIsNone(self._index_name({"node_id": "n"}, "id"))

    def test_sort_spec_adds_tiebreaker_without_index(self):
        self.assertEqual(
            self.crud._sort_spec("cn", "descending", None),
            [("cn", pymongo.DESCENDING), ("id", pymongo.DESCENDING)],
        )
        self.assertEqual(
            self.crud._sort_spec("id", "ascending", None),
            [("id", pymongo.ASCENDING)],
        )

    def test_sort_spec_without_tiebreaker(self):
        self.crud._sort_tiebreaker = None
        self.assertEqual(
            self.crud._sort_spec("cn", "ascending", None),
            [("cn", pymongo.ASCENDING)],
        )

    def test_sort_spec_follows_index(self):
        plain = pymongo.IndexModel([("space_id", 1), ("cn", 1)], name="a").document
        self.assertEqual(
            self.crud._sort_spec("cn", "ascending", plain),
            [("cn", pymongo.ASCENDING)],
        )
        mixed = pymongo.IndexModel(
            [("node_id", 1), ("created", -1), ("id", 1)], name="b"
        ).document
        self.assertEqual(
            self.crud._sort_spec("created", "ascending", mixed),
            [("created", pymongo.ASCENDING), ("id", pymongo.DESCENDING)],
        )
        self.assertEqual(
            self.crud._sort_spec("created", "descending", mixed),
            [("created", pymongo.DESCENDING), ("id", pymongo.ASCENDING)],
        )

    async def test_search_without_index_sorts_with_tiebreaker(self):
        self.mock_coll.count_documents = AsyncMock(return_value=0)
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[])
        self.mock_coll.find.return_value = mock_cursor

        await self.crud._search(
            {"status": "signed"}, sort="created", sort_order="ascending", limit=10
        )

        mock_cursor.sort.assert_called_once_with(
            [("created", pymongo.ASCENDING), ("id", pymongo.ASCENDING)]
        )
        mock_cursor.hint.assert_not_called()

    async def test_search_from_end_takes_the_search_signature(self):
        mock_cursor = self._scoped_search_setup(100000, [{"id": "b"}, {"id": "a"}])

        result = await self.crud._search_from_end(
            query={"space_id": "s"},
            fields=["id"],
            sort="id",
            sort_order="ascending",
            page=9000,
            limit=10,
            count=None,
        )

        self.assertEqual(
            result,
            {
                "result": [{"id": "a"}, {"id": "b"}],
                "meta": {"result_size": 100000},
            },
        )
        mock_cursor.sort.assert_called_once_with([("id", pymongo.DESCENDING)])
        mock_cursor.skip.assert_called_once_with(9990)
        self.mock_coll.find.assert_called_once_with(
            filter={"space_id": "s"}, projection={"id": 1}
        )

    async def test_search_from_end_without_index_counts_and_reads_forward(self):
        self.mock_coll.count_documents = AsyncMock(return_value=100000)
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[])
        self.mock_coll.find.return_value = mock_cursor

        result = await self.crud._search_from_end(
            {"space_id": "s"}, sort="cn", sort_order="ascending", page=9000, limit=10
        )

        self.assertEqual(result["meta"]["result_size"], 100000)
        mock_cursor.sort.assert_called_once_with(
            [("cn", pymongo.ASCENDING), ("id", pymongo.ASCENDING)]
        )
        mock_cursor.skip.assert_called_once_with(90000)
        mock_cursor.hint.assert_not_called()

    async def test_search_from_end_reads_forward_when_hint_fails(self):
        self.crud._indices.append(
            pymongo.IndexModel([("space_id", 1), ("cn", 1)], name="idx_space_cn")
        )
        self.mock_coll.count_documents = AsyncMock(return_value=100000)
        hinted = MagicMock()
        hinted.to_list = AsyncMock(
            side_effect=pymongo.errors.OperationFailure("bad hint", code=2)
        )
        plain = MagicMock()
        plain.to_list = AsyncMock(return_value=[{"id": "a"}, {"id": "b"}])
        self.mock_coll.find.side_effect = [hinted, plain]

        result = await self.crud._search(
            {"space_id": "s"}, sort="cn", sort_order="ascending", page=9000, limit=10
        )

        self.assertEqual(result["result"], [{"id": "a"}, {"id": "b"}])
        hinted.sort.assert_called_once_with([("cn", pymongo.DESCENDING)])
        hinted.hint.assert_called_once_with("idx_space_cn")
        plain.sort.assert_called_once_with(
            [("cn", pymongo.ASCENDING), ("id", pymongo.ASCENDING)]
        )
        plain.skip.assert_called_once_with(90000)
        plain.limit.assert_called_once_with(10)
        plain.hint.assert_not_called()

    def test_sort_index_accepts_keys_after_sort(self):
        self.crud._indices.extend(
            [
                pymongo.IndexModel(
                    [("node_id", 1), ("id", 1), ("uuid", 1)], name="idx_long"
                ),
                pymongo.IndexModel([("node_id", 1), ("id", 1)], name="idx_short"),
            ]
        )
        self.assertEqual(self._index_name({"node_id": "n"}, "id"), "idx_short")
        self.crud._indices.pop()
        self.assertEqual(self._index_name({"node_id": "n"}, "id"), "idx_long")

    def test_sort_spec_ignores_tiebreaker_not_directly_after_sort(self):
        index = pymongo.IndexModel(
            [("node_id", 1), ("created", 1), ("uuid", 1), ("id", 1)], name="a"
        ).document
        self.assertEqual(
            self.crud._sort_spec("created", "ascending", index),
            [("created", pymongo.ASCENDING)],
        )

    def _existing_indexes(self, *indexes):
        self.mock_coll.list_indexes.return_value.to_list = AsyncMock(
            return_value=[{"name": name, "key": key} for name, key in indexes]
        )
        self.mock_coll.drop_index = AsyncMock()
        self.mock_coll.full_name = "db.test_coll"

    def _shard_key(self, key):
        config_coll = MagicMock()
        config_coll.find_one = AsyncMock(return_value={"key": key} if key else None)
        client = MagicMock()
        client.__getitem__.return_value.__getitem__.return_value = config_coll
        self.mock_coll.database.client = client
        return config_coll

    async def test_drop_undeclared_indexes(self):
        self.crud._indices.append(pymongo.IndexModel([("a", 1)], name="idx_a"))
        self._existing_indexes(
            ("_id_", {"_id": 1}),
            ("idx_a", {"a": 1}),
            ("idx_version_common", {"_version": 1}),
            ("idx_old", {"old": 1}),
            ("ttl_created", {"created": 1}),
        )
        existing = self.mock_coll.list_indexes.return_value.to_list.return_value
        existing[-1]["expireAfterSeconds"] = 60
        self._shard_key(None)
        self.crud._indices.append(
            pymongo.IndexModel(
                [("created", 1)], expireAfterSeconds=60, name="ttl_created"
            )
        )
        self.mock_coll.create_indexes = AsyncMock()

        await self.crud._create_index()
        await self.crud._drop_undeclared_indexes()

        self.assertEqual(
            sorted(call.args[0] for call in self.mock_coll.drop_index.await_args_list),
            ["idx_old", "idx_version_common"],
        )

    async def test_drop_undeclared_indexes_keeps_shard_key_index(self):
        self._existing_indexes(
            ("_id_", {"_id": 1}),
            ("placement_1_node_id_1", {"placement": 1, "node_id": 1}),
            ("idx_old", {"placement": 1}),
        )
        config_coll = self._shard_key({"placement": 1, "node_id": 1})

        await self.crud._drop_undeclared_indexes()

        self.mock_coll.drop_index.assert_awaited_once_with("idx_old")
        config_coll.find_one.assert_awaited_once_with(
            {"_id": "db.test_coll"}, projection={"key": 1}
        )

    async def test_drop_undeclared_indexes_survives_failures(self):
        self._existing_indexes(("a", {"a": 1}), ("b", {"b": 1}))
        config_coll = self._shard_key(None)
        config_coll.find_one.side_effect = pymongo.errors.OperationFailure("denied")
        self.mock_coll.drop_index.side_effect = [
            pymongo.errors.OperationFailure("nope"),
            None,
        ]

        await self.crud._drop_undeclared_indexes()

        self.assertEqual(self.mock_coll.drop_index.await_count, 2)

    async def test_init_drops_undeclared_indexes_after_sync(self):
        calls = []
        self.crud._setup_schema_validation = AsyncMock()
        self.crud._migrate = AsyncMock()
        self.crud._create_index = AsyncMock(side_effect=lambda: calls.append("sync"))
        self.crud._drop_undeclared_indexes = AsyncMock(
            side_effect=lambda: calls.append("drop")
        )

        await self.crud.init()

        self.assertEqual(calls, ["sync", "drop"])

    async def test_update_success(self):
        self.mock_coll.find_one_and_update = AsyncMock(
            return_value={"_id": "obj1", "id": "r1", "val": "new"}
        )
        result = await self.crud._update({"id": "r1"}, {"val": "new"}, fields=[])
        self.assertEqual(result["val"], "new")

    async def test_update_upsert_without_fetch(self):
        self.mock_coll.update_one = AsyncMock()
        result = await self.crud._update(
            {"id": "r1"}, {"val": "new"}, fields=[], upsert=True, fetch=False
        )
        self.assertEqual(result, {})
        self.mock_coll.update_one.assert_called_once_with(
            filter={"id": "r1"},
            update={"$set": {"val": "new"}, "$setOnInsert": {"_version": 0}},
            upsert=True,
        )

    async def test_update_not_found(self):
        self.mock_coll.find_one_and_update = AsyncMock(return_value=None)
        with self.assertRaises(ResourceNotFound):
            await self.crud._update({"id": "r1"}, {"val": "new"}, fields=[])


class _Transaction:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        self._session.transactions += 1

    async def __aexit__(self, *exc):
        return False


class _Session:
    def __init__(self):
        self.transactions = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def start_transaction(self):
        return _Transaction(self)


class _Migrating(CrudMongo):
    schema_version = 4

    def __init__(self, config, log, coll):
        super().__init__(config, log, coll)
        self._migrations = {3: self.migrate_3, 4: self.migrate_4}

    async def migrate_3(self, session=None):
        return None

    async def migrate_4(self, session=None):
        return None


class TestCrudMongoMigrate(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.coll = MagicMock()
        self.coll.name = "things"
        self.coll.find_one = AsyncMock(return_value={"_id": "x"})
        self.coll.update_many = AsyncMock()
        self.session = _Session()
        self.coll.database.client.start_session = AsyncMock(return_value=self.session)
        self.calls = []

    def _migration(self, name, error=None):
        async def migration(session=None):
            self.calls.append((name, session))
            if error is not None and session is not None:
                raise error

        migration.__name__ = name
        return migration

    async def _run(self, schema_version, migrations):
        crud = CrudMongo(MagicMock(), self.log, self.coll)
        crud.schema_version = schema_version
        crud._migrations = migrations
        await crud._migrate()

    def _stamps(self):
        return [
            (call.args[0], call.args[1], call.kwargs["session"])
            for call in self.coll.update_many.await_args_list
        ]

    async def test_runs_pending_migrations_in_version_order_and_stamps_them(self):
        migrations = {3: self._migration("migrate_3"), 2: self._migration("migrate_2")}

        await self._run(3, migrations)

        self.assertEqual(
            self.calls, [("migrate_2", self.session), ("migrate_3", self.session)]
        )
        self.assertEqual(self.session.transactions, 2)
        self.assertEqual(
            self._stamps(),
            [
                ({"_version": 1}, {"$set": {"_version": 2}}, self.session),
                ({"_version": 2}, {"$set": {"_version": 3}}, self.session),
            ],
        )

    async def test_skips_versions_without_older_documents(self):
        self.coll.find_one = AsyncMock(side_effect=[None, {"_id": "x"}])
        migrations = {2: self._migration("migrate_2"), 3: self._migration("migrate_3")}

        await self._run(3, migrations)

        self.assertEqual([name for name, _ in self.calls], ["migrate_3"])
        self.assertEqual(
            [call.args[0] for call in self.coll.find_one.await_args_list],
            [{"_version": 1}, {"_version": 2}],
        )

    async def test_without_migrations_nothing_is_read(self):
        await self._run(0, {})

        self.coll.find_one.assert_not_awaited()
        self.coll.update_many.assert_not_awaited()

    async def test_migrations_must_run_without_gaps_up_to_the_schema_version(self):
        for schema_version, versions in (
            (3, [2, 5]),
            (4, [2, 4]),
            (3, [2]),
            (1, [0, 1]),
        ):
            migrations = {v: self._migration(f"migrate_{v}") for v in versions}
            with self.assertRaises(ValueError, msg=f"{schema_version} {versions}"):
                await self._run(schema_version, migrations)
        self.assertEqual(self.calls, [])

    async def test_deleted_old_migrations_are_allowed(self):
        migrations = {3: self._migration("migrate_3")}

        await self._run(3, migrations)

        self.assertEqual(self._stamps(), [({"_version": 2}, {"$set": {"_version": 3}}, self.session)])

    async def test_first_migration_lifts_unversioned_documents(self):
        migrations = {1: self._migration("migrate_1")}

        await self._run(1, migrations)

        self.assertEqual(
            self.coll.find_one.await_args.args[0], {"_version": {"$in": [0, None]}}
        )
        self.assertEqual(
            self._stamps(),
            [({"_version": {"$in": [0, None]}}, {"$set": {"_version": 1}}, self.session)],
        )

    async def test_failing_migration_runs_once_and_is_not_stamped(self):
        error = pymongo.errors.OperationFailure("boom", code=11000)
        migrations = {2: self._migration("migrate_2", error=error)}

        with self.assertRaises(pymongo.errors.OperationFailure):
            await self._run(2, migrations)

        self.assertEqual(self.calls, [("migrate_2", self.session)])
        self.coll.update_many.assert_not_awaited()


class TestCrudMongoSchemaVersion(unittest.IsolatedAsyncioTestCase):
    def _crud(self, cls):
        coll = MagicMock()
        coll.name = "things"
        coll.insert_one = AsyncMock(return_value=MagicMock(inserted_id="obj1"))
        coll.find_one_and_update = AsyncMock(return_value={"id": "a"})
        return cls(MagicMock(), logging.getLogger("test"), coll), coll

    async def test_unversioned_crud_stamps_version_zero_and_has_no_index(self):
        crud, coll = self._crud(CrudMongo)

        await crud._create(payload={"id": "a"}, fields=["id"], fetch=False)
        await crud._update({"id": "a"}, {"x": 1}, fields=["id"], upsert=True)

        self.assertEqual(coll.insert_one.await_args.args[0], {"id": "a", "_version": 0})
        self.assertEqual(
            coll.find_one_and_update.await_args.kwargs["update"]["$setOnInsert"],
            {"_version": 0},
        )
        self.assertEqual(crud._indices, [])

    async def test_bulk_and_upsert_helpers_stamp_the_version(self):
        crud, coll = self._crud(_Migrating)
        coll.insert_many = AsyncMock()
        coll.find_one_and_update = AsyncMock(return_value={"id": "a"})

        await crud._insert_many([{"id": "a"}, {"id": "b"}], ordered=False)
        await crud._update(
            {"id": "a"},
            {"x": 1},
            fields=[],
            upsert=True,
            set_on_insert={"since": 1},
            fetch=False,
        )

        coll.insert_many.assert_awaited_once_with(
            [{"id": "a", "_version": 4}, {"id": "b", "_version": 4}], ordered=False
        )
        coll.find_one_and_update.assert_awaited_once_with(
            filter={"id": "a"},
            update={"$set": {"x": 1}, "$setOnInsert": {"since": 1, "_version": 4}},
            projection={},
            return_document=1,
            upsert=True,
        )

    async def test_versioned_crud_stamps_created_documents(self):
        crud, coll = self._crud(_Migrating)

        await crud._create(payload={"id": "a"}, fields=["id"], fetch=False)

        self.assertEqual(coll.insert_one.await_args.args[0], {"id": "a", "_version": 4})
        self.assertEqual(
            [index.document for index in crud._indices],
            [{"key": {"_version": 1}, "name": "idx_schema_version"}],
        )

    async def test_versioned_crud_stamps_only_the_insert_of_an_upsert(self):
        crud, coll = self._crud(_Migrating)
        set_on_insert = {"created": "now"}

        await crud._update(
            {"id": "a"},
            {"x": 1},
            fields=["id"],
            upsert=True,
            set_on_insert=set_on_insert,
        )
        upserted = coll.find_one_and_update.await_args.kwargs["update"]
        await crud._update({"id": "a"}, {"x": 2}, fields=["id"])
        updated = coll.find_one_and_update.await_args.kwargs["update"]

        self.assertEqual(upserted["$setOnInsert"], {"created": "now", "_version": 4})
        self.assertEqual(upserted["$set"], {"x": 1})
        self.assertEqual(set_on_insert, {"created": "now"})
        self.assertNotIn("$setOnInsert", updated)

    async def test_migrate_hands_the_numbered_methods_to_the_migrator(self):
        crud, coll = self._crud(_Migrating)
        coll.find_one = AsyncMock(return_value=None)

        await crud._migrate()

        self.assertEqual(
            [call.args[0] for call in coll.find_one.await_args_list],
            [{"_version": 2}, {"_version": 3}],
        )
