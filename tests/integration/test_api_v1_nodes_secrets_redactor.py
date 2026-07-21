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
from pyppetdb.authorize import PERM_NODES_SECRETS_REDACTOR_CREATE
from pyppetdb.authorize import PERM_NODES_SECRETS_REDACTOR_DELETE
from tests.integration.base import IntegrationTestBase


class ApiV1NodesSecretsRedactorIntegrationTests(IntegrationTestBase):

    def test_secrets_redactor_crud_flow(self):
        secret_value = f"secret-{uuid.uuid4().hex}"

        # 1. Create secret
        resp = self.client.post(
            "/api/v1/nodes_secrets_redactor",
            headers=self._auth_headers(),
            json={"value": secret_value},
        )
        self.assertEqual(resp.status_code, 201)
        create_body = resp.json()
        secret_id = create_body["id"]
        # the plaintext secret (and its encrypted form) must never be echoed back
        self.assertNotIn("value", create_body)
        self.assertNotIn("value_encrypted", create_body)
        self.assertNotIn(secret_value, resp.text)

        # 2. Search
        resp = self.client.get(
            "/api/v1/nodes_secrets_redactor",
            headers=self._auth_headers(),
            params={"secret_id": secret_id},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["meta"]["result_size"], 1)
        # no secret material leaks through the search response either
        search_entry = resp.json()["result"][0]
        self.assertNotIn("value", search_entry)
        self.assertNotIn("value_encrypted", search_entry)
        self.assertNotIn(secret_value, resp.text)

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


class NodesSecretsRedactorAuthzIntegrationTests(IntegrationTestBase):
    def test_create_denied_without_permission(self):
        nu = self._make_non_admin()
        resp = self.client.post(
            "/api/v1/nodes_secrets_redactor",
            headers=nu.headers,
            json={"value": "denied"},
        )
        self.assertEqual(resp.status_code, 403)

    def test_create_granted_with_permission(self):
        nu = self._make_non_admin(permissions=[PERM_NODES_SECRETS_REDACTOR_CREATE])
        resp = self.client.post(
            "/api/v1/nodes_secrets_redactor",
            headers=nu.headers,
            json={"value": f"granted-{uuid.uuid4().hex}"},
        )
        self.assertEqual(resp.status_code, 201)
        self.addCleanup(
            self._db["nodes_secrets_redactor"].delete_many,
            {"id": resp.json()["id"]},
        )

    def test_delete_denied_without_permission(self):
        nu = self._make_non_admin()
        resp = self.client.delete(
            f"/api/v1/nodes_secrets_redactor/{uuid.uuid4().hex}", headers=nu.headers
        )
        self.assertEqual(resp.status_code, 403)

    def test_delete_granted_with_permission(self):
        secret_id = uuid.uuid4().hex
        self._db["nodes_secrets_redactor"].insert_one({"id": secret_id})
        self.addCleanup(
            self._db["nodes_secrets_redactor"].delete_many, {"id": secret_id}
        )
        nu = self._make_non_admin(permissions=[PERM_NODES_SECRETS_REDACTOR_DELETE])
        resp = self.client.delete(
            f"/api/v1/nodes_secrets_redactor/{secret_id}", headers=nu.headers
        )
        self.assertEqual(resp.status_code, 200)

    def test_search_requires_only_authentication(self):
        nu = self._make_non_admin()
        resp = self.client.get(
            "/api/v1/nodes_secrets_redactor", headers=nu.headers
        )
        self.assertEqual(resp.status_code, 200)
