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
from unittest.mock import MagicMock
from unittest.mock import PropertyMock
from unittest.mock import patch

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pyppetdb.config import ConfigAppFacts
from pyppetdb.config import ConfigAppPuppetdb
from pyppetdb.controller.pdb.query.v4 import ControllerPdbQueryV4
from pyppetdb.controller.pdb.query.v4 import apply_local_paging
from pyppetdb.controller.pdb.query.v4 import json_response
from pyppetdb.controller.pdb.query.v4 import stream_response
from pyppetdb.pdb.query.engine import RowStream
from pyppetdb.pdb.query import event_counts
from pyppetdb.pdb.query.errors import PuppetDBQueryError
from pyppetdb.pdb.query.paging import Paging


def build(config_kwargs=None):
    config = MagicMock()
    config.app.puppetdb = ConfigAppPuppetdb(**(config_kwargs or {}))
    config.app.main.facts = ConfigAppFacts()
    config.app.main.ssl = None
    authorize = MagicMock()
    authorize.require_cn_trusted = AsyncMock(return_value="admin")
    controller = ControllerPdbQueryV4(
        log=logging.getLogger("test"),
        config=config,
        crud_nodes=MagicMock(),
        crud_nodes_reports=MagicMock(),
        authorize_client_cert=authorize,
    )
    controller.engine.exists = AsyncMock(return_value=True)
    app = FastAPI()
    app.include_router(controller.router, prefix="/pdb/query/v4")
    return controller, TestClient(app), authorize


