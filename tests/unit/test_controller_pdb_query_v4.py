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
from pyppetdb.pdbquery import event_counts
from pyppetdb.pdbquery.errors import PuppetDBQueryError
from pyppetdb.pdbquery.paging import Paging


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

    def test_post_body_as_bare_ast(self):
        self.client.post("/pdb/query/v4/nodes", json=["=", "certname", "a"])
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
            self.assertEqual(
                kwargs["stages"], event_counts.summary_stages("certname", "certname")
            )

    def test_latest_report_queries_use_the_first_flags(self):
        self.client.get(
            "/pdb/query/v4/event-counts",
            params={
                "summarize_by": "resource",
                "query": '["=", "latest_report?", true]',
            },
        )
        kwargs = self.controller.engine.group.await_args.kwargs
        self.assertEqual(kwargs["extra"], {"first_for_resource": "$first_for_resource"})
        self.assertEqual(kwargs["ast"], ["extract", list(event_counts.SUMMARIZE_COLUMNS), ["=", "latest_report?", True]])
        self.assertEqual(len(kwargs["stages"]), 3)

    def test_every_summarize_by_is_grouped_separately(self):
        self.client.get(
            "/pdb/query/v4/event-counts",
            params={"summarize_by": "certname,resource"},
        )
        self.assertEqual(self.controller.engine.group.await_count, 2)

    def test_aggregate_event_counts(self):
        response = self.client.get(
            "/pdb/query/v4/aggregate-event-counts",
            params={"summarize_by": "certname"},
        )
        body = response.json()
        self.assertEqual(body[0]["total"], 1)
        self.assertEqual(body[0]["summarize_by"], "certname")

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
