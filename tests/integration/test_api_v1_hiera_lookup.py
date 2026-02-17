import unittest

from tests.integration.base import IntegrationTestBase


class TestApiV1HieraLookup(IntegrationTestBase):
    def _auth_headers(self):
        return {"x-secret-id": "test-cred", "x-secret": "test-secret"}

    def setUp(self):
        super().setUp()
        # Clean up collections before each test
        self._db["hiera_levels"].delete_many({})
        self._db["hiera_keys"].delete_many({})
        self._db["hiera_level_data"].delete_many({})
        self._db["hiera_lookup_cache"].delete_many({})
        # Create minimal hierarchy for simple tests - just common level
        # Tests that need template levels will create them explicitly
        self.client.post(
            "/api/v1/hiera/levels/common",
            json={"priority": 100, "description": "Common level (no template)"},
            headers=self._auth_headers(),
        )
        # Create test key
        self.client.post(
            "/api/v1/hiera/keys/app_name",
            json={
                "key_model_id": "static:SimpleString",
                "description": "Application name",
            },
            headers=self._auth_headers(),
        )

    def test_lookup_simple(self):
        """Test simple lookup without facts"""
        # Create data
        self.client.post(
            "/api/v1/hiera/data/common/common/app_name",
            json={"facts": {}, "data": "myapp"},
            headers=self._auth_headers(),
        )
        # Lookup
        response = self.client.get(
            "/api/v1/hiera/lookup/app_name",
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["data"], "myapp")

    def test_lookup_with_facts(self):
        """Test lookup with fact matching"""
        # Create environment level for this test
        self.client.post(
            "/api/v1/hiera/levels/{environment}",
            json={"priority": 50, "description": "Environment level (with template)"},
            headers=self._auth_headers(),
        )
        # Create data with facts using templated level
        self.client.post(
            "/api/v1/hiera/data/{environment}/prod/app_name",
            json={"facts": {"environment": "prod"}, "data": "prod-app"},
            headers=self._auth_headers(),
        )
        self.client.post(
            "/api/v1/hiera/data/{environment}/dev/app_name",
            json={"facts": {"environment": "dev"}, "data": "dev-app"},
            headers=self._auth_headers(),
        )
        # Lookup with fact
        response = self.client.get(
            "/api/v1/hiera/lookup/app_name?fact=environment:prod",
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["data"], "prod-app")

    def test_lookup_hierarchy_priority(self):
        """Test that lookup respects hierarchy priority"""
        # Create template levels
        self.client.post(
            "/api/v1/hiera/levels/{environment}",
            json={"priority": 50, "description": "Environment level"},
            headers=self._auth_headers(),
        )
        self.client.post(
            "/api/v1/hiera/levels/{hostname}",
            json={"priority": 10, "description": "Host level"},
            headers=self._auth_headers(),
        )
        # Create data at different levels
        self.client.post(
            "/api/v1/hiera/data/common/common/app_name",
            json={"facts": {}, "data": "common-app"},
            headers=self._auth_headers(),
        )
        self.client.post(
            "/api/v1/hiera/data/{environment}/prod/app_name",
            json={"facts": {"environment": "prod"}, "data": "prod-app"},
            headers=self._auth_headers(),
        )
        self.client.post(
            "/api/v1/hiera/data/{hostname}/server1/app_name",
            json={"facts": {"hostname": "server1"}, "data": "server1-app"},
            headers=self._auth_headers(),
        )
        # Lookup should return highest priority (lowest number) matching value
        response = self.client.get(
            "/api/v1/hiera/lookup/app_name?fact=environment:prod&fact=hostname:server1",
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        # Host level has priority 10 (highest priority)
        self.assertEqual(data["data"], "server1-app")

    def test_lookup_fallback_to_lower_priority(self):
        """Test fallback to lower priority when no match at higher level"""
        # Create environment level
        self.client.post(
            "/api/v1/hiera/levels/{environment}",
            json={"priority": 50},
            headers=self._auth_headers(),
        )
        # Create data only at common level
        self.client.post(
            "/api/v1/hiera/data/common/common/app_name",
            json={"facts": {}, "data": "default-app"},
            headers=self._auth_headers(),
        )
        # Lookup with facts that don't match any data
        response = self.client.get(
            "/api/v1/hiera/lookup/app_name?fact=environment:staging",
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        # Should fall back to common level
        self.assertEqual(data["data"], "default-app")

    def test_lookup_multiple_facts(self):
        """Test lookup with multiple facts"""
        # Create hostname level
        self.client.post(
            "/api/v1/hiera/levels/{hostname}",
            json={"priority": 10},
            headers=self._auth_headers(),
        )
        # Create data requiring multiple facts
        self.client.post(
            "/api/v1/hiera/data/{hostname}/server1/app_name",
            json={
                "facts": {
                    "hostname": "server1",
                    "environment": "prod",
                    "region": "us-east",
                    "tier": "web",
                },
                "data": "us-east-prod-web-app",
            },
            headers=self._auth_headers(),
        )
        # Lookup with all matching facts
        response = self.client.get(
            "/api/v1/hiera/lookup/app_name?fact=hostname:server1&fact=environment:prod&fact=region:us-east&fact=tier:web",
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["data"], "us-east-prod-web-app")

    def test_lookup_partial_fact_match(self):
        """Test that data matches when provided facts are subset of stored facts"""
        # Create environment level
        self.client.post(
            "/api/v1/hiera/levels/{environment}",
            json={"priority": 50},
            headers=self._auth_headers(),
        )
        # Create data with specific facts
        self.client.post(
            "/api/v1/hiera/data/{environment}/prod/app_name",
            json={
                "facts": {"environment": "prod", "region": "us-east"},
                "data": "specific-app",
            },
            headers=self._auth_headers(),
        )
        self.client.post(
            "/api/v1/hiera/data/common/common/app_name",
            json={"facts": {}, "data": "default-app"},
            headers=self._auth_headers(),
        )
        # Lookup with only environment fact - should match as provided facts match stored facts
        response = self.client.get(
            "/api/v1/hiera/lookup/app_name?fact=environment:prod",
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        # Matches the higher priority data since provided fact matches
        self.assertEqual(data["data"], "specific-app")

    def test_lookup_nonexistent_key(self):
        """Test lookup of non-existent key"""
        response = self.client.get(
            "/api/v1/hiera/lookup/nonexistent_key",
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 422)

    def test_lookup_key_with_no_data(self):
        """Test lookup when key exists but has no data"""
        # Create key without any data
        self.client.post(
            "/api/v1/hiera/keys/empty_key",
            json={"key_model_id": "static:SimpleString"},
            headers=self._auth_headers(),
        )
        # Lookup
        response = self.client.get(
            "/api/v1/hiera/lookup/empty_key",
            headers=self._auth_headers(),
        )
        # Should fail because no data exists
        self.assertEqual(response.status_code, 422)

    def test_lookup_integer_data(self):
        """Test lookup with integer data type"""
        # Create integer key
        self.client.post(
            "/api/v1/hiera/keys/port_number",
            json={"key_model_id": "static:SimpleInt"},
            headers=self._auth_headers(),
        )
        self.client.post(
            "/api/v1/hiera/data/common/common/port_number",
            json={"facts": {}, "data": 8080},
            headers=self._auth_headers(),
        )
        # Lookup
        response = self.client.get(
            "/api/v1/hiera/lookup/port_number",
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["data"], 8080)

    def test_lookup_complex_data(self):
        """Test lookup with complex data structures"""
        # Create dynamic model for complex data
        self.client.post(
            "/api/v1/hiera/key_models/dynamic/dynamic::complex",
            json={
                "model": {
                    "type": "object",
                    "properties": {
                        "servers": {"type": "array", "items": {"type": "string"}},
                        "config": {"type": "object"},
                    },
                }
            },
            headers=self._auth_headers(),
        )
        self.client.post(
            "/api/v1/hiera/keys/complex_key",
            json={"key_model_id": "dynamic::complex"},
            headers=self._auth_headers(),
        )
        # Create key and data with dict/list
        complex_data = {
            "servers": ["server1", "server2", "server3"],
            "config": {"timeout": 30, "retries": 3, "ssl": True},
        }
        self.client.post(
            "/api/v1/hiera/data/common/common/complex_key",
            json={"facts": {}, "data": complex_data},
            headers=self._auth_headers(),
        )
        # Lookup
        response = self.client.get(
            "/api/v1/hiera/lookup/complex_key",
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["data"]["servers"], ["server1", "server2", "server3"])
        self.assertEqual(data["data"]["config"]["timeout"], 30)

    def test_lookup_merge_dicts(self):
        """Test lookup with merge=true for dict merging"""
        # Create environment level
        self.client.post(
            "/api/v1/hiera/levels/{environment}",
            json={"priority": 50},
            headers=self._auth_headers(),
        )
        # Create dynamic model for complex data
        self.client.post(
            "/api/v1/hiera/key_models/dynamic/dynamic::dict",
            json={"model": {"type": "object"}},
            headers=self._auth_headers(),
        )
        self.client.post(
            "/api/v1/hiera/keys/config_data",
            json={"key_model_id": "dynamic::dict"},
            headers=self._auth_headers(),
        )
        # Create data at different levels with dicts
        self.client.post(
            "/api/v1/hiera/data/common/common/config_data",
            json={"facts": {}, "data": {"timeout": 30, "retries": 3}},
            headers=self._auth_headers(),
        )
        self.client.post(
            "/api/v1/hiera/data/{environment}/prod/config_data",
            json={
                "facts": {"environment": "prod"},
                "data": {"timeout": 60, "ssl": True},
            },
            headers=self._auth_headers(),
        )
        # Lookup with merge
        response = self.client.get(
            "/api/v1/hiera/lookup/config_data?merge=true&fact=environment:prod",
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        # Should merge dicts from both levels
        self.assertIsInstance(data["data"], dict)
        # Verify merge worked: timeout overridden, retries kept, ssl added
        self.assertEqual(data["data"]["timeout"], 60)  # overridden from prod
        self.assertEqual(data["data"]["retries"], 3)  # kept from common
        self.assertEqual(data["data"]["ssl"], True)  # added from prod

    def test_lookup_caching(self):
        """Test that lookups are cached"""
        # Create data
        self.client.post(
            "/api/v1/hiera/data/common/common/app_name",
            json={"facts": {}, "data": "cached-app"},
            headers=self._auth_headers(),
        )
        # First lookup (not cached)
        response1 = self.client.get(
            "/api/v1/hiera/lookup/app_name",
            headers=self._auth_headers(),
        )
        self.assertEqual(response1.status_code, 200)
        # Second lookup (should be cached)
        response2 = self.client.get(
            "/api/v1/hiera/lookup/app_name",
            headers=self._auth_headers(),
        )
        self.assertEqual(response2.status_code, 200)
        self.assertEqual(response1.json()["data"], response2.json()["data"])

    def test_lookup_cache_invalidation(self):
        """Test that cache is invalidated when data changes"""
        # Create initial data
        self.client.post(
            "/api/v1/hiera/data/common/common/app_name",
            json={"facts": {}, "data": "original"},
            headers=self._auth_headers(),
        )
        # Lookup (cached)
        response1 = self.client.get(
            "/api/v1/hiera/lookup/app_name",
            headers=self._auth_headers(),
        )
        self.assertEqual(response1.json()["data"], "original")
        # Update data (should invalidate cache)
        self.client.put(
            "/api/v1/hiera/data/common/common/app_name",
            json={"data": "updated"},
            headers=self._auth_headers(),
        )
        # Lookup again (should get new value)
        response2 = self.client.get(
            "/api/v1/hiera/lookup/app_name",
            headers=self._auth_headers(),
        )
        self.assertEqual(response2.json()["data"], "updated")

    def test_lookup_invalid_fact_format(self):
        """Test that invalid fact format returns error"""
        # Fact without colon
        response = self.client.get(
            "/api/v1/hiera/lookup/app_name?fact=invalid_format",
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 422)

    def test_lookup_empty_fact_value(self):
        """Test that empty fact value returns error"""
        response = self.client.get(
            "/api/v1/hiera/lookup/app_name?fact=key:",
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 422)

    def test_lookup_without_merge(self):
        """Test lookup without merge returns first match"""
        # Create hostname level
        self.client.post(
            "/api/v1/hiera/levels/{hostname}",
            json={"priority": 10},
            headers=self._auth_headers(),
        )
        # Create data at multiple levels
        self.client.post(
            "/api/v1/hiera/data/common/common/app_name",
            json={"facts": {}, "data": "common-value"},
            headers=self._auth_headers(),
        )
        self.client.post(
            "/api/v1/hiera/data/{hostname}/server1/app_name",
            json={"facts": {"hostname": "server1"}, "data": "host-value"},
            headers=self._auth_headers(),
        )
        # Lookup without merge
        response = self.client.get(
            "/api/v1/hiera/lookup/app_name?merge=false&fact=hostname:server1",
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        # Should return first match (highest priority)
        self.assertEqual(data["data"], "host-value")

    def test_unauthorized_access(self):
        """Test that lookup endpoint requires authentication"""
        response = self.client.get("/api/v1/hiera/lookup/app_name")
        self.assertEqual(response.status_code, 401)

    def test_lookup_with_deprecated_key(self):
        """Test lookup works with deprecated keys"""
        # Create deprecated key
        self.client.post(
            "/api/v1/hiera/keys/old_key",
            json={"key_model_id": "static:SimpleString", "deprecated": True},
            headers=self._auth_headers(),
        )
        self.client.post(
            "/api/v1/hiera/data/common/common/old_key",
            json={"facts": {}, "data": "old-value"},
            headers=self._auth_headers(),
        )
        # Lookup should still work
        response = self.client.get(
            "/api/v1/hiera/lookup/old_key",
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["data"], "old-value")

    def test_lookup_case_sensitive_facts(self):
        """Test that fact matching is case-sensitive"""
        # Create environment level
        self.client.post(
            "/api/v1/hiera/levels/{environment}",
            json={"priority": 50},
            headers=self._auth_headers(),
        )
        # Create data with specific case
        self.client.post(
            "/api/v1/hiera/data/{environment}/Prod/app_name",
            json={"facts": {"environment": "Prod"}, "data": "value"},
            headers=self._auth_headers(),
        )
        # Lookup with different case should not match
        response = self.client.get(
            "/api/v1/hiera/lookup/app_name?fact=environment:prod",
            headers=self._auth_headers(),
        )
        # Should fail to find or return different value
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
