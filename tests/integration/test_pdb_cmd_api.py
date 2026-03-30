import json
import time
from tests.integration.base import IntegrationTestBase


class PdbCmdApiIntegrationTests(IntegrationTestBase):
    def setUp(self):
        super().setUp()
        from pyppetdb.main import settings

        settings.app.puppetdb.serverurl = None

    def test_replace_facts(self):
        certname = "test-node-facts"
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

        # Give some time for background task to finish
        time.sleep(1)

        # Verify in MongoDB
        node = self._db["nodes"].find_one({"id": certname})
        self.assertIsNotNone(node)
        self.assertEqual(node["facts"]["os"], "Linux")
        self.assertEqual(node["environment"], "production")

    def test_replace_catalog(self):
        certname = "test-node-catalog"
        catalog_uuid = "uuid-1234"
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

        time.sleep(1)

        # Verify in nodes collection
        node = self._db["nodes"].find_one({"id": certname})
        self.assertIsNotNone(node)
        self.assertEqual(node["catalog"]["catalog_uuid"], catalog_uuid)
        self.assertEqual(node["catalog"]["num_resources"], 2)

        # Verify in nodes_catalogs collection (history)
        catalog_doc = self._db["nodes_catalogs"].find_one({"id": catalog_uuid})
        self.assertIsNotNone(catalog_doc)
        self.assertEqual(catalog_doc["node_id"], certname)

    def test_store_report(self):
        certname = "test-node-report"
        catalog_uuid = "uuid-1234"
        report_data = {
            "certname": certname,
            "environment": "production",
            "catalog_uuid": catalog_uuid,
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

        time.sleep(1)

        # Verify in nodes collection
        node = self._db["nodes"].find_one({"id": certname})
        self.assertIsNotNone(node)
        self.assertEqual(node["report"]["status"], "changed")

        # Verify in nodes_reports collection
        report_doc = self._db["nodes_reports"].find_one({"node_id": certname})
        self.assertIsNotNone(report_doc)
        self.assertEqual(report_doc["report"]["status"], "changed")
