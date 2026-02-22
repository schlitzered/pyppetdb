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
