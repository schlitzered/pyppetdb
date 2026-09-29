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

import json
import logging
import unittest
from unittest.mock import AsyncMock

import pymongo.errors
from datetime import UTC
from datetime import datetime

from pyppetdb.pdb.query.engine import NEVER_MATCH
from pyppetdb.pdb.query.engine import QueryEngine
from pyppetdb.pdb.query.engine import SUBQUERY_LIMIT
from pyppetdb.pdb.query.engine import build_prefilter
from pyppetdb.pdb.query.engine import build_prefilter_plan
from pyppetdb.pdb.query.paging import parse_paging
from pyppetdb.pdb.query.engine import expand_fact_contents
from pyppetdb.pdb.query.engine import expand_fact_paths
from pyppetdb.pdb.query import matcher
from pyppetdb.helpers.puppetdb import FactsIndexSpec
from pyppetdb.helpers.puppetdb import build_fact_paths
from pyppetdb.helpers.puppetdb import build_facts_index
from pyppetdb.pdb.query.entities import ENTITIES
from pyppetdb.pdb.query.entities import get_entity
from pyppetdb.pdb.query.errors import PuppetDBQueryError
from pyppetdb.pdb.query.paging import Paging
from pyppetdb.pdb.query.ast import FilterCompiler
from pyppetdb.pdb.query.ast import Query


class FakeCursor:
    def __init__(self, docs):
        self._docs = docs

    def max_time_ms(self, _value):
        return self

    def sort(self, key, direction):
        self.sorted_by = (key, direction)
        self._docs = sorted(
            self._docs, key=lambda doc: doc.get(key), reverse=direction < 0
        )
        return self

    def allow_disk_use(self, _value):
        return self

    def __aiter__(self):
        async def generate():
            for doc in self._docs:
                yield doc

        return generate()

    async def to_list(self, length=None):
        if length is None:
            batch, self._docs = list(self._docs), []
        else:
            batch, self._docs = list(self._docs[:length]), list(self._docs[length:])
        return batch

    async def close(self):
        self.closed = True


class FakeCollection:
    name = "fake"

    def __init__(self, docs=None, counts=None, distinct_values=None, indexes=None):
        self.docs = docs or []
        self.indexes = indexes or []
        self.counts = counts
        self.distinct_values = distinct_values or []
        self.pipelines = []
        self.options = []
        self.finds = []
        self.distincts = []

    async def distinct(self, key, filter=None, **options):
        self.distincts.append((key, filter))
        if not self.distinct_values and key == "fact_paths":
            return sorted(
                {
                    entry
                    for doc in self.docs
                    for entry in build_fact_paths(doc.get("facts"))
                }
            )
        return list(self.distinct_values)

    async def count_documents(self, filter=None, **options):
        if not hasattr(self, "counts_calls"):
            self.counts_calls = []
        self.counts_calls.append((filter, options))
        return self.counts if self.counts is not None else len(self.docs)

    def aggregate(self, pipeline, **options):
        self.pipelines.append(pipeline)
        self.options.append(options)
        if pipeline and pipeline[-1] == {"$count": "count"}:
            return FakeCursor([{"count": self.counts}] if self.counts else [])
        return FakeCursor(self.docs)

    async def list_indexes(self):
        for index in self.indexes:
            yield index

    def find(self, query=None, projection=None):
        self.finds.append((query, projection))
        self.cursor = FakeCursor(list(self.docs))
        return self.cursor


def stage(pipeline, name):
    for item in pipeline:
        if name in item:
            return item[name]
    return None


def stages(pipeline, name):
    return [item[name] for item in pipeline if name in item]


def engine_with(
    nodes=None,
    reports=None,
    resources=None,
    edges=None,
    events=None,
    facts_index=None,
):
    return QueryEngine(
        log=logging.getLogger("test"),
        collections={
            "nodes": nodes or FakeCollection(),
            "nodes_reports": reports or FakeCollection(),
            "nodes_resources": resources or FakeCollection(),
            "nodes_edges": edges or FakeCollection(),
            "nodes_events": events or FakeCollection(),
        },
        facts_index=facts_index,
    )


TWO_COLUMN_IN = [
    "in",
    ["certname", "environment"],
    [
        "extract",
        ["certname", "environment"],
        ["select_facts", ["=", "name", "kernel"]],
    ],
]


class TestQueryEngineMongo(unittest.IsolatedAsyncioTestCase):
    async def test_projects_puppetdb_columns(self):
        nodes = FakeCollection(docs=[{"certname": "a"}])
        engine = engine_with(nodes)
        rows, total = await engine.run("nodes", ["=", "certname", "a"])
        self.assertEqual([row["certname"] for row in rows], ["a"])
        self.assertEqual(total, 1)
        projection = stage(nodes.pipelines[0], "$project")
        self.assertEqual(projection["certname"], "$id")
        self.assertIn("latest_report_status", projection)

    async def test_missing_columns_are_emitted_as_null(self):
        engine = engine_with(FakeCollection(docs=[{"certname": "a"}]))
        rows, _total = await engine.run(
            "nodes", ["extract", ["certname"], ["=", "certname", "a"]]
        )
        self.assertEqual(rows, [{"certname": "a"}])

    async def test_match_stage_follows_projection(self):
        nodes = FakeCollection()
        engine = engine_with(nodes)
        await engine.run("nodes", ["=", "certname", "a"])
        pipeline = nodes.pipelines[0]
        project_at = next(i for i, s in enumerate(pipeline) if "$project" in s)
        match_at = next(
            i
            for i, s in enumerate(pipeline)
            if s.get("$match") == {"certname": "a"}
        )
        self.assertGreater(match_at, project_at)

    async def test_prefilter_precedes_the_projection(self):
        res = FakeCollection()
        engine = engine_with(resources=res)
        await engine.run("resources", ["=", "type", "File"])
        pipeline = res.pipelines[0]
        self.assertEqual(pipeline[0], {"$match": {"type": "File"}})
        project_at = next(i for i, s in enumerate(pipeline) if "$project" in s)
        self.assertLess(0, project_at)

    async def test_no_prefilter_when_nothing_is_derivable(self):
        res = FakeCollection()
        engine = engine_with(resources=res)
        await engine.run("resources", ["not", ["=", "type", "File"]])
        self.assertIn("$project", res.pipelines[0][0])

    async def test_empty_subquery_becomes_impossible_filter(self):
        nodes = FakeCollection()
        engine = engine_with(nodes)
        await engine.run(
            "nodes",
            [
                "and",
                ["=", "certname", "a"],
                ["in", "certname", ["extract", "certname", ["select_facts", None]]],
            ],
        )
        self.assertIn(
            {"$and": [{"certname": "a"}, NEVER_MATCH]},
            stages(nodes.pipelines[-1], "$match"),
        )

    async def test_top_level_never_skips_the_collection(self):
        nodes = FakeCollection(docs=[{"certname": "a"}])
        engine = engine_with(nodes, reports=FakeCollection())
        rows, total = await engine.run(
            "nodes",
            ["in", "certname", ["extract", "certname", ["select_reports", None]]],
        )
        self.assertEqual(rows, [])
        self.assertEqual(total, 0)
        self.assertEqual(nodes.pipelines, [])

    async def test_nested_never_keeps_the_sibling_branch(self):
        nodes = FakeCollection(docs=[{"certname": "a"}])
        engine = engine_with(nodes, reports=FakeCollection())
        rows, _total = await engine.run(
            "nodes",
            [
                "or",
                ["in", "certname", ["extract", "certname", ["select_reports", None]]],
                ["=", "certname", "a"],
            ],
        )
        self.assertEqual([row["certname"] for row in rows], ["a"])
        self.assertIn(
            {"$or": [NEVER_MATCH, {"certname": "a"}]},
            stages(nodes.pipelines[-1], "$match"),
        )

    async def test_negated_never_matches_everything(self):
        nodes = FakeCollection(docs=[{"certname": "a"}])
        engine = engine_with(nodes, reports=FakeCollection())
        rows, _total = await engine.run(
            "nodes",
            [
                "not",
                ["in", "certname", ["extract", "certname", ["select_reports", None]]],
            ],
        )
        self.assertEqual([row["certname"] for row in rows], ["a"])
        self.assertIn(
            {"$nor": [NEVER_MATCH]},
            stages(nodes.pipelines[-1], "$match"),
        )

    async def test_single_column_subquery_groups_on_the_storage_path(self):
        res = FakeCollection(docs=[{"_id": "a"}, {"_id": "b"}])
        nodes = FakeCollection()
        engine = engine_with(nodes, resources=res)
        await engine.run(
            "nodes",
            [
                "in",
                "certname",
                ["extract", "certname", ["select_resources", ["=", "type", "File"]]],
            ],
        )
        self.assertEqual(
            res.pipelines[0],
            [
                {"$match": {"type": "File"}},
                {"$group": {"_id": "$node_id"}},
                {"$match": {"_id": {"$ne": None}}},
                {"$limit": 100000},
            ],
        )
        self.assertIn({"id": {"$in": ["a", "b"]}}, stages(nodes.pipelines[0], "$match"))

    async def test_distinct_subquery_keeps_the_entity_base_stages(self):
        nodes = FakeCollection(docs=[{"_id": "a"}])
        engine = engine_with(nodes)
        await engine.select("catalog-inputs", ["certname"], ["=", "certname", "a"])
        first = nodes.pipelines[0][0]["$match"]
        self.assertEqual(
            first["$and"][:-1], [s["$match"] for s in ENTITIES["catalog-inputs"].stages]
        )
        self.assertEqual(nodes.pipelines[0][1], {"$group": {"_id": "$id"}})

    async def test_inexact_subquery_filter_keeps_the_full_pipeline(self):
        res = FakeCollection(docs=[{"certname": "a"}, {"certname": "b"}])
        engine = engine_with(resources=res)
        await engine.select("resources", ["certname"], ["not", ["=", "type", "File"]])
        pipeline = res.pipelines[0]
        group_at = next(i for i, s in enumerate(pipeline) if "$group" in s)
        limit_at = next(i for i, s in enumerate(pipeline) if "$limit" in s)
        self.assertEqual(
            pipeline[group_at]["$group"], {"_id": {"certname": "$certname"}}
        )
        self.assertLess(group_at, limit_at)

    async def test_array_column_subquery_keeps_the_full_pipeline(self):
        res = FakeCollection(docs=[{"tags": ["a"]}])
        engine = engine_with(resources=res)
        await engine.select("resources", ["tags"], ["=", "type", "File"])
        self.assertEqual(
            stage(res.pipelines[0], "$group"), {"_id": {"tags": "$tags"}}
        )

    async def test_subquery_rows_are_deduplicated(self):
        res = FakeCollection(docs=[{"_id": "a"}, {"_id": "a"}, {"_id": "b"}])
        engine = engine_with(resources=res)
        rows = await engine.select("resources", ["certname"], ["=", "type", "File"])
        self.assertEqual(rows, [("a",), ("b",)])

    async def test_multi_column_in_matches_on_a_tuple_key(self):
        nodes = FakeCollection(
            docs=[{"certname": "a", "environment": "prod"}]
        )
        engine = engine_with(nodes)
        await engine.run("facts", TWO_COLUMN_IN)
        outer = nodes.pipelines[-1]
        prefilter = outer[0]["$match"]
        self.assertIn({"id": {"$in": ["a"]}}, prefilter["$and"])
        self.assertIn({"environment": {"$in": ["prod"]}}, prefilter["$and"])
        added_at = next(i for i, s in enumerate(outer) if "$addFields" in s)
        self.assertEqual(
            outer[added_at]["$addFields"],
            {
                "__tuple_0": {
                    "0": {"$ifNull": ["$certname", None]},
                    "1": {"$ifNull": ["$environment", None]},
                }
            },
        )
        self.assertIn(
            {"__tuple_0": {"$in": [{"0": "a", "1": "prod"}]}},
            outer[added_at + 1]["$match"]["$and"],
        )
        self.assertIn("__tuple_0", outer[-1]["$unset"])

    async def test_tuple_key_is_added_to_the_count_pipeline(self):
        nodes = FakeCollection(
            docs=[{"certname": "a", "environment": "prod"}], counts=1
        )
        engine = engine_with(nodes)
        await engine.run(
            "facts", TWO_COLUMN_IN, paging=Paging(limit=1, include_total=True)
        )
        count = next(p for p in nodes.pipelines if stage(p, "$count"))
        self.assertIsNotNone(stage(count, "$addFields"))
        self.assertLess(
            next(i for i, s in enumerate(count) if "$addFields" in s),
            next(i for i, s in enumerate(count) if "$match" in s and "__tuple_0" in str(s)),
        )

    async def test_subquery_keeps_unhashable_rows(self):
        res = FakeCollection(docs=[{"tags": ["a"]}, {"tags": ["a"]}])
        engine = engine_with(resources=res)
        rows = await engine.select("resources", ["tags"], ["=", "type", "File"])
        self.assertEqual(rows, [(["a"],), (["a"],)])

    async def test_query_depth_limit(self):
        engine = QueryEngine(
            log=logging.getLogger("test"),
            collections={"nodes": FakeCollection()},
            max_query_depth=4,
        )
        await engine.run("nodes", ["and", ["=", "certname", "a"]])
        with self.assertRaises(PuppetDBQueryError) as ctx:
            await engine.run(
                "nodes", ["and", ["and", ["and", ["and", ["=", "certname", "a"]]]]]
            )
        self.assertIn("more than 4 levels deep", str(ctx.exception))
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_subquery_depth_limit(self):
        engine = QueryEngine(
            log=logging.getLogger("test"),
            collections={"nodes": FakeCollection(docs=[{"certname": "a"}])},
            max_subquery_depth=1,
        )
        one = ["in", "certname", ["extract", "certname", ["select_facts", None]]]
        await engine.run("nodes", one)
        two = ["in", "certname", ["extract", "certname", ["select_facts", one]]]
        with self.assertRaises(PuppetDBQueryError) as ctx:
            await engine.run("nodes", two)
        self.assertIn("more than 1 levels of subqueries", str(ctx.exception))

    async def test_nested_from_counts_as_a_subquery_level(self):
        engine = QueryEngine(
            log=logging.getLogger("test"),
            collections={"nodes": FakeCollection()},
            max_subquery_depth=1,
        )
        await engine.run("nodes", ["from", "nodes", ["=", "certname", "a"]])
        with self.assertRaises(PuppetDBQueryError):
            await engine.run(
                "nodes",
                [
                    "in",
                    "certname",
                    [
                        "extract",
                        "certname",
                        ["from", "facts", ["extract", "certname",
                                           ["from", "nodes", None]]],
                    ],
                ],
            )

    async def test_deep_query_is_rejected_instead_of_recursing(self):
        engine = QueryEngine(
            log=logging.getLogger("test"),
            collections={"nodes": FakeCollection()},
            max_query_depth=50,
        )
        node = ["=", "certname", "a"]
        for _ in range(600):
            node = ["and", node]
        with self.assertRaises(PuppetDBQueryError):
            await engine.run("nodes", node)

    async def test_depth_check_does_not_exhaust_the_stack(self):
        engine = QueryEngine(
            log=logging.getLogger("test"),
            collections={"nodes": FakeCollection()},
            max_query_depth=0,
            max_subquery_depth=3,
        )
        node = ["=", "certname", "a"]
        for _ in range(5000):
            node = ["and", node]
        with self.assertRaises(PuppetDBQueryError) as ctx:
            await engine.run("nodes", node)
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_both_limits_disabled_skips_the_check(self):
        engine = QueryEngine(
            log=logging.getLogger("test"),
            collections={"nodes": FakeCollection()},
            max_query_depth=0,
            max_subquery_depth=0,
        )
        node = ["=", "certname", "a"]
        for _ in range(200):
            node = ["and", node]
        await engine.run("nodes", node)

    def capped_engine(self, resources):
        return QueryEngine(
            log=logging.getLogger("test"),
            collections={"nodes": FakeCollection(), "nodes_reports": FakeCollection(), "nodes_resources": resources, "nodes_edges": FakeCollection()},
            max_page_size=5000,
        )

    async def test_page_cap_asks_for_one_row_more_than_it_allows(self):
        nodes = FakeCollection()
        await self.capped_engine(nodes).run("resources", ["=", "type", "File"])
        limits = [s["$limit"] for s in nodes.pipelines[-1] if "$limit" in s]
        self.assertEqual(limits, [5001])

    async def test_page_cap_refuses_instead_of_truncating(self):
        nodes = FakeCollection(docs=[{"title": str(index)} for index in range(5001)])
        with self.assertRaises(PuppetDBQueryError) as ctx:
            await self.capped_engine(nodes).run("resources", ["=", "type", "File"])
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("more than 5000 rows", ctx.exception.message)

    async def test_page_cap_passes_results_that_fit(self):
        nodes = FakeCollection(docs=[{"title": str(index)} for index in range(5000)])
        rows, total = await self.capped_engine(nodes).run("resources", ["=", "type", "File"])
        self.assertEqual((len(rows), total), (5000, 5000))

    async def test_streamed_results_are_not_capped(self):
        from pyppetdb.pdb.query import engine as module
        from pyppetdb.pdb.query.engine import RowStream

        nodes = FakeCollection(docs=[{"title": str(index)} for index in range(7)])
        original = module.STREAM_BATCH_SIZE
        module.STREAM_BATCH_SIZE = 3
        try:
            stream, total = await self.capped_engine(nodes).run(
                "resources", ["=", "type", "File"], stream=True
            )
            self.assertIsInstance(stream, RowStream)
            batches = [batch async for batch in stream.batches()]
        finally:
            module.STREAM_BATCH_SIZE = original
        self.assertEqual([len(batch) for batch in batches], [3, 3, 1])
        self.assertFalse(any("$limit" in stage for stage in nodes.pipelines[-1]))
        self.assertIsNone(total)

    async def test_streamed_include_total_counts_first(self):
        nodes = FakeCollection(docs=[{"title": "a"}], counts=42)
        stream, total = await self.capped_engine(nodes).run(
            "resources", None, paging=Paging(include_total=True), stream=True
        )
        self.assertEqual(total, 42)

    async def test_scalar_entities_stream_their_scalar(self):
        nodes = FakeCollection(docs=[{"name": "kernel"}])
        engine = engine_with(nodes)
        stream, _total = await engine.run(
            "fact-names", ["~", "name", "ker"], stream=True
        )
        self.assertEqual([batch async for batch in stream.batches()], [["kernel"]])

    async def test_python_entities_never_stream(self):
        nodes = FakeCollection(docs=[{"id": "h", "facts": {"a": 1}}])
        rows, _total = await engine_with(nodes).run("fact-contents", None, stream=True)
        self.assertIsInstance(rows, list)

    async def test_page_cap_shrinks_oversized_limit(self):
        nodes = FakeCollection()
        engine = QueryEngine(
            log=logging.getLogger("test"),
            collections={"nodes": FakeCollection(), "nodes_reports": FakeCollection(), "nodes_resources": nodes, "nodes_edges": FakeCollection()},
            max_page_size=5000,
        )
        await engine.run(
            "resources", ["=", "type", "File"], paging=Paging(limit=99999)
        )
        limits = [s["$limit"] for s in nodes.pipelines[-1] if "$limit" in s]
        self.assertEqual(limits, [5001])

    async def test_page_cap_leaves_small_limit_and_aggregates_alone(self):
        nodes = FakeCollection()
        engine = QueryEngine(
            log=logging.getLogger("test"),
            collections={"nodes": FakeCollection(), "nodes_reports": FakeCollection(), "nodes_resources": nodes, "nodes_edges": FakeCollection()},
            max_page_size=5000,
        )
        await engine.run(
            "resources", ["=", "type", "File"], paging=Paging(limit=100)
        )
        self.assertEqual(
            [s["$limit"] for s in nodes.pipelines[-1] if "$limit" in s], [100]
        )
        nodes.pipelines.clear()
        await engine.run("resources", ["extract", [["function", "count"]]])
        self.assertEqual(nodes.pipelines, [])
        self.assertEqual(nodes.counts_calls, [({}, {"hint": "_id_"})])

    async def test_no_page_cap_when_disabled(self):
        res = FakeCollection()
        engine = engine_with(resources=res)  # max_page_size default 0
        await engine.run("resources", ["=", "type", "File"])
        self.assertEqual(
            [s for s in res.pipelines[-1] if "$limit" in s], []
        )

    async def test_query_timeout_applies_max_time_ms(self):
        nodes = FakeCollection()
        engine = QueryEngine(
            log=logging.getLogger("test"),
            collections={"nodes": nodes},
            query_timeout=30,
        )
        await engine.run("nodes", ["=", "certname", "a"])
        self.assertEqual(nodes.options[0]["maxTimeMS"], 30000)
        await engine.run("nodes", ["=", "certname", "a"], timeout=5)
        self.assertEqual(nodes.options[1]["maxTimeMS"], 5000)

    async def test_query_timeout_max_caps_the_request(self):
        engine = QueryEngine(
            log=logging.getLogger("test"),
            collections={"nodes": FakeCollection()},
            query_timeout=600,
            query_timeout_max=60,
        )
        self.assertEqual(engine.effective_timeout(None), 60)
        self.assertEqual(engine.effective_timeout(10), 10)
        self.assertEqual(engine.effective_timeout(999), 60)
        self.assertEqual(engine.effective_timeout(0), 60)

    async def test_no_timeout_when_unconfigured(self):
        nodes = FakeCollection()
        engine = engine_with(nodes)
        await engine.run("nodes", ["=", "certname", "a"])
        self.assertNotIn("maxTimeMS", nodes.options[0])

    async def test_extract_projection(self):
        nodes = FakeCollection()
        engine = engine_with(nodes)
        await engine.run("nodes", ["extract", ["certname"], ["=", "certname", "a"]])
        self.assertEqual(
            [s for s in nodes.pipelines[0] if "$project" in s][-1], {"$project": {"_id": 0, "certname": 1}}
        )

    async def test_group_by_with_count(self):
        nodes = FakeCollection()
        engine = engine_with(nodes)
        await engine.run(
            "nodes",
            [
                "extract",
                [["function", "count"], "latest_report_status"],
                ["group_by", "latest_report_status"],
            ],
        )
        stages = nodes.pipelines[0]
        group = [stage for stage in stages if "$group" in stage][-1]["$group"]
        self.assertEqual(group["_id"], {"latest_report_status": "$latest_report_status"})
        self.assertEqual(group["count"], {"$sum": 1})

    async def test_paging_stages(self):
        nodes = FakeCollection(counts=42)
        engine = engine_with(nodes)
        rows, total = await engine.run(
            "nodes",
            ["from", "nodes", ["limit", 5], ["offset", 10]],
            paging=Paging(include_total=True),
        )
        self.assertEqual(total, 42)
        stages = nodes.pipelines[-1]
        self.assertIn({"$skip": 10}, stages)
        self.assertIn({"$limit": 5}, stages)

    async def test_implicit_filter_is_merged(self):
        res = FakeCollection()
        engine = engine_with(resources=res)
        await engine.run(
            "resources",
            ["=", "title", "t"],
            implicit=[["=", "type", "File"]],
        )
        match = [s for s in res.pipelines[0] if "$match" in s][-1]["$match"]
        self.assertEqual(match, {"$and": [{"type": "File"}, {"title": "t"}]})

    async def test_fact_names_returns_scalars(self):
        nodes = FakeCollection(distinct_values=["os", "kernel"])
        engine = engine_with(nodes)
        rows, _total = await engine.run("fact-names", None)
        self.assertEqual(rows, ["kernel", "os"])

    async def test_reports_use_report_collection(self):
        reports = FakeCollection(docs=[{"certname": "a"}])
        engine = engine_with(reports=reports)
        rows, _total = await engine.run("reports", ["=", "certname", "a"])
        self.assertEqual([row["certname"] for row in rows], ["a"])
        self.assertTrue(reports.pipelines)

    async def test_select_returns_tuples(self):
        nodes = FakeCollection(docs=[{"_id": "a"}, {"_id": "b"}])
        engine = engine_with(nodes)
        rows = await engine.select("nodes", ["certname"], ["=", "node_state", "active"])
        self.assertEqual(rows, [("a",), ("b",)])

    async def test_unknown_entity_rejected(self):
        with self.assertRaises(PuppetDBQueryError) as ctx:
            await engine_with().run("widgets", None)
        self.assertIn("Invalid query entity", str(ctx.exception))

    async def test_unknown_order_by_column_rejected(self):
        with self.assertRaises(PuppetDBQueryError):
            await engine_with().run("nodes", ["from", "nodes", ["order_by", ["nope"]]])

    async def test_validate_accepts_subquery_without_database(self):
        engine = engine_with()
        await engine.validate(
            "nodes",
            ["in", "certname", ["extract", "certname", ["select_facts", ["=", "name", "os"]]]],
        )


