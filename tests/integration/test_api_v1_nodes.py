import uuid
from tests.integration.base import IntegrationTestBase


class ApiV1NodesIntegrationTests(IntegrationTestBase):
    def _auth_headers(self):
        return {"x-secret-id": "test-cred", "x-secret": "test-secret"}

    def test_nodes_crud_flow(self):
        node_id = f"node-{uuid.uuid4().hex}"

        # 0. Setup: Create node in DB (since there's no POST in API) and a certificate
        self._db["nodes"].insert_one(
            {
                "id": node_id,
                "environment": "production",
                "disabled": False,
                "facts": {"os": "Linux", "hostname": node_id},
                "node_groups": [],
            }
        )
        self._db["ca_certificates"].insert_one(
            {
                "id": "12345",
                "space_id": "puppet-ca",
                "ca_id": "puppet-ca",
                "cn": node_id,
                "status": "signed",
                "serial_number": "12345",
                "certificate": "CERT_CONTENT",
            }
        )

        # 1. Search nodes
        resp = self.client.get(
            "/api/v1/nodes", headers=self._auth_headers(), params={"node_id": node_id}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["meta"]["result_size"], 1)
        self.assertEqual(resp.json()["result"][0]["id"], node_id)

        # 2. Get node
        resp = self.client.get(f"/api/v1/nodes/{node_id}", headers=self._auth_headers())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["id"], node_id)
        self.assertEqual(resp.json()["facts"]["os"], "Linux")

        # 3. Update node (facts_inject)
        resp = self.client.put(
            f"/api/v1/nodes/{node_id}",
            headers=self._auth_headers(),
            json={"disabled": True, "facts_inject": {"location": "Frankfurt"}},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["disabled"], True)
        self.assertEqual(resp.json()["facts_inject"]["location"], "Frankfurt")

        # 4. Verify update with GET
        resp = self.client.get(f"/api/v1/nodes/{node_id}", headers=self._auth_headers())
        self.assertEqual(resp.json()["disabled"], True)

        # 5. Delete node
        resp = self.client.delete(
            f"/api/v1/nodes/{node_id}", headers=self._auth_headers()
        )
        self.assertEqual(resp.status_code, 200)

        # 5.1 Verify certificate is revoked
        cert_doc = self._db["ca_certificates"].find_one({"cn": node_id, "space_id": "puppet-ca"})
        self.assertEqual(cert_doc["status"], "revoked")

        # 6. Verify deletion
        resp = self.client.get(f"/api/v1/nodes/{node_id}", headers=self._auth_headers())
        self.assertEqual(resp.status_code, 404)

    def test_nodes_post_create(self):
        node_id = f"node-post-{uuid.uuid4().hex}"

        # Create node using POST
        resp = self.client.post(
            f"/api/v1/nodes/{node_id}",
            headers=self._auth_headers(),
            json={"disabled": False, "facts_inject": {"env": "test"}},
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()["id"], node_id)
        self.assertEqual(resp.json()["facts_inject"]["env"], "test")

        # Verify with GET
        resp = self.client.get(f"/api/v1/nodes/{node_id}", headers=self._auth_headers())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["id"], node_id)

    def test_nodes_distinct_facts(self):
        # Setup multiple nodes with some facts
        self._db["nodes"].insert_many(
            [
                {"id": "n1", "facts": {"env": "prod"}, "node_groups": []},
                {"id": "n2", "facts": {"env": "prod"}, "node_groups": []},
                {"id": "n3", "facts": {"env": "dev"}, "node_groups": []},
            ]
        )

        resp = self.client.get(
            "/api/v1/nodes/_distinct_fact_values",
            headers=self._auth_headers(),
            params={"fact_id": "env"},
        )
        self.assertEqual(resp.status_code, 200)
        results = {item["value"]: item["count"] for item in resp.json()["result"]}
        self.assertEqual(results["prod"], 2)
        self.assertEqual(results["dev"], 1)
