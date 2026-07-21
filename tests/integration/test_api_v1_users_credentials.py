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

from pyppetdb.authorize import PERM_USERS_CREDENTIALS_CREATE
from tests.integration.base import IntegrationTestBase


class ApiV1UsersCredentialsIntegrationTests(IntegrationTestBase):
    def _auth_headers(self):
        return {"x-secret-id": "test-cred", "x-secret": "test-secret"}

    def test_users_credentials_crud_flow(self):
        resp = self.client.post(
            "/api/v1/users/_self/credentials",
            headers=self._auth_headers(),
            json={"description": "test credential"},
        )
        self.assertEqual(resp.status_code, 201)
        payload = resp.json()
        self.assertIn("id", payload)
        self.assertIn("secret", payload)
        credential_id = payload["id"]

        resp = self.client.get(
            f"/api/v1/users/_self/credentials/{credential_id}",
            headers=self._auth_headers(),
        )
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertEqual(payload["id"], credential_id)
        self.assertEqual(payload["description"], "test credential")
        self.assertNotIn("secret", payload)

        resp = self.client.get(
            "/api/v1/users/_self/credentials",
            headers=self._auth_headers(),
            params={"limit": 10},
        )
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertGreaterEqual(payload["meta"]["result_size"], 1)
        self.assertTrue(any(item["id"] == credential_id for item in payload["result"]))

        resp = self.client.put(
            f"/api/v1/users/_self/credentials/{credential_id}",
            headers=self._auth_headers(),
            json={"description": "updated credential"},
        )
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertEqual(payload["id"], credential_id)
        self.assertEqual(payload["description"], "updated credential")

        resp = self.client.delete(
            f"/api/v1/users/_self/credentials/{credential_id}",
            headers=self._auth_headers(),
        )
        self.assertEqual(resp.status_code, 200)

    def test_users_credentials_admin_flow(self):
        user_id = "credential-target"
        resp = self.client.post(
            f"/api/v1/users/{user_id}",
            headers=self._auth_headers(),
            json={
                "name": "Credential Target",
                "email": "target@example.com",
                "admin": False,
                "password": "pw1234",
            },
        )
        self.assertEqual(resp.status_code, 201)

        resp = self.client.post(
            f"/api/v1/users/{user_id}/credentials",
            headers=self._auth_headers(),
            json={"description": "target credential"},
        )
        self.assertEqual(resp.status_code, 201)
        payload = resp.json()
        credential_id = payload["id"]
        self.assertIn("secret", payload)

        resp = self.client.get(
            f"/api/v1/users/{user_id}/credentials",
            headers=self._auth_headers(),
            params={"limit": 10},
        )
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertTrue(any(item["id"] == credential_id for item in payload["result"]))

        resp = self.client.put(
            f"/api/v1/users/{user_id}/credentials/{credential_id}",
            headers=self._auth_headers(),
            json={"description": "updated target credential"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["description"], "updated target credential")

        resp = self.client.delete(
            f"/api/v1/users/{user_id}/credentials/{credential_id}",
            headers=self._auth_headers(),
        )
        self.assertEqual(resp.status_code, 200)


class UsersCredentialsAuthzIntegrationTests(IntegrationTestBase):
    def test_foreign_create_denied_without_permission(self):
        nu = self._make_non_admin()
        resp = self.client.post(
            "/api/v1/users/admin/credentials",
            headers=nu.headers,
            json={"description": "x"},
        )
        self.assertEqual(resp.status_code, 403)

    def test_foreign_create_granted_with_permission(self):
        nu = self._make_non_admin(permissions=[PERM_USERS_CREDENTIALS_CREATE])
        resp = self.client.post(
            "/api/v1/users/admin/credentials",
            headers=nu.headers,
            json={"description": "granted"},
        )
        self.assertEqual(resp.status_code, 201)
        self.addCleanup(
            self._db["users_credentials"].delete_many, {"id": resp.json()["id"]}
        )

    def test_self_create_allowed_without_permission(self):
        nu = self._make_non_admin()
        resp = self.client.post(
            "/api/v1/users/_self/credentials",
            headers=nu.headers,
            json={"description": "self"},
        )
        self.assertEqual(resp.status_code, 201)
        self.addCleanup(
            self._db["users_credentials"].delete_many, {"id": resp.json()["id"]}
        )

    def test_self_search_allowed_without_permission(self):
        nu = self._make_non_admin()
        resp = self.client.get(
            "/api/v1/users/_self/credentials", headers=nu.headers
        )
        self.assertEqual(resp.status_code, 200)

    def test_foreign_search_denied_without_permission(self):
        nu = self._make_non_admin()
        resp = self.client.get(
            "/api/v1/users/admin/credentials", headers=nu.headers
        )
        self.assertEqual(resp.status_code, 403)

    def test_own_real_id_still_requires_permission(self):
        nu = self._make_non_admin()
        resp = self.client.get(
            f"/api/v1/users/{nu.user_id}/credentials", headers=nu.headers
        )
        self.assertEqual(resp.status_code, 403)