class TestActiveRestriction(unittest.IsolatedAsyncioTestCase):
    async def test_restriction_adds_the_active_clause(self):
        nodes = FakeCollection()
        engine = engine_with(nodes)
        await engine.run("nodes", ["=", "certname", "a"], restrict_active=True)
        first = nodes.pipelines[0][0]["$match"]
        self.assertIn({"disabled": {"$ne": True}}, first["$and"])

    async def test_explicit_node_state_wins(self):
        nodes = FakeCollection()
        engine = engine_with(nodes)
        await engine.run("nodes", ["=", "node_state", "inactive"], restrict_active=True)
        self.assertEqual(nodes.pipelines[0][0], {"$match": {"disabled": True}})

    async def test_entities_without_node_state_are_left_alone(self):
        nodes = FakeCollection()
        engine = engine_with(nodes)
        await engine.run("environments", ["=", "name", "prod"], restrict_active=True)
        self.assertEqual(nodes.distincts, [("environment", {"environment": "prod"})])


class TestDistinctWindow(unittest.IsolatedAsyncioTestCase):
    async def test_latest_event_per_resource_is_picked_before_the_filter(self):
        events = FakeCollection()
        engine = engine_with(events=events)
        start, end = datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 2, tzinfo=UTC)
        await engine.run(
            "events",
            ["and", ["=", "certname", "a"], ["=", "status", "failure"]],
            distinct_window=(start, end),
        )
        pipeline = events.pipelines[0]
        self.assertEqual(pipeline[0], {"$match": {"node_id": "a"}})
        self.assertEqual(pipeline[1], {"$match": {"timestamp": {"$gte": start, "$lte": end}}})
        group = pipeline[2]["$group"]
        self.assertEqual(
            group["_id"],
            {
                "node_id": "$node_id",
                "resource_type": "$resource_type",
                "resource_title": "$resource_title",
                "property": "$property",
                "name": "$name",
            },
        )
        self.assertEqual(group["latest"], {"$max": "$timestamp"})
        self.assertEqual(pipeline[4], {"$unwind": "$events"})
        self.assertEqual(pipeline[5], {"$replaceRoot": {"newRoot": "$events"}})
        later = [s["$match"] for s in pipeline[6:] if "$match" in s]
        self.assertTrue(any("failure" in str(m) for m in later))


class TestExtraColumns(unittest.IsolatedAsyncioTestCase):
    async def test_extra_columns_are_projected_and_null_filled(self):
        nodes = FakeCollection()
        engine = engine_with(nodes)
        await engine.run("nodes", None, extra_columns=["expires_facts", "expires_facts_updated"])
        project = stage(nodes.pipelines[0], "$project")
        self.assertEqual(project["expires_facts"], {"$ifNull": ["$facts_expiration.expire", True]})
        self.assertIn("expires_facts_updated", stage(nodes.pipelines[0], "$set"))

    async def test_extract_ignores_extra_columns(self):
        nodes = FakeCollection()
        engine = engine_with(nodes)
        await engine.run("nodes", ["extract", ["certname"]], extra_columns=["expires_facts"])
        self.assertNotIn("expires_facts", stage(nodes.pipelines[0], "$project"))


class TestExtractNullFill(unittest.IsolatedAsyncioTestCase):
    async def test_only_requested_columns_are_null_filled(self):
        nodes = FakeCollection()
        engine = engine_with(nodes)
        await engine.run(
            "nodes", ["extract", ["certname"], ["=", "certname", "a"]], restrict_active=True
        )
        self.assertEqual(stage(nodes.pipelines[0], "$set"), {"certname": {"$ifNull": ["$certname", None]}})


