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
        self.assertEqual(resp.status_code, 201)

        node = self._wait_until(
            lambda: self._db["nodes"].find_one(
                {"id": certname, "facts.os": "Linux"}
            )
        )
        self.assertEqual(node["environment"], "production")

    def test_replace_catalog(self):
        certname = f"node-catalog-{uuid.uuid4().hex}"
        catalog_uuid = f"uuid-{uuid.uuid4().hex}"
        self.addCleanup(self._db["nodes"].delete_many, {"id": certname})
        self.addCleanup(self._db["nodes_catalogs"].delete_many, {"id": catalog_uuid})
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
        self.assertEqual(resp.status_code, 201)

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

    def test_store_report(self):
        certname = f"node-report-{uuid.uuid4().hex}"
        self.addCleanup(self._db["nodes"].delete_many, {"id": certname})
        self.addCleanup(
            self._db["nodes_reports"].delete_many, {"node_id": certname}
        )
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
        self.assertEqual(resp.status_code, 201)

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
