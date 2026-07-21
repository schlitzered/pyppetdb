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

import uuid
from pyppetdb.authorize import PERM_NODES_CREATE
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
        cert_doc = self._db["ca_certificates"].find_one(
            {"cn": node_id, "space_id": "puppet-ca"}
        )
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


class ApiV1NodesAuthzIntegrationTests(IntegrationTestBase):
    def setUp(self):
        super().setUp()
        self.ident = self._make_non_admin(permissions=[PERM_NODES_CREATE])
        self.pfx = uuid.uuid4().hex[:8]
        self.node_group_allowed = f"ng-allowed-{self.pfx}"
        self.node_group_denied = f"ng-denied-{self.pfx}"
        self.node_allowed = f"node-allowed-{self.pfx}"
        self.node_denied = f"node-denied-{self.pfx}"
        self.created_node = f"node-created-{self.pfx}"

        self._db["nodes_groups"].insert_many(
            [
                {
                    "id": self.node_group_allowed,
                    "teams": [self.ident.team_id],
                    "nodes": [],
                },
                {
                    "id": self.node_group_denied,
                    "teams": [f"foreign-{self.pfx}"],
                    "nodes": [],
                },
            ]
        )
        self._db["nodes"].insert_many(
            [
                {
                    "id": self.node_allowed,
                    "environment": "production",
                    "disabled": False,
                    "facts": {},
                    "node_groups": [self.node_group_allowed],
                },
                {
                    "id": self.node_denied,
                    "environment": "production",
                    "disabled": False,
                    "facts": {},
                    "node_groups": [self.node_group_denied],
                },
            ]
        )
        self.addCleanup(
            self._db["nodes_groups"].delete_many,
            {"id": {"$in": [self.node_group_allowed, self.node_group_denied]}},
        )
        self.addCleanup(
            self._db["nodes"].delete_many,
            {
                "id": {
                    "$in": [self.node_allowed, self.node_denied, self.created_node]
                }
            },
        )

    def test_unauthenticated_is_rejected(self):
        resp = self.client.get(f"/api/v1/nodes/{self.node_allowed}")
        self.assertEqual(resp.status_code, 401)

    def test_granted_permission_allows_create(self):
        resp = self.client.post(
            f"/api/v1/nodes/{self.created_node}",
            headers=self.ident.headers,
            json={"disabled": False},
        )
        self.assertEqual(resp.status_code, 201)

    def test_missing_permission_is_forbidden(self):
        resp = self.client.delete(
            f"/api/v1/nodes/{self.node_allowed}", headers=self.ident.headers
        )
        self.assertEqual(resp.status_code, 403)
        self.assertIsNotNone(self._db["nodes"].find_one({"id": self.node_allowed}))

    def test_node_group_scoping_get_allowed(self):
        resp = self.client.get(
            f"/api/v1/nodes/{self.node_allowed}", headers=self.ident.headers
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["id"], self.node_allowed)

    def test_node_group_scoping_get_denied(self):
        resp = self.client.get(
            f"/api/v1/nodes/{self.node_denied}", headers=self.ident.headers
        )
        self.assertEqual(resp.status_code, 404)

    def test_node_group_scoping_search(self):
        resp = self.client.get(
            "/api/v1/nodes",
            headers=self.ident.headers,
            params={"node_id": f"node-(allowed|denied)-{self.pfx}"},
        )
        self.assertEqual(resp.status_code, 200)
        ids = {n["id"] for n in resp.json()["result"]}
        self.assertIn(self.node_allowed, ids)
        self.assertNotIn(self.node_denied, ids)

    def test_admin_is_not_scoped(self):
        resp = self.client.get(
            f"/api/v1/nodes/{self.node_denied}",
            headers={"x-secret-id": "test-cred", "x-secret": "test-secret"},
        )
        self.assertEqual(resp.status_code, 200)