class TestSelectFactDocuments(unittest.IsolatedAsyncioTestCase):
    async def pipeline(self, columns, ast):
        nodes = FakeCollection(docs=[{"_id": "host1"}])
        engine = engine_with(nodes)
        rows = await engine.select("facts", columns, ast)
        return nodes.pipelines[0], rows

    async def test_pinned_name_selects_documents_that_carry_the_fact(self):
        pipeline, rows = await self.pipeline(["certname"], ["=", "name", "kernel"])
        self.assertEqual(
            pipeline,
            [
                {"$match": {"$and": [{"facts_index.p": "kernel"}, {"facts.kernel": {"$exists": True}}]}},
                {"$group": {"_id": "$id"}},
                {"$match": {"_id": {"$ne": None}}},
                {"$limit": SUBQUERY_LIMIT},
            ],
        )
        self.assertEqual(rows, [("host1",)])

    async def test_document_level_clauses_become_the_prefilter(self):
        pipeline, _rows = await self.pipeline(
            ["environment"],
            ["and", ["in", "name", ["array", ["kernel", "os"]]], ["in", "certname", ["array", ["a", "b"]]]],
        )
        self.assertEqual(
            pipeline[0],
            {
                "$match": {
                    "$and": [
                        {"id": {"$in": ["a", "b"]}},
                        {
                            "$or": [
                                {"$and": [{"facts_index.p": "kernel"}, {"facts.kernel": {"$exists": True}}]},
                                {"$and": [{"facts_index.p": "os"}, {"facts.os": {"$exists": True}}]},
                            ]
                        },
                    ]
                }
            },
        )
        self.assertEqual(pipeline[1], {"$group": {"_id": "$environment"}})

    async def test_disjoint_name_pins_select_nothing(self):
        nodes = FakeCollection(docs=[{"_id": "host1"}])
        rows = await engine_with(nodes).select(
            "facts", ["certname"], ["and", ["=", "name", "kernel"], ["=", "name", "os"]]
        )
        self.assertEqual(rows, [])
        self.assertEqual(nodes.pipelines, [])

    async def assert_falls_back(self, columns, ast):
        pipeline, _rows = await self.pipeline(columns, ast)
        self.assertNotEqual(pipeline[1], {"$group": {"_id": "$id"}}, ast)

    async def test_row_level_or_unpinned_filters_fall_back_to_the_expansion(self):
        await self.assert_falls_back(["certname"], ["and", ["=", "name", "kernel"], ["=", "value", "Linux"]])
        await self.assert_falls_back(["certname"], ["~", "name", "^ker"])
        await self.assert_falls_back(["certname"], ["or", ["=", "name", "kernel"], ["=", "certname", "a"]])
        await self.assert_falls_back(["certname"], ["=", "name", "os.family"])
        await self.assert_falls_back(["name"], ["=", "name", "kernel"])


class TestIncrementalSort(unittest.IsolatedAsyncioTestCase):
    INDEX = [{"key": {"node_id": 1, "timestamp": 1}}]

    def events(self):
        rows = []
        for node in ("a", "b"):
            for ts in (1, 2):
                for title in ("z", "m", "a"):
                    rows.append(
                        {
                            "certname": node,
                            "timestamp": datetime(2026, 1, 1, 0, 0, ts),
                            "resource_title": title,
                        }
                    )
        return rows

    async def run_events(self, paging, stream=False, indexes=None, columns=None):
        events = FakeCollection(docs=self.events(), indexes=indexes or self.INDEX)
        engine = engine_with(events=events)
        ast = ["extract", columns] if columns else None
        rows, total = await engine.run("events", ast, paging=paging, stream=stream)
        return events, rows, total

    def order(self, *keys):
        return [(key, direction) for key, direction in keys]

    async def test_sorts_only_the_index_prefix_in_the_database(self):
        events, rows, _total = await self.run_events(
            Paging(order_by=self.order(("certname", 1), ("timestamp", 1), ("resource_title", 1)), limit=4, offset=1)
        )
        pipeline = events.pipelines[0]
        self.assertEqual(stages(pipeline, "$sort"), [{"node_id": 1, "timestamp": 1}])
        self.assertFalse(any("$skip" in stage or "$limit" in stage for stage in pipeline))
        self.assertEqual(
            [(r["certname"], r["timestamp"].second, r["resource_title"]) for r in rows],
            [("a", 1, "m"), ("a", 1, "z"), ("a", 2, "a"), ("a", 2, "m")],
        )

    async def test_descending_rest_keys_and_streaming(self):
        _events, stream, _total = await self.run_events(
            Paging(order_by=self.order(("certname", 1), ("timestamp", 1), ("resource_title", -1))),
            stream=True,
        )
        rows = [row async for batch in stream.batches() for row in batch]
        self.assertEqual(len(rows), 12)
        self.assertEqual([r["resource_title"] for r in rows[:3]], ["z", "m", "a"])
        self.assertEqual(rows[3]["timestamp"].second, 2)

    async def test_a_full_index_match_sorts_in_the_database(self):
        events, _rows, _total = await self.run_events(
            Paging(order_by=self.order(("certname", 1), ("timestamp", 1)), limit=4),
        )
        self.assertEqual(stages(events.pipelines[0], "$sort"), [{"node_id": 1, "timestamp": 1}])
        self.assertTrue(any("$limit" in stage for stage in events.pipelines[0]))

    async def test_non_scalar_columns_sort_in_the_database(self):
        events, _rows, _total = await self.run_events(
            Paging(order_by=self.order(("certname", 1), ("new_value", 1)), limit=4),
        )
        self.assertEqual(stages(events.pipelines[0], "$sort"), [{"node_id": 1, "new_value": 1}])

    async def test_order_columns_missing_from_the_extract_sort_in_the_database(self):
        events, _rows, _total = await self.run_events(
            Paging(order_by=self.order(("certname", 1), ("timestamp", 1), ("resource_title", 1)), limit=4),
            columns=["certname"],
        )
        self.assertEqual(
            stages(events.pipelines[0], "$sort"),
            [{"node_id": 1, "timestamp": 1, "resource_title": 1}],
        )

    async def test_a_single_value_on_a_leading_index_key_sorts_in_the_database(self):
        events = FakeCollection(docs=self.events(), indexes=self.INDEX)
        engine = engine_with(events=events)
        await engine.run(
            "events",
            ["=", "certname", "a"],
            paging=Paging(order_by=self.order(("certname", 1), ("timestamp", 1), ("resource_title", 1)), limit=4),
        )
        self.assertEqual(
            stages(events.pipelines[0], "$sort"),
            [{"node_id": 1, "timestamp": 1, "resource_title": 1}],
        )

    async def test_many_values_keep_the_incremental_sort(self):
        events = FakeCollection(docs=self.events(), indexes=self.INDEX)
        engine = engine_with(events=events)
        await engine.run(
            "events",
            ["in", "certname", ["array", ["a", "b"]]],
            paging=Paging(order_by=self.order(("certname", 1), ("timestamp", 1), ("resource_title", 1)), limit=4),
        )
        self.assertEqual(stages(events.pipelines[0], "$sort"), [{"node_id": 1, "timestamp": 1}])

    def test_boundary_condition_selects_the_group_and_everything_after(self):
        from pyppetdb.pdb.query.engine import _boundary_condition

        self.assertEqual(
            _boundary_condition(["node_id", "timestamp"], ("b", 5)),
            {
                "$or": [
                    {"node_id": "b", "timestamp": 5},
                    {"node_id": {"$gt": "b"}},
                    {"node_id": "b", "timestamp": {"$gt": 5}},
                ]
            },
        )
        self.assertIsNone(_boundary_condition(["node_id", "timestamp"], ("b", None)))

    def test_bson_type_order(self):
        from pyppetdb.pdb.query.engine import _bson_order

        values = [datetime(2026, 1, 1), True, "b", 2, None, "a", 1.5]
        self.assertEqual(
            sorted(values, key=_bson_order),
            [None, 1.5, 2, "a", "b", True, datetime(2026, 1, 1)],
        )


class TestExists(unittest.IsolatedAsyncioTestCase):
    async def test_document_entities_answer_with_find_one(self):
        nodes = FakeCollection()
        nodes.find_one = AsyncMock(return_value={"_id": 1})
        engine = engine_with(nodes)
        self.assertTrue(await engine.exists("nodes", "certname", "a"))
        nodes.find_one.assert_awaited_once_with({"id": "a"}, projection={"_id": 1})
        self.assertEqual(nodes.pipelines, [])

    async def test_entity_stages_join_the_condition(self):
        nodes = FakeCollection()
        nodes.find_one = AsyncMock(return_value=None)
        engine = engine_with(nodes)
        self.assertFalse(await engine.exists("factsets", "certname", "a"))
        condition = nodes.find_one.await_args.args[0]
        self.assertIn({"id": "a"}, condition.get("$and", [condition]))

    async def test_other_entities_fall_back_to_a_one_row_query(self):
        nodes = FakeCollection(docs=[{"certname": "a"}])
        engine = engine_with(nodes)
        self.assertTrue(await engine.exists("catalogs", "certname", "a"))
        self.assertEqual(len(nodes.pipelines), 1)


class TestLookupPruning(unittest.IsolatedAsyncioTestCase):
    async def lookups(self, ast):
        nodes = FakeCollection()
        engine = engine_with(nodes)
        await engine.run("catalogs", ast)
        return [stage["$lookup"]["as"] for stage in nodes.pipelines[0] if "$lookup" in stage]

    async def test_catalog_columns_without_children_skip_both_lookups(self):
        self.assertEqual(
            await self.lookups(["extract", ["certname", "catalog_uuid"], ["=", "certname", "a"]]),
            [],
        )

    async def test_full_catalogs_keep_both_lookups(self):
        self.assertEqual(
            await self.lookups(["=", "certname", "a"]), ["_edges", "_resources"]
        )

    async def test_only_the_requested_child_is_looked_up(self):
        self.assertEqual(
            await self.lookups(["extract", ["certname", "edges"], ["=", "certname", "a"]]),
            ["_edges"],
        )

    def test_root_references_keep_every_lookup(self):
        from pyppetdb.pdb.query.engine import _prune_lookups

        pipeline = [
            {"$lookup": {"from": "x", "as": "_x", "pipeline": []}},
            {"$replaceRoot": {"newRoot": "$$ROOT"}},
        ]
        self.assertEqual(_prune_lookups(pipeline), pipeline)


class TestGroup(unittest.IsolatedAsyncioTestCase):
    async def test_group_appends_the_stages_behind_the_match(self):
        events = FakeCollection(docs=[{"subject": {"title": "a"}}])
        engine = engine_with(events=events)
        rows = await engine.group(
            "events",
            ["extract", ["certname", "status"], ["not", ["=", "status", "noop"]]],
            [{"$group": {"_id": "$certname"}}],
        )
        self.assertEqual(rows, [{"subject": {"title": "a"}}])
        pipeline = events.pipelines[0]
        self.assertEqual(
            pipeline[0], {"$project": {"_id": 0, "certname": "$node_id", "status": "$status"}}
        )
        self.assertEqual(pipeline[1], {"$match": {"$nor": [{"status": "noop"}]}})
        self.assertEqual(pipeline[2], {"$group": {"_id": "$certname"}})
        self.assertFalse(any("$limit" in stage for stage in pipeline))

    async def test_exact_filters_group_on_storage_paths_without_a_projection(self):
        events = FakeCollection()
        engine = engine_with(events=events)
        await engine.group(
            "events",
            ["extract", ["certname"], ["=", "latest_report?", True]],
            [{"$group": {"_id": {"certname": "$certname"}, "n": {"$sum": {"$cond": [{"$eq": ["$status", "failure"]}, 1, 0]}}}}],
            extra={"corrective_change": "$corrective_change"},
        )
        self.assertEqual(
            events.pipelines[0],
            [
                {"$match": {"latest": True}},
                {"$group": {"_id": {"certname": "$node_id"}, "n": {"$sum": {"$cond": [{"$eq": ["$status", "failure"]}, 1, 0]}}}},
            ],
        )

    async def group_pipeline(self, ast):
        events = FakeCollection()
        engine = engine_with(events=events)
        await engine.group(
            "events",
            ["extract", ["certname"], ast] if ast is not None else ["extract", ["certname"]],
            [{"$group": {"_id": {"certname": "$certname", "status": "$status"}}}],
        )
        return events.pipelines[0]

    async def test_unpinned_latest_is_spelled_out_for_the_covering_index(self):
        pipeline = await self.group_pipeline(
            ["or", ["=", "status", "success"], ["=", "status", "skipped"]]
        )
        self.assertEqual(
            pipeline[0],
            {
                "$match": {
                    "$and": [
                        {"$or": [{"status": "success"}, {"status": "skipped"}]},
                        {"latest": {"$in": [True, False]}},
                    ]
                }
            },
        )
        self.assertEqual(
            pipeline[1], {"$group": {"_id": {"certname": "$node_id", "status": "$status"}}}
        )

    async def test_an_unfiltered_group_also_uses_the_covering_index(self):
        pipeline = await self.group_pipeline(None)
        self.assertEqual(pipeline[0], {"$match": {"latest": {"$in": [True, False]}}})
        self.assertEqual(len(pipeline), 2)

    async def test_pinned_latest_is_left_alone(self):
        pipeline = await self.group_pipeline(["=", "latest_report?", True])
        self.assertEqual(pipeline[0], {"$match": {"latest": True}})

    async def test_fields_outside_the_covering_index_skip_the_prefix(self):
        pipeline = await self.group_pipeline(["=", "property", "ensure"])
        self.assertEqual(pipeline[0], {"$match": {"property": "ensure"}})

    def test_the_covering_index_matches_the_events_crud(self):
        from pyppetdb.crud.nodes_events import CrudNodesEvents
        from unittest.mock import MagicMock

        crud = CrudNodesEvents(
            config=MagicMock(), log=logging.getLogger("test"), coll=MagicMock()
        )
        model = next(
            index for index in crud._indices if index.document["name"] == "idx_latest_counts"
        )
        spec = get_entity("events").covering_index
        self.assertEqual(list(model.document["key"]), spec["fields"])
        self.assertEqual(spec["fields"][0], spec["prefix"])

    async def test_computed_columns_keep_the_projection(self):
        events = FakeCollection()
        engine = engine_with(events=events)
        await engine.group(
            "events",
            ["extract", ["certname"], ["=", "latest_report?", True]],
            [{"$group": {"_id": "$node_state"}}],
        )
        self.assertIn("$project", events.pipelines[0][1])
        self.assertEqual(events.pipelines[0][-1], {"$group": {"_id": "$node_state"}})

    async def test_group_carries_extra_storage_fields_through_the_projection(self):
        events = FakeCollection()
        engine = engine_with(events=events)
        await engine.group(
            "events",
            ["extract", ["certname"], ["not", ["=", "status", "noop"]]],
            [{"$group": {"_id": "$certname"}}],
            extra={"corrective_change": "$corrective_change"},
        )
        project = events.pipelines[0][0]["$project"]
        self.assertEqual(project["corrective_change"], "$corrective_change")
        self.assertEqual(project["certname"], "$node_id")

    async def test_group_skips_the_database_for_impossible_filters(self):
        events = FakeCollection(docs=[{"x": 1}])
        engine = engine_with(events=events)
        rows = await engine.group(
            "events",
            ["extract", ["certname"], ["in", "certname", ["extract", "certname", ["select_nodes", ["=", "certname", "nope"]]]]],
            [{"$group": {"_id": "$certname"}}],
        )
        self.assertEqual(rows, [])
        self.assertEqual(events.pipelines, [])

    async def test_python_entities_cannot_be_grouped(self):
        with self.assertRaises(PuppetDBQueryError) as ctx:
            await engine_with().group("fact-contents", None, [{"$count": "n"}])
        self.assertEqual(ctx.exception.status_code, 500)


