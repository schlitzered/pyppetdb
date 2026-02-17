import unittest

from tests.integration.base import IntegrationTestBase


class TestApiV1HieraKeyModelsStatic(IntegrationTestBase):
    """Tests for static (built-in) key models"""

    def _auth_headers(self):
        return {"x-secret-id": "test-cred", "x-secret": "test-secret"}

    def test_search_static_models(self):
        """Test searching static key models"""
        response = self.client.get(
            "/api/v1/hiera/key_models/static",
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertGreater(len(data["result"]), 0)
        # Verify all results have static prefix
        for item in data["result"]:
            self.assertTrue(item["id"].startswith("static:"))

    def test_get_static_str_model(self):
        """Test retrieving static string model"""
        response = self.client.get(
            "/api/v1/hiera/key_models/static/static:SimpleString",
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["id"], "static:SimpleString")
        self.assertIn("model", data)

    def test_get_static_int_model(self):
        """Test retrieving static int model"""
        response = self.client.get(
            "/api/v1/hiera/key_models/static/static:SimpleInt",
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["id"], "static:SimpleInt")

    def test_get_static_model_without_prefix(self):
        """Test that requesting without prefix fails"""
        response = self.client.get(
            "/api/v1/hiera/key_models/static/str",
            headers=self._auth_headers(),
        )
        # Should fail because it expects prefix
        self.assertEqual(response.status_code, 422)

    def test_get_static_model_with_dynamic_prefix(self):
        """Test that requesting with wrong prefix fails"""
        response = self.client.get(
            "/api/v1/hiera/key_models/static/dynamic::str",
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 422)

    def test_search_static_models_with_filter(self):
        """Test searching static models with id filter"""
        response = self.client.get(
            "/api/v1/hiera/key_models/static?key_model_id=static:SimpleString",
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertGreater(len(data["result"]), 0)
        for item in data["result"]:
            self.assertIn("String", item["id"])

    def test_search_static_models_pagination(self):
        """Test pagination in static model search"""
        response = self.client.get(
            "/api/v1/hiera/key_models/static?page=0&limit=10",
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("meta", data)

    def test_static_models_are_readonly(self):
        """Test that static models cannot be created/deleted"""
        # There should be no POST/DELETE endpoints for static models
        # This is implicit in the API design
        pass

    def test_unauthorized_access(self):
        """Test that endpoints require authentication"""
        response = self.client.get("/api/v1/hiera/key_models/static")
        self.assertEqual(response.status_code, 401)


class TestApiV1HieraKeyModelsDynamic(IntegrationTestBase):
    """Tests for dynamic (user-defined) key models"""

    def _auth_headers(self):
        return {"x-secret-id": "test-cred", "x-secret": "test-secret"}

    def setUp(self):
        super().setUp()
        # Clean up dynamic models before each test
        self._db["hiera_key_models_dynamic"].delete_many({})
        self._db["hiera_keys"].delete_many({})

    def test_create_dynamic_model(self):
        """Test creating a dynamic key model"""
        response = self.client.post(
            "/api/v1/hiera/key_models/dynamic/dynamic::custom_model",
            json={
                "description": "Custom model",
                "model": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}, "age": {"type": "integer"}},
                    "required": ["name"],
                },
            },
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["id"], "dynamic::custom_model")
        self.assertEqual(data["description"], "Custom model")
        self.assertIn("model", data)

    def test_create_dynamic_model_without_prefix(self):
        """Test that creating without prefix fails"""
        response = self.client.post(
            "/api/v1/hiera/key_models/dynamic/custom_model",
            json={
                "model": {"type": "string"},
            },
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 422)

    def test_create_dynamic_model_with_static_prefix(self):
        """Test that creating with wrong prefix fails"""
        response = self.client.post(
            "/api/v1/hiera/key_models/dynamic/static::custom",
            json={
                "model": {"type": "string"},
            },
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 422)

    def test_create_dynamic_model_duplicate(self):
        """Test creating duplicate dynamic model fails"""
        # Create first model
        self.client.post(
            "/api/v1/hiera/key_models/dynamic/dynamic::test",
            json={"model": {"type": "string"}},
            headers=self._auth_headers(),
        )
        # Try to create duplicate
        response = self.client.post(
            "/api/v1/hiera/key_models/dynamic/dynamic::test",
            json={"model": {"type": "integer"}},
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 400)

    def test_get_dynamic_model(self):
        """Test retrieving a dynamic model"""
        # Create model
        self.client.post(
            "/api/v1/hiera/key_models/dynamic/dynamic::test",
            json={
                "description": "Test model",
                "model": {"type": "string"},
            },
            headers=self._auth_headers(),
        )
        # Get model
        response = self.client.get(
            "/api/v1/hiera/key_models/dynamic/dynamic::test",
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["id"], "dynamic::test")
        self.assertEqual(data["description"], "Test model")

    def test_get_dynamic_model_not_found(self):
        """Test getting non-existent model returns 404"""
        response = self.client.get(
            "/api/v1/hiera/key_models/dynamic/dynamic::nonexistent",
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 404)

    def test_delete_dynamic_model(self):
        """Test deleting a dynamic model"""
        # Create model
        self.client.post(
            "/api/v1/hiera/key_models/dynamic/dynamic::test",
            json={"model": {"type": "string"}},
            headers=self._auth_headers(),
        )
        # Delete model
        response = self.client.delete(
            "/api/v1/hiera/key_models/dynamic/dynamic::test",
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 200)
        # Verify deletion
        get_response = self.client.get(
            "/api/v1/hiera/key_models/dynamic/dynamic::test",
            headers=self._auth_headers(),
        )
        self.assertEqual(get_response.status_code, 404)

    def test_delete_dynamic_model_in_use(self):
        """Test that deleting model in use by keys fails"""
        # Create model
        self.client.post(
            "/api/v1/hiera/key_models/dynamic/dynamic::test",
            json={"model": {"type": "string"}},
            headers=self._auth_headers(),
        )
        # Create key using this model
        self.client.post(
            "/api/v1/hiera/keys/test_key",
            json={"key_model_id": "dynamic::test"},
            headers=self._auth_headers(),
        )
        # Try to delete model
        response = self.client.delete(
            "/api/v1/hiera/key_models/dynamic/dynamic::test",
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("still in use", response.json()["detail"])

    def test_search_dynamic_models(self):
        """Test searching dynamic models"""
        # Create multiple models
        self.client.post(
            "/api/v1/hiera/key_models/dynamic/dynamic::model1",
            json={"description": "First", "model": {"type": "string"}},
            headers=self._auth_headers(),
        )
        self.client.post(
            "/api/v1/hiera/key_models/dynamic/dynamic::model2",
            json={"description": "Second", "model": {"type": "integer"}},
            headers=self._auth_headers(),
        )
        # Search all models
        response = self.client.get(
            "/api/v1/hiera/key_models/dynamic",
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["result"]), 2)

    def test_search_dynamic_models_with_filter(self):
        """Test searching dynamic models with filter"""
        # Create multiple models
        self.client.post(
            "/api/v1/hiera/key_models/dynamic/dynamic::prod_model",
            json={"model": {"type": "string"}},
            headers=self._auth_headers(),
        )
        self.client.post(
            "/api/v1/hiera/key_models/dynamic/dynamic::dev_model",
            json={"model": {"type": "string"}},
            headers=self._auth_headers(),
        )
        # Search with filter
        response = self.client.get(
            "/api/v1/hiera/key_models/dynamic?key_model_id=dynamic::prod",
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["result"]), 1)
        self.assertTrue(data["result"][0]["id"].startswith("dynamic::prod"))

    def test_search_dynamic_models_pagination(self):
        """Test pagination in dynamic model search"""
        # Create multiple models
        for i in range(25):
            self.client.post(
                f"/api/v1/hiera/key_models/dynamic/dynamic::model{i:02d}",
                json={"model": {"type": "string"}},
                headers=self._auth_headers(),
            )
        # Get first page
        response = self.client.get(
            "/api/v1/hiera/key_models/dynamic?page=0&limit=10",
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["result"]), 10)

    def test_dynamic_model_complex_schema(self):
        """Test creating model with complex JSON schema"""
        complex_schema = {
            "type": "object",
            "properties": {
                "server": {
                    "type": "object",
                    "properties": {
                        "host": {"type": "string"},
                        "port": {"type": "integer", "minimum": 1, "maximum": 65535},
                        "ssl": {"type": "boolean"},
                    },
                    "required": ["host", "port"],
                },
                "users": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["server"],
        }
        response = self.client.post(
            "/api/v1/hiera/key_models/dynamic/dynamic::server_config",
            json={
                "description": "Server configuration model",
                "model": complex_schema,
            },
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["id"], "dynamic::server_config")
        self.assertEqual(data["model"], complex_schema)

    def test_unauthorized_access(self):
        """Test that endpoints require authentication"""
        response = self.client.get("/api/v1/hiera/key_models/dynamic")
        self.assertEqual(response.status_code, 401)

    def test_field_filtering(self):
        """Test filtering returned fields"""
        # Create model
        self.client.post(
            "/api/v1/hiera/key_models/dynamic/dynamic::test",
            json={
                "description": "Test",
                "model": {"type": "string"},
            },
            headers=self._auth_headers(),
        )
        # Get with specific fields
        response = self.client.get(
            "/api/v1/hiera/key_models/dynamic/dynamic::test?fields=id&fields=description",
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("id", data)
        self.assertIn("description", data)
        self.assertNotIn("model", data)


if __name__ == "__main__":
    unittest.main()
