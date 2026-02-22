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
