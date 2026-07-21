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

import unittest

import uuid
from pyppetdb.authorize import PERM_HIERA_LEVELS_CREATE
from pyppetdb.authorize import PERM_HIERA_GET
from tests.integration.base import IntegrationTestBase


class TestApiV1HieraLevels(IntegrationTestBase):
    def _auth_headers(self):
        return {"x-secret-id": "test-cred", "x-secret": "test-secret"}

    def setUp(self):
        super().setUp()
        # Clean up hiera levels before each test
        self._db["hiera_levels"].delete_many({})

    def test_create_level(self):
        """Test creating a new hiera level"""
        response = self.client.post(
            "/api/v1/hiera/levels/test_level",
            json={"priority": 100, "description": "Test level"},
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["id"], "test_level")
        self.assertEqual(data["priority"], 100)
        self.assertEqual(data["description"], "Test level")

    def test_create_level_duplicate(self):
        """Test creating a duplicate level returns error"""
        # Create first level
        self.client.post(
            "/api/v1/hiera/levels/test_level",
            json={"priority": 100},
            headers=self._auth_headers(),
        )
        # Try to create duplicate
        response = self.client.post(
            "/api/v1/hiera/levels/test_level",
            json={"priority": 200},
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 400)

    def test_get_level(self):
        """Test retrieving a hiera level"""
        # Create level first
        self.client.post(
            "/api/v1/hiera/levels/test_level",
            json={"priority": 100, "description": "Test level"},
            headers=self._auth_headers(),
        )
        # Get level
        response = self.client.get(
            "/api/v1/hiera/levels/test_level",
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["id"], "test_level")
        self.assertEqual(data["priority"], 100)

    def test_get_level_not_found(self):
        """Test getting non-existent level returns 404"""
        response = self.client.get(
            "/api/v1/hiera/levels/nonexistent",
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 404)

    def test_update_level(self):
        """Test updating a hiera level"""
        # Create level
        self.client.post(
            "/api/v1/hiera/levels/test_level",
            json={"priority": 100, "description": "Original"},
            headers=self._auth_headers(),
        )
        # Update level
        response = self.client.put(
            "/api/v1/hiera/levels/test_level",
            json={"priority": 200, "description": "Updated"},
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["priority"], 200)
        self.assertEqual(data["description"], "Updated")

    def test_update_level_partial(self):
        """Test partially updating a level"""
        # Create level
        self.client.post(
            "/api/v1/hiera/levels/test_level",
            json={"priority": 100, "description": "Original"},
            headers=self._auth_headers(),
        )
        # Update only description
        response = self.client.put(
            "/api/v1/hiera/levels/test_level",
            json={"description": "Updated description only"},
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["priority"], 100)
        self.assertEqual(data["description"], "Updated description only")

    def test_delete_level(self):
        """Test deleting a hiera level"""
        # Create level
        self.client.post(
            "/api/v1/hiera/levels/test_level",
            json={"priority": 100},
            headers=self._auth_headers(),
        )
        # Delete level
        response = self.client.delete(
            "/api/v1/hiera/levels/test_level",
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 200)
        # Verify deletion
        get_response = self.client.get(
            "/api/v1/hiera/levels/test_level",
            headers=self._auth_headers(),
        )
        self.assertEqual(get_response.status_code, 404)

    def test_search_levels(self):
        """Test searching hiera levels"""
        # Create multiple levels
        self.client.post(
            "/api/v1/hiera/levels/level1",
            json={"priority": 100, "description": "First"},
            headers=self._auth_headers(),
        )
        self.client.post(
            "/api/v1/hiera/levels/level2",
            json={"priority": 200, "description": "Second"},
            headers=self._auth_headers(),
        )
        self.client.post(
            "/api/v1/hiera/levels/level3",
            json={"priority": 150, "description": "Third"},
            headers=self._auth_headers(),
        )
        # Search all levels
        response = self.client.get(
            "/api/v1/hiera/levels",
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["result"]), 3)
        # Verify sorted by priority (default)
        self.assertEqual(data["result"][0]["priority"], 100)
        self.assertEqual(data["result"][1]["priority"], 150)
        self.assertEqual(data["result"][2]["priority"], 200)

    def test_search_levels_with_filter(self):
        """Test searching levels with regex filter"""
        # Create multiple levels
        self.client.post(
            "/api/v1/hiera/levels/prod_level",
            json={"priority": 100},
            headers=self._auth_headers(),
        )
        self.client.post(
            "/api/v1/hiera/levels/dev_level",
            json={"priority": 200},
            headers=self._auth_headers(),
        )
        # Search with filter
        response = self.client.get(
            "/api/v1/hiera/levels?level_id=^prod",
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["result"]), 1)
        self.assertEqual(data["result"][0]["id"], "prod_level")

    def test_search_levels_pagination(self):
        """Test pagination in level search"""
        # Create multiple levels
        for i in range(25):
            self.client.post(
                f"/api/v1/hiera/levels/level{i:02d}",
                json={"priority": i * 10},
                headers=self._auth_headers(),
            )
        # Get first page
        response = self.client.get(
            "/api/v1/hiera/levels?page=0&limit=10",
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["result"]), 10)
        self.assertIn("meta", data)
        # Get second page
        response = self.client.get(
            "/api/v1/hiera/levels?page=1&limit=10",
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["result"]), 10)

    def test_search_levels_sort_order(self):
        """Test sorting order in search"""
        # Create levels
        self.client.post(
            "/api/v1/hiera/levels/aaa",
            json={"priority": 300},
            headers=self._auth_headers(),
        )
        self.client.post(
            "/api/v1/hiera/levels/zzz",
            json={"priority": 100},
            headers=self._auth_headers(),
        )
        # Sort by id ascending
        response = self.client.get(
            "/api/v1/hiera/levels?sort=id&sort_order=ascending",
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["result"][0]["id"], "aaa")
        self.assertEqual(data["result"][1]["id"], "zzz")
        # Sort by id descending
        response = self.client.get(
            "/api/v1/hiera/levels?sort=id&sort_order=descending",
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["result"][0]["id"], "zzz")
        self.assertEqual(data["result"][1]["id"], "aaa")

    def test_unauthorized_access(self):
        """Test that endpoints require authentication"""
        response = self.client.get("/api/v1/hiera/levels")
        self.assertEqual(response.status_code, 401)

    def test_field_filtering(self):
        """Test filtering returned fields"""
        # Create level
        self.client.post(
            "/api/v1/hiera/levels/test_level",
            json={"priority": 100, "description": "Test"},
            headers=self._auth_headers(),
        )
        # Get with specific fields
        response = self.client.get(
            "/api/v1/hiera/levels/test_level?fields=id&fields=priority",
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("id", data)
        self.assertIn("priority", data)
        self.assertNotIn("description", data)


class HieraLevelsAuthzIntegrationTests(IntegrationTestBase):
    def test_create_denied(self):
        nu = self._make_non_admin()
        resp = self.client.post(
            f"/api/v1/hiera/levels/lvl-{uuid.uuid4().hex}",
            headers=nu.headers,
            json={"priority": 100},
        )
        self.assertEqual(resp.status_code, 403)

    def test_create_granted(self):
        nu = self._make_non_admin(permissions=[PERM_HIERA_LEVELS_CREATE])
        level_id = f"lvl-{uuid.uuid4().hex}"
        resp = self.client.post(
            f"/api/v1/hiera/levels/{level_id}",
            headers=nu.headers,
            json={"priority": 100},
        )
        self.assertEqual(resp.status_code, 201)
        self.addCleanup(self._db["hiera_levels"].delete_many, {"id": level_id})

    def test_update_denied(self):
        nu = self._make_non_admin()
        resp = self.client.put(
            f"/api/v1/hiera/levels/lvl-{uuid.uuid4().hex}",
            headers=nu.headers,
            json={},
        )
        self.assertEqual(resp.status_code, 403)

    def test_delete_denied(self):
        nu = self._make_non_admin()
        resp = self.client.delete(
            f"/api/v1/hiera/levels/lvl-{uuid.uuid4().hex}", headers=nu.headers
        )
        self.assertEqual(resp.status_code, 403)

    def test_read_denied(self):
        nu = self._make_non_admin()
        resp = self.client.get("/api/v1/hiera/levels", headers=nu.headers)
        self.assertEqual(resp.status_code, 403)

    def test_read_granted(self):
        nu = self._make_non_admin(permissions=[PERM_HIERA_GET])
        resp = self.client.get("/api/v1/hiera/levels", headers=nu.headers)
        self.assertEqual(resp.status_code, 200)


if __name__ == "__main__":
    unittest.main()
