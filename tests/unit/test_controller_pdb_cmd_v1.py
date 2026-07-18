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

import asyncio
import unittest
from unittest.mock import MagicMock, AsyncMock
import logging
import json
import gzip
from pyppetdb.controller.pdb.cmd.v1 import ControllerPdbCmdV1


class TestControllerPdbCmdV1Unit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_config = MagicMock()
        self.mock_config.mongodb.placementFacts = ["provider"]
        self.mock_config.app.main.storeHistory.catalog = True
        self.mock_config.app.main.storeHistory.catalogUnchanged = True
        self.mock_config.app.puppetdb.serverurl = None

        self.mock_nodes = MagicMock()
        self.mock_nodes.calculate_placement = MagicMock(
            return_value={"provider": "aws"}
        )
        self.mock_nodes.get_placement = AsyncMock(return_value={"provider": "aws"})
        self.mock_catalogs = MagicMock()
        self.mock_groups = MagicMock()
        self.mock_reports = MagicMock()
        self.mock_auth_cert = MagicMock()
        self.mock_auth_cert.require_cn_trusted = AsyncMock()

        self.mock_cache = MagicMock()
        self.mock_cache.update_placement = AsyncMock()
        self.mock_catalogs.update_placement = AsyncMock()
        self.mock_reports.update_placement = AsyncMock()

        self.controller = ControllerPdbCmdV1(
            log=self.log,
            config=self.mock_config,
            crud_nodes=self.mock_nodes,
            crud_nodes_catalog_cache=self.mock_cache,
            crud_nodes_catalogs=self.mock_catalogs,
            crud_nodes_groups=self.mock_groups,
            crud_nodes_reports=self.mock_reports,
            authorize_client_cert=self.mock_auth_cert,
        )

    async def test_replace_facts(self):
        mock_request = MagicMock()
        data = {
            "certname": "node1",
            "environment": "prod",
            "values": {"os": "linux"},
            "producer_timestamp": "2026-03-06T00:00:00Z",
            "producer": "pm1",
        }
        mock_request.body = AsyncMock(return_value=json.dumps(data).encode())
        mock_request.headers = {}

        self.mock_groups.reevaluate_node_membership = AsyncMock(return_value=["g1"])
        self.mock_nodes.update = AsyncMock()

        await self.controller.create(
            request=mock_request,
            certname="node1",
            command="replace_facts",
            producer_timestamp="2026-03-06T00:00:00Z",
            version=1,
        )

        self.mock_groups.reevaluate_node_membership.assert_called_once()
        # Note: update is called via asyncio.create_task, so it might not be finished yet in a real run,
        # but in this unit test setUp it should be fine if we wait or if it's already triggered.
        # Actually, let's wait a bit to ensure tasks are triggered
        await asyncio.sleep(0.1)
        self.mock_nodes.update.assert_called_once()

    async def test_replace_catalog(self):
        mock_request = MagicMock()
        data = {
            "certname": "node1",
            "environment": "prod",
            "catalog_uuid": "uuid1",
            "resources": [
                {
                    "type": "File",
                    "title": "/t",
                    "exported": True,
                    "tags": [],
                    "parameters": {},
                }
            ],
        }
        mock_request.body = AsyncMock(return_value=json.dumps(data).encode())
        mock_request.headers = {}

        self.mock_nodes.update = AsyncMock()
        self.mock_catalogs.create = AsyncMock()

        await self.controller.create(
            request=mock_request,
            certname="node1",
            command="replace_catalog",
            producer_timestamp="2026-03-06T00:00:00Z",
            version=1,
        )
        await asyncio.sleep(0.1)
        self.mock_nodes.update.assert_called_once()
        self.mock_catalogs.create.assert_called_once()

    async def test_store_report(self):
        mock_request = MagicMock()
        data = {
            "certname": "node1",
            "environment": "prod",
            "catalog_uuid": "uuid1",
            "status": "changed",
            "noop": False,
            "noop_pending": False,
            "corrective_change": False,
            "logs": [],
            "metrics": [],
            "resources": [
                {
                    "skipped": False,
                    "timestamp": "now",
                    "resource_type": "F",
                    "resource_title": "t",
                    "containment_path": [],
                    "corrective_change": False,
                    "events": [],
                    "file": None,
                    "line": None,
                }
            ],
        }
        mock_request.body = AsyncMock(return_value=json.dumps(data).encode())
        mock_request.headers = {}

        self.mock_nodes.update = AsyncMock()
        self.mock_reports.create = AsyncMock()
        self.mock_catalogs.drop_created_no_report_ttl = AsyncMock()

        await self.controller.create(
            request=mock_request,
            certname="node1",
            command="store_report",
            producer_timestamp="2026-03-06T00:00:00Z",
            version=1,
        )
        await asyncio.sleep(0.1)
        self.mock_nodes.update.assert_called_once()
        self.mock_reports.create.assert_called_once()
        self.mock_catalogs.drop_created_no_report_ttl.assert_called_once()

    async def test_create_gzip(self):
        mock_request = MagicMock()
        data = {"environment": "prod"}
        body = gzip.compress(json.dumps(data).encode())
        mock_request.body = AsyncMock(return_value=body)
        mock_request.headers = {"content-encoding": "gzip"}

        await self.controller.create(
            request=mock_request,
            certname="node1",
            command="unknown",
            producer_timestamp="2026-03-06T00:00:00Z",
            version=1,
        )

    async def test_replace_facts_placement_propagation(self):
        mock_request = MagicMock()
        data = {
            "certname": "node1",
            "environment": "prod",
            "values": {"provider": "gcp"},
            "producer_timestamp": "2026-03-06T00:00:00Z",
            "producer": "pm1",
        }
        mock_request.body = AsyncMock(return_value=json.dumps(data).encode())
        mock_request.headers = {}

        self.mock_config.mongodb.placementFacts = ["provider"]
        self.mock_nodes.get_placement = AsyncMock(return_value={"provider": "aws"})
        self.mock_groups.reevaluate_node_membership = AsyncMock(return_value=["g1"])
        self.mock_nodes.update = AsyncMock()
        self.mock_reports.update_placement = AsyncMock()
        self.mock_catalogs.update_placement = AsyncMock()
        self.mock_cache.update_placement = AsyncMock()

        await self.controller.create(
            request=mock_request,
            certname="node1",
            command="replace_facts",
            producer_timestamp="2026-03-06T00:00:00Z",
            version=1,
        )

        await asyncio.sleep(0.1)
        self.mock_nodes.update.assert_called_once()
        self.mock_reports.update_placement.assert_called_once_with(
            node_id="node1",
            placement={"provider": "gcp"},
        )
        self.mock_catalogs.update_placement.assert_called_once_with(
            node_id="node1",
            placement={"provider": "gcp"},
        )
        self.mock_cache.update_placement.assert_called_once_with(
            node_id="node1",
            placement={"provider": "gcp"},
        )
        # Should not raise

    async def test_proxy_to_puppetdb_strips_hop_headers(self):
        self.mock_config.app.puppetdb.serverurl = "http://puppetdb:8081"
        mock_http = MagicMock()
        mock_http.post = AsyncMock()
        self.controller._http = mock_http

        request = MagicMock()
        request.headers = {
            "content-encoding": "gzip",
            "x-uncompressed-length": "100",
            "host": "pyppetdb",
            "content-length": "5",
            "transfer-encoding": "chunked",
            "x-authentication": "keep-me",
        }
        request.query_params = {"checksum": "abc"}

        await self.controller._proxy_to_puppetdb(request, b"payload")

        mock_http.post.assert_called_once()
        _, kwargs = mock_http.post.call_args
        self.assertEqual(kwargs["url"], "http://puppetdb:8081/pdb/cmd/v1")
        self.assertEqual(kwargs["content"], b"payload")
        sent_headers = kwargs["headers"]
        for stripped in (
            "content-encoding",
            "x-uncompressed-length",
            "host",
            "content-length",
            "transfer-encoding",
        ):
            self.assertNotIn(stripped, sent_headers)
        # non hop-by-hop headers are forwarded untouched
        self.assertEqual(sent_headers["x-authentication"], "keep-me")
