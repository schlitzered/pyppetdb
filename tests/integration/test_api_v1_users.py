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

from tests.integration.base import IntegrationTestBase


class ApiV1UsersIntegrationTests(IntegrationTestBase):
    def _auth_headers(self):
        return {"x-secret-id": "test-cred", "x-secret": "test-secret"}

    def test_users_crud_flow(self):
        user_id = f"user-{uuid.uuid4().hex}"

        resp = self.client.post(
            f"/api/v1/users/{user_id}",
            headers=self._auth_headers(),
            json={
                "name": "Test User",
                "email": "user@example.com",
                "admin": False,
                "password": "pw1234",
            },
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()["id"], user_id)

        resp = self.client.get(
            f"/api/v1/users/{user_id}",
            headers=self._auth_headers(),
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["id"], user_id)

        resp = self.client.put(
            f"/api/v1/users/{user_id}",
            headers=self._auth_headers(),
            json={
                "name": "Test User Updated",
                "email": "user@example.com",
                "admin": False,
                "password": "pw1234",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["name"], "Test User Updated")

        resp = self.client.get(
            "/api/v1/users",
            headers=self._auth_headers(),
            params={"user_id": user_id},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["meta"]["result_size"], 1)

        resp = self.client.delete(
            f"/api/v1/users/{user_id}",
            headers=self._auth_headers(),
        )
        self.assertEqual(resp.status_code, 200)

    def test_users_get_self(self):
        resp = self.client.get(
            "/api/v1/users/_self",
            headers=self._auth_headers(),
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["id"], "admin")

    def test_users_put_self(self):
        resp = self.client.put(
            "/api/v1/users/_self",
            headers=self._auth_headers(),
            json={"name": "Test User Updated"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["name"], "Test User Updated")