class TestProjectionPushdown(unittest.IsolatedAsyncioTestCase):
    async def projection(self, entity_name, ast):
        collection = FakeCollection()
        engine = engine_with(collection, collection)
        await engine.run(entity_name, ast)
        return stage(collection.pipelines[-1], "$project")

    async def test_full_projection_without_extract(self):
        projection = await self.projection("reports", ["=", "status", "failed"])
        self.assertIn("logs", projection)
        self.assertIn("metrics", projection)

    async def test_extract_projects_only_what_is_needed(self):
        projection = await self.projection(
            "reports", ["extract", ["certname"], ["=", "status", "failed"]]
        )
        self.assertEqual(set(projection), {"_id", "certname", "status"})

    async def test_order_by_and_group_by_columns_survive(self):
        projection = await self.projection(
            "nodes",
            [
                "from",
                "nodes",
                ["extract", ["certname"]],
                ["order_by", ["report_timestamp"]],
            ],
        )
        self.assertIn("report_timestamp", projection)

    async def test_count_without_columns_keeps_a_placeholder(self):
        projection = await self.projection(
            "catalogs", ["extract", [["function", "count"]]]
        )
        self.assertEqual(set(projection), {"_id", "_row"})


class TestElementFilter(unittest.IsolatedAsyncioTestCase):
    async def cond(self, entity_name, ast):
        entity = get_entity(entity_name)
        compiler = FilterCompiler(entity, engine=engine_with())
        match = await compiler.compile(ast)
        from pyppetdb.pdb.query.engine import build_element_filter

        return build_element_filter(entity, match)

    async def test_flat_resource_entity_has_no_element_filter(self):
        self.assertIsNone(await self.cond("resources", ["=", "type", "File"]))
        self.assertIsNone(
            await self.cond("resources", ["=", ["parameter", "owner"], "root"])
        )

    async def test_regex_on_json_column_guards_non_strings(self):
        self.assertEqual(
            await self.cond("facts", ["~", "value", "^Red"]),
            {
                "$cond": [
                    {"$eq": [{"$type": "$$item.v"}, "string"]},
                    {"$regexMatch": {"input": "$$item.v", "regex": "^Red"}},
                    False,
                ]
            },
        )

    async def test_entity_without_array_yields_nothing(self):
        self.assertIsNone(await self.cond("nodes", ["=", "certname", "a"]))

    async def test_fact_name_and_value(self):
        self.assertEqual(
            await self.cond("facts", ["=", "name", "osfamily"]),
            {"$eq": ["$$item.k", "osfamily"]},
        )
        self.assertEqual(
            await self.cond(
                "facts", ["and", ["=", "name", "osfamily"], ["=", "value", "Debian"]]
            ),
            {
                "$and": [
                    {"$eq": ["$$item.k", "osfamily"]},
                    {"$eq": ["$$item.v", "Debian"]},
                ]
            },
        )

    async def test_fact_document_level_column_is_ignored(self):
        self.assertIsNone(await self.cond("facts", ["=", "certname", "a"]))

    async def test_fact_names_groups_and_sorts(self):
        built = get_entity("fact-names").build_stages(
            {"$eq": ["$$item.k", "osfamily"]}
        )
        self.assertEqual(built[-2], {"$group": {"_id": "$kv.k"}})
        self.assertEqual(built[-1], {"$sort": {"_id": 1}})

    async def test_flat_resource_projection_has_no_element_filter(self):
        res = FakeCollection()
        engine = engine_with(resources=res)
        await engine.run("resources", ["=", "type", "File"])
        project = stage(res.pipelines[0], "$project")
        self.assertEqual(project["type"], "$type")
        self.assertNotIn("$filter", project.get("resource", {}))


class TestPinnedFactKeys(unittest.IsolatedAsyncioTestCase):
    async def pinned(self, entity_name, ast):
        from pyppetdb.pdb.query.engine import build_pinned_keys

        entity = get_entity(entity_name)
        match = await FilterCompiler(entity, engine=engine_with()).compile(ast)
        return build_pinned_keys(entity, match)

    async def test_equality_pins_one_key(self):
        self.assertEqual(await self.pinned("facts", ["=", "name", "osfamily"]), {"osfamily"})

    async def test_in_pins_a_set(self):
        self.assertEqual(
            await self.pinned("facts", ["in", "name", ["array", ["a", "b"]]]),
            {"a", "b"},
        )

    async def test_or_pins_only_when_every_branch_does(self):
        self.assertEqual(
            await self.pinned("facts", ["or", ["=", "name", "a"], ["=", "name", "b"]]),
            {"a", "b"},
        )
        self.assertIsNone(
            await self.pinned(
                "facts", ["or", ["=", "name", "a"], ["=", "certname", "x"]]
            )
        )

    async def test_negation_pins_nothing(self):
        self.assertIsNone(await self.pinned("facts", ["not", ["=", "name", "a"]]))

    async def test_unrelated_filter_pins_nothing(self):
        self.assertIsNone(await self.pinned("facts", ["=", "certname", "x"]))

    async def test_unsafe_key_is_rejected(self):
        self.assertIsNone(await self.pinned("facts", ["=", "name", "weird.name"]))

    async def test_other_entities_are_unaffected(self):
        self.assertIsNone(await self.pinned("resources", ["=", "type", "File"]))

    async def test_pipeline_avoids_object_to_array(self):
        nodes = FakeCollection()
        engine = engine_with(nodes)
        await engine.run("facts", ["=", "name", "osfamily"])
        project = stage(nodes.pipelines[-1], "$project")
        rendered = str(project["kv"])
        self.assertNotIn("$objectToArray", rendered)
        self.assertIn("$facts.osfamily", rendered)

    async def test_pipeline_falls_back_without_a_pinned_key(self):
        nodes = FakeCollection()
        engine = engine_with(nodes)
        await engine.run("facts", ["=", "certname", "x"])
        project = stage(nodes.pipelines[-1], "$project")
        self.assertIn("$objectToArray", str(project["kv"]))

    async def test_the_exact_match_still_runs(self):
        nodes = FakeCollection()
        engine = engine_with(nodes)
        await engine.run("facts", ["=", "name", "osfamily"])
        matches = stages(nodes.pipelines[-1], "$match")
        self.assertIn({"name": "osfamily"}, matches)


class TestPrefilterExactness(unittest.IsolatedAsyncioTestCase):
    async def plan(self, entity_name, ast):
        entity = get_entity(entity_name)
        match = await FilterCompiler(entity, engine=engine_with()).compile(ast)
        return build_prefilter_plan(entity, match)

    async def test_empty_match_is_exact(self):
        self.assertEqual(build_prefilter_plan(get_entity("nodes"), {}), ({}, True))

    async def test_node_state_is_exact(self):
        self.assertEqual(
            await self.plan("nodes", ["=", "node_state", "active"]),
            ({"disabled": {"$ne": True}}, True),
        )
        self.assertEqual(
            await self.plan("nodes", ["=", "node_state", "inactive"]),
            ({"disabled": True}, True),
        )

    async def test_identity_paths_are_exact(self):
        self.assertEqual(
            await self.plan("nodes", ["=", "certname", "a"]), ({"id": "a"}, True)
        )
        self.assertEqual(
            await self.plan("resources", ["in", "type", ["array", ["File", "User"]]]),
            ({"type": {"$in": ["File", "User"]}}, True),
        )
        self.assertEqual(
            await self.plan("resources", ["~", "title", "^/opt"]),
            ({"title": {"$regex": "^/opt"}}, True),
        )
        self.assertEqual(
            await self.plan("resources", [">", "line", 5]),
            ({"line": {"$gt": 5}}, True),
        )

    async def test_default_valued_columns(self):
        self.assertEqual(
            await self.plan("resources", ["=", "exported", True]),
            ({"exported": True}, True),
        )
        self.assertEqual(
            await self.plan("resources", ["=", "exported", False]), ({}, False)
        )
        _prefilter, exact = await self.plan(
            "resources", ["in", "exported", ["array", [True, False]]]
        )
        self.assertFalse(exact)

    async def test_conjunction_and_disjunction(self):
        self.assertEqual(
            await self.plan(
                "resources", ["and", ["=", "type", "File"], ["=", "title", "/x"]]
            ),
            ({"$and": [{"type": "File"}, {"title": "/x"}]}, True),
        )
        self.assertEqual(
            await self.plan(
                "resources", ["or", ["=", "type", "File"], ["=", "type", "User"]]
            ),
            ({"$or": [{"type": "File"}, {"type": "User"}]}, True),
        )
        self.assertEqual(
            await self.plan(
                "resources", ["or", ["=", "type", "File"], ["=", "exported", False]]
            ),
            ({}, False),
        )

    async def test_negation_and_dropped_leaves_are_not_exact(self):
        self.assertEqual(
            await self.plan("resources", ["not", ["=", "type", "File"]]), ({}, False)
        )
        prefilter, exact = await self.plan(
            "resources", ["and", ["=", "type", "File"], ["not", ["=", "title", "/x"]]]
        )
        self.assertEqual(prefilter, {"type": "File"})
        self.assertFalse(exact)
        prefilter, exact = await self.plan(
            "resources", ["and", ["=", "type", "File"], ["null?", "line", False]]
        )
        self.assertEqual(prefilter, {"type": "File"})
        self.assertFalse(exact)

    async def test_fact_equality_is_exact_through_the_direct_predicate(self):
        prefilter, exact = await self.plan("nodes", ["=", ["fact", "osfamily"], "Debian"])
        self.assertTrue(exact)
        self.assertIn({"facts.osfamily": "Debian"}, prefilter["$and"])
        self.assertEqual(
            await self.plan("nodes", ["=", ["fact", "big"], "x" * 300]),
            ({"facts.big": "x" * 300}, True),
        )

    async def test_existence_and_parameter_leaves_are_not_exact(self):
        _prefilter, exact = await self.plan("facts", ["=", "name", "osfamily"])
        self.assertFalse(exact)
        _prefilter, exact = await self.plan(
            "resources", ["=", ["parameter", "owner"], "root"]
        )
        self.assertFalse(exact)


class TestCountShortcut(unittest.IsolatedAsyncioTestCase):
    COUNT = ["extract", [["function", "count"]], ["=", "node_state", "active"]]
    PAGED = {
        "limit": "25",
        "offset": "0",
        "include_total": "true",
        "order_by": '[{"field":"certname","order":"asc"}]',
    }

    async def test_exact_count_uses_count_documents(self):
        nodes = FakeCollection(counts=7)
        engine = engine_with(nodes)
        rows, total = await engine.run("nodes", self.COUNT)
        self.assertEqual(rows, [{"count": 7}])
        self.assertEqual(total, 1)
        self.assertEqual(nodes.counts_calls, [({"disabled": {"$ne": True}}, {})])
        self.assertEqual(nodes.pipelines, [])

    async def test_zero_count_yields_a_zero_row(self):
        nodes = FakeCollection(counts=0)
        engine = engine_with(nodes)
        rows, total = await engine.run("nodes", self.COUNT)
        self.assertEqual((rows, total), ([{"count": 0}], 1))

    async def test_empty_aggregates_yield_one_row_like_upstream(self):
        res = FakeCollection()
        engine = engine_with(resources=res)
        rows, total = await engine.run(
            "resources",
            [
                "extract",
                [["function", "count"], ["function", "max", "line"], ["function", "avg", "line"]],
                ["not", ["=", "type", "File"]],
            ],
        )
        self.assertEqual((rows, total), ([{"count": 0, "max": None, "avg": None}], 1))
        rows, _total = await engine.run(
            "resources",
            [
                "extract",
                [["function", "count"], "type"],
                ["not", ["=", "type", "File"]],
                ["group_by", "type"],
            ],
        )
        self.assertEqual(rows, [])

    async def test_include_total_uses_count_documents_and_pages_normally(self):
        nodes = FakeCollection(docs=[{"certname": "a"}], counts=10000)
        engine = engine_with(nodes)
        rows, total = await engine.run(
            "nodes", None, paging=parse_paging(self.PAGED)
        )
        self.assertEqual(total, 10000)
        self.assertEqual([row["certname"] for row in rows], ["a"])
        self.assertEqual(nodes.counts_calls, [({}, {"hint": "_id_"})])
        self.assertEqual(len(nodes.pipelines), 1)
        self.assertIn({"$limit": 25}, nodes.pipelines[0])

    async def test_inexact_total_falls_back_to_a_slim_count_pipeline(self):
        nodes = FakeCollection(docs=[{"certname": "a"}], counts=3)
        engine = engine_with(nodes)
        rows, total = await engine.run(
            "nodes",
            ["not", ["=", "certname", "b"]],
            paging=parse_paging(self.PAGED),
        )
        self.assertEqual(total, 3)
        self.assertFalse(hasattr(nodes, "counts_calls"))
        count_pipeline = nodes.pipelines[0]
        self.assertNotIn("$sort", [key for item in count_pipeline for key in item])
        self.assertEqual(count_pipeline[-1], {"$count": "count"})
        self.assertEqual(
            set(stage(count_pipeline, "$project")) - {"_id"}, {"certname"}
        )
        self.assertIn({"$limit": 25}, nodes.pipelines[1])

    async def test_row_entities_never_take_the_shortcut(self):
        nodes = FakeCollection(docs=[{"count": 5}], counts=5)
        engine = engine_with(nodes)
        await engine.run(
            "facts", ["extract", [["function", "count"]], ["=", "name", "osfamily"]]
        )
        self.assertFalse(hasattr(nodes, "counts_calls"))
        self.assertTrue(nodes.pipelines)

    async def test_stage_matches_join_the_count_filter(self):
        nodes = FakeCollection(counts=4)
        engine = engine_with(nodes)
        rows, _total = await engine.run(
            "catalog-inputs",
            ["extract", [["function", "count"]], ["=", "certname", "a"]],
        )
        self.assertEqual(rows, [{"count": 4}])
        self.assertEqual(
            nodes.counts_calls,
            [
                (
                    {
                        "$and": [
                            {"id": {"$type": "string"}, "catalog_inputs": {"$type": "object"}},
                            {"id": "a"},
                        ]
                    },
                    {},
                )
            ],
        )

    async def test_grouped_counts_use_the_pipeline(self):
        nodes = FakeCollection(
            docs=[{"count": 1, "catalog_environment": "p"}], counts=1
        )
        engine = engine_with(nodes)
        await engine.run(
            "nodes",
            [
                "extract",
                [["function", "count"], "catalog_environment"],
                ["group_by", "catalog_environment"],
            ],
        )
        self.assertFalse(hasattr(nodes, "counts_calls"))
        self.assertTrue(nodes.pipelines)


