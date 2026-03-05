import uuid
from tests.integration.base import IntegrationTestBase

class ApiV1NodesCredentialsIntegrationTests(IntegrationTestBase):
    def _auth_headers(self):
        return {"x-secret-id": "test-cred", "x-secret": "test-secret"}

    def test_nodes_credentials_crud_flow(self):
        # 0. Setup: Need a node
        node_id = f"node-{uuid.uuid4().hex}"
        self._db["nodes"].insert_one({
            "id": node_id,
            "environment": "production",
            "node_groups": []
        })

        # 1. Create credential
        resp = self.client.post(
            f"/api/v1/nodes/{node_id}/credentials",
            headers=self._auth_headers(),
            json={"description": "Test Credential"}
        )
        self.assertEqual(resp.status_code, 201)
        cred_id = resp.json()["id"]
        self.assertIn("secret", resp.json())

        # 2. Get credential
        resp = self.client.get(
            f"/api/v1/nodes/{node_id}/credentials/{cred_id}",
            headers=self._auth_headers()
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["description"], "Test Credential")

        # 3. Search credentials
        resp = self.client.get(
            f"/api/v1/nodes/{node_id}/credentials",
            headers=self._auth_headers()
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["meta"]["result_size"], 1)

        # 4. Update credential
        resp = self.client.put(
            f"/api/v1/nodes/{node_id}/credentials/{cred_id}",
            headers=self._auth_headers(),
            json={"description": "Updated Test Credential"}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["description"], "Updated Test Credential")

        # 5. Delete credential
        resp = self.client.delete(
            f"/api/v1/nodes/{node_id}/credentials/{cred_id}",
            headers=self._auth_headers()
        )
        self.assertEqual(resp.status_code, 200)

        # 6. Verify deletion
        resp = self.client.get(
            f"/api/v1/nodes/{node_id}/credentials/{cred_id}",
            headers=self._auth_headers()
        )
        self.assertEqual(resp.status_code, 404)