class TestQueryRouting(unittest.TestCase):
    def setUp(self):
        self.controller, self.client, self.authorize = build()
        self.run = AsyncMock(return_value=([{"certname": "a"}], 1))
        self.controller.engine.run = self.run

    def test_entity_endpoint_uses_entity(self):
        response = self.client.get("/pdb/query/v4/nodes")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [{"certname": "a"}])
        self.assertEqual(self.run.await_args.kwargs["entity_name"], "nodes")

    def test_requires_trusted_client_cert(self):
        self.client.get("/pdb/query/v4/nodes")
        self.authorize.require_cn_trusted.assert_awaited()

    def test_get_query_param_is_parsed(self):
        self.client.get(
            "/pdb/query/v4/nodes", params={"query": '["=", "certname", "a"]'}
        )
        self.assertEqual(self.run.await_args.kwargs["ast"], ["=", "certname", "a"])

    def test_post_body_with_query_key(self):
        self.client.post(
            "/pdb/query/v4/nodes", json={"query": ["=", "certname", "a"], "limit": 3}
        )
        self.assertEqual(self.run.await_args.kwargs["ast"], ["=", "certname", "a"])
        self.assertEqual(self.run.await_args.kwargs["paging"].limit, 3)

    def test_post_body_must_be_a_map(self):
        response = self.client.post("/pdb/query/v4/nodes", json=["=", "certname", "a"])
        self.assertEqual(response.status_code, 400)
        self.client.post("/pdb/query/v4/nodes", json={"query": ["=", "certname", "a"]})
        self.assertEqual(self.run.await_args.kwargs["ast"], ["=", "certname", "a"])

    def test_path_parameters_become_implicit_filters(self):
        self.client.get("/pdb/query/v4/resources/File/%2Ftmp%2Fx")
        self.assertEqual(
            self.run.await_args.kwargs["implicit"],
            [["=", "type", "File"], ["=", "title", "/tmp/x"]],
        )

    def test_node_subpath_scopes_to_certname(self):
        self.client.get("/pdb/query/v4/nodes/host1/facts")
        self.assertEqual(self.run.await_args.kwargs["entity_name"], "facts")
        self.assertEqual(
            self.run.await_args.kwargs["implicit"], [["=", "certname", "host1"]]
        )

    def test_environment_endpoint_maps_to_name(self):
        self.client.get("/pdb/query/v4/environments/prod")
        self.assertEqual(
            self.run.await_args.kwargs["implicit"], [["=", "name", "prod"]]
        )

    def test_single_resource_returns_object(self):
        response = self.client.get("/pdb/query/v4/nodes/host1")
        self.assertEqual(response.json(), {"certname": "a"})

    def test_single_resource_missing_is_404(self):
        self.controller.engine.run = AsyncMock(return_value=([], 0))
        response = self.client.get("/pdb/query/v4/nodes/host1")
        self.assertEqual(response.status_code, 404)

    def test_include_total_sets_header(self):
        self.controller.engine.run = AsyncMock(return_value=([{"a": 1}], 17))
        response = self.client.get(
            "/pdb/query/v4/nodes", params={"include_total": "true"}
        )
        self.assertEqual(response.headers["X-Records"], "17")

    def test_include_total_absent_by_default(self):
        response = self.client.get("/pdb/query/v4/nodes")
        self.assertNotIn("x-records", response.headers)

    def test_root_requires_from(self):
        response = self.client.get(
            "/pdb/query/v4", params={"query": '["=", "certname", "a"]'}
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("from", response.text)

    def test_root_uses_from_entity(self):
        self.client.get(
            "/pdb/query/v4", params={"query": '["from", "facts", ["=", "name", "os"]]'}
        )
        self.assertEqual(self.run.await_args.kwargs["entity_name"], "facts")


class TestQueryErrors(unittest.TestCase):
    def setUp(self):
        self.controller, self.client, _ = build()

    def test_malformed_json_query_is_400(self):
        response = self.client.get("/pdb/query/v4/nodes", params={"query": "[not json"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("malformed query", response.text)

    def test_pql_is_rejected_with_explanation(self):
        response = self.client.get(
            "/pdb/query/v4/nodes", params={"query": "nodes { certname = 'a' }"}
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("PQL", response.text)

    def test_unknown_field_is_400(self):
        response = self.client.get(
            "/pdb/query/v4/nodes", params={"query": '["=", "sourcefile", "/foo"]'}
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("is not a queryable object for nodes", response.text)

    def test_bad_limit_is_400(self):
        response = self.client.get("/pdb/query/v4/nodes", params={"limit": "0"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("positive non-zero integer", response.text)

    def test_engine_error_is_surfaced(self):
        self.controller.engine.run = AsyncMock(
            side_effect=PuppetDBQueryError("boom", status_code=400)
        )
        response = self.client.get("/pdb/query/v4/nodes")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.text, "boom")


class TestQuerySourceSwitch(unittest.TestCase):
    def test_internal_is_the_default(self):
        controller, client, _ = build()
        controller.engine.run = AsyncMock(return_value=([], 0))
        client.get("/pdb/query/v4/nodes")
        controller.engine.run.assert_awaited()

    def test_upstream_forwards_and_skips_engine(self):
        controller, client, _ = build(
            {"serverurl": "https://pdb:8081", "querySource": "upstream"}
        )
        controller.engine.run = AsyncMock(return_value=([], 0))
        upstream = MagicMock()
        upstream.content = json.dumps([{"certname": "remote"}]).encode()
        upstream.status_code = 200
        upstream.headers = {"content-type": "application/json", "x-records": "5"}

        with patch.object(
            ControllerPdbQueryV4, "http", new_callable=PropertyMock
        ) as http_property:
            client_mock = AsyncMock(spec=httpx.AsyncClient)
            client_mock.request.return_value = upstream
            http_property.return_value = client_mock
            response = client.get("/pdb/query/v4/nodes")

        self.assertEqual(response.json(), [{"certname": "remote"}])
        self.assertEqual(response.headers["X-Records"], "5")
        controller.engine.run.assert_not_awaited()
        called = client_mock.request.await_args.kwargs
        self.assertEqual(called["url"], "https://pdb:8081/pdb/query/v4/nodes")

    def test_upstream_strips_hop_headers(self):
        controller, client, _ = build(
            {"serverurl": "https://pdb:8081", "querySource": "upstream"}
        )
        upstream = MagicMock()
        upstream.content = b"[]"
        upstream.status_code = 200
        upstream.headers = {"content-type": "application/json"}

        with patch.object(
            ControllerPdbQueryV4, "http", new_callable=PropertyMock
        ) as http_property:
            client_mock = AsyncMock(spec=httpx.AsyncClient)
            client_mock.request.return_value = upstream
            http_property.return_value = client_mock
            client.get("/pdb/query/v4/nodes")

        headers = client_mock.request.await_args.kwargs["headers"]
        for name in ("host", "content-length", "transfer-encoding", "connection"):
            self.assertNotIn(name, {key.lower() for key in headers})

    def test_legacy_resource_flag_only_affects_resources(self):
        controller, client, _ = build(
            {"serverurl": "https://pdb:8081", "resourceQueryInternal": False}
        )
        controller.engine.run = AsyncMock(return_value=([], 0))
        upstream = MagicMock()
        upstream.content = b"[]"
        upstream.status_code = 200
        upstream.headers = {"content-type": "application/json"}

        with patch.object(
            ControllerPdbQueryV4, "http", new_callable=PropertyMock
        ) as http_property:
            client_mock = AsyncMock(spec=httpx.AsyncClient)
            client_mock.request.return_value = upstream
            http_property.return_value = client_mock
            client.get("/pdb/query/v4/resources")
            client.get("/pdb/query/v4/nodes")

        self.assertEqual(client_mock.request.await_count, 1)
        controller.engine.run.assert_awaited_once()

    def test_upstream_without_serverurl_is_rejected_by_config(self):
        with self.assertRaises(ValueError):
            ConfigAppPuppetdb(querySource="upstream")


class TestUpstreamRouteBehaviour(unittest.TestCase):
    def setUp(self):
        self.controller, self.client, _ = build()
        self.run = AsyncMock(return_value=([{"certname": "a"}], 1))
        self.controller.engine.run = self.run

    def test_unknown_parameter_is_a_400(self):
        response = self.client.get("/pdb/query/v4/nodes", params={"bogus": "1"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.text, "Unsupported query parameter 'bogus'")

    def test_root_requires_a_query(self):
        response = self.client.get("/pdb/query/v4")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.text, "Missing required query parameter 'query'")

    def test_entity_lists_are_restricted_to_active_nodes(self):
        self.client.get("/pdb/query/v4/nodes")
        self.assertTrue(self.run.await_args.kwargs["restrict_active"])
        self.client.get("/pdb/query/v4/reports")
        self.assertFalse(self.run.await_args.kwargs["restrict_active"])
        self.client.get("/pdb/query/v4/nodes/a")
        self.assertFalse(self.run.await_args.kwargs["restrict_active"])

    def test_root_restriction_skips_entities_without_certname(self):
        self.client.get("/pdb/query/v4", params={"query": '["from", "nodes"]'})
        self.assertTrue(self.run.await_args.kwargs["restrict_active"])
        self.client.get("/pdb/query/v4", params={"query": '["from", "fact_paths"]'})
        self.assertFalse(self.run.await_args.kwargs["restrict_active"])

    def test_ast_only_echoes_the_query(self):
        response = self.client.get(
            "/pdb/query/v4",
            params={"query": '["from", "nodes", ["=", "certname", "x"]]', "ast_only": "true"},
        )
        self.assertEqual(response.json(), ["from", "nodes", ["=", "certname", "x"]])
        self.run.assert_not_awaited()

    def test_child_routes_check_the_parent(self):
        self.controller.engine.exists = AsyncMock(return_value=False)
        response = self.client.get("/pdb/query/v4/nodes/nope/facts")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.json(), {"error": "No information is known about node nope"}
        )
        self.controller.engine.exists.assert_awaited_once_with("nodes", "certname", "nope")

    def test_single_routes_answer_a_json_404(self):
        self.controller.engine.run = AsyncMock(return_value=([], 0))
        response = self.client.get("/pdb/query/v4/environments/nope")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.json(), {"error": "No information is known about environment nope"}
        )

    def test_nested_routes_exist(self):
        for path, entity in (
            ("/nodes/a/facts/os/linux", "facts"),
            ("/nodes/a/resources/File/%2Fx", "resources"),
            ("/environments/prod/facts/os", "facts"),
            ("/environments/prod/resources/File", "resources"),
            ("/environments/prod/reports/abc/events", "events"),
            ("/producers/p/factsets", "factsets"),
            ("/producers/p/catalogs/a/edges", "edges"),
            ("/producers/p/reports", "reports"),
            ("/factsets/a/facts", "factsets"),
            ("/package-inventory/a", "packages"),
            ("/catalogs/a/resources/File/x", "resources"),
        ):
            self.run.reset_mock()
            response = self.client.get("/pdb/query/v4" + path)
            self.assertEqual(response.status_code, 200, msg=path)
            self.assertEqual(self.run.await_args.kwargs["entity_name"], entity, msg=path)

    def test_environment_children_carry_the_environment_filter(self):
        self.client.get("/pdb/query/v4/environments/prod/reports/abc/events")
        self.assertEqual(
            self.run.await_args.kwargs["implicit"],
            [["=", "environment", "prod"], ["=", "report", "abc"]],
        )

    def test_report_metrics_and_logs_return_the_data_array(self):
        self.controller.engine.run = AsyncMock(
            return_value=([{"metrics": {"href": "/x", "data": [{"name": "total"}]}}], 1)
        )
        response = self.client.get("/pdb/query/v4/reports/abc/metrics")
        self.assertEqual(response.json(), [{"name": "total"}])
        kwargs = self.controller.engine.run.await_args.kwargs
        self.assertEqual(kwargs["ast"], ["extract", ["metrics"]])
        self.assertEqual(kwargs["implicit"], [["=", "hash", "abc"]])

    def test_pretty_indents_the_output(self):
        response = self.client.get("/pdb/query/v4/nodes", params={"pretty": "true"})
        self.assertIn("\n", response.text)

    def test_include_flags_add_extra_columns(self):
        self.client.get("/pdb/query/v4/nodes", params={"include_facts_expiration": "true"})
        self.assertEqual(
            self.run.await_args.kwargs["extra_columns"],
            ["expires_facts", "expires_facts_updated"],
        )
        self.client.get("/pdb/query/v4/factsets", params={"include_package_inventory": "true"})
        self.assertEqual(self.run.await_args.kwargs["extra_columns"], ["package_inventory"])
        self.client.get("/pdb/query/v4/nodes", params={"include_package_inventory": "true"})
        self.assertEqual(self.run.await_args.kwargs["extra_columns"], [])
        self.client.get("/pdb/query/v4/nodes/a", params={"include_facts_expiration": "true"})
        self.assertEqual(
            self.run.await_args.kwargs["extra_columns"],
            ["expires_facts", "expires_facts_updated"],
        )
        self.client.get("/pdb/query/v4/factsets/a", params={"include_package_inventory": "true"})
        self.assertEqual(self.run.await_args.kwargs["extra_columns"], [])

    def test_distinct_window_reaches_the_engine(self):
        self.client.get(
            "/pdb/query/v4/events",
            params={
                "distinct_resources": "true",
                "distinct_start_time": "2026-01-01T00:00:00Z",
                "distinct_end_time": "2026-01-02T00:00:00Z",
            },
        )
        window = self.run.await_args.kwargs["distinct_window"]
        self.assertEqual(window[0].isoformat(), "2026-01-01T00:00:00+00:00")

    def test_explain_uses_the_explain_entry_point(self):
        self.controller.engine.explain = AsyncMock(return_value=[{"query plan": {}}])
        response = self.client.get("/pdb/query/v4/nodes", params={"explain": "analyze"})
        self.assertEqual(response.json(), [{"query plan": {}}])
        self.run.assert_not_awaited()

    def test_float_timeout_is_accepted(self):
        response = self.client.get("/pdb/query/v4/nodes", params={"timeout": "1.5"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.run.await_args.kwargs["timeout"], 1.5)


class TestCatalogChildRoutes(unittest.TestCase):
    def setUp(self):
        self.controller, self.client, _ = build()
        self.controller.engine.run = AsyncMock(return_value=([{"certname": "a"}], 1))

    def test_catalog_hrefs_resolve_to_the_flat_entities(self):
        for child, entity in (("edges", "edges"), ("resources", "resources")):
            self.controller.engine.run.reset_mock()
            response = self.client.get(f"/pdb/query/v4/catalogs/a/{child}")
            self.assertEqual(response.status_code, 200, msg=child)
            kwargs = self.controller.engine.run.await_args.kwargs
            self.assertEqual(kwargs["entity_name"], entity)
            self.assertEqual(kwargs["implicit"], [["=", "certname", "a"]])


class TestEventCountsEndpoints(unittest.TestCase):
    def setUp(self):
        self.controller, self.client, _ = build()
        self.controller.engine.group = AsyncMock(
            return_value=[
                {
                    "subject_type": "certname",
                    "subject": {"title": "a"},
                    "failures": 1,
                    "successes": 0,
                    "noops": 0,
                    "skips": 0,
                }
            ]
        )

    def test_summarize_by_is_required(self):
        response = self.client.get("/pdb/query/v4/event-counts")
        self.assertEqual(response.status_code, 400)
        self.assertIn("summarize_by", response.text)

    def test_event_counts_by_certname(self):
        response = self.client.get(
            "/pdb/query/v4/event-counts", params={"summarize_by": "certname"}
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body[0]["subject"], {"title": "a"})
        self.assertEqual(body[0]["failures"], 1)

    def test_event_counts_are_grouped_in_the_database(self):
        for path in ("/pdb/query/v4/event-counts", "/pdb/query/v4/aggregate-event-counts"):
            self.controller.engine.group.reset_mock()
            response = self.client.get(
                path, params={"summarize_by": "certname", "count_by": "certname"}
            )
            self.assertEqual(response.status_code, 200)
            self.controller.engine.group.assert_awaited_once()
            kwargs = self.controller.engine.group.await_args.kwargs
            self.assertEqual(kwargs["entity_name"], "events")
            expected = event_counts.summary_stages("certname", "certname")
            if "aggregate" in path:
                expected = expected + event_counts.aggregate_stages()
            self.assertEqual(kwargs["stages"], expected)

    def test_every_summarize_by_is_grouped_separately(self):
        self.client.get(
            "/pdb/query/v4/event-counts",
            params={"summarize_by": "certname,resource"},
        )
        self.assertEqual(self.controller.engine.group.await_count, 2)

    def test_aggregate_event_counts_are_summed_in_the_database(self):
        self.controller.engine.group = AsyncMock(
            return_value=[{"failures": 1, "successes": 0, "noops": 0, "skips": 0, "total": 1}]
        )
        response = self.client.get(
            "/pdb/query/v4/aggregate-event-counts",
            params={"summarize_by": "certname"},
        )
        self.assertEqual(
            response.json(),
            [{"failures": 1, "successes": 0, "noops": 0, "skips": 0, "total": 1, "summarize_by": "certname"}],
        )

    def test_aggregate_event_counts_with_a_counts_filter_sum_in_python(self):
        response = self.client.get(
            "/pdb/query/v4/aggregate-event-counts",
            params={"summarize_by": "certname", "counts_filter": '[">", "failures", 0]'},
        )
        self.assertEqual(
            self.controller.engine.group.await_args.kwargs["stages"],
            event_counts.summary_stages("certname", "resource"),
        )
        self.assertEqual(response.json()[0]["total"], 1)
        self.assertEqual(response.json()[0]["failures"], 1)

    def test_counts_filter_applies(self):
        response = self.client.get(
            "/pdb/query/v4/event-counts",
            params={
                "summarize_by": "certname",
                "counts_filter": '["=", "successes", 1]',
            },
        )
        self.assertEqual(response.json(), [])

    def test_broken_counts_filter_is_a_400(self):
        for counts_filter in (
            '["not"]',
            '[">", "failures", "1"]',
            '["=", "bogus", 1]',
            '["nope", "failures", 1]',
        ):
            response = self.client.get(
                "/pdb/query/v4/event-counts",
                params={
                    "summarize_by": "certname",
                    "counts_filter": counts_filter,
                },
            )
            self.assertEqual(response.status_code, 400, msg=counts_filter)

    def test_query_is_wrapped_in_an_extract(self):
        self.client.get(
            "/pdb/query/v4/event-counts",
            params={
                "summarize_by": "certname",
                "query": '["=", "status", "failure"]',
            },
        )
        self.assertEqual(
            self.controller.engine.group.await_args.kwargs["ast"],
            [
                "extract",
                list(event_counts.SUMMARIZE_COLUMNS),
                ["=", "status", "failure"],
            ],
        )

    def test_extract_is_added_without_a_query(self):
        self.client.get(
            "/pdb/query/v4/aggregate-event-counts",
            params={"summarize_by": "resource"},
        )
        self.assertEqual(
            self.controller.engine.group.await_args.kwargs["ast"],
            ["extract", list(event_counts.SUMMARIZE_COLUMNS)],
        )


class TestApplyLocalPaging(unittest.TestCase):
    def rows(self):
        return [
            {"subject": {"title": "a"}, "failures": 2},
            {"subject": {"title": "b"}, "failures": 10},
            {"subject": {"title": "c"}, "failures": None},
            {"subject": {"title": "d"}, "failures": 9},
        ]

    def failures(self, rows):
        return [row["failures"] for row in rows]

    def test_numeric_column_descending(self):
        rows = apply_local_paging(self.rows(), Paging(order_by=[("failures", -1)]))
        self.assertEqual(self.failures(rows), [10, 9, 2, None])

    def test_numeric_column_ascending(self):
        rows = apply_local_paging(self.rows(), Paging(order_by=[("failures", 1)]))
        self.assertEqual(self.failures(rows), [None, 2, 9, 10])

    def test_string_column(self):
        rows = apply_local_paging(
            [
                {"subject_type": "certname", "subject": "b"},
                {"subject_type": "certname", "subject": "a"},
                {"subject_type": "certname", "subject": "c"},
            ],
            Paging(order_by=[("subject", -1)]),
        )
        self.assertEqual([row["subject"] for row in rows], ["c", "b", "a"])

    def test_secondary_column_breaks_ties(self):
        rows = apply_local_paging(
            [
                {"skips": 1, "failures": 1},
                {"skips": 1, "failures": 3},
                {"skips": 0, "failures": 2},
            ],
            Paging(order_by=[("skips", 1), ("failures", -1)]),
        )
        self.assertEqual(
            [(row["skips"], row["failures"]) for row in rows],
            [(0, 2), (1, 3), (1, 1)],
        )

    def test_limit_and_offset(self):
        rows = apply_local_paging(
            self.rows(), Paging(order_by=[("failures", -1)], limit=2, offset=1)
        )
        self.assertEqual(self.failures(rows), [9, 2])

    def test_without_order_by_the_order_is_kept(self):
        rows = apply_local_paging(self.rows(), Paging())
        self.assertEqual(self.failures(rows), [2, 10, None, 9])


if __name__ == "__main__":
    unittest.main()


class TestJsonRendering(unittest.TestCase):
    def test_datetimes_render_as_zulu_and_object_ids_as_strings(self):
        from datetime import UTC, datetime
        from bson import ObjectId
        from pyppetdb.controller.pdb.query.v4 import PdbJSONResponse

        oid = ObjectId()
        body = PdbJSONResponse(
            content=[{"t": datetime(2026, 3, 1, 12, 0, 0, 123000), "u": datetime(2026, 3, 1, tzinfo=UTC), "o": oid, "ü": "ä"}]
        ).body
        self.assertEqual(
            body,
            ('[{"t":"2026-03-01T12:00:00.123000Z","u":"2026-03-01T00:00:00Z","o":"%s","ü":"ä"}]' % oid).encode(),
        )


class FakeStreamCursor:
    def __init__(self, docs):
        self.docs = list(docs)
        self.closed = False

    async def to_list(self, length=None):
        batch, self.docs = self.docs[:length], self.docs[length:]
        return batch

    async def close(self):
        self.closed = True


class TestStreamResponse(unittest.IsolatedAsyncioTestCase):
    async def body(self, rows, pretty, batch=2):
        from pyppetdb.pdb.query import engine as module

        original = module.STREAM_BATCH_SIZE
        module.STREAM_BATCH_SIZE = batch
        try:
            cursor = FakeStreamCursor(rows[batch:])
            response = stream_response(
                RowStream(cursor, rows[:batch]), pretty, logging.getLogger("test")
            )
            chunks = [chunk async for chunk in response.body_iterator]
        finally:
            module.STREAM_BATCH_SIZE = original
        return b"".join(chunks), cursor

    async def test_streamed_bytes_equal_the_buffered_response(self):
        from datetime import datetime

        rows = [
            {"certname": "a", "facts": {"os": {"family": "Debian"}}, "ts": datetime(2026, 1, 1)},
            {"certname": "b", "facts": {}, "ts": None},
            {"certname": "c", "list": [1, 2]},
        ]
        for pretty in (False, True):
            body, cursor = await self.body(rows, pretty)
            self.assertEqual(body, json_response(rows, pretty).body, pretty)
            self.assertTrue(cursor.closed)

    async def test_an_empty_stream_is_an_empty_array(self):
        for pretty in (False, True):
            body, _cursor = await self.body([], pretty)
            self.assertEqual(body, json_response([], pretty).body)

    async def test_a_disconnected_client_stops_the_cursor(self):
        from pyppetdb.pdb.query import engine as module

        class Request:
            calls = 0

            async def is_disconnected(self):
                Request.calls += 1
                return Request.calls > 1

        original = module.STREAM_BATCH_SIZE
        module.STREAM_BATCH_SIZE = 1
        try:
            cursor = FakeStreamCursor([{"a": 2}, {"a": 3}])
            response = stream_response(
                RowStream(cursor, [{"a": 1}]),
                False,
                logging.getLogger("test"),
                request=Request(),
            )
            chunks = [chunk async for chunk in response.body_iterator]
        finally:
            module.STREAM_BATCH_SIZE = original
        self.assertEqual(chunks, [b'[{"a":1}'])
        self.assertTrue(cursor.closed)
        self.assertEqual(cursor.docs, [{"a": 3}])

