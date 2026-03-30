import json
from datetime import datetime
from tests.integration.base import IntegrationTestBase


class TestNodesRedactors(IntegrationTestBase):
    def _auth_headers(self):
        return {"x-secret-id": "test-cred", "x-secret": "test-secret"}

    def _setup_node_and_secret(self, node_id, secret_value):
        # 0. Create a node directly in DB
        self._db["nodes"].insert_one(
            {
                "id": node_id,
                "environment": "production",
                "disabled": False,
                "node_groups": [],
            }
        )

        # 1. Add a secret to be redacted
        response = self.client.post(
            "/api/v1/nodes_secrets_redactor",
            json={"value": secret_value},
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 200)

    def test_report_redaction(self):
        node_id = "test-node-report-redactor"
        secret_value = "REPORT_SECRET"
        self._setup_node_and_secret(node_id, secret_value)

        # Use PDB API to store report
        report_payload = {
            "environment": "production",
            "catalog_uuid": "873f440f-b0ce-4662-8e57-0238c5a66034",
            "status": "changed",
            "noop": False,
            "noop_pending": False,
            "corrective_change": False,
            "logs": [
                {
                    "level": "info",
                    "message": f"Applied secret {secret_value}",
                    "source": "Puppet",
                    "tags": ["notice"],
                    "time": "2023-01-01T00:00:00Z",
                    "file": "site.pp",
                    "line": 1,
                }
            ],
            "metrics": [],
            "resources": [
                {
                    "skipped": False,
                    "timestamp": "2023-01-01T00:00:00Z",
                    "resource_type": "File",
                    "resource_title": f"/etc/secret_{secret_value}",
                    "file": "site.pp",
                    "line": 10,
                    "containment_path": ["Stage[main]", "Main", "File[/etc/secret]"],
                    "corrective_change": True,
                    "events": [
                        {
                            "status": "success",
                            "timestamp": "2023-01-01T00:00:00Z",
                            "name": "content_changed",
                            "property": "content",
                            "new_value": f"new_{secret_value}",
                            "old_value": f"old_{secret_value}",
                            "corrective_change": True,
                            "message": f"changed to {secret_value}",
                        }
                    ],
                }
            ],
        }

        response = self.client.post(
            f"/pdb/cmd/v1?certname={node_id}&command=store_report&version=8&producer-timestamp=2023-01-01T00:00:00Z",
            json=report_payload,
        )
        self.assertEqual(response.status_code, 201)

        # Get the report via API and verify redaction
        response = self.client.get(
            f"/api/v1/nodes/{node_id}/reports",
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 200)
        reports = response.json()["result"]
        self.assertEqual(len(reports), 1)
        report = reports[0]["report"]

        self.assertEqual(report["logs"][0]["message"], "Applied secret XXXXX")
        event = report["resources"][0]["events"][0]
        self.assertEqual(event["new_value"], "new_XXXXX")
        self.assertEqual(event["old_value"], "old_XXXXX")
        self.assertEqual(event["message"], "changed to XXXXX")

    def test_catalog_redaction(self):
        node_id = "test-node-catalog-redactor"
        secret_value = "CATALOG_SECRET"
        self._setup_node_and_secret(node_id, secret_value)

        # Use PDB API to replace catalog
        catalog_payload = {
            "environment": "production",
            "catalog_uuid": "3597dadd-2804-4f8a-ac15-6f6c18aa1dce",
            "resources": [
                {
                    "exported": False,
                    "type": "File",
                    "title": f"file_{secret_value}",
                    "tags": ["tag"],
                    "parameters": {
                        "content": f"Secret is {secret_value}",
                        "owner": "root",
                    },
                }
            ],
            "edges": [],
        }

        response = self.client.post(
            f"/pdb/cmd/v1?certname={node_id}&command=replace_catalog&version=9&producer-timestamp=2023-01-01T00:00:00Z",
            json=catalog_payload,
        )
        self.assertEqual(response.status_code, 201)

        # Get the catalog via API and verify redaction
        response = self.client.get(
            f"/api/v1/nodes/{node_id}/catalogs",
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 200)
        catalogs = response.json()["result"]
        self.assertEqual(len(catalogs), 1)

        resource = catalogs[0]["catalog"]["resources"][0]
        self.assertEqual(resource["title"], f"file_{secret_value}")
        self.assertEqual(resource["parameters"]["content"], "Secret is XXXXX")
        self.assertEqual(resource["parameters"]["owner"], "root")
