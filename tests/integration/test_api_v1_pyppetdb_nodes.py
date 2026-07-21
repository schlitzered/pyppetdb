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
from datetime import datetime, timezone

from pyppetdb.authorize import PERM_PYPPETDB_NODES_GET
from pyppetdb.authorize import PERM_PYPPETDB_NODES_DELETE
from tests.integration.base import IntegrationTestBase


class ApiV1PyppetDBNodesIntegrationTests(IntegrationTestBase):

    def _insert_node(self):
        node_id = f"pyppetdb-{uuid.uuid4().hex}:8000"
        now = datetime.now(timezone.utc)
        self._db["pyppetdb_nodes"].insert_one(
            {
                "id": node_id,
                "heartbeat": now,
                "online_since": now,
            }
        )
        return node_id

    def test_get_node(self):
        node_id = self._insert_node()
        resp = self.client.get(
            f"/api/v1/pyppetdb_nodes/{node_id}", headers=self._auth_headers()
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["id"], node_id)

    def test_get_node_not_found(self):
        resp = self.client.get(
            f"/api/v1/pyppetdb_nodes/does-not-exist-{uuid.uuid4().hex}",
            headers=self._auth_headers(),
        )
        self.assertEqual(resp.status_code, 404)

    def test_search_node_by_id(self):
        node_id = self._insert_node()
        resp = self.client.get(
            "/api/v1/pyppetdb_nodes",
            headers=self._auth_headers(),
            params={"_id": f"^{node_id}$"},
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["meta"]["result_size"], 1)
        self.assertEqual(body["result"][0]["id"], node_id)

    def test_delete_node(self):
        node_id = self._insert_node()

        resp = self.client.delete(
            f"/api/v1/pyppetdb_nodes/{node_id}", headers=self._auth_headers()
        )
        self.assertEqual(resp.status_code, 200)

        # verify it is gone
        resp = self.client.get(
            f"/api/v1/pyppetdb_nodes/{node_id}", headers=self._auth_headers()
        )
        self.assertEqual(resp.status_code, 404)

    def test_requires_authentication(self):
        node_id = self._insert_node()
        resp = self.client.get(f"/api/v1/pyppetdb_nodes/{node_id}")
        self.assertEqual(resp.status_code, 401)


class PyppetdbNodesAuthzIntegrationTests(IntegrationTestBase):
    def test_search_denied_without_permission(self):
        nu = self._make_non_admin()
        resp = self.client.get("/api/v1/pyppetdb_nodes", headers=nu.headers)
        self.assertEqual(resp.status_code, 403)

    def test_search_granted_with_permission(self):
        nu = self._make_non_admin(permissions=[PERM_PYPPETDB_NODES_GET])
        resp = self.client.get("/api/v1/pyppetdb_nodes", headers=nu.headers)
        self.assertEqual(resp.status_code, 200)

    def test_get_denied_without_permission(self):
        nu = self._make_non_admin()
        resp = self.client.get(
            f"/api/v1/pyppetdb_nodes/pyppetdb-{uuid.uuid4().hex}:8000",
            headers=nu.headers,
        )
        self.assertEqual(resp.status_code, 403)

    def test_delete_denied_without_permission(self):
        nu = self._make_non_admin()
        resp = self.client.delete(
            f"/api/v1/pyppetdb_nodes/pyppetdb-{uuid.uuid4().hex}:8000",
            headers=nu.headers,
        )
        self.assertEqual(resp.status_code, 403)

    def test_delete_granted_with_permission(self):
        node_id = f"pyppetdb-{uuid.uuid4().hex}:8000"
        self._db["pyppetdb_nodes"].insert_one(
            {
                "id": node_id,
                "heartbeat": datetime.now(timezone.utc),
                "online_since": datetime.now(timezone.utc),
            }
        )
        self.addCleanup(self._db["pyppetdb_nodes"].delete_many, {"id": node_id})
        nu = self._make_non_admin(permissions=[PERM_PYPPETDB_NODES_DELETE])
        resp = self.client.delete(
            f"/api/v1/pyppetdb_nodes/{node_id}", headers=nu.headers
        )
        self.assertEqual(resp.status_code, 200)