class TestPrefilter(unittest.IsolatedAsyncioTestCase):
    async def compile(self, entity_name, ast):
        entity = get_entity(entity_name)
        compiler = FilterCompiler(entity, engine=engine_with())
        return entity, await compiler.compile(ast)

    async def prefilter(self, entity_name, ast):
        entity, match = await self.compile(entity_name, ast)
        return build_prefilter(entity, match)

    async def test_maps_columns_to_storage_paths(self):
        self.assertEqual(
            await self.prefilter("resources", ["=", "type", "File"]),
            {"type": "File"},
        )
        self.assertEqual(
            await self.prefilter("nodes", ["=", "certname", "a"]),
            {"id": "a"},
        )
        self.assertEqual(
            await self.prefilter("reports", ["=", "certname", "a"]),
            {"node_id": "a"},
        )

    async def test_dotted_parameters(self):
        self.assertEqual(
            await self.prefilter("resources", ["=", ["parameter", "owner"], "root"]),
            {"params_index": {"$elemMatch": {"n": "owner", "v": "root"}}},
        )

    async def test_parameter_large_value_has_no_prefilter(self):
        big = "x" * 600
        self.assertEqual(
            await self.prefilter(
                "resources", ["=", ["parameter", "content"], big]
            ),
            {},
        )

    async def test_resource_param_prefilter_matches_the_built_array(self):
        # Soundness: was build_resource_params ins Array legt, findet der
        # elemMatch-Prefilter auch; was ausgeschlossen wird, erzeugt keinen
        # Prefilter (also keinen faelschlichen Drop).
        from pyppetdb.helpers.puppetdb import build_resource_params

        resources = [{
            "resource": "h1", "type": "File", "title": "/a",
            "parameters": {"ensure": "present", "mode": "0644",
                           "content": "x" * 600},
        }]
        params = build_resource_params(resources)

        def elem_match(spec):
            n = spec["n"]
            v = spec["v"]
            for e in params:
                if e["n"] != n:
                    continue
                if isinstance(v, dict) and "$in" in v:
                    if e["v"] in v["$in"]:
                        return True
                elif e["v"] == v:
                    return True
            return False

        # indexierbar -> Prefilter da und trifft das Array
        pf = await self.prefilter(
            "resources", ["=", ["parameter", "ensure"], "present"]
        )
        self.assertTrue(elem_match(pf["params_index"]["$elemMatch"]))

        # grosser Wert -> kein Prefilter (Node wird nicht gedroppt)
        pf_big = await self.prefilter(
            "resources", ["=", ["parameter", "content"], "x" * 600]
        )
        self.assertEqual(pf_big, {})

    async def test_parameter_regex_has_no_prefilter(self):
        self.assertEqual(
            await self.prefilter(
                "resources", ["~", ["parameter", "owner"], "^ro"]
            ),
            {},
        )

    async def test_and_collects_every_derivable_clause(self):
        self.assertEqual(
            await self.prefilter(
                "resources", ["and", ["=", "type", "File"], ["=", "title", "/x"]]
            ),
            {
                "$and": [
                    {"type": "File"},
                    {"title": "/x"},
                ]
            },
        )

    async def test_negation_yields_nothing(self):
        self.assertEqual(
            await self.prefilter("resources", ["not", ["=", "type", "File"]]), {}
        )

    async def test_negated_branch_does_not_leak_into_prefilter(self):
        result = await self.prefilter(
            "resources",
            ["and", ["=", "type", "File"], ["not", ["=", "title", "/x"]]],
        )
        self.assertEqual(result, {"type": "File"})

    async def test_or_requires_every_branch(self):
        both = await self.prefilter(
            "resources", ["or", ["=", "type", "File"], ["=", "type", "Package"]]
        )
        self.assertEqual(
            both,
            {
                "$or": [
                    {"type": "File"},
                    {"type": "Package"},
                ]
            },
        )
        partial = await self.prefilter(
            "resources", ["or", ["=", "type", "File"], ["not", ["=", "title", "/x"]]]
        )
        self.assertEqual(partial, {})

    async def test_not_null_is_not_derivable(self):
        self.assertEqual(
            await self.prefilter("resources", ["null?", "line", False]), {}
        )

    async def test_null_is_not_derivable(self):
        self.assertEqual(
            await self.prefilter("resources", ["null?", "line", True]), {}
        )

    async def test_default_valued_equality_is_skipped(self):
        self.assertEqual(
            await self.prefilter("resources", ["=", "exported", False]), {}
        )
        self.assertEqual(
            await self.prefilter("resources", ["=", "exported", True]),
            {"exported": True},
        )

    async def test_range_and_regex_are_derivable(self):
        self.assertEqual(
            await self.prefilter("resources", [">", "line", 5]),
            {"line": {"$gt": 5}},
        )
        self.assertEqual(
            await self.prefilter("resources", ["~", "title", "^/opt"]),
            {"title": {"$regex": "^/opt"}},
        )

    async def test_fact_name_becomes_a_key_existence_check(self):
        self.assertEqual(
            await self.prefilter("facts", ["=", "name", "osfamily"]),
            {"facts.osfamily": {"$exists": True}},
        )

    async def test_pinned_fact_names_become_an_existence_disjunction(self):
        self.assertEqual(
            await self.prefilter(
                "facts",
                ["or", ["=", "name", "osfamily"], ["=", "name", "uptime"]],
            ),
            {
                "$or": [
                    {"facts.osfamily": {"$exists": True}},
                    {"facts.uptime": {"$exists": True}},
                ]
            },
        )
        self.assertEqual(
            await self.prefilter("facts", ["in", "name", ["array", ["b", "a"]]]),
            {
                "$or": [
                    {"facts.a": {"$exists": True}},
                    {"facts.b": {"$exists": True}},
                ]
            },
        )

    async def test_fact_name_regex_is_not_derivable(self):
        self.assertEqual(
            await self.prefilter("facts", ["~", "name", "^os"]), {}
        )

    async def test_node_state(self):
        self.assertEqual(
            await self.prefilter("nodes", ["=", "node_state", "active"]),
            {"disabled": {"$ne": True}},
        )
        self.assertEqual(
            await self.prefilter("nodes", ["=", "node_state", "inactive"]),
            {"disabled": True},
        )

    async def test_unmapped_column_yields_nothing(self):
        self.assertEqual(
            await self.prefilter("reports", ["=", "resource_events", []]), {}
        )

    async def test_node_report_timestamp_maps_to_the_report_end_time(self):
        self.assertEqual(
            await self.prefilter(
                "nodes", ["<", "report_timestamp", "2026-01-01T00:00:00Z"]
            ),
            {"report.end_time": {"$lt": datetime(2026, 1, 1, tzinfo=UTC)}},
        )

    async def test_path_prefilters_agree_with_their_column_expression(self):
        for name, entity in ENTITIES.items():
            if not entity.document_rows:
                continue
            for column in entity.columns:
                if not column.prefilter or column.prefilter_kind != "path":
                    continue
                if not isinstance(column.expr, str) or not column.expr.startswith("$"):
                    continue
                self.assertEqual(
                    column.expr[1:],
                    column.prefilter,
                    f"{name}.{column.name} pre-filters on a different document "
                    f"field than it projects from",
                )

    async def test_prefilter_never_narrows_the_result(self):
        from pyppetdb.pdb.query import matcher

        resources = [
            {
                "node_id": "one", "environment": "prod", "type": "File",
                "title": "/a", "exported": True, "line": 3,
                "parameters": {}, "tags": [],
            },
            {
                "node_id": "one", "environment": "prod", "type": "Package",
                "title": "/b", "exported": False, "line": 9,
                "parameters": {}, "tags": [],
            },
            {
                "node_id": "two", "environment": "dev", "type": "Service",
                "title": "/a", "exported": False, "line": 1,
                "parameters": {}, "tags": [],
            },
        ]
        queries = [
            ["=", "type", "File"],
            ["=", "title", "/a"],
            ["and", ["=", "type", "File"], ["=", "title", "/a"]],
            ["and", ["=", "type", "File"], ["=", "title", "/b"]],
            ["not", ["=", "type", "File"]],
            ["and", ["=", "type", "Service"], ["not", ["=", "title", "/a"]]],
            ["or", ["=", "type", "File"], ["=", "type", "Service"]],
            ["=", "exported", False],
            ["=", "exported", True],
            [">", "line", 2],
            ["null?", "line", False],
            ["=", "certname", "two"],
        ]
        for query in queries:
            entity, match = await self.compile("resources", query)
            prefilter = build_prefilter(entity, match)
            if not prefilter:
                continue
            projected = [
                {
                    "certname": resource["node_id"],
                    "environment": resource["environment"],
                    "type": resource.get("type"),
                    "title": resource.get("title"),
                    "exported": resource.get("exported", False),
                    "line": resource.get("line"),
                    "parameters": resource.get("parameters", {}),
                    "tags": resource.get("tags", []),
                    "_source": index,
                }
                for index, resource in enumerate(resources)
            ]
            expected = {
                row["_source"] for row in projected if matcher.matches(row, match)
            }
            kept = {
                index
                for index, resource in enumerate(resources)
                if matcher.matches(resource, prefilter)
            }
            self.assertTrue(
                expected <= kept,
                f"prefilter dropped documents for {query}: "
                f"expected {expected}, prefilter kept {kept}",
            )

    async def test_node_prefilter_never_narrows_the_result(self):
        from pyppetdb.pdb.query import matcher

        documents = [
            {
                "id": "ontime",
                "environment": "prod",
                "disabled": False,
                "change_facts": datetime(2026, 1, 1, 10, 5, tzinfo=UTC),
                "change_catalog": datetime(2026, 1, 1, 10, 5, tzinfo=UTC),
                "change_report": datetime(2026, 1, 1, 10, 5, tzinfo=UTC),
                "report": {
                    "end_time": datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
                    "status": "changed",
                },
            },
            {
                "id": "delayed",
                "environment": "prod",
                "disabled": False,
                "change_facts": datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
                "change_catalog": datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
                "change_report": datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
                "report": {
                    "end_time": datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
                    "status": "unchanged",
                },
            },
            {
                "id": "noreport",
                "environment": "dev",
                "disabled": True,
                "change_facts": datetime(2026, 1, 1, 9, 0, tzinfo=UTC),
                "change_catalog": datetime(2026, 1, 1, 9, 0, tzinfo=UTC),
            },
        ]
        boundary = "2026-01-01T11:00:00Z"
        queries = [
            ["<", "report_timestamp", boundary],
            ["<=", "report_timestamp", boundary],
            [">", "report_timestamp", boundary],
            [">=", "report_timestamp", boundary],
            ["=", "report_timestamp", "2026-01-01T10:00:00Z"],
            ["null?", "report_timestamp", True],
            ["and",
             ["=", "catalog_environment", "prod"],
             ["<", "report_timestamp", boundary]],
            ["or",
             ["<", "report_timestamp", boundary],
             ["=", "certname", "noreport"]],
            ["<", "facts_timestamp", boundary],
            ["<", "catalog_timestamp", boundary],
            ["=", "latest_report_status", "unchanged"],
        ]
        for query in queries:
            entity, match = await self.compile("nodes", query)
            prefilter = build_prefilter(entity, match)
            if not prefilter:
                continue
            projected = [
                {
                    "certname": document["id"],
                    "catalog_environment": document["environment"],
                    "facts_environment": document["environment"],
                    "report_environment": document["environment"],
                    "catalog_timestamp": document.get("change_catalog"),
                    "facts_timestamp": document.get("change_facts"),
                    "report_timestamp": (
                        document.get("report", {}).get("end_time")
                    ),
                    "latest_report_status": (
                        document.get("report", {}).get("status")
                    ),
                    "node_state": (
                        "inactive" if document.get("disabled") else "active"
                    ),
                    "_source": document["id"],
                }
                for document in documents
            ]
            expected = {
                row["_source"] for row in projected if matcher.matches(row, match)
            }
            kept = {
                document["id"]
                for document in documents
                if matcher.matches(document, prefilter)
            }
            self.assertTrue(
                expected <= kept,
                f"prefilter dropped documents for {query}: "
                f"expected {expected}, prefilter kept {kept}",
            )


