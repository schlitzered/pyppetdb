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
from pyppetdb.crud.nodes import CrudNodes
from pyppetdb.crud.nodes import NodePutInternal


class TestCrudNodesUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_coll = MagicMock()
        self.mock_config = MagicMock()
        # Setup basic config structure if needed
        self.mock_config.app.main.facts.index = []
        self.crud = CrudNodes(self.log, self.mock_config, self.mock_coll)

    async def test_delete(self):
        self.crud._delete = AsyncMock()
        await self.crud.delete(_id="node1")
        self.crud._delete.assert_called_once_with(query={"id": "node1"})

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

    async def test_resource_exists(self):
        self.crud._resource_exists = AsyncMock(return_value=MagicMock())
        await self.crud.resource_exists(_id="node1", user_node_groups=["g1"])
        self.crud._resource_exists.assert_called_once()

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
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(
            return_value=[
                {
                    "results": [
                        {
                            "type": "File",
                            "title": "/tmp/test",
                            "tags": [],
                            "exported": True,
                            "parameters": {},
                        }
                    ]
                }
            ]
        )
        self.mock_coll.aggregate.return_value = mock_cursor

        result = await self.crud.exported_resources(resource_type="File")

        self.assertEqual(len(result.result), 1)
        self.assertEqual(result.result[0].type, "File")

    def test_translate_resource_query_basic(self):
        ast = ["and", ["=", "type", "File"], ["=", "exported", True]]
        expected = {"catalog.resources_exported.type": "File"}
        self.assertEqual(self.crud.translate_resource_query(ast), expected)

    def test_translate_resource_query_no_exported(self):
        # Now it should NOT return None, but translate the query as is
        ast = ["=", "type", "File"]
        expected = {"catalog.resources_exported.type": "File"}
        self.assertEqual(self.crud.translate_resource_query(ast), expected)

    def test_translate_resource_query_complex(self):
        ast = [
            "and",
            ["=", "type", "File"],
            ["=", "exported", True],
            ["not", ["=", "certname", "node1"]],
            ["=", ["parameter", "owner"], "root"],
            ["=", "fact_pyppetdb__role", "web"],
            ["~", "tag", "shared"],
            [">", "fact_os__release__major", "7"],
            ["null?", "fact_old", True],
        ]
        result = self.crud.translate_resource_query(ast)
        # Order might change due to how cleanup handles single-element $and
        self.assertEqual(result["$and"][0], {"catalog.resources_exported.type": "File"})
        self.assertEqual(result["$and"][1], {"id": {"$ne": "node1"}})
        self.assertEqual(
            result["$and"][2], {"catalog.resources_exported.parameters.owner": "root"}
        )
        self.assertEqual(result["$and"][3], {"facts.pyppetdb.role": "web"})
        self.assertEqual(
            result["$and"][4], {"catalog.resources_exported.tags": {"$regex": "shared"}}
        )
        self.assertEqual(result["$and"][5], {"facts.os.release.major": {"$gt": "7"}})
        self.assertEqual(result["$and"][6], {"facts.old": {"$type": 10}})

    def test_translate_resource_query_in_array(self):
        ast = [
            "and",
            ["=", "exported", True],
            ["in", "certname", ["array", ["n1", "n2"]]],
        ]
        result = self.crud.translate_resource_query(ast)
        self.assertEqual(result, {"id": {"$in": ["n1", "n2"]}})

    def test_translate_resource_query_tag(self):
        ast = ["=", "tag", "foo"]
        expected = {"catalog.resources_exported.tags": "foo"}
        self.assertEqual(self.crud.translate_resource_query(ast), expected)
