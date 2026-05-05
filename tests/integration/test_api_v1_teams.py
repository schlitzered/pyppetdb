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


class ApiV1TeamsIntegrationTests(IntegrationTestBase):
    def _auth_headers(self):
        return {"x-secret-id": "test-cred", "x-secret": "test-secret"}

    def test_teams_crud_flow(self):
        team_id = f"team-{uuid.uuid4().hex}"

        # 1. Create team
        resp = self.client.post(
            f"/api/v1/teams/{team_id}",
            headers=self._auth_headers(),
            json={"ldap_group": "", "users": ["admin"]},
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()["id"], team_id)

        # 2. Search teams
        resp = self.client.get(
            "/api/v1/teams", headers=self._auth_headers(), params={"team_id": team_id}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["meta"]["result_size"], 1)

        # 3. Get team
        resp = self.client.get(f"/api/v1/teams/{team_id}", headers=self._auth_headers())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["ldap_group"], "")

        # 4. Update team
        resp = self.client.put(
            f"/api/v1/teams/{team_id}",
            headers=self._auth_headers(),
            json={"ldap_group": "", "users": ["admin", "user2"]},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("user2", resp.json()["users"])

        # 5. Delete team
        resp = self.client.delete(
            f"/api/v1/teams/{team_id}", headers=self._auth_headers()
        )
        self.assertEqual(resp.status_code, 200)

        # 6. Verify deletion
        resp = self.client.get(f"/api/v1/teams/{team_id}", headers=self._auth_headers())
        self.assertEqual(resp.status_code, 404)