class TestFactValuePrefilter(unittest.IsolatedAsyncioTestCase):
    spec = FactsIndexSpec(max_value_len=8, depth=2, deny=["secret"])

    async def prefilter(self, entity_name, ast, spec=None):
        entity = get_entity(entity_name)
        match = await FilterCompiler(entity, engine=engine_with()).compile(ast)
        return build_prefilter(entity, match, spec or self.spec)

    async def test_glob_denied_paths_fall_back_to_the_direct_predicate(self):
        spec = FactsIndexSpec(depth=3, deny=["*.available"])
        self.assertEqual(
            await self.prefilter(
                "nodes", ["=", "facts.mountpoints./boot.available", "3 GiB"], spec
            ),
            {"facts.mountpoints./boot.available": "3 GiB"},
        )
        self.assertIn(
            "$and",
            await self.prefilter(
                "nodes", ["=", "facts.mountpoints./boot.filesystem", "ext4"], spec
            ),
        )

    async def test_equality_emits_both_forms(self):
        self.assertEqual(
            await self.prefilter("nodes", ["=", ["fact", "osfamily"], "Debian"]),
            {
                "$and": [
                    {"facts_index": {"$elemMatch": {"p": "osfamily", "v": "Debian"}}},
                    {"facts.osfamily": "Debian"},
                ]
            },
        )

    async def test_inventory_facts_and_trusted(self):
        self.assertEqual(
            await self.prefilter("inventory", ["=", "facts.osfamily", "Debian"]),
            {
                "$and": [
                    {"facts_index": {"$elemMatch": {"p": "osfamily", "v": "Debian"}}},
                    {"facts.osfamily": "Debian"},
                ]
            },
        )
        self.assertEqual(
            await self.prefilter("inventory", ["=", "trusted.authenticated", "remote"]),
            {
                "$and": [
                    {
                        "facts_index": {
                            "$elemMatch": {"p": "trusted.authenticated", "v": "remote"}
                        }
                    },
                    {"facts.trusted.authenticated": "remote"},
                ]
            },
        )

    async def test_in_becomes_an_indexed_disjunction(self):
        self.assertEqual(
            await self.prefilter(
                "nodes", ["in", ["fact", "osfamily"], ["array", ["Debian", "RedHat"]]]
            ),
            {
                "$and": [
                    {
                        "facts_index": {
                            "$elemMatch": {
                                "p": "osfamily",
                                "v": {"$in": ["Debian", "RedHat"]},
                            }
                        }
                    },
                    {"facts.osfamily": {"$in": ["Debian", "RedHat"]}},
                ]
            },
        )

    async def test_regex_and_comparison_stay_direct(self):
        self.assertEqual(
            await self.prefilter("nodes", ["~", ["fact", "osfamily"], "^Deb"]),
            {"facts.osfamily": {"$regex": "^Deb"}},
        )
        self.assertEqual(
            await self.prefilter("nodes", [">", ["fact", "uptime"], 5]),
            {"facts.uptime": {"$gt": 5}},
        )

    async def test_non_indexable_values_stay_direct(self):
        self.assertEqual(
            await self.prefilter("nodes", ["=", ["fact", "osfamily"], "x" * 9]),
            {"facts.osfamily": "x" * 9},
        )
        self.assertEqual(
            await self.prefilter("nodes", ["=", ["fact", "secret"], "hunter2"]),
            {"facts.secret": "hunter2"},
        )
        self.assertEqual(
            await self.prefilter("nodes", ["=", "facts.os.release.major", "12"]),
            {"facts.os.release.major": "12"},
        )

    async def test_null_fact_is_not_derivable(self):
        self.assertEqual(
            await self.prefilter("nodes", ["null?", ["fact", "osfamily"], True]), {}
        )

    async def test_pinned_fact_name_and_value_pair_up(self):
        self.assertEqual(
            await self.prefilter(
                "facts",
                ["and", ["=", "name", "osfamily"], ["=", "value", "Debian"]],
            ),
            {
                "$and": [
                    {"facts.osfamily": {"$exists": True}},
                    {
                        "$and": [
                            {
                                "facts_index": {
                                    "$elemMatch": {"p": "osfamily", "v": "Debian"}
                                }
                            },
                            {"facts.osfamily": "Debian"},
                        ]
                    },
                ]
            },
        )

    async def test_pinned_name_set_pairs_with_every_name(self):
        prefilter = await self.prefilter(
            "facts",
            [
                "and",
                ["in", "name", ["array", ["a", "b"]]],
                ["=", "value", "x"],
            ],
        )
        pair = prefilter["$and"][-1]
        self.assertEqual(
            pair,
            {
                "$or": [
                    {
                        "$and": [
                            {"facts_index": {"$elemMatch": {"p": "a", "v": "x"}}},
                            {"facts.a": "x"},
                        ]
                    },
                    {
                        "$and": [
                            {"facts_index": {"$elemMatch": {"p": "b", "v": "x"}}},
                            {"facts.b": "x"},
                        ]
                    },
                ]
            },
        )

    async def test_a_dotted_fact_name_is_not_paired(self):
        self.assertEqual(
            await self.prefilter(
                "facts",
                ["and", ["=", "name", "a.b"], ["=", "value", "x"]],
                FactsIndexSpec(depth=2),
            ),
            {"facts.a.b": {"$exists": True}},
        )

    async def test_value_without_a_pinned_name_is_not_derivable(self):
        self.assertEqual(await self.prefilter("facts", ["=", "value", "Debian"]), {})

    async def test_denied_name_falls_back_to_the_existence_check(self):
        self.assertEqual(
            await self.prefilter(
                "facts", ["and", ["=", "name", "secret"], ["=", "value", "hunter2"]]
            ),
            {"facts.secret": {"$exists": True}},
        )

    async def test_fact_contents_keeps_its_key_existence_prefilter(self):
        self.assertEqual(
            await self.prefilter(
                "fact-contents",
                ["and", ["=", "name", "osfamily"], ["=", "value", "Debian"]],
            ),
            {"facts.osfamily": {"$exists": True}},
        )

    async def test_engine_defaults_index_scalars_down_to_depth_three(self):
        self.assertEqual(
            await self.prefilter(
                "nodes", ["=", ["fact", "osfamily"], "Debian"], FactsIndexSpec()
            ),
            {
                "$and": [
                    {"facts_index": {"$elemMatch": {"p": "osfamily", "v": "Debian"}}},
                    {"facts.osfamily": "Debian"},
                ]
            },
        )
        self.assertEqual(
            await self.prefilter(
                "nodes", ["=", "facts.os.release.major", "12"], FactsIndexSpec()
            ),
            {
                "$and": [
                    {
                        "facts_index": {
                            "$elemMatch": {"p": "os.release.major", "v": "12"}
                        }
                    },
                    {"facts.os.release.major": "12"},
                ]
            },
        )
        self.assertEqual(
            await self.prefilter(
                "nodes", ["=", "facts.a.b.c.d", "deep"], FactsIndexSpec()
            ),
            {"facts.a.b.c.d": "deep"},
        )

    async def test_slash_keys_are_indexable_but_positional_ones_are_not(self):
        self.assertEqual(
            await self.prefilter(
                "nodes", ["=", "facts.mountpoints./boot.filesystem", "xfs"], FactsIndexSpec()
            ),
            {
                "$and": [
                    {
                        "facts_index": {
                            "$elemMatch": {"p": "mountpoints./boot.filesystem", "v": "xfs"}
                        }
                    },
                    {"facts.mountpoints./boot.filesystem": "xfs"},
                ]
            },
        )
        self.assertEqual(
            await self.prefilter("nodes", ["=", "facts.roles.0", "web"], FactsIndexSpec()),
            {"facts.roles.0": "web"},
        )


def _entry_matches(entry, condition) -> bool:
    for key, want in condition.items():
        if key not in entry:
            return False
        if isinstance(want, dict) and "$in" in want:
            if not any(entry[key] == item for item in want["$in"]):
                return False
        elif entry[key] != want:
            return False
    return True


def document_matches(document, condition) -> bool:
    from pyppetdb.pdb.query import matcher

    if not condition:
        return True
    for key, value in condition.items():
        if key == "$and":
            if not all(document_matches(document, item) for item in value):
                return False
        elif key == "$or":
            if not any(document_matches(document, item) for item in value):
                return False
        elif key == "facts_index":
            entries = document.get("facts_index") or []
            if not any(
                _entry_matches(entry, value["$elemMatch"]) for entry in entries
            ):
                return False
        elif not matcher.matches(document, {key: value}):
            return False
    return True


class TestFactValuePrefilterSoundness(unittest.IsolatedAsyncioTestCase):
    max_value_len = 8
    depth = 2
    deny = ["secret"]

    facts = [
        {
            "osfamily": "Debian",
            "roles": ["web", "db"],
            "secret": "hunter2",
            "huge": "x" * 20,
            "uptime": 5,
            "virtual": True,
            "os": {"family": "Debian", "release": {"major": "12"}},
        },
        {
            "osfamily": "RedHat",
            "roles": ["db"],
            "uptime": 9,
            "virtual": False,
            "os": {"family": "RedHat"},
        },
        {"osfamily": "Debian", "os": [{"family": "Debian"}]},
        {},
    ]

    queries = [
        ["=", ["fact", "osfamily"], "Debian"],
        ["=", ["fact", "roles"], "web"],
        ["=", ["fact", "secret"], "hunter2"],
        ["=", ["fact", "huge"], "x" * 20],
        ["=", ["fact", "uptime"], 5],
        ["=", ["fact", "virtual"], True],
        ["=", ["fact", "virtual"], False],
        ["=", "facts.os.family", "Debian"],
        ["=", "facts.os.release.major", "12"],
        ["in", ["fact", "osfamily"], ["array", ["Debian", "RedHat"]]],
        ["~", ["fact", "osfamily"], "^Deb"],
        ["and", ["=", ["fact", "osfamily"], "Debian"], ["=", ["fact", "uptime"], 5]],
        ["or", ["=", ["fact", "osfamily"], "Debian"], ["=", ["fact", "uptime"], 9]],
        ["and", ["=", ["fact", "osfamily"], "Debian"], ["=", ["fact", "secret"], "hunter2"]],
        ["not", ["=", ["fact", "osfamily"], "Debian"]],
        ["null?", ["fact", "osfamily"], True],
    ]

    fact_queries = [
        ["and", ["=", "name", "osfamily"], ["=", "value", "Debian"]],
        ["and", ["=", "name", "roles"], ["=", "value", "web"]],
        ["and", ["=", "name", "secret"], ["=", "value", "hunter2"]],
        ["and", ["=", "name", "huge"], ["=", "value", "x" * 20]],
        ["and", ["=", "name", "os"], ["=", "value", "Debian"]],
        ["and", ["in", "name", ["array", ["osfamily", "uptime"]]], ["=", "value", "Debian"]],
        ["and", ["=", "name", "osfamily"], ["~", "value", "^Deb"]],
        ["or",
         ["and", ["=", "name", "osfamily"], ["=", "value", "Debian"]],
         ["and", ["=", "name", "uptime"], ["=", "value", 9]]],
    ]

    @property
    def spec(self):
        return FactsIndexSpec(
            max_value_len=self.max_value_len, depth=self.depth, deny=self.deny
        )

    def documents(self):
        return [
            {
                "id": f"node{index}",
                "environment": "prod",
                "disabled": False,
                "facts": facts,
                "facts_index": build_facts_index(
                    facts,
                    max_value_len=self.max_value_len,
                    depth=self.depth,
                    deny=self.deny,
                ),
            }
            for index, facts in enumerate(self.facts)
        ]

    async def compile(self, entity_name, ast):
        entity = get_entity(entity_name)
        return entity, await FilterCompiler(
            entity, engine=engine_with()
        ).compile(ast)

    async def assert_sound(self, entity_name, queries, project):
        documents = self.documents()
        for query in queries:
            entity, match = await self.compile(entity_name, query)
            prefilter = build_prefilter(entity, match, self.spec)
            if not prefilter:
                continue
            expected = {
                document["id"]
                for document in documents
                for row in project(document)
                if matcher.matches(row, match)
            }
            kept = {
                document["id"]
                for document in documents
                if document_matches(document, prefilter)
            }
            self.assertTrue(
                expected <= kept,
                f"prefilter dropped documents for {query}: "
                f"expected {expected}, prefilter kept {kept}",
            )

    async def test_node_fact_prefilter_never_narrows_the_result(self):
        await self.assert_sound(
            "nodes",
            self.queries,
            lambda document: [
                {
                    "certname": document["id"],
                    "facts": document["facts"],
                    "node_state": "active",
                }
            ],
        )

    async def test_inventory_prefilter_never_narrows_the_result(self):
        queries = [
            ["=", "facts.osfamily", "Debian"],
            ["=", "facts.roles", "web"],
            ["=", "facts.secret", "hunter2"],
            ["=", "facts.huge", "x" * 20],
            ["=", "facts.uptime", 5],
            ["=", "facts.os.family", "Debian"],
            ["=", "facts.os.release.major", "12"],
            ["in", "facts.osfamily", ["array", ["Debian", "RedHat"]]],
            ["~", "facts.osfamily", "^Deb"],
            ["and", ["=", "facts.osfamily", "Debian"], ["=", "facts.uptime", 5]],
            ["or", ["=", "facts.osfamily", "Debian"], ["=", "facts.uptime", 9]],
        ]
        await self.assert_sound(
            "inventory",
            queries,
            lambda document: [
                {
                    "certname": document["id"],
                    "facts": document["facts"],
                    "trusted": document["facts"].get("trusted"),
                }
            ],
        )

    async def test_fact_prefilter_never_narrows_the_result(self):
        await self.assert_sound(
            "facts",
            self.fact_queries,
            lambda document: [
                {"certname": document["id"], "name": name, "value": value}
                for name, value in document["facts"].items()
            ],
        )


class TestDistinctEntities(unittest.IsolatedAsyncioTestCase):
    async def test_fact_names_uses_a_distinct_scan(self):
        nodes = FakeCollection(distinct_values=["osfamily", "os", "os.family"])
        engine = engine_with(nodes)
        rows, total = await engine.run("fact-names", None)
        self.assertEqual(nodes.distincts, [("facts_index.p", None)])
        self.assertEqual(rows, ["os", "osfamily"])
        self.assertEqual(total, 2)
        self.assertEqual(nodes.pipelines, [])

    async def test_environments_and_producers_use_distinct(self):
        nodes = FakeCollection(distinct_values=["prod", "dev"])
        engine = engine_with(nodes)
        rows, _total = await engine.run("environments", None)
        self.assertEqual(rows, [{"name": "dev"}, {"name": "prod"}])
        self.assertEqual(nodes.distincts, [("environment", None)])
        nodes = FakeCollection(distinct_values=["pm1"])
        engine = engine_with(nodes)
        rows, _total = await engine.run("producers", None)
        self.assertEqual(rows, [{"name": "pm1"}])
        self.assertEqual(nodes.distincts, [("producer", None)])

    async def test_paging_applies_to_the_distinct_result(self):
        nodes = FakeCollection(distinct_values=["a", "b", "c"])
        engine = engine_with(nodes)
        rows, total = await engine.run(
            "fact-names", None, paging=Paging(limit=2, include_total=True)
        )
        self.assertEqual(rows, ["a", "b"])
        self.assertEqual(total, 3)
        rows, _total = await engine.run(
            "fact-names", None, paging=Paging(limit=2, offset=2)
        )
        self.assertEqual(rows, ["c"])

    async def test_order_by_applies_to_the_distinct_result(self):
        nodes = FakeCollection(distinct_values=["a", "b"])
        engine = engine_with(nodes)
        rows, _total = await engine.run(
            "fact-names", None, paging=Paging(order_by=[("name", -1)])
        )
        self.assertEqual(rows, ["b", "a"])

    async def test_an_exact_filter_is_passed_to_distinct(self):
        nodes = FakeCollection(distinct_values=["prod"])
        engine = engine_with(nodes)
        rows, _total = await engine.run("environments", ["=", "name", "prod"])
        self.assertEqual(nodes.distincts, [("environment", {"environment": "prod"})])
        self.assertEqual(nodes.pipelines, [])
        self.assertEqual(rows, [{"name": "prod"}])

    async def test_a_count_is_the_number_of_distinct_values(self):
        nodes = FakeCollection(distinct_values=["os", "kernel", "os.family"])
        engine = engine_with(nodes)
        rows, total = await engine.run("fact-names", ["extract", [["function", "count"]]])
        self.assertEqual(nodes.distincts, [("facts_index.p", None)])
        self.assertEqual((rows, total), ([{"count": 2}], 1))

    async def test_an_inexact_filter_still_aggregates(self):
        nodes = FakeCollection(docs=[{"name": "os"}])
        engine = engine_with(nodes)
        await engine.run("fact-names", ["~", "name", "^o"])
        self.assertEqual(nodes.distincts, [])
        self.assertTrue(nodes.pipelines)

    async def test_grouped_or_multi_column_extracts_still_aggregate(self):
        nodes = FakeCollection(docs=[{"count": 1}])
        engine = engine_with(nodes)
        await engine.run("environments", ["extract", [["function", "count"], "name"], ["group_by", "name"]])
        self.assertEqual(nodes.distincts, [])


