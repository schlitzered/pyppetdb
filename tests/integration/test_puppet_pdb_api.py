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

import json
from unittest.mock import patch
from tests.integration.base import IntegrationTestBase
import httpx


class PuppetPdbApiIntegrationTests(IntegrationTestBase):
    def setUp(self):
        super().setUp()
        from pyppetdb.main import settings

        settings.app.puppet.serverurl = "http://puppetmaster"
        settings.app.puppetdb.serverurl = "http://puppetdb"

    @patch("httpx.AsyncClient.put")
    def test_puppet_v3_facts_put(self, mock_put):
        mock_response_data = {"status": "success"}
        mock_response = httpx.Response(
            200,
            content=json.dumps(mock_response_data).encode(),
            headers={"Content-Type": "application/json"},
        )
        mock_put.return_value = mock_response

        facts_data = {
            "values": {"os": "linux"},
            "name": "node1",
            "timestamp": "2026-03-20T10:00:00Z",
            "expiration": "2026-03-20T11:00:00Z",
        }
        resp = self.client.put(
            "/puppet/v3/facts/test-node",  # test-node because require_cn_match returns test-node
            content=json.dumps(facts_data),
            headers={"Content-Type": "application/json"},
        )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"status": "success"})
        mock_put.assert_called_once()

    @patch("httpx.AsyncClient.get")
    def test_puppet_v3_node_get(self, mock_get):
        mock_response_data = {"name": "test-node"}
        mock_response = httpx.Response(
            200,
            content=json.dumps(mock_response_data).encode(),
            headers={"Content-Type": "application/json"},
        )
        mock_get.return_value = mock_response

        resp = self.client.get("/puppet/v3/node/test-node")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"name": "test-node"})

    @patch("httpx.AsyncClient.put")
    def test_puppet_v3_report_put(self, mock_put):
        mock_response_data = {"status": "received"}
        mock_response = httpx.Response(
            200,
            content=json.dumps(mock_response_data).encode(),
            headers={"Content-Type": "application/json"},
        )
        mock_put.return_value = mock_response

        report_data = {"report": "data"}
        resp = self.client.put(
            "/puppet/v3/report/test-node",
            content=json.dumps(report_data),
            headers={"Content-Type": "application/json"},
        )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"status": "received"})

    @patch("httpx.AsyncClient.get")
    def test_pdb_query_v4_resources_forwarding(self, mock_get):
        from pyppetdb.main import settings

        settings.app.puppetdb.resourceQueryInternal = False

        mock_response_data = [{"certname": "node1"}]
        mock_response = httpx.Response(
            200,
            content=json.dumps(mock_response_data).encode(),
            headers={"Content-Type": "application/json"},
        )
        mock_get.return_value = mock_response

        resp = self.client.get('/pdb/query/v4/resources?query=["=", "type", "Class"]')

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), [{"certname": "node1"}])
        mock_get.assert_called_once()

    def test_pdb_query_v4_resources_local(self):
        from pyppetdb.main import settings

        settings.app.puppetdb.resourceQueryInternal = True

        # Database is empty, so it should return []
        resp = self.client.get('/pdb/query/v4/resources?query=["=", "type", "Class"]')

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), [])
