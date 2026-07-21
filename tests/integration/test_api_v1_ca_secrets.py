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


class ApiV1CASecretsIntegrationTests(IntegrationTestBase):
    def _auth_headers(self):
        return {"x-secret-id": "test-cred", "x-secret": "test-secret"}

    def _http_check_config(self, secret_id):
        return {
            "san_validation": {
                "http_checks": [
                    {
                        "url": "https://validate.example.com",
                        "headers": [
                            {
                                "name": "Authorization",
                                "value": f"Bearer $secrets[{secret_id}]",
                            }
                        ],
                    }
                ]
            }
        }

    def test_secret_crud_is_write_only(self):
        secret_id = f"SEC_{uuid.uuid4().hex}"

        # create
        resp = self.client.post(
            f"/api/v1/ca/secrets/{secret_id}",
            headers=self._auth_headers(),
            json={"secret": "topsecret", "description": "gh token"},
        )
        self.assertEqual(resp.status_code, 201)
        body = resp.json()
        self.assertEqual(body["id"], secret_id)
        self.assertEqual(body["description"], "gh token")
        # the secret value is never returned
        self.assertNotIn("secret", body)
        self.assertNotIn("secret_encrypted", body)

        # get
        resp = self.client.get(
            f"/api/v1/ca/secrets/{secret_id}", headers=self._auth_headers()
        )
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("secret", resp.json())

        # the stored value is encrypted at rest (never cleartext in mongo)
        doc = self._db["ca_secrets"].find_one({"id": secret_id})
        self.assertIsNotNone(doc)
        self.assertNotIn("secret", doc)
        self.assertNotEqual(doc["secret_encrypted"], "topsecret")

        # delete (not referenced)
        resp = self.client.delete(
            f"/api/v1/ca/secrets/{secret_id}", headers=self._auth_headers()
        )
        self.assertEqual(resp.status_code, 200)

    def test_invalid_secret_id_rejected(self):
        resp = self.client.post(
            "/api/v1/ca/secrets/bad id!",
            headers=self._auth_headers(),
            json={"secret": "x"},
        )
        self.assertEqual(resp.status_code, 422)

    def test_reference_lifecycle_and_delete_protection(self):
        secret_id = f"SEC_{uuid.uuid4().hex}"
        ca_id = f"ca-{uuid.uuid4().hex}"

        # create secret
        resp = self.client.post(
            f"/api/v1/ca/secrets/{secret_id}",
            headers=self._auth_headers(),
            json={"secret": "topsecret"},
        )
        self.assertEqual(resp.status_code, 201)

        # create CA authority referencing the secret in a webhook header
        resp = self.client.post(
            f"/api/v1/ca/authorities/{ca_id}",
            headers=self._auth_headers(),
            json={
                "cn": "Ref CA",
                "validation_config": self._http_check_config(secret_id),
            },
        )
        self.assertEqual(resp.status_code, 201)

        # deleting the referenced secret must be blocked with 409 + location
        resp = self.client.delete(
            f"/api/v1/ca/secrets/{secret_id}", headers=self._auth_headers()
        )
        self.assertEqual(resp.status_code, 409)
        self.assertIn(ca_id, resp.json()["detail"])

        # remove the reference from the authority
        resp = self.client.put(
            f"/api/v1/ca/authorities/{ca_id}",
            headers=self._auth_headers(),
            json={"validation_config": {}},
        )
        self.assertEqual(resp.status_code, 200)

        # now deletion succeeds
        resp = self.client.delete(
            f"/api/v1/ca/secrets/{secret_id}", headers=self._auth_headers()
        )
        self.assertEqual(resp.status_code, 200)

    def test_unknown_reference_rejected_on_save(self):
        ca_id = f"ca-{uuid.uuid4().hex}"
        resp = self.client.post(
            f"/api/v1/ca/authorities/{ca_id}",
            headers=self._auth_headers(),
            json={
                "cn": "Bad Ref CA",
                "validation_config": self._http_check_config("DOES_NOT_EXIST"),
            },
        )
        self.assertEqual(resp.status_code, 422)

    def test_literal_password_rejected_on_save(self):
        ca_id = f"ca-{uuid.uuid4().hex}"
        config = {
            "san_validation": {
                "http_checks": [
                    {
                        "url": "https://validate.example.com",
                        "basic_auth_enabled": True,
                        "username": "admin",
                        "password": "literal-secret",
                    }
                ]
            }
        }
        resp = self.client.post(
            f"/api/v1/ca/authorities/{ca_id}",
            headers=self._auth_headers(),
            json={"cn": "Literal PW CA", "validation_config": config},
        )
        self.assertEqual(resp.status_code, 422)

    def test_url_reference_rejected_on_save(self):
        secret_id = f"SEC_{uuid.uuid4().hex}"
        ca_id = f"ca-{uuid.uuid4().hex}"
        self.client.post(
            f"/api/v1/ca/secrets/{secret_id}",
            headers=self._auth_headers(),
            json={"secret": "x"},
        )
        config = {
            "san_validation": {
                "http_checks": [
                    {"url": f"https://validate.example.com/$secrets[{secret_id}]"}
                ]
            }
        }
        resp = self.client.post(
            f"/api/v1/ca/authorities/{ca_id}",
            headers=self._auth_headers(),
            json={"cn": "Url Ref CA", "validation_config": config},
        )
        self.assertEqual(resp.status_code, 422)
        # cleanup the secret we created
        self.client.delete(
            f"/api/v1/ca/secrets/{secret_id}", headers=self._auth_headers()
        )