class TestPythonEntities(unittest.IsolatedAsyncioTestCase):
    document = {
        "id": "host1",
        "environment": "prod",
        "disabled": False,
        "facts": {
            "os": {"family": "Debian", "release": {"major": "12"}},
            "uptime": 500,
            "tags": ["a", "b"],
        },
    }

    async def test_fact_contents_expansion(self):
        rows = expand_fact_contents(self.document)
        paths = sorted(tuple(row["path"]) for row in rows)
        self.assertIn(("os", "family"), paths)
        self.assertIn(("os", "release", "major"), paths)
        self.assertIn(("tags", 0), paths)
        self.assertIn(("uptime",), paths)

    async def test_array_indices_stay_integers(self):
        rows = expand_fact_paths(build_fact_paths(self.document["facts"]))
        indices = [row["path"][1] for row in rows if row["path"][0] == "tags"]
        self.assertEqual(sorted(indices), [0, 1])
        self.assertTrue(all(isinstance(item, int) for item in indices))

    async def test_fact_contents_equality_on_integer_path(self):
        nodes = FakeCollection(docs=[self.document])
        engine = engine_with(nodes)
        rows, total = await engine.run(
            "fact-contents", ["=", "path", ["tags", 0]]
        )
        self.assertEqual(total, 1)
        self.assertEqual(rows[0]["value"], "a")

    async def test_fact_contents_path_regex_matches_integer_index(self):
        nodes = FakeCollection(docs=[self.document])
        engine = engine_with(nodes)
        expected = {
            ("tags", 0): ["a"],
            ("tags", "0"): [],
            ("tags", "[01]"): ["a", "b"],
            ("ta.*", ".*"): ["a", "b"],
        }
        for patterns, values in expected.items():
            rows, _total = await engine.run(
                "fact-contents", ["~>", "path", list(patterns)]
            )
            self.assertEqual(
                sorted(row["value"] for row in rows), values, patterns
            )

    async def test_fact_paths_types(self):
        rows = expand_fact_paths(build_fact_paths(self.document["facts"]))
        types = {tuple(row["path"]): row["type"] for row in rows}
        self.assertEqual(types[("uptime",)], "integer")
        self.assertEqual(types[("os", "family")], "string")

    async def test_fact_contents_filtering(self):
        nodes = FakeCollection(docs=[self.document])
        engine = engine_with(nodes)
        rows, total = await engine.run(
            "fact-contents", ["=", "value", "Debian"]
        )
        self.assertEqual(total, 1)
        self.assertEqual(rows[0]["path"], ["os", "family"])

    async def test_fact_contents_path_regex(self):
        nodes = FakeCollection(docs=[self.document])
        engine = engine_with(nodes)
        rows, _total = await engine.run(
            "fact-contents", ["~>", "path", ["os", "re.*"]]
        )
        self.assertEqual(rows, [])

    async def test_fact_contents_extract_and_limit(self):
        nodes = FakeCollection(docs=[self.document])
        engine = engine_with(nodes)
        rows, total = await engine.run(
            "fact-contents",
            ["from", "fact-contents", ["extract", ["certname"], ["=", "certname", "host1"]], ["limit", 2]],
        )
        self.assertEqual(len(rows), 2)
        self.assertTrue(total >= 2)
        self.assertEqual(set(rows[0]), {"certname"})


