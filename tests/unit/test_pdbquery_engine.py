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

import logging
import unittest
from datetime import UTC
from datetime import datetime

from pyppetdb.pdbquery.engine import NEVER_MATCH
from pyppetdb.pdbquery.engine import QueryEngine
from pyppetdb.pdbquery.engine import build_prefilter
from pyppetdb.pdbquery.engine import expand_fact_contents
from pyppetdb.pdbquery.engine import expand_fact_paths
from pyppetdb.pdbquery.engine import convert_timestamps
from pyppetdb.pdbquery.engine import output_timestamp_fields
from pyppetdb.pdbquery.entities import ENTITIES
from pyppetdb.pdbquery.entities import get_entity
from pyppetdb.pdbquery.errors import PuppetDBQueryError
from pyppetdb.pdbquery.paging import Paging
from pyppetdb.pdbquery.ast import FilterCompiler
from pyppetdb.pdbquery.ast import Query


class FakeCursor:
    def __init__(self, docs):
        self._docs = docs

    async def to_list(self, length=None):
        return list(self._docs)


class FakeCollection:
    def __init__(self, docs=None, counts=None):
        self.docs = docs or []
        self.counts = counts
        self.pipelines = []
        self.options = []
        self.finds = []

    def aggregate(self, pipeline, **options):
        self.pipelines.append(pipeline)
        self.options.append(options)
        if pipeline and pipeline[-1] == {"$count": "count"}:
            return FakeCursor([{"count": self.counts}] if self.counts else [])
        return FakeCursor(self.docs)

    def find(self, query=None, projection=None):
        self.finds.append((query, projection))
        return FakeCursor(self.docs)


def stage(pipeline, name):
    for item in pipeline:
        if name in item:
            return item[name]
    return None


def stages(pipeline, name):
    return [item[name] for item in pipeline if name in item]


def engine_with(nodes=None, reports=None, aggregate_cache_ttl=0):
    return QueryEngine(
        log=logging.getLogger("test"),
        collections={
            "nodes": nodes or FakeCollection(),
            "nodes_reports": reports or FakeCollection(),
        },
        aggregate_cache_ttl=aggregate_cache_ttl,
    )


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
        nodes = FakeCollection(docs=[{"certname": "a"}])
        engine = engine_with(nodes)
        rows, _total = await engine.run("nodes", ["=", "certname", "a"])
        self.assertIsNone(rows[0]["catalog_timestamp"])
        self.assertIn("latest_report_status", rows[0])
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
        nodes = FakeCollection()
        engine = engine_with(nodes)
        await engine.run("resources", ["=", "type", "File"])
        pipeline = nodes.pipelines[0]
        self.assertEqual(
            pipeline[0], {"$match": {"catalog.resources.type": "File"}}
        )
        project_at = next(i for i, s in enumerate(pipeline) if "$project" in s)
        self.assertLess(0, project_at)

    async def test_no_prefilter_when_nothing_is_derivable(self):
        nodes = FakeCollection()
        engine = engine_with(nodes)
        await engine.run("resources", ["not", ["=", "type", "File"]])
        entity = get_entity("resources")
        self.assertEqual(nodes.pipelines[0][0], entity.build_stages()[0])

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

    async def test_subquery_deduplicates_in_the_pipeline(self):
        nodes = FakeCollection(docs=[{"certname": "a"}, {"certname": "b"}])
        engine = engine_with(nodes)
        await engine.run(
            "nodes",
            [
                "in",
                "certname",
                ["extract", "certname", ["select_resources", ["=", "type", "File"]]],
            ],
        )
        pipeline = nodes.pipelines[0]
        group_at = next(i for i, s in enumerate(pipeline) if "$group" in s)
        limit_at = next(i for i, s in enumerate(pipeline) if "$limit" in s)
        self.assertEqual(
            pipeline[group_at]["$group"], {"_id": {"certname": "$certname"}}
        )
        self.assertLess(group_at, limit_at)

    async def test_subquery_rows_are_deduplicated(self):
        nodes = FakeCollection(
            docs=[{"certname": "a"}, {"certname": "a"}, {"certname": "b"}]
        )
        engine = engine_with(nodes)
        rows = await engine.select("resources", ["certname"], ["=", "type", "File"])
        self.assertEqual(rows, [("a",), ("b",)])

    async def test_subquery_keeps_unhashable_rows(self):
        nodes = FakeCollection(docs=[{"tags": ["a"]}, {"tags": ["a"]}])
        engine = engine_with(nodes)
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
            nodes.pipelines[0][-1], {"$project": {"_id": 0, "certname": 1}}
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
        nodes = FakeCollection()
        engine = engine_with(nodes)
        await engine.run(
            "resources",
            ["=", "title", "t"],
            implicit=[["=", "type", "File"]],
        )
        match = nodes.pipelines[0][-1]["$match"]
        self.assertEqual(match, {"$and": [{"type": "File"}, {"title": "t"}]})

    async def test_fact_names_returns_scalars(self):
        nodes = FakeCollection(docs=[{"name": "os"}, {"name": "kernel"}])
        engine = engine_with(nodes)
        rows, _total = await engine.run("fact-names", None)
        self.assertEqual(rows, ["os", "kernel"])

    async def test_reports_use_report_collection(self):
        reports = FakeCollection(docs=[{"certname": "a"}])
        engine = engine_with(reports=reports)
        rows, _total = await engine.run("reports", ["=", "certname", "a"])
        self.assertEqual([row["certname"] for row in rows], ["a"])
        self.assertTrue(reports.pipelines)

    async def test_select_returns_tuples(self):
        nodes = FakeCollection(docs=[{"certname": "a"}, {"certname": "b"}])
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
            "nodes", ["extract", [["function", "count"]]]
        )
        self.assertEqual(set(projection), {"_id", "_row"})


