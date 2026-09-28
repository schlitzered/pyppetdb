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
from datetime import datetime
import logging
from pyppetdb.config import ConfigAppFacts
from pyppetdb.crud.nodes import CrudNodes
from pyppetdb.crud.nodes import NodePutInternal


class TestCrudNodesUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_coll = MagicMock()
        self.mock_config = MagicMock()
        # Setup basic config structure if needed
        self.mock_config.app.main.facts = ConfigAppFacts()
        self.crud = CrudNodes(self.log, self.mock_config, self.mock_coll)

    async def test_delete(self):
        self.crud._delete = AsyncMock()
        await self.crud.delete(_id="node1")
        self.crud._delete.assert_called_once_with(query={"id": "node1"})

    async def test_update_catalog_metadata_sets_dotted_fields(self):
        self.mock_coll.update_one = AsyncMock()
        await self.crud.update_catalog_metadata(
            _id="node1",
            metadata={"version": "2-1", "catalog_uuid": "uuid1"},
        )
        self.mock_coll.update_one.assert_called_once_with(
            filter={"id": "node1"},
            update={
                "$set": {
                    "catalog.version": "2-1",
                    "catalog.catalog_uuid": "uuid1",
                }
            },
        )

    async def test_update_catalog_metadata_ignores_empty_metadata(self):
        self.mock_coll.update_one = AsyncMock()
        await self.crud.update_catalog_metadata(_id="node1", metadata={})
        self.mock_coll.update_one.assert_not_called()

    def _aggregate_returning(self, rows):
        cursor = MagicMock()
        cursor.to_list = AsyncMock(return_value=rows)
        self.mock_coll.aggregate = MagicMock(return_value=cursor)

    async def test_get_ingest_state_reports_facts_catalog_and_uuid(self):
        self._aggregate_returning(
            [{"has_facts": True, "has_catalog": True, "catalog_uuid": "abc", "content_hash": "h"}]
        )
        state = await self.crud.get_ingest_state(_id="node1")
        self.assertEqual(
            state,
            {
                "has_facts": True,
                "has_catalog": True,
                "catalog_uuid": "abc",
                "content_hash": "h",
                "disabled": False,
                "environment": None,
                "placement": None,
            },
        )
        pipeline = self.mock_coll.aggregate.call_args.args[0]
        self.assertEqual(pipeline[0], {"$match": {"id": "node1"}})
        self.assertEqual(pipeline[1], {"$limit": 1})
        self.assertEqual(
            pipeline[2]["$project"]["has_facts"],
            {"$eq": [{"$type": "$facts"}, "object"]},
        )

    async def test_get_ingest_state_without_catalog_has_no_uuid(self):
        self._aggregate_returning([{"has_facts": True, "has_catalog": False}])
        state = await self.crud.get_ingest_state(_id="node1")
        self.assertEqual(
            state,
            {
                "has_facts": True,
                "has_catalog": False,
                "catalog_uuid": None,
                "content_hash": None,
                "disabled": False,
                "environment": None,
                "placement": None,
            },
        )

    async def test_get_ingest_state_for_unknown_node_is_none(self):
        self._aggregate_returning([])
        self.assertIsNone(await self.crud.get_ingest_state(_id="missing"))

    async def test_delete_node_group_from_all(self):
        self.mock_coll.update_many = AsyncMock()
        await self.crud.delete_node_group_from_all(node_group_id="group1")
        self.mock_coll.update_many.assert_called_once()
        call_args = self.mock_coll.update_many.call_args[1]
        self.assertEqual(call_args["filter"], {"node_groups": "group1"})
        self.assertEqual(call_args["update"], {"$pull": {"node_groups": "group1"}})

    async def test_get(self):
        self.crud._get = AsyncMock(return_value={"id": "node1"})
        await self.crud.get(_id="node1", fields=[], user_node_groups=["g1"])
        self.crud._get.assert_called_once()
        query = self.crud._get.call_args[1]["query"]
        self.assertEqual(query["id"], "node1")
        self.assertEqual(query["node_groups"], {"$in": ["g1"]})

    async def test_get_fetches_report_status_sources_and_strips_them(self):
        self.crud._get = AsyncMock(
            return_value={
                "id": "node1",
                "disabled": False,
                "change_report": datetime.now(),
                "report": {"status": "changed"},
            }
        )
        node = await self.crud.get(_id="node1", fields=["id"])
        fetched_fields = self.crud._get.call_args[1]["fields"]
        self.assertIn("report.status", fetched_fields)
        self.assertIn("disabled", fetched_fields)
        self.assertIn("change_report", fetched_fields)
        self.assertEqual(node.report_status_computed, "changed")
        self.assertIsNone(node.report)
        self.assertIsNone(node.disabled)
        self.assertIsNone(node.change_report)

    async def test_get_keeps_requested_report_status_sources(self):
        change_report = datetime.now()
        self.crud._get = AsyncMock(
            return_value={
                "id": "node1",
                "disabled": False,
                "change_report": change_report,
                "report": {"status": "unchanged", "noop": True},
            }
        )
        node = await self.crud.get(
            _id="node1", fields=["id", "disabled", "report.noop"]
        )
        self.assertEqual(node.report_status_computed, "unchanged")
        self.assertFalse(node.disabled)
        self.assertIsNone(node.change_report)
        self.assertTrue(node.report.noop)
        self.assertIsNone(node.report.status)

    async def test_get_without_fields_keeps_everything(self):
        change_report = datetime.now()
        self.crud._get = AsyncMock(
            return_value={
                "id": "node1",
                "disabled": False,
                "change_report": change_report,
                "report": {"status": "failed"},
            }
        )
        node = await self.crud.get(_id="node1", fields=[])
        self.assertEqual(self.crud._get.call_args[1]["fields"], [])
        self.assertEqual(node.report_status_computed, "failed")
        self.assertFalse(node.disabled)
        self.assertEqual(node.change_report, change_report)
        self.assertEqual(node.report.status, "failed")

    async def test_resource_exists(self):
        self.crud._resource_exists = AsyncMock(return_value=MagicMock())
        await self.crud.resource_exists(_id="node1", user_node_groups=["g1"])
        self.crud._resource_exists.assert_called_once()
        query = self.crud._resource_exists.call_args[1]["query"]
        self.assertEqual(query["id"], "node1")
        self.assertEqual(query["node_groups"], {"$in": ["g1"]})

    async def test_search_scopes_by_node_groups(self):
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(
            return_value=[
                {
                    "meta_counts": [],
                    "total_results": [{"count": 0}],
                    "paginated_results": [],
                }
            ]
        )
        self.mock_coll.aggregate.return_value = mock_cursor

        await self.crud.search(user_node_groups=["g1"])

        pipeline = self.mock_coll.aggregate.call_args[0][0]
        scoped = any(
            "$match" in stage
            and stage["$match"].get("node_groups") == {"$in": ["g1"]}
            for stage in pipeline
        )
        self.assertTrue(scoped)

    async def test_count_scopes_by_node_groups(self):
        self.mock_coll.count_documents = AsyncMock(return_value=0)

        await self.crud.count(user_node_groups=["g1"])

        query = self.mock_coll.count_documents.call_args[0][0]
        self.assertEqual(query["node_groups"], {"$in": ["g1"]})

    async def test_search(self):
        # Mock aggregation for status counts and results
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(
            return_value=[
                {
                    "meta_counts": [
                        {"_id": "changed", "count": 5},
                        {"_id": "unchanged", "count": 10},
                        {"_id": "outdated", "count": 2},
                    ],
                    "total_results": [{"count": 1}],
                    "paginated_results": [{"id": "node1"}],
                }
            ]
        )
        self.mock_coll.aggregate.return_value = mock_cursor

        result = await self.crud.search(_id="node1", disabled=False)

        self.assertEqual(result.meta.result_size, 1)
        self.assertEqual(result.meta.status_changed, 5)
        self.assertEqual(result.meta.status_unchanged, 10)
        self.assertEqual(result.meta.status_outdated, 2)

    async def test_search_with_threshold(self):
        # Mock aggregation for status counts and results
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(
            return_value=[
                {
                    "meta_counts": [],
                    "total_results": [{"count": 0}],
                    "paginated_results": [],
                }
            ]
        )
        self.mock_coll.aggregate.return_value = mock_cursor

        await self.crud.search(outdated_threshold="2026-03-06T00:00:00Z")
        self.mock_coll.aggregate.assert_called_once()

    async def test_search_by_computed_status(self):
        # Mock aggregation for status counts and results
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(
            return_value=[
                {
                    "meta_counts": [{"_id": "outdated", "count": 1}],
                    "total_results": [{"count": 1}],
                    "paginated_results": [
                        {"id": "node1", "report_status_computed": "outdated"}
                    ],
                }
            ]
        )
        self.mock_coll.aggregate.return_value = mock_cursor

        result = await self.crud.search(report_status="outdated")

        self.assertEqual(result.meta.result_size, 1)
        self.assertEqual(result.meta.status_outdated, 1)
        self.assertEqual(result.result[0].report_status_computed, "outdated")

        # Verify that aggregate was called with the correct pipeline
        call_args = self.mock_coll.aggregate.call_args[0][0]
        # Check if $match for report_status_computed is in the pipeline
        has_match = any(
            "$match" in stage
            and stage["$match"].get("report_status_computed") == {"$regex": "outdated"}
            for stage in call_args
        )
        self.assertTrue(has_match)

    async def test_update(self):
        self.crud.get_placement = AsyncMock(return_value={})
        self.crud._update = AsyncMock(return_value={"id": "node1"})
        payload = NodePutInternal(disabled=True)
        await self.crud.update(
            _id="node1",
            payload=payload,
            fields=[],
        )
        self.crud._update.assert_called_once()

    async def test_facts_write_carries_a_facts_index(self):
        self.crud._update = AsyncMock(return_value={"id": "node1"})
        await self.crud.update(
            _id="node1",
            payload=NodePutInternal(facts={"osfamily": "Debian", "os": {"a": 1}}),
            fields=[],
            return_none=True,
        )
        payload = self.crud._update.call_args.kwargs["payload"]
        self.assertEqual(
            payload["facts_index"],
            [
                {"p": "osfamily", "v": "Debian"},
                {"p": "os"},
                {"p": "os.a", "v": 1},
            ],
        )

    async def test_facts_index_honours_the_configured_limits(self):
        self.crud._config.app.main.facts = ConfigAppFacts(
            indexDepth=2, indexMaxValueLen=3, indexDeny=["secret"]
        )
        self.crud._update = AsyncMock(return_value={"id": "node1"})
        await self.crud.update(
            _id="node1",
            payload=NodePutInternal(
                facts={"os": {"a": "long value"}, "secret": "s", "x": "ab"}
            ),
            fields=[],
            return_none=True,
        )
        payload = self.crud._update.call_args.kwargs["payload"]
        self.assertEqual(
            [entry for entry in payload["facts_index"] if "v" in entry],
            [{"p": "x", "v": "ab"}],
        )

    async def test_facts_write_carries_the_fact_paths(self):
        self.crud._update = AsyncMock(return_value={"id": "node1"})
        await self.crud.update(
            _id="node1",
            payload=NodePutInternal(facts={"os": {"family": "Debian"}, "cpus": [4]}),
            fields=[],
            return_none=True,
        )
        payload = self.crud._update.call_args.kwargs["payload"]
        self.assertEqual(
            payload["fact_paths"],
            ['[["cpus",0],"integer"]', '[["os","family"],"string"]'],
        )

    async def test_a_write_without_facts_has_no_fact_paths(self):
        self.crud._update = AsyncMock(return_value={"id": "node1"})
        await self.crud.update(
            _id="node1",
            payload=NodePutInternal(disabled=True),
            fields=[],
            return_none=True,
        )
        payload = self.crud._update.call_args.kwargs["payload"]
        self.assertIsNone(payload["fact_paths"])

    def test_fact_paths_are_indexed(self):
        model = next(
            index
            for index in self.crud._indices
            if index.document["name"] == "idx_fact_paths"
        )
        self.assertEqual(list(model.document["key"].items()), [("fact_paths", 1)])

    async def test_distinct_fact_names_unscoped_uses_distinct(self):
        self.mock_coll.distinct = AsyncMock(
            return_value=[
                '[["os","release","major"],"string"]',
                '[["processors","models",0],"string"]',
                '[["processors","models",1],"string"]',
                '[["uptime"],"integer"]',
            ]
        )
        result = await self.crud.distinct_fact_names()
        self.mock_coll.distinct.assert_awaited_once_with("fact_paths")
        self.mock_coll.aggregate.assert_not_called()
        self.assertEqual(
            result.result, ["os.release.major", "processors.models", "uptime"]
        )
        self.assertEqual(result.meta.result_size, 3)

    async def test_distinct_fact_names_scoped_to_node_groups(self):
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(
            return_value=[{"_id": '[["kernel"],"string"]'}]
        )
        self.mock_coll.aggregate.return_value = mock_cursor
        self.mock_coll.distinct = AsyncMock()
        result = await self.crud.distinct_fact_names(
            user_node_groups=["g1"], environment="prod"
        )
        self.mock_coll.distinct.assert_not_called()
        pipeline = self.mock_coll.aggregate.call_args.args[0]
        self.assertEqual(
            pipeline,
            [
                {"$match": {"node_groups": {"$in": ["g1"]}, "environment": "prod"}},
                {"$group": {"_id": "$fact_paths"}},
                {"$unwind": "$_id"},
                {"$group": {"_id": "$_id"}},
            ],
        )
        self.assertEqual(result.result, ["kernel"])

    async def test_a_write_without_facts_has_no_facts_index(self):
        self.crud._update = AsyncMock(return_value={"id": "node1"})
        await self.crud.update(
            _id="node1",
            payload=NodePutInternal(disabled=True),
            fields=[],
            return_none=True,
        )
        payload = self.crud._update.call_args.kwargs["payload"]
        self.assertIsNone(payload["facts_index"])

    async def test_create_builds_the_facts_index(self):
        self.crud._create = AsyncMock(return_value={"id": "node1"})
        await self.crud.create(
            _id="node1",
            payload=NodePutInternal(facts={"osfamily": "Debian"}),
            fields=[],
        )
        payload = self.crud._create.call_args.kwargs["payload"]
        self.assertIn({"p": "osfamily", "v": "Debian"}, payload["facts_index"])

    def test_status_grouping_is_covered_by_an_index(self):
        model = next(
            index
            for index in self.crud._indices
            if index.document["name"] == "idx_disabled_report_status"
        )
        self.assertEqual(
            list(model.document["key"].items()), [("disabled", 1), ("report.status", 1)]
        )

    def test_disabled_index_covers_active_counts(self):
        model = next(
            index for index in self.crud._indices if index.document["name"] == "idx_disabled"
        )
        self.assertNotIn("partialFilterExpression", model.document)

    def test_facts_index_is_indexed(self):
        names = {index.document["name"] for index in self.crud._indices}
        self.assertIn("idx_facts_index", names)
        model = next(
            index
            for index in self.crud._indices
            if index.document["name"] == "idx_facts_index"
        )
        self.assertEqual(
            list(model.document["key"].items()),
            [("facts_index.p", 1), ("facts_index.v", 1)],
        )

    async def test_update_nodegroup(self):
        self.mock_coll.update_many = AsyncMock()
        await self.crud.update_nodegroup(node_group_id="g1", nodes=["node1", "node2"])
        # Should be called twice: once for $pull (remove others) and once for $addToSet (add these)
        self.assertEqual(self.mock_coll.update_many.call_count, 2)

    async def test_distinct_fact_values(self):
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(
            return_value=[{"_id": "RedHat", "count": 5}, {"_id": "Debian", "count": 3}]
        )
        self.mock_coll.aggregate.return_value = mock_cursor

        result = await self.crud.distinct_fact_values(fact_id="osfamily")

        self.assertEqual(len(result.result), 2)
        self.assertEqual(result.result[0].value, "RedHat")
        self.assertEqual(result.result[0].count, 5)

    async def test_distinct_fact_values_invalid_id(self):
        result = await self.crud.distinct_fact_values(fact_id="invalid.")
        self.assertEqual(len(result.result), 0)
        self.assertEqual(result.meta.result_size, 0)

        result = await self.crud.distinct_fact_values(fact_id="")
        self.assertEqual(len(result.result), 0)
        self.assertEqual(result.meta.result_size, 0)

    async def test_exported_resources(self):
        docs = [
            {
                "type": "File",
                "title": "/tmp/test",
                "tags": [],
                "exported": True,
                "parameters": {},
            }
        ]

        class _Cursor:
            def __aiter__(self):
                async def gen():
                    for doc in docs:
                        yield doc

                return gen()

        resources_coll = MagicMock()
        resources_coll.find = MagicMock(return_value=_Cursor())
        self.mock_coll.database = {"nodes_resources": resources_coll}

        result = await self.crud.exported_resources(resource_type="File")

        self.assertEqual(len(result.result), 1)
        self.assertEqual(result.result[0].type, "File")
        query = resources_coll.find.call_args.kwargs["filter"]
        self.assertEqual(query["exported"], True)
        self.assertEqual(query["type"], "File")
