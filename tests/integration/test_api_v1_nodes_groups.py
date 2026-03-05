import uuid
from tests.integration.base import IntegrationTestBase

class ApiV1NodesGroupsIntegrationTests(IntegrationTestBase):
    def _auth_headers(self):
        return {"x-secret-id": "test-cred", "x-secret": "test-secret"}

    def test_nodes_groups_crud_flow(self):
        # 0. Setup: Need a team and a node
        team_id = f"team-{uuid.uuid4().hex}"
        self.client.post(
            f"/api/v1/teams/{team_id}",
            headers=self._auth_headers(),
            json={"ldap_group": "", "users": ["admin"]}
        )
        
        node_id = f"node-{uuid.uuid4().hex}"
        self._db["nodes"].insert_one({
            "id": node_id,
            "environment": "production",
            "facts": {"role": "webserver"},
            "node_groups": []
        })

        group_id = f"group-{uuid.uuid4().hex}"
        
        # 1. Create node group with filter
        resp = self.client.post(
            f"/api/v1/nodes_groups/{group_id}",
            headers=self._auth_headers(),
            json={
                "teams": [team_id],
                "filters": [
                    {
                        "part": [
                            {"fact": "role", "values": ["webserver"]}
                        ]
                    }
                ]
            }
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()["id"], group_id)
        # Verify node was automatically added based on filter
        self.assertIn(node_id, resp.json()["nodes"])

        # 2. Search
        resp = self.client.get(
            "/api/v1/nodes_groups",
            headers=self._auth_headers(),
            params={"node_group_id": group_id}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["meta"]["result_size"], 1)

        # 3. Get
        resp = self.client.get(
            f"/api/v1/nodes_groups/{group_id}",
            headers=self._auth_headers()
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["id"], group_id)

        # 4. Update (add another team)
        # Note: we need another team if we want to test multi-team
        resp = self.client.put(
            f"/api/v1/nodes_groups/{group_id}",
            headers=self._auth_headers(),
            json={"teams": [team_id], "filters": []} # Clearing filters
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["nodes"], []) # No filters means no nodes now

        # 5. Delete
        resp = self.client.delete(
            f"/api/v1/nodes_groups/{group_id}",
            headers=self._auth_headers()
        )
        self.assertEqual(resp.status_code, 200)

        # 6. Verify deletion
        resp = self.client.get(
            f"/api/v1/nodes_groups/{group_id}",
            headers=self._auth_headers()
        )
        self.assertEqual(resp.status_code, 404)
