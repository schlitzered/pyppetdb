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


class ApiV1NodesSecretsRedactorIntegrationTests(IntegrationTestBase):
    def _auth_headers(self):
        return {"x-secret-id": "test-cred", "x-secret": "test-secret"}

    def test_secrets_redactor_crud_flow(self):
        secret_value = f"secret-{uuid.uuid4().hex}"

        # 1. Create secret
        resp = self.client.post(
            "/api/v1/nodes_secrets_redactor",
            headers=self._auth_headers(),
            json={"value": secret_value},
        )
        self.assertEqual(resp.status_code, 200)
        secret_id = resp.json()["id"]
        # Value is not returned in GET/POST for security

        # 2. Search
        resp = self.client.get(
            "/api/v1/nodes_secrets_redactor",
            headers=self._auth_headers(),
            params={"secret_id": secret_id},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["meta"]["result_size"], 1)

        # 3. Delete
        resp = self.client.delete(
            f"/api/v1/nodes_secrets_redactor/{secret_id}", headers=self._auth_headers()
        )
        self.assertEqual(resp.status_code, 200)

        # 4. Verify deletion
        resp = self.client.get(
            "/api/v1/nodes_secrets_redactor",
            headers=self._auth_headers(),
            params={"secret_id": secret_id},
        )
        self.assertEqual(resp.json()["meta"]["result_size"], 0)
