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


class PdbCmdApiIntegrationTests(IntegrationTestBase):
    def setUp(self):
        super().setUp()
        from pyppetdb.main import settings

        settings.app.puppetdb.serverurl = None

    def test_replace_facts(self):
        certname = f"node-facts-{uuid.uuid4().hex}"
        self.addCleanup(self._db["nodes"].delete_many, {"id": certname})
        facts_data = {
            "certname": certname,
            "environment": "production",
            "values": {"os": "Linux", "ipaddress": "127.0.0.1"},
            "producer_timestamp": "2026-03-20T10:00:00Z",
            "producer": "puppetmaster",
        }

        resp = self.client.post(
            f"/pdb/cmd/v1?certname={certname}&command=replace_facts&producer-timestamp=2026-03-20T10:00:00Z&version=1",
            content=json.dumps(facts_data),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("uuid", resp.json())

        node = self._wait_until(
            lambda: self._db["nodes"].find_one(
                {"id": certname, "facts.os": "Linux"}
            )
        )
        self.assertEqual(node["environment"], "production")

    def _seed_facts(self, certname):
        resp = self.client.post(
            f"/pdb/cmd/v1?certname={certname}&command=replace_facts&producer-timestamp=2026-03-20T10:00:00Z&version=1",
            content=json.dumps(
                {
                    "certname": certname,
                    "environment": "production",
                    "values": {"os": "Linux"},
                    "producer_timestamp": "2026-03-20T10:00:00Z",
                    "producer": "puppetmaster",
                }
            ),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(resp.status_code, 200)
        self._wait_until(
            lambda: self._db["nodes"].find_one({"id": certname, "facts.os": "Linux"})
        )

    def _seed_catalog(self, certname):
        catalog_uuid = f"uuid-{uuid.uuid4().hex}"
        self.addCleanup(self._db["nodes_catalogs"].delete_many, {"id": catalog_uuid})
        resp = self.client.post(
            f"/pdb/cmd/v1?certname={certname}&command=replace_catalog&producer-timestamp=2026-03-20T10:00:00Z&version=1",
            content=json.dumps(
                {
                    "certname": certname,
                    "environment": "production",
                    "catalog_uuid": catalog_uuid,
                    "resources": [],
                    "edges": [],
                }
            ),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(resp.status_code, 200)
        self._wait_until(
            lambda: self._db["nodes"].find_one(
                {"id": certname, "catalog.catalog_uuid": catalog_uuid}
            )
        )

    def test_replace_catalog(self):
        certname = f"node-catalog-{uuid.uuid4().hex}"
        catalog_uuid = f"uuid-{uuid.uuid4().hex}"
        self.addCleanup(self._db["nodes"].delete_many, {"id": certname})
        self.addCleanup(self._db["nodes_catalogs"].delete_many, {"id": catalog_uuid})
        self._seed_facts(certname)
        catalog_data = {
            "certname": certname,
            "environment": "production",
            "catalog_uuid": catalog_uuid,
            "resources": [
                {
                    "type": "File",
                    "title": "/tmp/test",
                    "exported": False,
                    "tags": ["test"],
                    "parameters": {},
                },
                {
                    "type": "Notify",
                    "title": "hello",
                    "exported": True,
                    "tags": ["test"],
                    "parameters": {},
                },
            ],
        }

        resp = self.client.post(
            f"/pdb/cmd/v1?certname={certname}&command=replace_catalog&producer-timestamp=2026-03-20T10:00:00Z&version=1",
            content=json.dumps(catalog_data),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("uuid", resp.json())

        node = self._wait_until(
            lambda: self._db["nodes"].find_one(
                {"id": certname, "catalog.catalog_uuid": catalog_uuid}
            )
        )
        self.assertEqual(node["catalog"]["num_resources"], 2)

        catalog_doc = self._wait_until(
            lambda: self._db["nodes_catalogs"].find_one({"id": catalog_uuid})
        )
        self.assertEqual(catalog_doc["node_id"], certname)

    def test_replace_catalog_preserves_resource_and_edge_detail(self):
        certname = f"node-catdetail-{uuid.uuid4().hex}"
        catalog_uuid = f"uuid-{uuid.uuid4().hex}"
        self.addCleanup(self._db["nodes"].delete_many, {"id": certname})
        self.addCleanup(
            self._db["nodes_catalogs"].delete_many, {"id": catalog_uuid}
        )
        self._seed_facts(certname)
        catalog_data = {
            "certname": certname,
            "environment": "production",
            "catalog_uuid": catalog_uuid,
            "version": "42",
            "transaction_uuid": "tx-detail",
            "code_id": "code-1",
            "producer": "puppetmaster",
            "resources": [
                {
                    "type": "File",
                    "title": "/tmp/detail",
                    "file": "/etc/puppetlabs/code/site.pp",
                    "line": 17,
                    "exported": False,
                    "tags": ["detail"],
                    "parameters": {"ensure": "present"},
                },
            ],
            "edges": [
                {
                    "source": {"type": "Class", "title": "main"},
                    "target": {"type": "File", "title": "/tmp/detail"},
                    "relationship": "contains",
                },
            ],
        }
        resp = self.client.post(
            f"/pdb/cmd/v1?certname={certname}&command=replace_catalog"
            f"&producer-timestamp=2026-03-20T10:00:00Z&version=1",
            content=json.dumps(catalog_data),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(resp.status_code, 200)

        node = self._wait_until(
            lambda: self._db["nodes"].find_one(
                {"id": certname, "catalog.catalog_uuid": catalog_uuid}
            )
        )
        stored = node["catalog"]["resources"][0]
        self.assertEqual(stored["file"], "/etc/puppetlabs/code/site.pp")
        self.assertEqual(stored["line"], 17)
        self.assertEqual(len(node["catalog"]["edges"]), 1)
        self.assertEqual(node["catalog"]["edges"][0]["relationship"], "contains")
        self.assertEqual(node["catalog"]["version"], "42")
        self.assertEqual(node["catalog"]["transaction_uuid"], "tx-detail")
        self.assertEqual(node["catalog"]["producer"], "puppetmaster")

        # normalisierte Parameter fuer den indizierten Prefilter
        rp = {(e["n"], e["v"]) for e in node.get("resource_params", [])}
        self.assertIn(("ensure", "present"), rp)

        resources = self.client.get(
            "/pdb/query/v4/resources",
            params={"query": json.dumps(
                ["and", ["=", "certname", certname], ["=", "type", "File"]]
            )},
        ).json()
        self.assertEqual(resources[0]["file"], "/etc/puppetlabs/code/site.pp")
        self.assertEqual(resources[0]["line"], 17)

        edges = self.client.get(
            "/pdb/query/v4/edges",
            params={"query": json.dumps(["=", "certname", certname])},
        ).json()
        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0]["target_title"], "/tmp/detail")

        catalogs = self.client.get(
            "/pdb/query/v4/catalogs",
            params={"query": json.dumps(["=", "certname", certname])},
        ).json()
        self.assertEqual(catalogs[0]["version"], "42")
        self.assertEqual(catalogs[0]["transaction_uuid"], "tx-detail")

    def test_store_report(self):
        certname = f"node-report-{uuid.uuid4().hex}"
        self.addCleanup(self._db["nodes"].delete_many, {"id": certname})
        self.addCleanup(
            self._db["nodes_reports"].delete_many, {"node_id": certname}
        )
        self._seed_facts(certname)
        self._seed_catalog(certname)
        report_data = {
            "certname": certname,
            "environment": "production",
            "catalog_uuid": f"uuid-{uuid.uuid4().hex}",
            "status": "changed",
            "noop": False,
            "noop_pending": False,
            "corrective_change": False,
            "logs": [],
            "metrics": [],
            "resources": [],
        }

        resp = self.client.post(
            f"/pdb/cmd/v1?certname={certname}&command=store_report&producer-timestamp=2026-03-20T10:00:00Z&version=1",
            content=json.dumps(report_data),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("uuid", resp.json())

        node = self._wait_until(
            lambda: self._db["nodes"].find_one(
                {"id": certname, "report.status": "changed"}
            )
        )
        self.assertEqual(node["report"]["status"], "changed")

        report_doc = self._wait_until(
            lambda: self._db["nodes_reports"].find_one({"node_id": certname})
        )
        self.assertEqual(report_doc["report"]["status"], "changed")
