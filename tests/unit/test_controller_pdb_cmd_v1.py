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
from pyppetdb.config import ConfigAppFacts
from pyppetdb.controller.pdb.cmd.v1 import ControllerPdbCmdV1
from pyppetdb.crud.nodes import CrudNodes
from pyppetdb.ingest import IngestQueue


def ingest_state(catalog_uuid=None, has_facts=True, has_catalog=True):
    return {
        "has_facts": has_facts,
        "has_catalog": has_catalog,
        "catalog_uuid": catalog_uuid,
        "disabled": False,
        "environment": "production",
        "placement": {"provider": "aws"},
    }


STORED_REPORT = {
    "report": {
        "hash": "abc",
        "start_time": None,
        "end_time": None,
        "environment": "prod",
        "configuration_version": "1",
        "resources": [
            {
                "resource_type": "File",
                "resource_title": "/tmp/x",
                "file": None,
                "line": None,
                "containment_path": ["Stage[main]", "Profile::Base", "File[/tmp/x]"],
                "events": [
                    {"status": "success", "timestamp": None, "property": "ensure"}
                ],
            }
        ],
    }
}


class TestControllerPdbCmdV1Unit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_config = MagicMock()
        self.mock_config.mongodb.placementFacts = ["provider"]
        self.mock_config.app.main.facts = ConfigAppFacts()
        self.mock_config.app.main.storeHistory.catalog = True
        self.mock_config.app.main.storeHistory.catalogUnchanged = True
        self.mock_config.app.puppetdb.serverurl = None
        self.mock_config.app.puppetdb.writeQueueWaitTimeout = 0

        self.mock_nodes = MagicMock()
        self.mock_nodes.calculate_placement = MagicMock(
            return_value={"provider": "aws"}
        )
        self.mock_nodes.get_placement = AsyncMock(return_value={"provider": "aws"})
        self.mock_nodes.get_ingest_state = AsyncMock(return_value=ingest_state(None))
        self.mock_nodes.update_catalog_metadata = AsyncMock()
        self.mock_catalogs = MagicMock()
        self.mock_groups = MagicMock()
        self.mock_reports = MagicMock()
        self.mock_reports.set_node_disabled = AsyncMock(return_value=0)
        self.mock_auth_cert = MagicMock()
        self.mock_auth_cert.require_cn_trusted = AsyncMock()

        self.mock_cache = MagicMock()
        self.mock_cache.update_placement = AsyncMock()
        self.mock_catalogs.update_placement = AsyncMock()
        self.mock_reports.update_placement = AsyncMock()
        self.mock_reports.create_latest = AsyncMock(return_value=(True, STORED_REPORT))
        self.mock_resources = MagicMock()
        self.mock_resources.replace_for_node = AsyncMock()
        self.mock_resources.set_node_disabled = AsyncMock(return_value=0)
        self.mock_resources.update_placement = AsyncMock()
        self.mock_edges = MagicMock()
        self.mock_edges.replace_for_node = AsyncMock()
        self.mock_edges.set_node_disabled = AsyncMock(return_value=0)
        self.mock_edges.update_placement = AsyncMock()
        self.mock_events = MagicMock()
        self.mock_events.insert_for_report = AsyncMock()
        self.mock_events.set_latest = AsyncMock()
        self.mock_events.set_node_disabled = AsyncMock()
        self.mock_events.update_placement = AsyncMock()

        self.queue = IngestQueue(log=self.log, size=100, workers=4)
        self.controller = ControllerPdbCmdV1(
            log=self.log,
            config=self.mock_config,
            crud_nodes=self.mock_nodes,
            crud_nodes_catalog_cache=self.mock_cache,
            crud_nodes_catalogs=self.mock_catalogs,
            crud_nodes_groups=self.mock_groups,
            crud_nodes_reports=self.mock_reports,
            crud_nodes_resources=self.mock_resources,
            crud_nodes_edges=self.mock_edges,
            crud_nodes_events=self.mock_events,
            authorize_client_cert=self.mock_auth_cert,
            ingest_queue=self.queue,
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

        await asyncio.sleep(0.1)
        self.mock_groups.reevaluate_node_membership.assert_called_once()
        self.mock_nodes.update.assert_called_once()

    async def test_replace_facts_stores_a_facts_index(self):
        crud = CrudNodes(self.log, self.mock_config, MagicMock())
        crud.get_placement = AsyncMock(return_value={})
        crud._update = AsyncMock(return_value={"id": "node1"})
        self.controller._crud_nodes = crud

        mock_request = MagicMock()
        data = {
            "certname": "node1",
            "environment": "prod",
            "values": {"os": "linux", "structured": {"a": 1}},
            "producer_timestamp": "2026-03-06T00:00:00Z",
            "producer": "pm1",
        }
        mock_request.body = AsyncMock(return_value=json.dumps(data).encode())
        mock_request.headers = {}
        self.mock_groups.reevaluate_node_membership = AsyncMock(return_value=["g1"])

        await self.controller.create(
            request=mock_request,
            certname="node1",
            command="replace_facts",
            producer_timestamp="2026-03-06T00:00:00Z",
            version=5,
        )
        await asyncio.sleep(0.1)

        payload = crud._update.call_args.kwargs["payload"]
        self.assertEqual(payload["facts"], {"os": "linux", "structured": {"a": 1}})
        self.assertEqual(
            payload["facts_index"],
            [
                {"p": "os", "v": "linux"},
                {"p": "structured"},
                {"p": "structured.a", "v": 1},
            ],
        )

    async def test_deactivate_node_propagates_to_stored_reports(self):
        mock_request = MagicMock()
        mock_request.body = AsyncMock(
            return_value=json.dumps({"certname": "node1"}).encode()
        )
        mock_request.headers = {}
        self.mock_nodes.update = AsyncMock()

        await self.controller.create(
            request=mock_request,
            certname="node1",
            command="deactivate_node",
            producer_timestamp=None,
            version=3,
        )
        await asyncio.sleep(0.1)
        self.mock_reports.set_node_disabled.assert_awaited_once_with(
            node_id="node1", disabled=True
        )

    async def test_replace_facts_propagates_reactivation(self):
        mock_request = MagicMock()
        mock_request.body = AsyncMock(
            return_value=json.dumps(
                {
                    "certname": "node1",
                    "environment": "prod",
                    "values": {"os": "linux"},
                    "producer_timestamp": "2026-03-06T00:00:00Z",
                    "producer": "pm1",
                }
            ).encode()
        )
        mock_request.headers = {}
        self.mock_groups.reevaluate_node_membership = AsyncMock(return_value=[])
        self.mock_nodes.update = AsyncMock()

        await self.controller.create(
            request=mock_request,
            certname="node1",
            command="replace_facts",
            producer_timestamp="2026-03-06T00:00:00Z",
            version=5,
        )
        await asyncio.sleep(0.1)
        self.mock_reports.set_node_disabled.assert_awaited_once_with(
            node_id="node1", disabled=False
        )

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

    async def test_full_queue_waits_for_room_when_a_wait_timeout_is_set(self):
        self.mock_config.app.puppetdb.writeQueueWaitTimeout = 5
        self.mock_nodes.update = AsyncMock()
        release = asyncio.Event()

        async def blocking():
            await release.wait()

        self.queue._size = 1
        self.queue._workers = 1
        self.queue.submit(blocking)
        await asyncio.sleep(0.05)
        self.queue.submit(blocking)

        mock_request = MagicMock()
        mock_request.body = AsyncMock(
            return_value=json.dumps(
                {"certname": "node1", "environment": "prod", "disabled": True}
            ).encode()
        )
        mock_request.headers = {}

        pending = asyncio.create_task(
            self.controller.create(
                request=mock_request,
                certname="node1",
                command="deactivate_node",
                producer_timestamp="2026-03-06T00:00:00Z",
                version=3,
            )
        )
        await asyncio.sleep(0.1)
        self.assertFalse(pending.done())
        self.assertEqual(self.queue.stats["dropped"], 0)
        release.set()
        result = await pending
        self.assertIn("uuid", result)
        self.assertEqual(self.queue.stats["waited"], 1)
        await self.queue.stop()
        self.mock_nodes.update.assert_called()

    async def test_rejects_with_503_when_the_queue_is_full(self):
        from fastapi import HTTPException

        release = asyncio.Event()

        async def blocking():
            await release.wait()

        self.queue._size = 1
        self.queue._workers = 1
        self.queue.submit(blocking)
        await asyncio.sleep(0.05)
        self.queue.submit(blocking)

        mock_request = MagicMock()
        mock_request.body = AsyncMock(
            return_value=json.dumps(
                {"certname": "node1", "environment": "prod", "disabled": True}
            ).encode()
        )
        mock_request.headers = {}

        with self.assertRaises(HTTPException) as ctx:
            await self.controller.create(
                request=mock_request,
                certname="node1",
                command="deactivate_node",
                producer_timestamp="2026-03-06T00:00:00Z",
                version=3,
            )
        self.assertEqual(ctx.exception.status_code, 503)
        self.assertEqual(ctx.exception.headers["Retry-After"], "60")
        release.set()

    async def test_unknown_command_is_accepted_without_queueing(self):
        mock_request = MagicMock()
        mock_request.body = AsyncMock(
            return_value=json.dumps({"certname": "node1", "environment": "prod"}).encode()
        )
        mock_request.headers = {}
        result = await self.controller.create(
            request=mock_request,
            certname="node1",
            command="something_else",
            producer_timestamp="2026-03-06T00:00:00Z",
            version=1,
        )
        self.assertIn("uuid", result)
        self.assertEqual(self.queue.stats["accepted"], 0)

    async def _post_catalog(self, generation=1):
        mock_request = MagicMock()
        data = {
            "certname": "node1",
            "environment": "prod",
            "catalog_uuid": "uuid1",
            "version": f"{generation}-1",
            "producer_timestamp": "2026-03-06T00:00:00Z",
            "resources": [
                {
                    "type": "File",
                    "title": "/tmp/a",
                    "exported": False,
                    "tags": ["file"],
                    "parameters": {"owner": "root"},
                }
            ],
            "edges": [],
        }
        mock_request.body = AsyncMock(return_value=json.dumps(data).encode())
        mock_request.headers = {}
        await self.controller.create(
            request=mock_request,
            certname="node1",
            command="replace_catalog",
            producer_timestamp="2026-03-06T00:00:00Z",
            version=9,
        )
        await asyncio.sleep(0.1)

    async def test_replace_catalog_writes_when_content_is_new(self):
        self.mock_nodes.update = AsyncMock()
        self.mock_catalogs.create = AsyncMock()
        self.mock_nodes.get_ingest_state = AsyncMock(return_value=ingest_state(None))

        await self._post_catalog()

        payload = self.mock_nodes.update.call_args.kwargs["payload"]
        self.assertIsNotNone(payload.catalog)
        self.assertEqual(payload.catalog.catalog_uuid, "uuid1")

    async def test_replace_catalog_skips_the_catalog_when_unchanged(self):
        self.mock_nodes.update = AsyncMock()
        self.mock_catalogs.create = AsyncMock()
        self.mock_nodes.get_ingest_state = AsyncMock(return_value=ingest_state(None))
        await self._post_catalog(generation=1)
        stored = self.mock_nodes.update.call_args.kwargs["payload"].catalog.catalog_uuid

        self.mock_nodes.update = AsyncMock()
        self.mock_nodes.update_catalog_metadata = AsyncMock()
        self.mock_nodes.get_ingest_state = AsyncMock(return_value=ingest_state(stored))
        await self._post_catalog(generation=2)

        payload = self.mock_nodes.update.call_args.kwargs["payload"]
        self.assertIsNone(payload.catalog)
        self.assertIsNotNone(payload.change_catalog)
        self.assertEqual(payload.environment, "prod")

        metadata = self.mock_nodes.update_catalog_metadata.call_args.kwargs["metadata"]
        self.assertEqual(
            self.mock_nodes.update_catalog_metadata.call_args.kwargs["_id"], "node1"
        )
        self.assertEqual(metadata["version"], "2-1")
        self.assertEqual(metadata["catalog_uuid"], "uuid1")
        self.assertEqual(metadata["catalog_uuid"], stored)
        self.assertIn("hash", metadata)
        self.assertIn("producer_timestamp", metadata)
        self.assertIn("num_resources", metadata)
        for heavy in ("resources", "resources_exported", "edges"):
            self.assertNotIn(heavy, metadata)

    async def test_replace_catalog_does_not_write_metadata_when_changed(self):
        self.mock_nodes.update = AsyncMock()
        self.mock_catalogs.create = AsyncMock()
        self.mock_nodes.update_catalog_metadata = AsyncMock()
        self.mock_nodes.get_ingest_state = AsyncMock(return_value=ingest_state("stale"))

        await self._post_catalog()

        self.mock_nodes.update_catalog_metadata.assert_not_called()

    async def test_replace_catalog_writes_when_content_differs(self):
        self.mock_nodes.update = AsyncMock()
        self.mock_catalogs.create = AsyncMock()
        self.mock_nodes.get_ingest_state = AsyncMock(return_value=ingest_state("stale"))

        await self._post_catalog()

        payload = self.mock_nodes.update.call_args.kwargs["payload"]
        self.assertIsNotNone(payload.catalog)

    async def test_replace_catalog_history_is_not_rewritten_for_a_stored_uuid(self):
        self.mock_nodes.update = AsyncMock()
        self.mock_catalogs.create = AsyncMock()
        self.mock_nodes.get_ingest_state = AsyncMock(return_value=ingest_state(None))
        await self._post_catalog(generation=1)
        stored = self.mock_nodes.update.call_args.kwargs["payload"].catalog.catalog_uuid
        self.mock_catalogs.create.assert_called_once()

        self.mock_catalogs.create = AsyncMock()
        self.mock_nodes.update_catalog_metadata = AsyncMock()
        self.mock_nodes.get_ingest_state = AsyncMock(return_value=ingest_state(stored))
        await self._post_catalog(generation=2)

        self.mock_catalogs.create.assert_not_called()
        self.mock_nodes.update_catalog_metadata.assert_called_once()

    async def _post_report(self):
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
                    "timestamp": "2026-03-06T00:00:00Z",
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
        await self.controller.create(
            request=mock_request,
            certname="node1",
            command="store_report",
            producer_timestamp="2026-03-06T00:00:00Z",
            version=1,
        )
        await asyncio.sleep(0.1)

    async def test_store_report(self):
        self.mock_nodes.update = AsyncMock()
        self.mock_reports.create_latest = AsyncMock(return_value=(True, STORED_REPORT))
        self.mock_catalogs.drop_created_no_report_ttl = AsyncMock()

        await self._post_report()

        self.mock_nodes.update.assert_called_once()
        self.mock_reports.create_latest.assert_called_once()
        self.mock_catalogs.drop_created_no_report_ttl.assert_called_once()

    async def test_store_report_writes_the_events_collection(self):
        self.mock_nodes.update = AsyncMock()
        self.mock_catalogs.drop_created_no_report_ttl = AsyncMock()

        await self._post_report()

        self.mock_events.set_latest.assert_awaited_once_with(
            node_id="node1", latest=False
        )
        docs = self.mock_events.insert_for_report.await_args.args[0]
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]["node_id"], "node1")
        self.assertEqual(docs[0]["report_hash"], "abc")
        self.assertEqual(docs[0]["containing_class"], "Profile::Base")
        self.assertTrue(docs[0]["latest"])

    async def test_store_report_that_is_not_latest_keeps_the_latest_flags(self):
        self.mock_reports.create_latest = AsyncMock(return_value=(False, STORED_REPORT))
        self.mock_nodes.update = AsyncMock()
        self.mock_catalogs.drop_created_no_report_ttl = AsyncMock()

        await self._post_report()

        self.mock_events.set_latest.assert_not_awaited()
        docs = self.mock_events.insert_for_report.await_args.args[0]
        self.assertFalse(docs[0]["latest"])

    async def test_store_report_is_discarded_without_a_catalog(self):
        self.mock_nodes.update = AsyncMock()
        self.mock_reports.create_latest = AsyncMock(return_value=(True, STORED_REPORT))
        self.mock_catalogs.drop_created_no_report_ttl = AsyncMock()
        self.mock_nodes.get_ingest_state = AsyncMock(
            return_value=ingest_state(has_catalog=False)
        )

        await self._post_report()

        self.mock_nodes.update.assert_not_called()
        self.mock_reports.create_latest.assert_not_called()
        self.mock_catalogs.drop_created_no_report_ttl.assert_not_called()

    async def test_store_report_is_discarded_for_an_unknown_node(self):
        self.mock_nodes.update = AsyncMock()
        self.mock_reports.create_latest = AsyncMock(return_value=(True, STORED_REPORT))
        self.mock_nodes.get_ingest_state = AsyncMock(return_value=None)

        await self._post_report()

        self.mock_nodes.update.assert_not_called()
        self.mock_reports.create_latest.assert_not_called()

    async def test_replace_catalog_is_discarded_without_facts(self):
        self.mock_nodes.update = AsyncMock()
        self.mock_catalogs.create = AsyncMock()
        self.mock_nodes.update_catalog_metadata = AsyncMock()
        self.mock_nodes.get_ingest_state = AsyncMock(
            return_value=ingest_state(has_facts=False)
        )

        await self._post_catalog()

        self.mock_nodes.update.assert_not_called()
        self.mock_nodes.update_catalog_metadata.assert_not_called()
        self.mock_catalogs.create.assert_not_called()

    async def test_replace_catalog_is_discarded_for_an_unknown_node(self):
        self.mock_nodes.update = AsyncMock()
        self.mock_catalogs.create = AsyncMock()
        self.mock_nodes.get_ingest_state = AsyncMock(return_value=None)

        await self._post_catalog()

        self.mock_nodes.update.assert_not_called()
        self.mock_catalogs.create.assert_not_called()

    async def test_create_gzip(self):
        mock_request = MagicMock()
        data = {
            "certname": "node1",
            "environment": "prod",
            "values": {"os": "linux"},
            "producer_timestamp": "2026-03-06T00:00:00Z",
            "producer": "pm1",
        }
        mock_request.body = AsyncMock(
            return_value=gzip.compress(json.dumps(data).encode())
        )
        mock_request.headers = {"content-encoding": "gzip"}

        self.mock_groups.reevaluate_node_membership = AsyncMock(return_value=["g1"])
        self.mock_nodes.update = AsyncMock()

        await self.controller.create(
            request=mock_request,
            certname="node1",
            command="replace_facts",
            producer_timestamp="2026-03-06T00:00:00Z",
            version=1,
        )

        await asyncio.sleep(0.1)
        self.mock_groups.reevaluate_node_membership.assert_called_once()
        self.mock_nodes.update.assert_called_once()

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
        self.mock_config.app.main.facts = ConfigAppFacts()
        self.mock_nodes.get_placement = AsyncMock(return_value={"provider": "aws"})
        self.mock_nodes.get_ingest_state = AsyncMock(return_value=ingest_state(None))
        self.mock_groups.reevaluate_node_membership = AsyncMock(return_value=["g1"])
        self.mock_nodes.update = AsyncMock()
        self.mock_reports.update_placement = AsyncMock()
        self.mock_reports.create_latest = AsyncMock(return_value=(True, STORED_REPORT))
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

    async def _post_deactivate(self):
        mock_request = MagicMock()
        mock_request.body = AsyncMock(
            return_value=json.dumps(
                {"certname": "node1", "environment": "prod"}
            ).encode()
        )
        mock_request.headers = {}
        mock_request.query_params = {"certname": "node1"}
        return await self.controller.create(
            request=mock_request,
            certname="node1",
            command="deactivate_node",
            producer_timestamp="2026-03-06T00:00:00Z",
            version=3,
        )

    async def test_local_and_proxy_jobs_are_queued_together(self):
        self.mock_config.app.puppetdb.serverurl = "http://puppetdb:8081"
        self.mock_nodes.update = AsyncMock()
        mock_http = MagicMock()
        mock_http.post = AsyncMock()
        self.controller._http = mock_http

        result = await self._post_deactivate()

        self.assertIn("uuid", result)
        self.assertEqual(self.queue.stats["accepted"], 2)
        await asyncio.sleep(0.1)
        self.mock_nodes.update.assert_called_once()
        mock_http.post.assert_called_once()

    async def test_proxy_job_is_not_dropped_silently_when_only_one_slot_is_free(self):
        from fastapi import HTTPException

        self.mock_config.app.puppetdb.serverurl = "http://puppetdb:8081"
        self.mock_nodes.update = AsyncMock()
        mock_http = MagicMock()
        mock_http.post = AsyncMock()
        self.controller._http = mock_http

        release = asyncio.Event()

        async def blocking():
            await release.wait()

        self.queue._size = 2
        self.queue._workers = 1
        self.queue.submit(blocking)
        await asyncio.sleep(0.05)
        self.queue.submit(blocking)
        self.assertEqual(self.queue.depth, 1)

        with self.assertRaises(HTTPException) as ctx:
            await self._post_deactivate()
        self.assertEqual(ctx.exception.status_code, 503)

        await asyncio.sleep(0.05)
        self.mock_nodes.update.assert_not_called()
        mock_http.post.assert_not_called()
        release.set()

    async def test_unknown_command_still_proxies(self):
        self.mock_config.app.puppetdb.serverurl = "http://puppetdb:8081"
        mock_http = MagicMock()
        mock_http.post = AsyncMock()
        self.controller._http = mock_http

        mock_request = MagicMock()
        mock_request.body = AsyncMock(
            return_value=json.dumps({"certname": "node1"}).encode()
        )
        mock_request.headers = {}
        mock_request.query_params = {"certname": "node1"}
        await self.controller.create(
            request=mock_request,
            certname="node1",
            command="something_else",
            producer_timestamp="2026-03-06T00:00:00Z",
            version=1,
        )
        self.assertEqual(self.queue.stats["accepted"], 1)
        await asyncio.sleep(0.1)
        mock_http.post.assert_called_once()

    async def test_unknown_command_returns_503_when_the_proxy_cannot_be_queued(self):
        from fastapi import HTTPException

        self.mock_config.app.puppetdb.serverurl = "http://puppetdb:8081"
        mock_http = MagicMock()
        mock_http.post = AsyncMock()
        self.controller._http = mock_http

        release = asyncio.Event()

        async def blocking():
            await release.wait()

        self.queue._size = 1
        self.queue._workers = 1
        self.queue.submit(blocking)
        await asyncio.sleep(0.05)
        self.queue.submit(blocking)
        self.assertEqual(self.queue.depth, 1)

        mock_request = MagicMock()
        mock_request.body = AsyncMock(
            return_value=json.dumps({"certname": "node1"}).encode()
        )
        mock_request.headers = {}
        mock_request.query_params = {"certname": "node1"}
        with self.assertRaises(HTTPException) as ctx:
            await self.controller.create(
                request=mock_request,
                certname="node1",
                command="something_else",
                producer_timestamp="2026-03-06T00:00:00Z",
                version=1,
            )
        self.assertEqual(ctx.exception.status_code, 503)
        await asyncio.sleep(0.05)
        mock_http.post.assert_not_called()
        release.set()

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

        headers = self.controller._proxy_headers(request)
        await self.controller._job_proxy_to_puppetdb(
            params=dict(request.query_params), headers=headers, body=b"payload"
        )

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
