import unittest

from tests.integration.base import IntegrationTestBase


class TestApiV1HieraKeys(IntegrationTestBase):
    def _auth_headers(self):
        return {"x-secret-id": "test-cred", "x-secret": "test-secret"}

    def setUp(self):
        super().setUp()
        # Clean up collections before each test
        self._db["hiera_keys"].delete_many({})
        self._db["hiera_key_models_dynamic"].delete_many({})

    def test_create_key_with_static_model(self):
        """Test creating a key with a static model"""
        response = self.client.post(
            "/api/v1/hiera/keys/test_key",
            json={
                "key_model_id": "static:SimpleString",
                "description": "Test string key",
                "deprecated": False,
            },
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["id"], "test_key")
        self.assertEqual(data["key_model_id"], "static:SimpleString")
        self.assertEqual(data["description"], "Test string key")
        self.assertFalse(data["deprecated"])

    def test_create_key_duplicate(self):
        """Test creating a duplicate key returns error"""
        # Create first key
        self.client.post(
            "/api/v1/hiera/keys/test_key",
            json={"key_model_id": "static:SimpleString"},
            headers=self._auth_headers(),
        )
        # Try to create duplicate
        response = self.client.post(
            "/api/v1/hiera/keys/test_key",
            json={"key_model_id": "static:SimpleInt"},
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 400)

    def test_create_key_with_dynamic_model(self):
        """Test creating a key with a dynamic model"""
        # First create a dynamic model
        self.client.post(
            "/api/v1/hiera/key_models/dynamic/dynamic::custom_model",
            json={
                "description": "Custom model",
                "model": {"type": "object", "properties": {"name": {"type": "string"}}},
            },
            headers=self._auth_headers(),
        )
        # Create key with dynamic model
        response = self.client.post(
            "/api/v1/hiera/keys/custom_key",
            json={"key_model_id": "dynamic::custom_model", "description": "Custom key"},
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["key_model_id"], "dynamic::custom_model")

    def test_create_key_invalid_model(self):
        """Test creating key with non-existent model fails"""
        response = self.client.post(
            "/api/v1/hiera/keys/test_key",
            json={"key_model_id": "static:nonexistent"},
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 422)

    def test_get_key(self):
        """Test retrieving a hiera key"""
        # Create key
        self.client.post(
            "/api/v1/hiera/keys/test_key",
            json={"key_model_id": "static:SimpleString", "description": "Test key"},
            headers=self._auth_headers(),
        )
        # Get key
        response = self.client.get(
            "/api/v1/hiera/keys/test_key",
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["id"], "test_key")
        self.assertEqual(data["key_model_id"], "static:SimpleString")

    def test_get_key_not_found(self):
        """Test getting non-existent key returns 404"""
        response = self.client.get(
            "/api/v1/hiera/keys/nonexistent",
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 404)

    def test_update_key_description(self):
        """Test updating key description"""
        # Create key
        self.client.post(
            "/api/v1/hiera/keys/test_key",
            json={"key_model_id": "static:SimpleString", "description": "Original"},
            headers=self._auth_headers(),
        )
        # Update description
        response = self.client.put(
            "/api/v1/hiera/keys/test_key",
            json={"description": "Updated description"},
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["description"], "Updated description")

    def test_update_key_deprecation(self):
        """Test marking key as deprecated"""
        # Create key
        self.client.post(
            "/api/v1/hiera/keys/test_key",
            json={"key_model_id": "static:SimpleString", "deprecated": False},
            headers=self._auth_headers(),
        )
        # Mark as deprecated
        response = self.client.put(
            "/api/v1/hiera/keys/test_key",
            json={"deprecated": True},
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["deprecated"])

    def test_update_key_model(self):
        """Test updating key model"""
        # Create key
        self.client.post(
            "/api/v1/hiera/keys/test_key",
            json={"key_model_id": "static:SimpleString"},
            headers=self._auth_headers(),
        )
        # Update model
        response = self.client.put(
            "/api/v1/hiera/keys/test_key",
            json={"key_model_id": "static:SimpleInt"},
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["key_model_id"], "static:SimpleInt")

    def test_delete_key(self):
        """Test deleting a hiera key"""
        # Create key
        self.client.post(
            "/api/v1/hiera/keys/test_key",
            json={"key_model_id": "static:SimpleString"},
            headers=self._auth_headers(),
        )
        # Delete key
        response = self.client.delete(
            "/api/v1/hiera/keys/test_key",
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 200)
        # Verify deletion
        get_response = self.client.get(
            "/api/v1/hiera/keys/test_key",
            headers=self._auth_headers(),
        )
        self.assertEqual(get_response.status_code, 404)

    def test_search_keys(self):
        """Test searching hiera keys"""
        # Create multiple keys
        self.client.post(
            "/api/v1/hiera/keys/key1",
            json={"key_model_id": "static:SimpleString", "description": "First"},
            headers=self._auth_headers(),
        )
        self.client.post(
            "/api/v1/hiera/keys/key2",
            json={"key_model_id": "static:SimpleInt", "description": "Second"},
            headers=self._auth_headers(),
        )
        self.client.post(
            "/api/v1/hiera/keys/key3",
            json={"key_model_id": "static:SimpleString", "description": "Third"},
            headers=self._auth_headers(),
        )
        # Search all keys
        response = self.client.get(
            "/api/v1/hiera/keys",
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["result"]), 3)

    def test_search_keys_by_id(self):
        """Test searching keys with id filter"""
        # Create multiple keys
        self.client.post(
            "/api/v1/hiera/keys/prod_key",
            json={"key_model_id": "static:SimpleString"},
            headers=self._auth_headers(),
        )
        self.client.post(
            "/api/v1/hiera/keys/dev_key",
            json={"key_model_id": "static:SimpleString"},
            headers=self._auth_headers(),
        )
        # Search with filter
        response = self.client.get(
            "/api/v1/hiera/keys?key_id=^prod",
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["result"]), 1)
        self.assertEqual(data["result"][0]["id"], "prod_key")

    def test_search_keys_by_model(self):
        """Test searching keys by model type"""
        # Create keys with different models
        self.client.post(
            "/api/v1/hiera/keys/str_key1",
            json={"key_model_id": "static:SimpleString"},
            headers=self._auth_headers(),
        )
        self.client.post(
            "/api/v1/hiera/keys/str_key2",
            json={"key_model_id": "static:SimpleString"},
            headers=self._auth_headers(),
        )
        self.client.post(
            "/api/v1/hiera/keys/int_key",
            json={"key_model_id": "static:SimpleInt"},
            headers=self._auth_headers(),
        )
        # Search for string model keys
        response = self.client.get(
            "/api/v1/hiera/keys?key_model_id=static:SimpleString",
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["result"]), 2)

    def test_search_keys_by_deprecated(self):
        """Test searching keys by deprecated status"""
        # Create deprecated and active keys
        self.client.post(
            "/api/v1/hiera/keys/old_key",
            json={"key_model_id": "static:SimpleString", "deprecated": True},
            headers=self._auth_headers(),
        )
        self.client.post(
            "/api/v1/hiera/keys/new_key",
            json={"key_model_id": "static:SimpleString", "deprecated": False},
            headers=self._auth_headers(),
        )
        # Search for deprecated keys
        response = self.client.get(
            "/api/v1/hiera/keys?deprecated=true",
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["result"]), 1)
        self.assertEqual(data["result"][0]["id"], "old_key")

    def test_search_keys_pagination(self):
        """Test pagination in key search"""
        # Create multiple keys
        for i in range(25):
            self.client.post(
                f"/api/v1/hiera/keys/key{i:02d}",
                json={"key_model_id": "static:SimpleString"},
                headers=self._auth_headers(),
            )
        # Get first page
        response = self.client.get(
            "/api/v1/hiera/keys?page=0&limit=10",
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["result"]), 10)

    def test_unauthorized_access(self):
        """Test that endpoints require authentication"""
        response = self.client.get("/api/v1/hiera/keys")
        self.assertEqual(response.status_code, 401)

    def test_field_filtering(self):
        """Test filtering returned fields"""
        # Create key
        self.client.post(
            "/api/v1/hiera/keys/test_key",
            json={
                "key_model_id": "static:SimpleString",
                "description": "Test",
                "deprecated": False,
            },
            headers=self._auth_headers(),
        )
        # Get with specific fields
        response = self.client.get(
            "/api/v1/hiera/keys/test_key?fields=id&fields=key_model_id",
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("id", data)
        self.assertIn("key_model_id", data)
        self.assertNotIn("description", data)


if __name__ == "__main__":
    unittest.main()
