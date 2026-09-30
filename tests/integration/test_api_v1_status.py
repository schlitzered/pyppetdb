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

from tests.integration.base import IntegrationTestBase


class ApiV1StatusIntegrationTests(IntegrationTestBase):
    def _status(self):
        resp = self.client.get("/api/v1/status", headers=self._auth_headers())
        self.assertEqual(resp.status_code, 200)
        return resp.json()

    def test_requires_authentication(self):
        resp = self.client.get("/api/v1/status")
        self.assertEqual(resp.status_code, 401)

    def test_reports_every_watcher_as_ready(self):
        status = self._wait_until(
            lambda: (lambda body: body if body["ready"] else None)(self._status())
        )
        self.assertEqual(
            sorted(watcher["name"] for watcher in status["watchers"]),
            [
                "ca_authorities",
                "ca_certificates",
                "ca_spaces",
                "hiera_key_models_dynamic",
                "hiera_keys",
                "hiera_levels",
                "nodes_groups",
                "nodes_secrets_redactor",
            ],
        )
        for watcher in status["watchers"]:
            self.assertEqual(watcher["state"], "ready", watcher)
            self.assertIsNotNone(watcher["last_sync"], watcher)
            self.assertIsNone(watcher["last_error"], watcher)
        self.assertRegex(status["instance"], r":\d+$")