class TestTotalCount(unittest.IsolatedAsyncioTestCase):
    async def test_limit_without_include_total_runs_one_aggregation(self):
        nodes = FakeCollection(docs=[{"certname": "a"}], counts=42)
        engine = engine_with(nodes)
        rows, total = await engine.run(
            "nodes", ["from", "nodes", ["limit", 5]]
        )
        self.assertEqual(len(nodes.pipelines), 1)
        self.assertEqual(total, len(rows))

    async def test_include_total_runs_the_count_pipeline(self):
        nodes = FakeCollection(docs=[{"certname": "a"}], counts=42)
        engine = engine_with(nodes)
        _rows, total = await engine.run(
            "nodes", None, paging=Paging(limit=5, include_total=True)
        )
        self.assertEqual(len(nodes.pipelines), 1)
        self.assertEqual(nodes.counts_calls, [({}, {"hint": "_id_"})])
        self.assertEqual(total, 42)

    async def test_count_pipeline_has_no_paging_stages(self):
        nodes = FakeCollection(counts=42)
        engine = engine_with(nodes)
        await engine.run(
            "nodes",
            ["not", ["=", "certname", "zzz"]],
            paging=Paging(limit=5, offset=3, include_total=True),
        )
        counting = nodes.pipelines[0]
        self.assertEqual(counting[-1], {"$count": "count"})
        self.assertIsNone(stage(counting, "$limit"))
        self.assertIsNone(stage(counting, "$skip"))
        self.assertIsNone(stage(counting, "$sort"))

    async def test_include_total_without_paging_needs_no_count(self):
        nodes = FakeCollection(docs=[{"certname": "a"}], counts=42)
        engine = engine_with(nodes)
        _rows, total = await engine.run(
            "nodes", None, paging=Paging(include_total=True)
        )
        self.assertEqual(len(nodes.pipelines), 1)
        self.assertEqual(total, 1)

    async def test_subquery_never_counts(self):
        nodes = FakeCollection()
        reports = FakeCollection(docs=[{"_id": "a"}], counts=7)
        engine = engine_with(nodes, reports)
        await engine.run(
            "nodes",
            [
                "in",
                "certname",
                [
                    "extract",
                    "certname",
                    ["select_reports", ["=", "certname", "a"]],
                ],
            ],
            paging=Paging(include_total=True),
        )
        self.assertEqual(len(reports.pipelines), 1)
        self.assertIsNone(stage(reports.pipelines[0], "$count"))

    async def test_python_entity_keeps_the_full_total(self):
        document = {"id": "host1", "facts": {"a": 1, "b": 2}}
        nodes = FakeCollection(docs=[document])
        engine = engine_with(nodes)
        rows, total = await engine.run(
            "fact-contents", None, paging=Paging(limit=1)
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(total, 2)


class TestSortHoisting(unittest.IsolatedAsyncioTestCase):
    async def test_reports_sort_moves_before_the_projection(self):
        reports = FakeCollection()
        engine = engine_with(reports=reports)
        await engine.run(
            "reports", None, paging=Paging(order_by=[("end_time", -1)], limit=5)
        )
        pipeline = reports.pipelines[0]
        self.assertEqual(pipeline[0], {"$sort": {"report.end_time": -1}})
        sort_at = next(i for i, s in enumerate(pipeline) if "$sort" in s)
        project_at = next(i for i, s in enumerate(pipeline) if "$project" in s)
        self.assertLess(sort_at, project_at)
        self.assertEqual(len(stages(pipeline, "$sort")), 1)

    async def test_hoisted_paging_follows_the_early_sort(self):
        reports = FakeCollection()
        engine = engine_with(reports=reports)
        await engine.run(
            "reports",
            None,
            paging=Paging(order_by=[("end_time", -1)], limit=5, offset=2),
        )
        pipeline = reports.pipelines[0]
        self.assertEqual(pipeline[0], {"$sort": {"report.end_time": -1}})
        self.assertEqual(pipeline[1], {"$skip": 2})
        self.assertEqual(pipeline[2], {"$limit": 5})

    async def test_exact_filter_limits_before_and_skips_behind_the_projection(self):
        reports = FakeCollection()
        engine = engine_with(reports=reports)
        await engine.run(
            "reports",
            ["=", "status", "changed"],
            paging=Paging(order_by=[("end_time", -1)], limit=5, offset=2),
        )
        pipeline = reports.pipelines[0]
        self.assertEqual(pipeline[0], {"$match": {"report.status": "changed"}})
        self.assertEqual(pipeline[1], {"$sort": {"report.end_time": -1}})
        self.assertEqual(pipeline[2], {"$limit": 7})
        self.assertIn("$project", pipeline[3])
        self.assertIn("$match", pipeline[4])
        self.assertEqual(pipeline[5], {"$skip": 2})

    async def test_deep_offsets_skip_on_index_keys_in_the_query_layer(self):
        reports = FakeCollection(
            indexes=[{"key": {"report.end_time": -1, "report.status": 1}}]
        )
        engine = engine_with(reports=reports)
        await engine.run(
            "reports",
            ["=", "status", "changed"],
            paging=Paging(order_by=[("end_time", -1)], limit=5, offset=10000),
        )
        pipeline = reports.pipelines[0]
        self.assertEqual(pipeline[2], {"$skip": 10000})
        self.assertEqual(pipeline[3], {"$limit": 5})
        self.assertIn("$project", pipeline[4])

    async def test_events_page_before_the_projection(self):
        events = FakeCollection()
        engine = engine_with(events=events)
        await engine.run(
            "events",
            ["in", "certname", ["array", ["a", "b"]]],
            paging=Paging(order_by=[("certname", 1), ("timestamp", 1)], limit=5),
        )
        pipeline = events.pipelines[0]
        self.assertEqual(pipeline[0], {"$match": {"node_id": {"$in": ["a", "b"]}}})
        self.assertEqual(pipeline[1], {"$sort": {"node_id": 1, "timestamp": 1}})
        self.assertEqual(pipeline[2], {"$limit": 5})
        self.assertIn("$project", pipeline[3])

    async def test_unwound_rows_page_before_the_projection_on_document_columns(self):
        nodes = FakeCollection()
        engine = engine_with(nodes)
        await engine.run(
            "facts",
            ["in", "certname", ["array", ["a", "b"]]],
            paging=Paging(order_by=[("certname", 1), ("name", 1)], limit=5),
        )
        pipeline = nodes.pipelines[0]
        unwinds = [i for i, s in enumerate(pipeline) if "$unwind" in s]
        sort_at = next(i for i, s in enumerate(pipeline) if "$sort" in s)
        limit_at = next(i for i, s in enumerate(pipeline) if "$limit" in s)
        project_at = [i for i, s in enumerate(pipeline) if "$project" in s][-1]
        self.assertEqual(pipeline[sort_at]["$sort"], {"id": 1, "kv.k": 1})
        self.assertLess(unwinds[-1], sort_at)
        self.assertLess(limit_at, project_at)
        self.assertEqual(len(stages(pipeline, "$sort")), 1)

    async def test_unwound_rows_page_late_on_element_columns(self):
        nodes = FakeCollection()
        engine = engine_with(nodes)
        await engine.run(
            "facts",
            ["=", "name", "kernel"],
            paging=Paging(order_by=[("certname", 1)], limit=5),
        )
        pipeline = nodes.pipelines[0]
        project_at = [i for i, s in enumerate(pipeline) if "$project" in s][-1]
        sort_at = next(i for i, s in enumerate(pipeline) if "$sort" in s)
        limit_at = next(i for i, s in enumerate(pipeline) if "$limit" in s)
        self.assertGreater(sort_at, project_at)
        self.assertGreater(limit_at, project_at)

    async def test_active_restriction_still_pages_before_the_projection(self):
        resources = FakeCollection(
            indexes=[{"key": {"node_id": 1, "type": 1, "title": 1, "disabled": 1}}]
        )
        engine = engine_with(resources=resources)
        await engine.run(
            "resources",
            ["=", "type", "File"],
            paging=Paging(order_by=[("certname", 1), ("type", 1), ("title", 1)], limit=5, offset=20000),
            restrict_active=True,
        )
        pipeline = resources.pipelines[0]
        self.assertEqual(
            pipeline[0], {"$match": {"$and": [{"disabled": {"$ne": True}}, {"type": "File"}]}}
        )
        self.assertEqual(pipeline[1], {"$sort": {"node_id": 1, "type": 1, "title": 1}})
        self.assertEqual(pipeline[2], {"$skip": 20000})
        self.assertEqual(pipeline[3], {"$limit": 5})
        self.assertIn("$project", pipeline[4])

    async def test_deep_offsets_without_a_covering_index_skip_behind_the_match(self):
        reports = FakeCollection(indexes=[{"key": {"report.end_time": -1}}])
        engine = engine_with(reports=reports)
        await engine.run(
            "reports",
            ["=", "status", "changed"],
            paging=Paging(order_by=[("end_time", -1)], limit=5, offset=10000),
        )
        pipeline = reports.pipelines[0]
        self.assertEqual(pipeline[2], {"$limit": 10005})
        self.assertEqual(pipeline[5], {"$skip": 10000})

    async def test_partial_indexes_never_count_as_covering(self):
        reports = FakeCollection(
            indexes=[
                {
                    "key": {"report.end_time": -1, "report.status": 1},
                    "partialFilterExpression": {"report.status": "changed"},
                }
            ]
        )
        engine = engine_with(reports=reports)
        await engine.run(
            "reports",
            ["=", "status", "changed"],
            paging=Paging(order_by=[("end_time", -1)], limit=5, offset=10000),
        )
        self.assertEqual(reports.pipelines[0][2], {"$limit": 10005})

    async def test_negated_node_state_pages_late(self):
        resources = FakeCollection()
        engine = engine_with(resources=resources)
        await engine.run(
            "resources",
            ["not", ["=", "node_state", "active"]],
            paging=Paging(order_by=[("certname", 1)], limit=5, offset=10),
        )
        pipeline = resources.pipelines[0]
        project_at = next(i for i, s in enumerate(pipeline) if "$project" in s)
        skip_at = next(i for i, s in enumerate(pipeline) if "$skip" in s)
        self.assertGreater(skip_at, project_at)

    async def test_paging_stays_late_when_a_filter_survives(self):
        reports = FakeCollection()
        engine = engine_with(reports=reports)
        await engine.run(
            "reports",
            ["not", ["=", "status", "changed"]],
            paging=Paging(order_by=[("end_time", -1)], limit=5),
        )
        pipeline = reports.pipelines[0]
        sort_at = next(i for i, s in enumerate(pipeline) if "$sort" in s)
        match_at = [i for i, s in enumerate(pipeline) if "$match" in s][-1]
        limit_at = next(i for i, s in enumerate(pipeline) if "$limit" in s)
        self.assertLess(sort_at, match_at)
        self.assertGreater(limit_at, match_at)
        self.assertEqual(len(stages(pipeline, "$sort")), 1)

    async def test_nodes_sort_uses_the_projection_source(self):
        nodes = FakeCollection()
        engine = engine_with(nodes)
        await engine.run(
            "nodes", None, paging=Paging(order_by=[("report_timestamp", 1)])
        )
        self.assertEqual(
            nodes.pipelines[0][0], {"$sort": {"report.end_time": 1}}
        )

    async def test_unwound_entities_sort_behind_the_unwind(self):
        nodes = FakeCollection()
        engine = engine_with(nodes)
        await engine.run(
            "facts", None, paging=Paging(order_by=[("name", -1)], limit=5)
        )
        pipeline = nodes.pipelines[0]
        sort_at = next(i for i, s in enumerate(pipeline) if "$sort" in s)
        unwind_at = [i for i, s in enumerate(pipeline) if "$unwind" in s][-1]
        project_at = [i for i, s in enumerate(pipeline) if "$project" in s][-1]
        self.assertGreater(sort_at, unwind_at)
        self.assertLess(sort_at, project_at)
        self.assertEqual(pipeline[sort_at], {"$sort": {"kv.k": -1}})
        self.assertEqual(pipeline[sort_at + 1], {"$limit": 5})

    async def test_computed_columns_are_not_hoisted(self):
        nodes = FakeCollection()
        engine = engine_with(nodes)
        await engine.run(
            "nodes", None, paging=Paging(order_by=[("deactivated", 1)], limit=5)
        )
        pipeline = nodes.pipelines[0]
        sort_at = next(i for i, s in enumerate(pipeline) if "$sort" in s)
        project_at = next(i for i, s in enumerate(pipeline) if "$project" in s)
        self.assertGreater(sort_at, project_at)

    async def test_aggregation_keeps_the_late_sort(self):
        reports = FakeCollection()
        engine = engine_with(reports=reports)
        await engine.run(
            "reports",
            [
                "from",
                "reports",
                ["extract", [["function", "count"], "status"], ["group_by", "status"]],
            ],
            paging=Paging(order_by=[("status", 1)]),
        )
        pipeline = reports.pipelines[0]
        sort_at = next(i for i, s in enumerate(pipeline) if "$sort" in s)
        group_at = next(i for i, s in enumerate(pipeline) if "$group" in s)
        self.assertGreater(sort_at, group_at)

    async def test_mixed_directions_on_one_path_are_not_hoisted(self):
        nodes = FakeCollection()
        engine = engine_with(nodes)
        await engine.run(
            "nodes",
            None,
            paging=Paging(
                order_by=[("catalog_environment", 1), ("facts_environment", -1)]
            ),
        )
        pipeline = nodes.pipelines[0]
        sort_at = next(i for i, s in enumerate(pipeline) if "$sort" in s)
        project_at = next(i for i, s in enumerate(pipeline) if "$project" in s)
        self.assertGreater(sort_at, project_at)

    def test_document_row_entities(self):
        expected = {
            "nodes": True,
            "reports": True,
            "factsets": True,
            "inventory": True,
            "catalogs": False,
            "catalog-inputs": True,
            "facts": False,
            "fact-names": False,
            "fact-contents": False,
            "fact-paths": False,
            "resources": True,
            "edges": True,
            "events": True,
            "packages": False,
            "catalog-input-contents": False,
            "environments": False,
            "producers": False,
        }
        for name, document_rows in expected.items():
            self.assertEqual(get_entity(name).document_rows, document_rows, name)

    async def test_aggregations_allow_disk_use(self):
        nodes = FakeCollection(counts=3)
        engine = engine_with(nodes)
        await engine.run(
            "nodes",
            ["not", ["=", "certname", "zzz"]],
            paging=Paging(limit=5, include_total=True),
        )
        self.assertEqual(len(nodes.options), 2)
        for options in nodes.options:
            self.assertTrue(options["allowDiskUse"])


class TestPythonEntityFetch(unittest.IsolatedAsyncioTestCase):
    document = {
        "id": "host1",
        "environment": "prod",
        "disabled": False,
        "facts": {"osfamily": "Debian", "uptime": 500},
    }

    async def run_query(self, entity_name, ast):
        nodes = FakeCollection(docs=[self.document])
        engine = engine_with(nodes)
        await engine.run(entity_name, ast)
        return nodes.finds[0]

    async def test_fact_contents_projects_only_expander_fields(self):
        _query, projection = await self.run_query("fact-contents", None)
        self.assertEqual(
            projection,
            {"_id": 0, "id": 1, "environment": 1, "disabled": 1, "facts": 1},
        )

    async def test_fact_paths_read_the_distinct_fact_paths(self):
        nodes = FakeCollection(
            docs=[self.document],
            distinct_values=build_fact_paths(self.document["facts"]),
        )
        engine = engine_with(nodes)
        rows, total = await engine.run("fact-paths", None)
        self.assertEqual(nodes.finds, [])
        self.assertEqual(nodes.distincts, [("fact_paths", None)])
        self.assertEqual(total, 2)
        self.assertEqual(
            sorted(rows, key=lambda row: row["name"]),
            [
                {"name": "osfamily", "path": ["osfamily"], "type": "string"},
                {"name": "uptime", "path": ["uptime"], "type": "integer"},
            ],
        )

    async def test_unfiltered_query_has_an_empty_document_filter(self):
        query, _projection = await self.run_query("fact-contents", None)
        self.assertEqual(query, {})

    async def test_certname_becomes_a_document_filter(self):
        query, _projection = await self.run_query(
            "fact-contents", ["=", "certname", "host1"]
        )
        self.assertEqual(query, {"id": "host1"})

    async def test_environment_becomes_a_document_filter(self):
        query, _projection = await self.run_query(
            "fact-contents", ["=", "environment", "prod"]
        )
        self.assertEqual(query, {"environment": "prod"})

    async def test_fact_name_becomes_a_key_existence_check(self):
        query, _projection = await self.run_query(
            "fact-contents", ["=", "name", "osfamily"]
        )
        self.assertEqual(
            query,
            {
                "$and": [
                    {"facts.osfamily": {"$exists": True}},
                    {"fact_paths": {"$in": ['[["osfamily"],"string"]']}},
                ]
            },
        )

    async def test_fact_paths_filter_the_distinct_entries(self):
        nodes = FakeCollection(
            distinct_values=build_fact_paths(
                {"os": {"family": "Debian", "release": {"major": 12}}, "uptime": 500}
            )
        )
        engine = engine_with(nodes)
        rows, _total = await engine.run("fact-paths", ["=", "type", "integer"])
        self.assertEqual(
            sorted(row["path"] for row in rows),
            [["os", "release", "major"], ["uptime"]],
        )
        rows, _total = await engine.run("fact-paths", ["=", "name", "os"])
        self.assertEqual(
            sorted(row["path"] for row in rows),
            [["os", "family"], ["os", "release", "major"]],
        )
        rows, _total = await engine.run(
            "fact-paths", ["~>", "path", ["os", "rel.*", "maj.*"]]
        )
        self.assertEqual([row["path"] for row in rows], [["os", "release", "major"]])

    async def test_node_state_becomes_a_document_filter(self):
        query, _projection = await self.run_query(
            "fact-contents", ["=", "node_state", "inactive"]
        )
        self.assertEqual(query, {"disabled": True})

    async def test_pinned_names_narrow_the_projection(self):
        _query, projection = await self.run_query(
            "fact-contents", ["in", "name", ["array", ["osfamily", "uptime"]]]
        )
        self.assertEqual(
            projection,
            {"_id": 0, "id": 1, "environment": 1, "disabled": 1,
             "facts.osfamily": 1, "facts.uptime": 1},
        )
        _query, projection = await self.run_query(
            "fact-contents", ["~", "name", "^os"]
        )
        self.assertEqual(
            projection,
            {"_id": 0, "id": 1, "environment": 1, "disabled": 1, "facts.osfamily": 1},
        )
        _query, projection = await self.run_query(
            "fact-contents", ["=", "value", "Debian"]
        )
        self.assertIn("facts", projection)

    async def test_path_filters_resolve_through_the_fact_paths(self):
        query, projection = await self.run_query(
            "fact-contents", ["~>", "path", ["upt.*"]]
        )
        self.assertEqual(query, {"fact_paths": {"$in": ['[["uptime"],"integer"]']}})
        self.assertEqual(
            projection,
            {"_id": 0, "id": 1, "environment": 1, "disabled": 1, "facts.uptime": 1},
        )

    async def test_path_filters_matching_nothing_read_nothing(self):
        nodes = FakeCollection(docs=[self.document])
        engine = engine_with(nodes)
        rows, total = await engine.run("fact-contents", ["~>", "path", ["nope"]])
        self.assertEqual((rows, total), ([], 0))
        self.assertEqual(nodes.finds, [])

    async def test_clauses_on_other_columns_do_not_narrow_the_paths(self):
        query, projection = await self.run_query(
            "fact-contents",
            ["or", ["=", "name", "uptime"], ["=", "value", "Debian"]],
        )
        self.assertNotIn("fact_paths", json.dumps(query))
        self.assertIn("facts", projection)

    async def test_negated_path_filters_do_not_narrow_the_paths(self):
        nodes = FakeCollection(docs=[self.document])
        engine = engine_with(nodes)
        rows, _total = await engine.run(
            "fact-contents", ["not", ["=", "name", "uptime"]]
        )
        self.assertEqual([row["name"] for row in rows], ["osfamily"])
        self.assertIn("facts", nodes.finds[0][1])


    async def test_value_alone_is_not_derivable(self):
        query, _projection = await self.run_query(
            "fact-contents", ["=", "value", "Debian"]
        )
        self.assertEqual(query, {})

    async def test_negation_yields_no_document_filter(self):
        query, _projection = await self.run_query(
            "fact-contents", ["not", ["=", "certname", "host1"]]
        )
        self.assertEqual(query, {})

    async def test_impossible_filter_skips_the_collection(self):
        nodes = FakeCollection(docs=[self.document])
        engine = engine_with(nodes, reports=FakeCollection())
        rows, total = await engine.run(
            "fact-contents",
            ["in", "certname", ["extract", "certname", ["select_reports", None]]],
        )
        self.assertEqual((rows, total), ([], 0))
        self.assertEqual(nodes.finds, [])

    async def test_prefilter_keeps_the_matching_document(self):
        nodes = FakeCollection(docs=[self.document])
        engine = engine_with(nodes)
        rows, _total = await engine.run(
            "fact-contents",
            ["and", ["=", "certname", "host1"], ["=", "name", "osfamily"]],
        )
        self.assertEqual(
            rows,
            [
                {
                    "certname": "host1",
                    "environment": "prod",
                    "name": "osfamily",
                    "path": ["osfamily"],
                    "value": "Debian",
                }
            ],
        )


class TestRowShape(unittest.IsolatedAsyncioTestCase):
    async def test_timestamps_stay_datetimes_for_the_serializer(self):
        stamp = datetime(2026, 3, 1, 12, 0)
        nodes = FakeCollection(docs=[{"certname": "a", "catalog_timestamp": stamp}])
        engine = engine_with(nodes)
        rows, _total = await engine.run("nodes", ["=", "certname", "a"])
        self.assertIs(rows[0]["catalog_timestamp"], stamp)

    async def test_missing_columns_are_filled_by_the_pipeline(self):
        nodes = FakeCollection(docs=[{"certname": "a"}])
        engine = engine_with(nodes)
        await engine.run("nodes", ["=", "certname", "a"])
        pipeline = nodes.pipelines[0]
        fill = pipeline[-1]["$set"]
        self.assertEqual(fill["catalog_timestamp"], {"$ifNull": ["$catalog_timestamp", None]})
        self.assertIn("latest_report_status", fill)
        self.assertNotIn("node_state", fill)

    async def test_null_fill_runs_after_match_and_paging(self):
        nodes = FakeCollection(docs=[{"certname": "a"}])
        engine = engine_with(nodes)
        await engine.run(
            "nodes", ["=", "certname", "a"], paging=Paging(limit=5, offset=2)
        )
        kinds = [next(iter(stage)) for stage in nodes.pipelines[0]]
        self.assertEqual(kinds[-1], "$set")
        self.assertLess(kinds.index("$match", kinds.index("$project")), kinds.index("$set"))
        self.assertLess(kinds.index("$limit"), kinds.index("$set"))

    async def test_aggregates_are_not_null_filled(self):
        nodes = FakeCollection(docs=[{"count": 1}])
        engine = engine_with(nodes)
        await engine.run("nodes", ["extract", [["function", "count"]], ["not", ["=", "certname", "b"]]])
        self.assertFalse(any("$set" in s for s in nodes.pipelines[0]))


class TestPythonExpansionBudget(unittest.IsolatedAsyncioTestCase):
    def docs(self, count):
        return [{"id": f"h{index}", "facts": {"a": 1, "b": 2}} for index in range(count)]

    async def test_stops_reading_once_the_page_is_full(self):
        from pyppetdb.pdb.query import engine as module

        nodes = FakeCollection(docs=self.docs(10))
        engine = engine_with(nodes)
        original = module.PYTHON_BATCH_SIZE
        module.PYTHON_BATCH_SIZE = 1
        try:
            rows, total = await engine.run(
                "fact-contents", None, paging=Paging(limit=3)
            )
        finally:
            module.PYTHON_BATCH_SIZE = original
        self.assertEqual(len(rows), 3)
        self.assertEqual(total, 4)

    async def test_certname_order_stops_reading_once_the_page_is_full(self):
        from pyppetdb.pdb.query import engine as module

        docs = list(reversed(self.docs(10)))
        nodes = FakeCollection(docs=docs)
        engine = engine_with(nodes)
        original = module.PYTHON_BATCH_SIZE
        module.PYTHON_BATCH_SIZE = 1
        try:
            rows, total = await engine.run(
                "fact-contents",
                None,
                paging=Paging(
                    limit=3,
                    offset=2,
                    order_by=[("certname", -1), ("name", 1)],
                ),
            )
        finally:
            module.PYTHON_BATCH_SIZE = original
        self.assertEqual(nodes.cursor.sorted_by, ("id", -1))
        self.assertEqual(
            [(row["certname"], row["name"]) for row in rows],
            [("h8", "a"), ("h8", "b"), ("h7", "a")],
        )
        self.assertEqual(total, 6)

    async def test_other_orders_still_read_everything(self):
        nodes = FakeCollection(docs=self.docs(10))
        engine = engine_with(nodes)
        rows, total = await engine.run(
            "fact-contents",
            None,
            paging=Paging(limit=3, order_by=[("name", 1), ("certname", 1)]),
        )
        self.assertFalse(hasattr(nodes.cursor, "sorted_by"))
        self.assertEqual(total, 20)
        self.assertEqual(
            [(row["name"], row["certname"]) for row in rows],
            [("a", "h0"), ("a", "h1"), ("a", "h2")],
        )

    async def test_include_total_reads_everything(self):
        nodes = FakeCollection(docs=self.docs(10))
        engine = engine_with(nodes)
        rows, total = await engine.run(
            "fact-contents", None, paging=Paging(limit=3, include_total=True)
        )
        self.assertEqual(len(rows), 3)
        self.assertEqual(total, 20)

    def test_an_expired_deadline_aborts_the_expansion(self):
        from pyppetdb.pdb.query.engine import _expand_batch
        from pyppetdb.pdb.query.engine import expand_fact_contents

        with self.assertRaises(PuppetDBQueryError) as ctx:
            _expand_batch(expand_fact_contents, self.docs(1), {}, 0.0)
        self.assertEqual(ctx.exception.status_code, 500)


if __name__ == "__main__":
    unittest.main()


class TestGroupKeysAndSubqueryLimits(unittest.IsolatedAsyncioTestCase):
    async def test_dotted_group_by_uses_a_safe_group_key(self):
        nodes = FakeCollection()
        engine = engine_with(nodes)
        await engine.run(
            "inventory",
            ["extract", [["function", "count"], "facts.os.family"], ["group_by", "facts.os.family"]],
        )
        pipeline = nodes.pipelines[0]
        group = [stage for stage in pipeline if "$group" in stage][-1]["$group"]
        self.assertEqual(group["_id"], {"facts__os__family": "$facts.os.family"})
        shaped = [stage for stage in pipeline if "$project" in stage][-1]["$project"]
        self.assertEqual(shaped["facts.os.family"], "$_id.facts__os__family")

    async def test_an_oversized_subquery_answers_400(self):
        class Exploding(FakeCollection):
            def aggregate(self, pipeline, **options):
                raise pymongo.errors.DocumentTooLarge("too large")

        engine = engine_with(Exploding())
        with self.assertRaises(PuppetDBQueryError) as ctx:
            await engine.run("nodes", ["=", "certname", "a"])
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("too large", str(ctx.exception))
