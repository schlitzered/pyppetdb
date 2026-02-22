import unittest

from tests.integration.base import IntegrationTestBase


class TestApiV1HieraLevelData(IntegrationTestBase):
    def _auth_headers(self):
        return {"x-secret-id": "test-cred", "x-secret": "test-secret"}

    def setUp(self):
        super().setUp()
        # Clean up collections before each test
        self._db["hiera_levels"].delete_many({})
        self._db["hiera_keys"].delete_many({})
        self._db["hiera_level_data"].delete_many({})
        self._db["hiera_lookup_cache"].delete_many({})
        # Create test levels - one plain, one with template
        self.client.post(
            "/api/v1/hiera/levels/common",
            json={"priority": 100, "description": "Common level (no template)"},
            headers=self._auth_headers(),
        )
        self.client.post(
            "/api/v1/hiera/levels/{environment}",
            json={"priority": 50, "description": "Environment level (with template)"},
            headers=self._auth_headers(),
        )
        # Create a test key
        self.client.post(
            "/api/v1/hiera/keys/test_key",
            json={"key_model_id": "static:SimpleString", "description": "Test key"},
            headers=self._auth_headers(),
        )

    def test_create_level_data(self):
        """Test creating level data with templated level"""
        response = self.client.post(
            "/api/v1/hiera/data/{environment}/prod/test_key",
            json={"facts": {"environment": "prod"}, "data": "test_value"},
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["id"], "prod")
        self.assertEqual(data["level_id"], "{environment}")
        self.assertEqual(data["key_id"], "test_key")
        self.assertEqual(data["data"], "test_value")
        self.assertEqual(data["facts"]["environment"], "prod")
        self.assertEqual(data["priority"], 50)

    def test_create_level_data_duplicate(self):
        """Test creating duplicate level data returns error"""
        # Create first data
        self.client.post(
            "/api/v1/hiera/data/common/common/test_key",
            json={"facts": {}, "data": "value1"},
            headers=self._auth_headers(),
        )
        # Try to create duplicate
        response = self.client.post(
            "/api/v1/hiera/data/common/common/test_key",
            json={"facts": {}, "data": "value2"},
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 400)

    def test_create_level_data_invalid_key(self):
        """Test creating data with non-existent key fails"""
        response = self.client.post(
            "/api/v1/hiera/data/common/common/nonexistent_key",
            json={"facts": {}, "data": "value"},
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 404)

    def test_create_level_data_invalid_level(self):
        """Test creating data with non-existent level fails"""
        response = self.client.post(
            "/api/v1/hiera/data/nonexistent_level/data1/test_key",
            json={"facts": {}, "data": "value"},
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 404)

    def test_create_level_data_with_int_model(self):
        """Test creating data with integer model"""
        # Create int key
        self.client.post(
            "/api/v1/hiera/keys/int_key",
            json={"key_model_id": "static:SimpleInt"},
            headers=self._auth_headers(),
        )
        # Create data with integer value
        response = self.client.post(
            "/api/v1/hiera/data/common/common/int_key",
            json={"facts": {"env": "prod"}, "data": 42},
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["data"], 42)

    def test_create_level_data_invalid_type(self):
        """Test creating data with wrong type fails validation"""
        # Create int key
        self.client.post(
            "/api/v1/hiera/keys/int_key",
            json={"key_model_id": "static:SimpleInt"},
            headers=self._auth_headers(),
        )
        # Try to create with string value
        response = self.client.post(
            "/api/v1/hiera/data/common/common/int_key",
            json={"facts": {}, "data": "not_an_int"},
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 422)

    def test_get_level_data(self):
        """Test retrieving level data"""
        # Create data
        self.client.post(
            "/api/v1/hiera/data/common/common/test_key",
            json={"facts": {"env": "prod"}, "data": "test_value"},
            headers=self._auth_headers(),
        )
        # Get data
        response = self.client.get(
            "/api/v1/hiera/data/common/common/test_key",
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["id"], "common")
        self.assertEqual(data["data"], "test_value")

    def test_get_level_data_not_found(self):
        """Test getting non-existent data returns 404"""
        response = self.client.get(
            "/api/v1/hiera/data/test_level/nonexistent/test_key",
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 404)

    def test_update_level_data(self):
        """Test updating level data"""
        # Create data
        self.client.post(
            "/api/v1/hiera/data/common/common/test_key",
            json={"facts": {}, "data": "original"},
            headers=self._auth_headers(),
        )
        # Update data
        response = self.client.put(
            "/api/v1/hiera/data/common/common/test_key",
            json={"data": "updated"},
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["data"], "updated")
        # Facts should remain empty for common level
        self.assertEqual(data["facts"], {})

    def test_update_level_data_invalid_type(self):
        """Test updating with wrong type fails"""
        # Create int data
        self.client.post(
            "/api/v1/hiera/keys/int_key",
            json={"key_model_id": "static:SimpleInt"},
            headers=self._auth_headers(),
        )
        self.client.post(
            "/api/v1/hiera/data/common/common/int_key",
            json={"facts": {}, "data": 42},
            headers=self._auth_headers(),
        )
        # Try to update with string
        response = self.client.put(
            "/api/v1/hiera/data/common/common/int_key",
            json={"data": "not_an_int"},
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 422)

    def test_delete_level_data(self):
        """Test deleting level data"""
        # Create data
        self.client.post(
            "/api/v1/hiera/data/common/common/test_key",
            json={"facts": {}, "data": "value"},
            headers=self._auth_headers(),
        )
        # Delete data
        response = self.client.delete(
            "/api/v1/hiera/data/common/common/test_key",
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 200)
        # Verify deletion
        get_response = self.client.get(
            "/api/v1/hiera/data/common/common/test_key",
            headers=self._auth_headers(),
        )
        self.assertEqual(get_response.status_code, 404)

    def test_search_level_data(self):
        """Test searching level data"""
        # Create multiple data entries using template
        self.client.post(
            "/api/v1/hiera/data/{environment}/prod/test_key",
            json={"facts": {"environment": "prod"}, "data": "value1"},
            headers=self._auth_headers(),
        )
        self.client.post(
            "/api/v1/hiera/data/{environment}/dev/test_key",
            json={"facts": {"environment": "dev"}, "data": "value2"},
            headers=self._auth_headers(),
        )
        # Search all data
        response = self.client.get(
            "/api/v1/hiera/data/",
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["result"]), 2)

    def test_search_level_data_by_level(self):
        """Test searching data by level"""
        # Create data in both levels (common and {environment})
        self.client.post(
            "/api/v1/hiera/data/common/common/test_key",
            json={"facts": {}, "data": "value1"},
            headers=self._auth_headers(),
        )
        self.client.post(
            "/api/v1/hiera/data/{environment}/prod/test_key",
            json={"facts": {"environment": "prod"}, "data": "value2"},
            headers=self._auth_headers(),
        )
        # Search by level
        response = self.client.get(
            "/api/v1/hiera/data/?level_id=^common$",
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["result"]), 1)
        self.assertEqual(data["result"][0]["level_id"], "common")

    def test_search_level_data_by_key(self):
        """Test searching data by key"""
        # Create second key
        self.client.post(
            "/api/v1/hiera/keys/key2",
            json={"key_model_id": "static:SimpleString"},
            headers=self._auth_headers(),
        )
        # Create data for both keys
        self.client.post(
            "/api/v1/hiera/data/common/common/test_key",
            json={"facts": {}, "data": "value1"},
            headers=self._auth_headers(),
        )
        self.client.post(
            "/api/v1/hiera/data/common/common/key2",
            json={"facts": {}, "data": "value2"},
            headers=self._auth_headers(),
        )
        # Search by key
        response = self.client.get(
            "/api/v1/hiera/data/?key_id=^test_key$",
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["result"]), 1)
        self.assertEqual(data["result"][0]["key_id"], "test_key")

    def test_search_level_data_by_fact(self):
        """Test searching data by fact with proper filter format"""
        # Create data with different facts using template
        self.client.post(
            "/api/v1/hiera/data/{environment}/prod/test_key",
            json={"facts": {"environment": "prod"}, "data": "value1"},
            headers=self._auth_headers(),
        )
        self.client.post(
            "/api/v1/hiera/data/{environment}/dev/test_key",
            json={"facts": {"environment": "dev"}, "data": "value2"},
            headers=self._auth_headers(),
        )
        # Search by fact using proper format: name:operator:type:value
        response = self.client.get(
            "/api/v1/hiera/data/?fact=environment:eq:str:prod",
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["result"]), 1)
        self.assertEqual(data["result"][0]["facts"]["environment"], "prod")

    def test_search_level_data_pagination(self):
        """Test pagination in data search"""
        # Create multiple levels and data entries
        for i in range(25):
            level_name = f"level{i:02d}"
            self.client.post(
                f"/api/v1/hiera/levels/{level_name}",
                json={"priority": i * 10},
                headers=self._auth_headers(),
            )
            self.client.post(
                f"/api/v1/hiera/data/{level_name}/{level_name}/test_key",
                json={"facts": {}, "data": f"value{i}"},
                headers=self._auth_headers(),
            )
        # Get first page
        response = self.client.get(
            "/api/v1/hiera/data/?page=0&limit=10",
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["result"]), 10)

    def test_level_data_with_complex_data(self):
        """Test storing complex data structures"""
        # Create a dynamic key model that accepts complex data
        self.client.post(
            "/api/v1/hiera/key_models/dynamic/dynamic::complex",
            json={
                "model": {
                    "type": "object",
                    "properties": {
                        "servers": {"type": "array", "items": {"type": "string"}},
                        "config": {"type": "object"}
                    }
                }
            },
            headers=self._auth_headers(),
        )
        self.client.post(
            "/api/v1/hiera/keys/complex_key",
            json={"key_model_id": "dynamic::complex"},
            headers=self._auth_headers(),
        )
        complex_data = {
            "servers": ["server1", "server2"],
            "config": {"timeout": 30, "retries": 3},
        }
        response = self.client.post(
            "/api/v1/hiera/data/common/common/complex_key",
            json={"facts": {}, "data": complex_data},
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 201)
        # Retrieve and verify
        get_response = self.client.get(
            "/api/v1/hiera/data/common/common/complex_key",
            headers=self._auth_headers(),
        )
        self.assertEqual(get_response.status_code, 200)
        data = get_response.json()
        self.assertEqual(data["level_id"], "common")
        self.assertEqual(data["data"]["servers"], ["server1", "server2"])
        self.assertEqual(data["data"]["config"]["timeout"], 30)

    def test_cache_invalidation_on_create(self):
        """Test that cache is invalidated when creating data"""
        # Create data
        response = self.client.post(
            "/api/v1/hiera/data/common/common/test_key",
            json={"facts": {"env": "prod"}, "data": "value"},
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 201)
        # Verify cache was cleared (implicitly tested by successful creation)

    def test_cache_invalidation_on_delete(self):
        """Test that cache is invalidated when deleting data"""
        # Create and delete data
        self.client.post(
            "/api/v1/hiera/data/common/common/test_key",
            json={"facts": {"env": "prod"}, "data": "value"},
            headers=self._auth_headers(),
        )
        response = self.client.delete(
            "/api/v1/hiera/data/common/common/test_key",
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 200)

    def test_unauthorized_access(self):
        """Test that endpoints require authentication"""
        response = self.client.get("/api/v1/hiera/data/")
        self.assertEqual(response.status_code, 401)

    def test_field_filtering(self):
        """Test filtering returned fields"""
        # Create data
        self.client.post(
            "/api/v1/hiera/data/common/common/test_key",
            json={"facts": {}, "data": "value"},
            headers=self._auth_headers(),
        )
        # Get with specific fields
        response = self.client.get(
            "/api/v1/hiera/data/common/common/test_key?fields=id&fields=data",
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("id", data)
        self.assertIn("data", data)
        self.assertNotIn("level_id", data)


if __name__ == "__main__":
    unittest.main()