class TestElementFilter(unittest.IsolatedAsyncioTestCase):
    async def cond(self, entity_name, ast):
        entity = get_entity(entity_name)
        compiler = FilterCompiler(entity, engine=engine_with())
        match = await compiler.compile(ast)
        from pyppetdb.pdbquery.engine import build_element_filter

        return build_element_filter(entity, match)

    async def test_equality_on_element_field(self):
        self.assertEqual(
            await self.cond("resources", ["=", "type", "File"]),
            {"$eq": ["$$item.type", "File"]},
        )

    async def test_conjunction(self):
        self.assertEqual(
            await self.cond(
                "resources", ["and", ["=", "type", "File"], ["=", "title", "/x"]]
            ),
            {"$and": [{"$eq": ["$$item.type", "File"]}, {"$eq": ["$$item.title", "/x"]}]},
        )

    async def test_document_level_clause_is_ignored(self):
        self.assertEqual(
            await self.cond(
                "resources", ["and", ["=", "certname", "a"], ["=", "type", "File"]]
            ),
            {"$eq": ["$$item.type", "File"]},
        )

    async def test_or_with_a_document_level_branch_yields_nothing(self):
        self.assertIsNone(
            await self.cond(
                "resources", ["or", ["=", "certname", "a"], ["=", "type", "File"]]
            )
        )

    async def test_negation_yields_nothing(self):
        self.assertIsNone(
            await self.cond("resources", ["not", ["=", "type", "File"]])
        )

    async def test_tag_uses_membership(self):
        self.assertEqual(
            await self.cond("resources", ["=", "tag", "one"]),
            {"$in": ["one", {"$ifNull": ["$$item.tags", []]}]},
        )

    async def test_dotted_parameter(self):
        self.assertEqual(
            await self.cond("resources", ["=", ["parameter", "owner"], "root"]),
            {"$eq": ["$$item.parameters.owner", "root"]},
        )

    async def test_regex(self):
        self.assertEqual(
            await self.cond("resources", ["~", "title", "^/opt"]),
            {
                "$cond": [
                    {"$eq": [{"$type": "$$item.title"}, "string"]},
                    {"$regexMatch": {"input": "$$item.title", "regex": "^/opt"}},
                    False,
                ]
            },
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

    async def test_range_excludes_null(self):
        self.assertEqual(
            await self.cond("resources", [">", "line", 5]),
            {"$and": [{"$ne": ["$$item.line", None]}, {"$gt": ["$$item.line", 5]}]},
        )

    async def test_default_value_equality_is_skipped(self):
        self.assertIsNone(await self.cond("resources", ["=", "exported", False]))

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

    async def test_filter_is_wired_into_the_pipeline(self):
        nodes = FakeCollection()
        engine = engine_with(nodes)
        await engine.run("resources", ["=", "type", "File"])
        project = stage(nodes.pipelines[0], "$project")
        self.assertEqual(
            project["resource"]["$filter"]["cond"],
            {"$eq": ["$$item.type", "File"]},
        )


class TestPinnedFactKeys(unittest.IsolatedAsyncioTestCase):
    async def pinned(self, entity_name, ast):
        from pyppetdb.pdbquery.engine import build_pinned_keys

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


class TestAggregateCache(unittest.IsolatedAsyncioTestCase):
    async def test_repeated_query_hits_the_cache(self):
        nodes = FakeCollection(docs=[{"name": "os"}])
        engine = engine_with(nodes, aggregate_cache_ttl=60)
        first, _ = await engine.run("fact-names", None)
        second, _ = await engine.run("fact-names", None)
        self.assertEqual(first, ["os"])
        self.assertEqual(second, ["os"])
        self.assertEqual(len(nodes.pipelines), 1)

    async def test_cache_is_off_by_default_in_tests(self):
        nodes = FakeCollection(docs=[{"name": "os"}])
        engine = engine_with(nodes)
        await engine.run("fact-names", None)
        await engine.run("fact-names", None)
        self.assertEqual(len(nodes.pipelines), 2)

    async def test_only_cacheable_entities_are_cached(self):
        nodes = FakeCollection(docs=[{"certname": "a"}])
        engine = engine_with(nodes, aggregate_cache_ttl=60)
        await engine.run("nodes", None)
        await engine.run("nodes", None)
        self.assertEqual(len(nodes.pipelines), 2)

    async def test_a_filtered_query_is_never_cached(self):
        nodes = FakeCollection(docs=[{"name": "prod"}])
        engine = engine_with(nodes, aggregate_cache_ttl=60)
        await engine.run("environments", ["=", "name", "prod"])
        await engine.run("environments", ["=", "name", "prod"])
        self.assertEqual(len(nodes.pipelines), 2)

    async def test_paging_bypasses_the_cache(self):
        from pyppetdb.pdbquery.paging import parse_paging

        nodes = FakeCollection(docs=[{"name": "prod"}])
        engine = engine_with(nodes, aggregate_cache_ttl=60)
        await engine.run("environments", None, paging=parse_paging({"limit": "1"}))
        after_first = len(nodes.pipelines)
        await engine.run("environments", None, paging=parse_paging({"limit": "1"}))
        self.assertGreater(len(nodes.pipelines), after_first)

    async def test_expired_entry_is_refetched(self):
        nodes = FakeCollection(docs=[{"name": "os"}])
        engine = engine_with(nodes, aggregate_cache_ttl=60)
        await engine.run("fact-names", None)
        engine._aggregate_cache["fact-names"] = (
            0.0,
            *engine._aggregate_cache["fact-names"][1:],
        )
        await engine.run("fact-names", None)
        self.assertEqual(len(nodes.pipelines), 2)


class TestNestedElementFilter(unittest.IsolatedAsyncioTestCase):
    async def cond(self, ast):
        from pyppetdb.pdbquery.engine import build_element_filter

        entity = get_entity("events")
        match = await FilterCompiler(entity, engine=engine_with()).compile(ast)
        return build_element_filter(entity, match)

    async def test_event_level_column_lands_in_the_inner_filter(self):
        cond = await self.cond(["=", "status", "failure"])
        self.assertEqual(cond["inner"], {"$eq": ["$$nested.status", "failure"]})
        self.assertIn("$gt", cond["outer"])

    async def test_resource_level_column_lands_in_the_outer_filter(self):
        cond = await self.cond(["=", "resource_type", "File"])
        self.assertEqual(cond["outer"], {"$eq": ["$$item.resource_type", "File"]})
        self.assertIsNone(cond["inner"])

    async def test_both_levels_combine(self):
        cond = await self.cond(
            ["and", ["=", "status", "failure"], ["=", "resource_type", "File"]]
        )
        self.assertEqual(cond["inner"], {"$eq": ["$$nested.status", "failure"]})
        self.assertIn("$and", cond["outer"])

    async def test_document_level_column_yields_nothing(self):
        self.assertIsNone(await self.cond(["=", "certname", "a"]))

    async def test_negation_yields_nothing(self):
        self.assertIsNone(await self.cond(["not", ["=", "status", "failure"]]))

    async def test_stages_keep_both_unwinds(self):
        entity = get_entity("events")
        stages = entity.build_stages(
            {"outer": {"$literal": True}, "inner": {"$literal": True}}
        )
        unwinds = [item["$unwind"] for item in stages if "$unwind" in item]
        self.assertEqual(unwinds, ["$report.resources", "$report.resources.events"])
        self.assertTrue(any("$addFields" in item for item in stages))

    async def test_stages_without_a_condition_do_not_filter(self):
        stages = get_entity("events").build_stages()
        self.assertFalse(any("$addFields" in item for item in stages))


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
            {"catalog.resources.type": "File"},
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
            {"catalog.resources.parameters.owner": "root"},
        )

    async def test_and_collects_every_derivable_clause(self):
        self.assertEqual(
            await self.prefilter(
                "resources", ["and", ["=", "type", "File"], ["=", "title", "/x"]]
            ),
            {
                "$and": [
                    {"catalog.resources.type": "File"},
                    {"catalog.resources.title": "/x"},
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
        self.assertEqual(result, {"catalog.resources.type": "File"})

    async def test_or_requires_every_branch(self):
        both = await self.prefilter(
            "resources", ["or", ["=", "type", "File"], ["=", "type", "Package"]]
        )
        self.assertEqual(
            both,
            {
                "$or": [
                    {"catalog.resources.type": "File"},
                    {"catalog.resources.type": "Package"},
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
            {"catalog.resources.exported": True},
        )

    async def test_range_and_regex_are_derivable(self):
        self.assertEqual(
            await self.prefilter("resources", [">", "line", 5]),
            {"catalog.resources.line": {"$gt": 5}},
        )
        self.assertEqual(
            await self.prefilter("resources", ["~", "title", "^/opt"]),
            {"catalog.resources.title": {"$regex": "^/opt"}},
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
        from pyppetdb.pdbquery import matcher

        documents = [
            {
                "id": "one",
                "environment": "prod",
                "catalog": {
                    "resources": [
                        {"type": "File", "title": "/a", "exported": True, "line": 3},
                        {"type": "Package", "title": "/b", "line": 9},
                    ]
                },
            },
            {
                "id": "two",
                "environment": "dev",
                "catalog": {
                    "resources": [
                        {"type": "Service", "title": "/a", "line": 1},
                    ]
                },
            },
            {"id": "three", "environment": "prod", "catalog": {"resources": []}},
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
            unwound = [
                {**document, "resource": resource}
                for document in documents
                for resource in document["catalog"]["resources"]
            ]
            projected = [
                {
                    "certname": row["id"],
                    "environment": row["environment"],
                    "type": row["resource"].get("type"),
                    "title": row["resource"].get("title"),
                    "exported": row["resource"].get("exported", False),
                    "line": row["resource"].get("line"),
                    "parameters": row["resource"].get("parameters", {}),
                    "tags": row["resource"].get("tags", []),
                    "_source": row["id"],
                }
                for row in unwound
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

    async def test_node_prefilter_never_narrows_the_result(self):
        from pyppetdb.pdbquery import matcher

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
        rows = expand_fact_paths(self.document)
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
        rows = expand_fact_paths(self.document)
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
        self.assertEqual(len(nodes.pipelines), 2)
        self.assertEqual(nodes.pipelines[0][-1], {"$count": "count"})
        self.assertEqual(total, 42)

    async def test_count_pipeline_has_no_paging_stages(self):
        nodes = FakeCollection(counts=42)
        engine = engine_with(nodes)
        await engine.run(
            "nodes", None, paging=Paging(limit=5, offset=3, include_total=True)
        )
        counting = nodes.pipelines[0]
        self.assertIsNone(stage(counting, "$limit"))
        self.assertIsNone(stage(counting, "$skip"))

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
        reports = FakeCollection(docs=[{"certname": "a"}], counts=7)
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

    async def test_paging_stays_late_when_a_filter_survives(self):
        reports = FakeCollection()
        engine = engine_with(reports=reports)
        await engine.run(
            "reports",
            ["=", "status", "changed"],
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

    async def test_unwound_entities_keep_the_late_sort(self):
        reports = FakeCollection()
        engine = engine_with(reports=reports)
        await engine.run(
            "events", None, paging=Paging(order_by=[("timestamp", -1)], limit=5)
        )
        pipeline = reports.pipelines[0]
        sort_at = next(i for i, s in enumerate(pipeline) if "$sort" in s)
        project_at = [i for i, s in enumerate(pipeline) if "$project" in s][-1]
        self.assertGreater(sort_at, project_at)
        self.assertEqual(pipeline[sort_at], {"$sort": {"timestamp": -1}})

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
            "catalogs": True,
            "catalog-inputs": True,
            "facts": False,
            "fact-names": False,
            "fact-contents": False,
            "fact-paths": False,
            "resources": False,
            "edges": False,
            "events": False,
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
            "nodes", None, paging=Paging(limit=5, include_total=True)
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

    async def test_fact_paths_projects_only_facts(self):
        _query, projection = await self.run_query("fact-paths", None)
        self.assertEqual(projection, {"_id": 0, "facts": 1})

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
        self.assertEqual(query, {"facts.osfamily": {"$exists": True}})

    async def test_fact_paths_name_becomes_a_key_existence_check(self):
        query, _projection = await self.run_query(
            "fact-paths", ["=", "name", "osfamily"]
        )
        self.assertEqual(query, {"facts.osfamily": {"$exists": True}})

    async def test_node_state_becomes_a_document_filter(self):
        query, _projection = await self.run_query(
            "fact-contents", ["=", "node_state", "inactive"]
        )
        self.assertEqual(query, {"disabled": True})

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


class TestTimestampConversion(unittest.IsolatedAsyncioTestCase):
    def test_projected_timestamp_columns_become_iso_z(self):
        entity = get_entity("nodes")
        rows = [{"certname": "a", "catalog_timestamp": datetime(2026, 3, 1, 12, 0)}]
        convert_timestamps(entity, Query(entity="nodes"), rows)
        self.assertEqual(rows[0]["catalog_timestamp"], "2026-03-01T12:00:00Z")
        self.assertEqual(rows[0]["certname"], "a")

    def test_aware_datetimes_keep_a_single_zulu_marker(self):
        entity = get_entity("nodes")
        rows = [{"catalog_timestamp": datetime(2026, 3, 1, 12, 0, tzinfo=UTC)}]
        convert_timestamps(entity, Query(entity="nodes"), rows)
        self.assertEqual(rows[0]["catalog_timestamp"], "2026-03-01T12:00:00Z")

    def test_extract_limits_the_conversion(self):
        entity = get_entity("nodes")
        fields = output_timestamp_fields(
            entity, Query(entity="nodes", columns=["certname", "report_timestamp"])
        )
        self.assertEqual(fields, ["report_timestamp"])

    def test_entity_without_timestamps_needs_no_work(self):
        entity = get_entity("resources")
        self.assertEqual(output_timestamp_fields(entity, Query(entity="resources")), [])

    def test_min_max_alias_is_converted(self):
        from pyppetdb.pdbquery.ast import Function

        entity = get_entity("reports")
        query = Query(
            entity="reports",
            functions=[Function(name="max", column="end_time", alias="max")],
        )
        self.assertEqual(output_timestamp_fields(entity, query), ["max"])

    def test_non_timestamp_values_are_untouched(self):
        entity = get_entity("nodes")
        rows = [{"catalog_timestamp": None, "certname": "a"}]
        convert_timestamps(entity, Query(entity="nodes"), rows)
        self.assertIsNone(rows[0]["catalog_timestamp"])


if __name__ == "__main__":
    unittest.main()
