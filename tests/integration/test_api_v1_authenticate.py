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

from tests.integration.base import IntegrationTestBase


class ApiV1AuthenticateIntegrationTests(IntegrationTestBase):
    def test_authenticate_success_and_get(self):
        resp = self.client.post(
            "/api/v1/authenticate",
            json={"user": "admin", "password": "adminpass"},
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json(), {"user": "admin"})

        resp = self.client.get("/api/v1/authenticate")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"user": "admin"})

    def test_authenticate_invalid_password(self):
        resp = self.client.post(
            "/api/v1/authenticate",
            json={"user": "admin", "password": "wrong"},
        )
        self.assertEqual(resp.status_code, 401)

    def test_authenticate_delete_clears_session(self):
        resp = self.client.post(
            "/api/v1/authenticate",
            json={"user": "admin", "password": "adminpass"},
        )
        self.assertEqual(resp.status_code, 201)

        resp = self.client.delete("/api/v1/authenticate")
        self.assertEqual(resp.status_code, 200)

        resp = self.client.get("/api/v1/authenticate")
        self.assertEqual(resp.status_code, 401)

    def test_authenticate_get_with_api_credentials(self):
        resp = self.client.get(
            "/api/v1/authenticate",
            headers={"x-secret-id": "test-cred", "x-secret": "test-secret"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"user": "admin"})

    def test_authenticate_get_with_invalid_api_credentials(self):
        resp = self.client.get(
            "/api/v1/authenticate",
            headers={"x-secret-id": "test-cred", "x-secret": "wrong"},
        )
        self.assertEqual(resp.status_code, 401)
