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
import uuid

from tests.integration.base import IntegrationTestBase


COMMAND_VERSIONS = {
    "replace_facts": 5,
    "replace_catalog": 9,
    "store_report": 8,
    "deactivate_node": 3,
    "replace_catalog_inputs": 1,
    "configure_expiration": 1,
}


class PdbQueryApiIntegrationTests(IntegrationTestBase):
    def setUp(self):
        super().setUp()
        from pyppetdb.main import settings

        settings.app.puppetdb.serverurl = None
        settings.app.puppetdb.querySource = "internal"
        self.certname = f"node-query-{uuid.uuid4().hex}"
        self.addCleanup(self._db["nodes"].delete_many, {"id": self.certname})
        self.addCleanup(
            self._db["nodes_reports"].delete_many, {"node_id": self.certname}
        )
        self.addCleanup(
            self._db["nodes_resources"].delete_many, {"node_id": self.certname}
        )
        self.addCleanup(
            self._db["nodes_edges"].delete_many, {"node_id": self.certname}
        )
        self._seed()

    def _post(self, command, payload, version=None):
        if version is None:
            version = COMMAND_VERSIONS[command]
        resp = self.client.post(
            f"/pdb/cmd/v1?certname={self.certname}&command={command}"
            f"&producer-timestamp=2026-03-20T10:00:00Z&version={version}",
            content=json.dumps(payload),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(resp.status_code, 200, resp.text)

    def _seed(self):
        self._post(
            "replace_facts",
            {
                "certname": self.certname,
                "environment": "production",
                "producer_timestamp": "2026-03-20T10:00:00Z",
                "producer": "master1",
                "values": {
                    "osfamily": "Debian",
                    "os": {"family": "Debian", "release": {"major": "12"}},
                    "uptime_seconds": 5000,
                },
                "package_inventory": [["vim", "9.0", "apt"]],
            },
        )
        self._wait_until(
            lambda: self._db["nodes"].find_one(
                {"id": self.certname, "facts.osfamily": "Debian"}
            )
        )
        self._post(
            "replace_catalog",
            {
                "certname": self.certname,
                "environment": "production",
                "catalog_uuid": str(uuid.uuid4()),
                "version": "42",
                "transaction_uuid": str(uuid.uuid4()),
                "producer": "master1",
                "producer_timestamp": "2026-03-20T10:00:00Z",
                "resources": [
                    {
                        "type": "File",
                        "title": "/tmp/one",
                        "exported": False,
                        "tags": ["file", "one"],
                        "file": "init.pp",
                        "line": 3,
                        "parameters": {"owner": "root", "ensure": "file"},
                    },
                    {
                        "type": "Notify",
                        "title": "exported",
                        "exported": True,
                        "tags": ["notify"],
                        "parameters": {"message": "hi"},
                    },
                ],
                "edges": [
                    {
                        "source": {"type": "Stage", "title": "main"},
                        "target": {"type": "File", "title": "/tmp/one"},
                        "relationship": "contains",
                    }
                ],
            },
            version=9,
        )
        self._wait_until(
            lambda: self._db["nodes_resources"].find_one(
                {"node_id": self.certname, "type": "File"}
            )
        )
        self._post(
            "store_report",
            {
                "certname": self.certname,
                "environment": "production",
                "catalog_uuid": str(uuid.uuid4()),
                "status": "changed",
                "noop": False,
                "noop_pending": False,
                "corrective_change": False,
                "puppet_version": "8.4.0",
                "report_format": 12,
                "configuration_version": "1710930000",
                "start_time": "2026-03-20T09:59:00Z",
                "end_time": "2026-03-20T10:00:00Z",
                "producer_timestamp": "2026-03-20T10:00:00Z",
                "producer": "master1",
                "transaction_uuid": str(uuid.uuid4()),
                "logs": [
                    {
                        "file": None,
                        "line": None,
                        "level": "notice",
                        "message": "Applied catalog",
                        "source": "Puppet",
                        "tags": ["notice"],
                        "time": "2026-03-20T10:00:00.000Z",
                    }
                ],
                "metrics": [
                    {"category": "time", "name": "total", "value": 12.5}
                ],
                "resources": [
                    {
                        "skipped": False,
                        "timestamp": "2026-03-20T10:00:00Z",
                        "resource_type": "File",
                        "resource_title": "/tmp/one",
                        "file": "init.pp",
                        "line": 3,
                        "containment_path": [
                            "Stage[main]",
                            "Bench::Config",
                            "File[/tmp/one]",
                        ],
                        "corrective_change": False,
                        "events": [
                            {
                                "status": "success",
                                "timestamp": "2026-03-20T10:00:00Z",
                                "name": None,
                                "property": "ensure",
                                "new_value": "file",
                                "old_value": "absent",
                                "corrective_change": False,
                                "message": "created",
                            }
                        ],
                    }
                ],
            },
            version=8,
        )
        self._wait_until(
            lambda: self._db["nodes_reports"].find_one({"node_id": self.certname})
        )

    def _query(self, path, query=None, **params):
        if query is not None:
            params["query"] = json.dumps(query)
        resp = self.client.get(path, params=params)
        self.assertEqual(resp.status_code, 200, resp.text)
        return resp

    def test_list_responses_stream_with_totals_and_pretty_output(self):
        query = ["=", "certname", self.certname]
        resp = self._query("/pdb/query/v4/resources", query, include_total="true")
        rows = resp.json()
        self.assertEqual(resp.headers["x-records"], str(len(rows)))
        self.assertEqual({row["type"] for row in rows}, {"File", "Notify"})
        pretty = self._query("/pdb/query/v4/resources", query, pretty="true")
        self.assertEqual(pretty.json(), self._query("/pdb/query/v4/resources", query).json())
        self.assertIn(b"\n  {\n", pretty.content)
        empty = self._query("/pdb/query/v4/resources", ["=", "certname", "nope"])
        self.assertEqual(empty.content, b"[]")

    def test_event_pages_follow_the_full_order_at_every_offset(self):
        from datetime import datetime

        prefix = f"inc-{uuid.uuid4().hex[:8]}"
        docs = []
        for node in range(3):
            for second in (1, 2, None):
                for title in ("z", "m", "a", None):
                    docs.append(
                        {
                            "node_id": f"{prefix}-{node}",
                            "timestamp": datetime(2026, 1, 1, 0, 0, second) if second else None,
                            "resource_type": "File",
                            "resource_title": title,
                            "property": "ensure",
                            "name": "ensure_changed",
                            "status": "success",
                            "report_hash": prefix,
                            "latest": True,
                        }
                    )
        self._db["nodes_events"].insert_many(docs)
        self.addCleanup(self._db["nodes_events"].delete_many, {"report_hash": prefix})
        query = ["~", "certname", f"^{prefix}"]
        for directions in (("asc", "asc", "asc"), ("asc", "asc", "desc"), ("desc", "asc", "asc")):
            order = json.dumps(
                [
                    {"field": field, "order": direction}
                    for field, direction in zip(("certname", "timestamp", "resource_title"), directions)
                ]
            )
            everything = self._query(
                "/pdb/query/v4/events", query, order_by=order
            ).json()
            self.assertEqual(len(everything), len(docs))
            identity = [(row["certname"], row["timestamp"], row["resource_title"]) for row in everything]
            expected = [
                (doc["node_id"], doc["timestamp"], doc["resource_title"]) for doc in docs
            ]
            for position, direction in reversed(list(enumerate(directions))):
                expected.sort(
                    key=lambda item: (item[position] is not None, item[position] or ""),
                    reverse=direction == "desc",
                )
            self.assertEqual(
                [
                    (
                        row["certname"],
                        datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00")).replace(tzinfo=None)
                        if row["timestamp"]
                        else None,
                        row["resource_title"],
                    )
                    for row in everything
                ],
                expected,
                directions,
            )
            for offset in range(0, len(docs) + 1):
                page = self._query(
                    "/pdb/query/v4/events", query, order_by=order, limit=5, offset=offset
                ).json()
                self.assertEqual(
                    [(row["certname"], row["timestamp"], row["resource_title"]) for row in page],
                    identity[offset:offset + 5],
                    (directions, offset),
                )

    def test_nodes_endpoint(self):
        rows = self._query(
            "/pdb/query/v4/nodes", ["=", "certname", self.certname]
        ).json()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["certname"], self.certname)
        self.assertEqual(rows[0]["latest_report_status"], "changed")
        self.assertEqual(rows[0]["catalog_environment"], "production")

    def test_nodes_fact_field_form(self):
        rows = self._query(
            "/pdb/query/v4/nodes",
            ["and", ["=", "certname", self.certname], ["=", ["fact", "osfamily"], "Debian"]],
        ).json()
        self.assertEqual(len(rows), 1)

    def test_single_node_endpoint(self):
        body = self._query(f"/pdb/query/v4/nodes/{self.certname}").json()
        self.assertEqual(body["certname"], self.certname)

    def test_facts_endpoint(self):
        rows = self._query(
            "/pdb/query/v4/facts",
            ["and", ["=", "certname", self.certname], ["=", "name", "osfamily"]],
        ).json()
        self.assertEqual(rows[0]["value"], "Debian")

    def test_pinned_fact_name_returns_the_same_rows(self):
        pinned = self._query(
            "/pdb/query/v4/facts",
            ["and", ["=", "certname", self.certname], ["=", "name", "osfamily"]],
        ).json()
        unpinned = self._query(
            "/pdb/query/v4/facts",
            ["and", ["=", "certname", self.certname], ["~", "name", "^osfamily$"]],
        ).json()
        self.assertEqual(pinned, unpinned)
        self.assertEqual(pinned[0]["value"], "Debian")

    def test_pinned_fact_name_skips_absent_facts(self):
        rows = self._query(
            "/pdb/query/v4/facts", ["=", "name", "definitely_not_a_fact"]
        ).json()
        self.assertEqual(rows, [])

    def test_pinned_fact_names_from_a_set(self):
        rows = self._query(
            "/pdb/query/v4/facts",
            [
                "and",
                ["=", "certname", self.certname],
                ["in", "name", ["array", ["osfamily", "uptime_seconds"]]],
            ],
        ).json()
        self.assertEqual(
            sorted(row["name"] for row in rows), ["osfamily", "uptime_seconds"]
        )

    def test_pinned_fact_name_with_a_value_filter(self):
        rows = self._query(
            "/pdb/query/v4/facts",
            [
                "and",
                ["=", "certname", self.certname],
                ["=", "name", "osfamily"],
                ["=", "value", "Debian"],
            ],
        ).json()
        self.assertEqual(len(rows), 1)

    def test_pinned_fact_name_grouped(self):
        rows = self._query(
            "/pdb/query/v4",
            [
                "from",
                "facts",
                [
                    "extract",
                    ["value", ["function", "count"]],
                    ["=", "name", "osfamily"],
                    ["group_by", "value"],
                ],
            ],
        ).json()
        self.assertTrue(any(row["value"] == "Debian" for row in rows))

    def test_fact_names_returns_strings(self):
        rows = self._query("/pdb/query/v4/fact-names").json()
        self.assertIn("osfamily", rows)
        self.assertTrue(all(isinstance(item, str) for item in rows))

    def test_fact_paths_come_from_the_ingested_facts(self):
        rows = self._query(
            "/pdb/query/v4/fact-paths", ["=", "name", "os"]
        ).json()
        self.assertIn(
            {"name": "os", "path": ["os", "release", "major"], "type": "string"},
            rows,
        )
        rows = self._query(
            "/pdb/query/v4/fact-paths",
            ["and", ["=", "type", "integer"], ["=", "name", "uptime_seconds"]],
        ).json()
        self.assertEqual(
            rows,
            [{"name": "uptime_seconds", "path": ["uptime_seconds"], "type": "integer"}],
        )

    def test_fact_contents_nested_paths(self):
        rows = self._query(
            "/pdb/query/v4/fact-contents",
            ["and", ["=", "certname", self.certname], ["=", "value", "12"]],
        ).json()
        self.assertEqual(rows[0]["path"], ["os", "release", "major"])

    def test_inventory_dotted_facts(self):
        rows = self._query(
            "/pdb/query/v4/inventory",
            ["and", ["=", "certname", self.certname], ["=", "facts.os.family", "Debian"]],
        ).json()
        self.assertEqual(len(rows), 1)

    def test_resources_include_unexported(self):
        rows = self._query(
            "/pdb/query/v4/resources",
            ["and", ["=", "certname", self.certname], ["=", "type", "File"]],
        ).json()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "/tmp/one")
        self.assertEqual(rows[0]["file"], "init.pp")
        self.assertEqual(rows[0]["line"], 3)
        self.assertFalse(rows[0]["exported"])

    def test_resources_dotted_parameter(self):
        rows = self._query(
            "/pdb/query/v4/resources",
            [
                "and",
                ["=", "certname", self.certname],
                ["=", "parameters.owner", "root"],
            ],
        ).json()
        self.assertEqual(len(rows), 1)

    def test_resources_tag_filter(self):
        rows = self._query(
            "/pdb/query/v4/resources",
            ["and", ["=", "certname", self.certname], ["=", "tag", "one"]],
        ).json()
        self.assertEqual(len(rows), 1)

    def test_resources_exported_filter(self):
        rows = self._query(
            "/pdb/query/v4/resources",
            ["and", ["=", "certname", self.certname], ["=", "exported", True]],
        ).json()
        self.assertEqual(rows[0]["type"], "Notify")

    def test_resources_subquery_against_facts(self):
        rows = self._query(
            "/pdb/query/v4/resources",
            [
                "and",
                ["=", "type", "File"],
                [
                    "in",
                    "certname",
                    [
                        "extract",
                        "certname",
                        [
                            "select_facts",
                            ["and", ["=", "name", "osfamily"], ["=", "value", "Debian"]],
                        ],
                    ],
                ],
            ],
        ).json()
        self.assertTrue(any(row["certname"] == self.certname for row in rows))

    def test_edges_endpoint(self):
        rows = self._query(
            "/pdb/query/v4/edges", ["=", "certname", self.certname]
        ).json()
        self.assertEqual(rows[0]["relationship"], "contains")
        self.assertEqual(rows[0]["target_title"], "/tmp/one")

    def test_catalogs_endpoint(self):
        rows = self._query(
            "/pdb/query/v4/catalogs", ["=", "certname", self.certname]
        ).json()
        self.assertEqual(rows[0]["version"], "42")
        self.assertTrue(rows[0]["hash"])

    def test_reports_endpoint(self):
        rows = self._query(
            "/pdb/query/v4/reports", ["=", "certname", self.certname]
        ).json()
        self.assertEqual(rows[0]["status"], "changed")
        self.assertEqual(rows[0]["puppet_version"], "8.4.0")
        self.assertEqual(len(rows[0]["logs"]["data"]), 1)
        self.assertEqual(rows[0]["logs"]["data"][0]["message"], "Applied catalog")
        self.assertEqual(len(rows[0]["metrics"]["data"]), 1)
        self.assertEqual(rows[0]["type"], "agent")
        self.assertTrue(rows[0]["hash"])
        events = rows[0]["resource_events"]["data"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["resource_title"], "/tmp/one")
        self.assertEqual(
            set(events[0]),
            {
                "status", "timestamp", "resource_type", "resource_title",
                "property", "name", "new_value", "old_value", "message",
                "file", "line", "containment_path", "containing_class",
                "corrective_change",
            },
        )
        self.assertEqual(
            rows[0]["resource_events"]["href"],
            f"/pdb/query/v4/reports/{rows[0]['hash']}/events",
        )

    def test_report_events_href_resolves(self):
        report = self._query(
            "/pdb/query/v4/reports", ["=", "certname", self.certname]
        ).json()[0]
        rows = self.client.get(report["resource_events"]["href"]).json()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["resource_title"], "/tmp/one")

    def test_extract_projects_only_requested_columns(self):
        rows = self._query(
            "/pdb/query/v4/reports",
            [
                "extract",
                ["certname", "status"],
                ["=", "certname", self.certname],
            ],
        ).json()
        self.assertEqual(set(rows[0]), {"certname", "status"})

    def test_timestamp_range_filter_matches(self):
        rows = self._query(
            "/pdb/query/v4/nodes",
            [
                "and",
                ["=", "certname", self.certname],
                [">=", "catalog_timestamp", "2000-01-01T00:00:00Z"],
            ],
        ).json()
        self.assertEqual(len(rows), 1)

    def test_timestamp_range_filter_excludes(self):
        rows = self._query(
            "/pdb/query/v4/nodes",
            [
                "and",
                ["=", "certname", self.certname],
                ["<", "catalog_timestamp", "2000-01-01T00:00:00Z"],
            ],
        ).json()
        self.assertEqual(rows, [])

    def test_timestamp_filter_on_reports(self):
        rows = self._query(
            "/pdb/query/v4/reports",
            [
                "and",
                ["=", "certname", self.certname],
                [">=", "end_time", "2000-01-01T00:00:00Z"],
            ],
        ).json()
        self.assertEqual(len(rows), 1)

    def test_order_by_timestamp(self):
        resp = self._query(
            "/pdb/query/v4/nodes",
            None,
            order_by=json.dumps([{"field": "catalog_timestamp", "order": "desc"}]),
            limit=5,
        )
        stamps = [row["catalog_timestamp"] for row in resp.json()]
        self.assertIn(self.certname, [row["certname"] for row in resp.json()])
        present = [stamp for stamp in stamps if stamp is not None]
        self.assertEqual(present, sorted(present, reverse=True))
        self.assertEqual(stamps[: len(present)], present)

    def test_timestamps_are_iso8601_zulu(self):
        rows = self._query(
            "/pdb/query/v4/nodes", ["=", "certname", self.certname]
        ).json()
        stamp = rows[0]["catalog_timestamp"]
        self.assertRegex(
            stamp, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$"
        )

    def test_null_timestamp_stays_null(self):
        rows = self._query(
            "/pdb/query/v4/nodes", ["=", "certname", self.certname]
        ).json()
        self.assertIsNone(rows[0]["expired"])

    def test_events_endpoint(self):
        rows = self._query(
            "/pdb/query/v4/events", ["=", "certname", self.certname]
        ).json()
        self.assertEqual(rows[0]["status"], "success")
        self.assertEqual(rows[0]["resource_title"], "/tmp/one")
        self.assertEqual(rows[0]["containing_class"], "Bench::Config")

    def test_event_counts_endpoint(self):
        rows = self._query(
            "/pdb/query/v4/event-counts",
            ["=", "certname", self.certname],
            summarize_by="certname",
        ).json()
        self.assertEqual(rows[0]["successes"], 1)

    def test_aggregate_event_counts_endpoint(self):
        rows = self._query(
            "/pdb/query/v4/aggregate-event-counts",
            ["=", "certname", self.certname],
            summarize_by="certname",
        ).json()
        self.assertEqual(rows[0]["total"], 1)

    def test_packages_endpoint(self):
        rows = self._query(
            "/pdb/query/v4/packages", ["=", "certname", self.certname]
        ).json()
        self.assertEqual(rows[0]["package_name"], "vim")
        self.assertEqual(rows[0]["provider"], "apt")

    def test_environments_endpoint(self):
        rows = self._query("/pdb/query/v4/environments").json()
        self.assertIn({"name": "production"}, rows)

    def test_producers_endpoint(self):
        rows = self._query("/pdb/query/v4/producers").json()
        self.assertIn({"name": "master1"}, rows)

    def test_root_from_query(self):
        rows = self._query(
            "/pdb/query/v4", ["from", "nodes", ["=", "certname", self.certname]]
        ).json()
        self.assertEqual(rows[0]["certname"], self.certname)

    def test_extract_and_count(self):
        rows = self._query(
            "/pdb/query/v4",
            [
                "from",
                "resources",
                [
                    "extract",
                    [["function", "count"], "type"],
                    ["=", "certname", self.certname],
                    ["group_by", "type"],
                ],
            ],
        ).json()
        counts = {row["type"]: row["count"] for row in rows}
        self.assertEqual(counts["File"], 1)
        self.assertEqual(counts["Notify"], 1)

    def test_paging_and_include_total(self):
        resp = self._query(
            "/pdb/query/v4/resources",
            ["=", "certname", self.certname],
            limit=1,
            include_total="true",
            order_by=json.dumps([{"field": "type", "order": "asc"}]),
        )
        self.assertEqual(len(resp.json()), 1)
        self.assertEqual(resp.json()[0]["type"], "File")
        self.assertEqual(resp.headers["X-Records"], "2")

    def test_post_query(self):
        resp = self.client.post(
            "/pdb/query/v4/nodes",
            json={"query": ["=", "certname", self.certname]},
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()[0]["certname"], self.certname)

    def test_unknown_field_returns_400(self):
        resp = self.client.get(
            "/pdb/query/v4/resources", params={"query": '["=", "sourcefile", "/x"]'}
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("is not a queryable object for resources", resp.text)

    def test_deactivate_node_marks_inactive(self):
        self._post(
            "deactivate_node",
            {"certname": self.certname, "producer_timestamp": "2026-03-20T11:00:00Z"},
            version=3,
        )
        self._wait_until(
            lambda: self._db["nodes"].find_one(
                {"id": self.certname, "disabled": True}
            )
        )
        rows = self._query(
            "/pdb/query/v4/nodes",
            ["and", ["=", "certname", self.certname], ["=", "node_state", "inactive"]],
        ).json()
        self.assertEqual(len(rows), 1)
        self.assertIsNotNone(rows[0]["deactivated"])

    def test_meta_version_endpoint(self):
        resp = self.client.get("/pdb/meta/v1/version")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("version", resp.json())

    def test_status_services_endpoint(self):
        resp = self.client.get("/status/v1/services")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp.json()["puppetdb-status"]["state"], "running"
        )
