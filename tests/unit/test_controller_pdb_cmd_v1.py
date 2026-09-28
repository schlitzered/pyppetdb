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
from pyppetdb.controller.pdb.cmd.v1 import COMMAND_FAILED
from pyppetdb.controller.pdb.cmd.v1 import ControllerPdbCmdV1
from pyppetdb.crud.nodes import CrudNodes
from pyppetdb.pdb.ingest.queue import IngestQueue


def ingest_state(catalog_uuid=None, has_facts=True, has_catalog=True, content_hash=None):
    return {
        "has_facts": has_facts,
        "has_catalog": has_catalog,
        "catalog_uuid": catalog_uuid,
        "content_hash": content_hash,
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
        self.mock_config.app.puppetdb.maxCommandSize = 0

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
        self.mock_reports.hash_exists = AsyncMock(return_value=False)
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
        mock_request.headers = {"content-type": "application/json"}

        self.mock_groups.reevaluate_node_membership = AsyncMock(return_value=["g1"])
        self.mock_nodes.update = AsyncMock()

        await self.controller.create(
            request=mock_request,
            certname="node1",
            command="replace_facts",
            producer_timestamp="2026-03-06T00:00:00Z",
            version=5,
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
        mock_request.headers = {"content-type": "application/json"}
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
        mock_request.headers = {"content-type": "application/json"}
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
        mock_request.headers = {"content-type": "application/json"}
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
        mock_request.headers = {"content-type": "application/json"}

        self.mock_nodes.update = AsyncMock()
        self.mock_catalogs.create = AsyncMock()

        await self.controller.create(
            request=mock_request,
            certname="node1",
            command="replace_catalog",
            producer_timestamp="2026-03-06T00:00:00Z",
            version=9,
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
        mock_request.headers = {"content-type": "application/json"}

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
        mock_request.headers = {"content-type": "application/json"}

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

    async def test_unknown_command_is_rejected_without_queueing(self):
        mock_request = MagicMock()
        mock_request.body = AsyncMock(
            return_value=json.dumps({"certname": "node1", "environment": "prod"}).encode()
        )
        mock_request.headers = {"content-type": "application/json"}
        result = await self.controller.create(
            request=mock_request,
            certname="node1",
            command="something_else",
            producer_timestamp="2026-03-06T00:00:00Z",
            version=1,
        )
        self.assertEqual(result.status_code, 400)
        self.assertEqual(
            json.loads(result.body)["error"],
            'Command "something else" for certname "node1" is invalid. '
            "Command must be one of: configure expiration, deactivate node, "
            "replace catalog, replace catalog inputs, replace facts, store report.",
        )
        self.assertEqual(self.queue.stats["accepted"], 0)

    async def _post_catalog(self, generation=1, catalog_uuid="uuid1"):
        mock_request = MagicMock()
        data = {
            "certname": "node1",
            "environment": "prod",
            "catalog_uuid": catalog_uuid,
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
        mock_request.headers = {"content-type": "application/json"}
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
        self.assertIsNotNone(payload.catalog.content_hash)

    async def test_replace_catalog_skips_the_catalog_when_unchanged(self):
        self.mock_nodes.update = AsyncMock()
        self.mock_catalogs.create = AsyncMock()
        self.mock_nodes.get_ingest_state = AsyncMock(return_value=ingest_state(None))
        await self._post_catalog(generation=1)
        stored = self.mock_nodes.update.call_args.kwargs["payload"].catalog.content_hash

        self.mock_nodes.update = AsyncMock()
        self.mock_catalogs.create = AsyncMock()
        self.mock_resources.replace_for_node = AsyncMock()
        self.mock_nodes.update_catalog_metadata = AsyncMock()
        self.mock_nodes.get_ingest_state = AsyncMock(
            return_value=ingest_state("uuid1", content_hash=stored)
        )
        await self._post_catalog(generation=2, catalog_uuid="uuid2")

        payload = self.mock_nodes.update.call_args.kwargs["payload"]
        self.assertIsNone(payload.catalog)
        self.assertIsNotNone(payload.change_catalog)
        self.assertEqual(payload.environment, "prod")
        self.mock_resources.replace_for_node.assert_not_called()
        self.mock_catalogs.create.assert_called_once()

        metadata = self.mock_nodes.update_catalog_metadata.call_args.kwargs["metadata"]
        self.assertEqual(
            self.mock_nodes.update_catalog_metadata.call_args.kwargs["_id"], "node1"
        )
        self.assertEqual(metadata["version"], "2-1")
        self.assertEqual(metadata["catalog_uuid"], "uuid2")
        self.assertEqual(metadata["content_hash"], stored)
        self.assertIn("hash", metadata)
        self.assertIn("producer_timestamp", metadata)
        self.assertIn("num_resources", metadata)
        for heavy in ("resources", "resources_exported", "edges"):
            self.assertNotIn(heavy, metadata)

    async def test_replace_catalog_does_not_write_metadata_when_changed(self):
        self.mock_nodes.update = AsyncMock()
        self.mock_catalogs.create = AsyncMock()
        self.mock_nodes.update_catalog_metadata = AsyncMock()
        self.mock_nodes.get_ingest_state = AsyncMock(
            return_value=ingest_state("uuid1", content_hash="stale")
        )

        await self._post_catalog()

        self.mock_nodes.update_catalog_metadata.assert_not_called()

    async def test_replace_catalog_writes_when_content_differs(self):
        self.mock_nodes.update = AsyncMock()
        self.mock_catalogs.create = AsyncMock()
        self.mock_nodes.get_ingest_state = AsyncMock(
            return_value=ingest_state("uuid0", content_hash="stale")
        )

        await self._post_catalog()

        payload = self.mock_nodes.update.call_args.kwargs["payload"]
        self.assertIsNotNone(payload.catalog)
        self.mock_resources.replace_for_node.assert_called_once()

    async def test_replace_catalog_history_is_not_rewritten_for_a_stored_uuid(self):
        self.mock_nodes.update = AsyncMock()
        self.mock_catalogs.create = AsyncMock()
        self.mock_nodes.get_ingest_state = AsyncMock(return_value=ingest_state(None))
        await self._post_catalog(generation=1)
        first = self.mock_nodes.update.call_args.kwargs["payload"].catalog
        self.mock_catalogs.create.assert_called_once()

        self.mock_catalogs.create = AsyncMock()
        self.mock_nodes.update_catalog_metadata = AsyncMock()
        self.mock_nodes.get_ingest_state = AsyncMock(
            return_value=ingest_state(first.catalog_uuid, content_hash=first.content_hash)
        )
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
        mock_request.headers = {"content-type": "application/json"}
        await self.controller.create(
            request=mock_request,
            certname="node1",
            command="store_report",
            producer_timestamp="2026-03-06T00:00:00Z",
            version=8,
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
        node_report = self.mock_nodes.update.call_args.kwargs["payload"].report
        self.assertIsNone(node_report.resources)
        self.assertIsNone(node_report.logs)
        report_payload = self.mock_reports.create_latest.call_args.kwargs["payload"]
        self.assertEqual(len(report_payload.report.resources), 1)

    async def test_store_report_that_is_not_latest_leaves_the_node_report_state(self):
        self.mock_nodes.update = AsyncMock()
        self.mock_reports.create_latest = AsyncMock(return_value=(False, STORED_REPORT))
        self.mock_catalogs.drop_created_no_report_ttl = AsyncMock()

        await self._post_report()

        payload = self.mock_nodes.update.call_args.kwargs["payload"]
        self.assertIsNone(payload.report)
        self.assertIsNone(payload.change_report)
        self.assertIsNotNone(payload.change_last)

    async def test_store_report_skips_an_already_stored_hash(self):
        self.mock_nodes.update = AsyncMock()
        self.mock_reports.hash_exists = AsyncMock(return_value=True)
        self.mock_catalogs.drop_created_no_report_ttl = AsyncMock()

        await self._post_report()

        self.mock_reports.create_latest.assert_not_called()
        self.mock_events.insert_for_report.assert_not_awaited()
        self.mock_nodes.update.assert_not_called()

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
        mock_request.headers = {
            "content-type": "application/json",
            "content-encoding": "gzip",
        }

        self.mock_groups.reevaluate_node_membership = AsyncMock(return_value=["g1"])
        self.mock_nodes.update = AsyncMock()

        await self.controller.create(
            request=mock_request,
            certname="node1",
            command="replace_facts",
            producer_timestamp="2026-03-06T00:00:00Z",
            version=5,
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
        mock_request.headers = {"content-type": "application/json"}

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
            version=5,
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
        mock_request.headers = {"content-type": "application/json"}
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

    async def test_unknown_command_is_not_proxied(self):
        self.mock_config.app.puppetdb.serverurl = "http://puppetdb:8081"
        mock_http = MagicMock()
        mock_http.post = AsyncMock()
        self.controller._http = mock_http

        mock_request = MagicMock()
        mock_request.body = AsyncMock(
            return_value=json.dumps({"certname": "node1"}).encode()
        )
        mock_request.headers = {"content-type": "application/json"}
        mock_request.query_params = {"certname": "node1"}
        result = await self.controller.create(
            request=mock_request,
            certname="node1",
            command="something_else",
            producer_timestamp="2026-03-06T00:00:00Z",
            version=1,
        )
        self.assertEqual(result.status_code, 400)
        self.assertEqual(self.queue.stats["accepted"], 0)
        await asyncio.sleep(0.05)
        mock_http.post.assert_not_called()

    async def test_proxy_forwards_only_the_command_params_with_a_string_version(self):
        self.mock_config.app.puppetdb.serverurl = "http://puppetdb:8081"
        self.mock_nodes.update = AsyncMock()
        mock_http = MagicMock()
        mock_http.post = AsyncMock()
        self.controller._http = mock_http

        mock_request = MagicMock()
        mock_request.body = AsyncMock(
            return_value=json.dumps({"certname": "node1"}).encode()
        )
        mock_request.headers = {"content-type": "application/json"}
        mock_request.query_params = {
            "certname": "node1",
            "command": "deactivate_node",
            "version": "3",
            "checksum": "abc",
        }
        await self.controller.create(
            request=mock_request,
            certname="node1",
            command="deactivate_node",
            producer_timestamp="2026-03-06T00:00:00Z",
            version="3",
            checksum="abc",
        )
        await asyncio.sleep(0.1)
        self.assertEqual(
            mock_http.post.call_args.kwargs["params"],
            {
                "certname": "node1",
                "command": "deactivate node",
                "version": "3",
                "producer-timestamp": "2026-03-06T00:00:00Z",
            },
        )

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


class TestControllerPdbCmdV1Validation(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        TestControllerPdbCmdV1Unit.setUp(self)

    def request(self, data=None, headers=None, body=None, query_params=None):
        mock_request = MagicMock()
        if body is None:
            body = json.dumps(data if data is not None else {"certname": "node1"}).encode()
        mock_request.body = AsyncMock(return_value=body)
        mock_request.headers = (
            headers if headers is not None else {"content-type": "application/json"}
        )
        if query_params is not None:
            mock_request.query_params = query_params
        return mock_request

    async def create(self, mock_request, **kwargs):
        params = {
            "certname": "node1",
            "command": "deactivate_node",
            "producer_timestamp": None,
            "version": 3,
        }
        params.update(kwargs)
        return await self.controller.create(request=mock_request, **params)

    def assert_bad_request(self, result, message):
        self.assertEqual(result.status_code, 400)
        self.assertEqual(json.loads(result.body), {"error": message})
        self.assertEqual(self.queue.stats["accepted"], 0)

    async def test_invalid_parameter(self):
        result = await self.create(
            self.request(
                query_params={
                    "certname": "node1",
                    "command": "deactivate_node",
                    "version": "3",
                    "bogus": "1",
                    "other": "2",
                }
            )
        )
        self.assert_bad_request(
            result,
            'Command "deactivate node" for certname "node1" is invalid. '
            "Command has invalid parameters: bogus, other.",
        )

    async def test_checksum_is_accepted_and_ignored(self):
        self.mock_nodes.update = AsyncMock()
        result = await self.create(
            self.request(
                query_params={
                    "certname": "node1",
                    "command": "deactivate_node",
                    "version": "3",
                    "checksum": "deadbeef",
                }
            ),
            checksum="deadbeef",
        )
        self.assertIn("uuid", result)
        self.assertEqual(self.queue.stats["accepted"], 1)

    async def test_missing_parameters(self):
        result = await self.create(self.request(), version=None, certname=None)
        self.assert_bad_request(
            result,
            'Command "deactivate node" for certname nil is invalid. '
            "Command is missing required parameters: certname, version.",
        )

    async def test_blank_certname(self):
        result = await self.create(self.request(), certname="   ")
        self.assert_bad_request(
            result,
            'Command "deactivate node" for certname "   " is invalid. '
            "Certname must be a non-empty string.",
        )

    async def test_unknown_command(self):
        result = await self.create(self.request(), command="drop_tables")
        self.assert_bad_request(
            result,
            'Command "drop tables" for certname "node1" is invalid. '
            "Command must be one of: configure expiration, deactivate node, "
            "replace catalog, replace catalog inputs, replace facts, store report.",
        )

    async def test_version_must_be_an_integer(self):
        result = await self.create(self.request(), version="three")
        self.assert_bad_request(
            result,
            'Command "deactivate node" for certname "node1" is invalid. '
            "Version must be a valid integer.",
        )

    async def test_retired_version(self):
        result = await self.create(self.request(), version="2")
        self.assert_bad_request(
            result,
            'Command "deactivate node" for certname "node1" is invalid. '
            'Version 2 of command "deactivate node" is retired. '
            "The minimum supported version is 3.",
        )

    async def test_every_command_has_its_upstream_minimum(self):
        for command, minimum in (
            ("configure_expiration", 1),
            ("replace_catalog", 6),
            ("replace_catalog_inputs", 1),
            ("replace_facts", 4),
            ("store_report", 5),
            ("deactivate_node", 3),
        ):
            if minimum == 1:
                continue
            result = await self.create(
                self.request(), command=command, version=str(minimum - 1)
            )
            self.assertEqual(result.status_code, 400, command)
            self.assertIn(
                f"The minimum supported version is {minimum}.",
                json.loads(result.body)["error"],
            )

    async def test_space_form_of_the_command_name_is_accepted(self):
        self.mock_nodes.update = AsyncMock()
        result = await self.create(self.request(), command="deactivate node")
        self.assertIn("uuid", result)
        await asyncio.sleep(0.05)
        self.mock_nodes.update.assert_called_once()

    async def test_body_that_is_not_json(self):
        result = await self.create(self.request(body=b"not json"))
        self.assert_bad_request(
            result,
            'Command "deactivate node" for certname "node1" is invalid. '
            "The request body must be a JSON map.",
        )

    async def test_old_format_takes_command_version_and_certname_from_the_body(self):
        self.mock_nodes.update = AsyncMock()
        body = {
            "command": "deactivate node",
            "version": 3,
            "payload": {"certname": "old1", "producer_timestamp": "2026-03-06T00:00:00Z"},
        }
        result = await self.create(
            self.request(data=body), certname=None, command=None, version=None
        )
        self.assertIn("uuid", result)
        await asyncio.sleep(0.05)
        self.assertEqual(self.mock_nodes.update.call_args.kwargs["_id"], "old1")
        self.assertTrue(self.mock_nodes.update.call_args.kwargs["payload"].disabled)

    async def test_old_format_proxies_the_payload_as_the_body(self):
        self.mock_config.app.puppetdb.serverurl = "http://puppetdb:8081"
        self.mock_nodes.update = AsyncMock()
        mock_http = MagicMock()
        mock_http.post = AsyncMock()
        self.controller._http = mock_http
        body = {
            "command": "deactivate node",
            "version": 3,
            "payload": {"certname": "old1"},
        }
        await self.create(
            self.request(data=body), certname=None, command=None, version=None
        )
        await asyncio.sleep(0.05)
        kwargs = mock_http.post.call_args.kwargs
        self.assertEqual(json.loads(kwargs["content"]), {"certname": "old1"})
        self.assertEqual(
            kwargs["params"],
            {"certname": "old1", "command": "deactivate node", "version": "3"},
        )

    async def test_old_format_with_missing_keys(self):
        body = {"command": "deactivate node", "payload": {"certname": "old1"}}
        result = await self.create(
            self.request(data=body), certname=None, command=None, version=None
        )
        self.assert_bad_request(
            result,
            'Command "deactivate node" for certname "old1" is invalid. '
            "Command was submitted without query parameters (old format). "
            "The request body must be a JSON map with required keys: command, version, payload.",
        )

    async def test_old_format_with_an_unparseable_body(self):
        result = await self.create(
            self.request(body=b"nope"), certname=None, command=None, version=None
        )
        self.assert_bad_request(
            result,
            "Command nil for certname nil is invalid. "
            "Command was submitted without query parameters (old format). "
            "The request body must be a JSON map with required keys: command, version, payload.",
        )

    async def test_old_format_with_a_payload_that_is_not_a_map(self):
        body = {"command": "deactivate node", "version": 3, "payload": [1]}
        result = await self.create(
            self.request(data=body), certname=None, command=None, version=None
        )
        self.assert_bad_request(
            result,
            'Command "deactivate node" for certname nil is invalid. '
            "Command was submitted without query parameters (old format). "
            "The payload value must be a JSON map.",
        )

    async def test_old_format_validates_the_body_keys_as_parameters(self):
        body = {
            "command": "deactivate node",
            "version": 3,
            "payload": {"certname": "old1"},
            "extra": True,
        }
        result = await self.create(
            self.request(data=body), certname=None, command=None, version=None
        )
        self.assert_bad_request(
            result,
            'Command "deactivate node" for certname "old1" is invalid. '
            "Command has invalid parameters: extra.",
        )

    async def test_wait_for_completion_answers_processed(self):
        self.mock_nodes.update = AsyncMock()
        result = await self.create(self.request(), seconds_to_wait="5")
        self.assertEqual(result.status_code, 200)
        content = json.loads(result.body)
        self.assertIn("uuid", content)
        self.assertEqual(content["processed"], True)
        self.assertEqual(content["timed_out"], False)
        self.mock_nodes.update.assert_called_once()

    async def test_wait_for_completion_times_out(self):
        release = asyncio.Event()

        async def blocked(**kwargs):
            await release.wait()

        self.mock_nodes.update = blocked
        result = await self.create(self.request(), seconds_to_wait="0.1")
        self.assertEqual(result.status_code, 503)
        content = json.loads(result.body)
        self.assertEqual(content["processed"], False)
        self.assertEqual(content["timed_out"], True)
        self.assertNotIn("error", content)
        release.set()

    async def test_wait_for_completion_reports_the_job_error(self):
        self.mock_nodes.update = AsyncMock(side_effect=RuntimeError("mongo is gone"))
        with self.assertLogs("test", level="ERROR") as logs:
            result = await self.create(self.request(), seconds_to_wait="5")
        self.assertEqual(result.status_code, 503)
        content = json.loads(result.body)
        self.assertEqual(content["processed"], True)
        self.assertEqual(content["timed_out"], False)
        self.assertEqual(content["error"], COMMAND_FAILED)
        self.assertNotIn("mongo is gone", json.dumps(content))
        self.assertTrue(any("mongo is gone" in line for line in logs.output))
        self.assertTrue(any(content["uuid"] in line for line in logs.output))
        self.assertEqual(self.queue.stats["failed"], 1)

    async def test_wait_for_completion_covers_only_the_local_job(self):
        self.mock_config.app.puppetdb.serverurl = "http://puppetdb:8081"
        self.mock_nodes.update = AsyncMock()
        mock_http = MagicMock()
        mock_http.post = AsyncMock(side_effect=RuntimeError("upstream down"))
        self.controller._http = mock_http

        with self.assertLogs("test", level="ERROR"):
            result = await self.create(
                self.request(query_params={"certname": "node1"}), seconds_to_wait="5"
            )
            await asyncio.sleep(0.05)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(json.loads(result.body)["processed"], True)

    async def test_zero_seconds_to_wait_does_not_block(self):
        release = asyncio.Event()

        async def blocked(**kwargs):
            await release.wait()

        self.mock_nodes.update = blocked
        result = await self.create(self.request(), seconds_to_wait="0")
        self.assertIn("uuid", result)
        release.set()

    async def test_seconds_to_wait_must_be_a_number(self):
        result = await self.create(self.request(), seconds_to_wait="soon")
        self.assert_bad_request(
            result,
            'Command "deactivate node" for certname "node1" is invalid. '
            "secondsToWaitForCompletion must be a valid number.",
        )

    async def test_unsupported_content_type(self):
        result = await self.create(self.request(headers={"content-type": "text/plain"}))
        self.assertEqual(result.status_code, 415)
        self.assertEqual(
            json.loads(result.body),
            {
                "kind": "unsupported-type",
                "msg": "content-type text/plain is not a supported type for request of type :post at /pdb/cmd/v1",
            },
        )
        self.assertEqual(self.queue.stats["accepted"], 0)

    async def test_missing_content_type(self):
        result = await self.create(self.request(headers={}))
        self.assertEqual(result.status_code, 415)
        self.assertEqual(json.loads(result.body)["kind"], "unsupported-type")

    async def test_content_type_parameters_are_allowed(self):
        self.mock_nodes.update = AsyncMock()
        result = await self.create(
            self.request(headers={"content-type": "application/json; charset=utf-8"})
        )
        self.assertIn("uuid", result)

    async def test_unsupported_content_encoding(self):
        result = await self.create(
            self.request(
                headers={"content-type": "application/json", "content-encoding": "br"}
            )
        )
        self.assertEqual(result.status_code, 415)
        self.assertEqual(result.body, b"content encoding br not supported")
        self.assertEqual(self.queue.stats["accepted"], 0)

    async def test_identity_content_encoding_is_accepted(self):
        self.mock_nodes.update = AsyncMock()
        result = await self.create(
            self.request(
                headers={
                    "content-type": "application/json",
                    "content-encoding": "identity",
                }
            )
        )
        self.assertIn("uuid", result)

    async def test_gzip_body_without_the_header_is_still_sniffed(self):
        self.mock_nodes.update = AsyncMock()
        result = await self.create(
            self.request(body=gzip.compress(json.dumps({"certname": "node1"}).encode()))
        )
        self.assertIn("uuid", result)
        await asyncio.sleep(0.05)
        self.mock_nodes.update.assert_called_once()

    async def test_max_command_size_by_uncompressed_length_header(self):
        self.mock_config.app.puppetdb.maxCommandSize = 100
        result = await self.create(
            self.request(
                headers={
                    "content-type": "application/json",
                    "x-uncompressed-length": "101",
                    "content-length": "10",
                }
            )
        )
        self.assertEqual(result.status_code, 413)
        self.assertEqual(result.body, b"Command size exceeds max-command-size")

    async def test_max_command_size_by_content_length_header(self):
        self.mock_config.app.puppetdb.maxCommandSize = 100
        result = await self.create(
            self.request(
                headers={"content-type": "application/json", "content-length": "101"}
            )
        )
        self.assertEqual(result.status_code, 413)

    async def test_max_command_size_by_decoded_body_length(self):
        self.mock_config.app.puppetdb.maxCommandSize = 10
        result = await self.create(self.request())
        self.assertEqual(result.status_code, 413)
        self.assertEqual(self.queue.stats["accepted"], 0)

    async def test_max_command_size_accepts_a_command_within_the_limit(self):
        self.mock_config.app.puppetdb.maxCommandSize = 1000
        self.mock_nodes.update = AsyncMock()
        result = await self.create(
            self.request(
                headers={"content-type": "application/json", "content-length": "20"}
            )
        )
        self.assertIn("uuid", result)

    async def test_max_command_size_ignores_an_unparseable_uncompressed_length(self):
        self.mock_config.app.puppetdb.maxCommandSize = 100
        self.mock_nodes.update = AsyncMock()
        with self.assertLogs("test", level="WARNING"):
            result = await self.create(
                self.request(
                    headers={
                        "content-type": "application/json",
                        "x-uncompressed-length": "lots",
                    }
                )
            )
        self.assertIn("uuid", result)

    async def test_configure_expiration_stores_the_expiration_on_the_node(self):
        self.mock_nodes.update = AsyncMock()
        result = await self.create(
            self.request(
                data={
                    "certname": "node1",
                    "producer_timestamp": "2026-03-06T00:00:00Z",
                    "expire": {"facts": False},
                }
            ),
            command="configure_expiration",
            version=1,
        )
        self.assertIn("uuid", result)
        await asyncio.sleep(0.05)
        kwargs = self.mock_nodes.update.call_args.kwargs
        self.assertEqual(kwargs["_id"], "node1")
        self.assertTrue(kwargs["upsert"])
        payload = kwargs["payload"]
        self.assertFalse(payload.facts_expiration.expire)
        self.assertIsNotNone(payload.facts_expiration.updated)
        self.assertIsNotNone(payload.change_last)
        self.assertIsNone(payload.disabled)
        self.assertIsNone(payload.environment)
        self.mock_reports.set_node_disabled.assert_not_called()

    async def test_configure_expiration_defaults_to_expiring(self):
        self.mock_nodes.update = AsyncMock()
        await self.create(
            self.request(data={"certname": "node1", "expire": {"facts": True}}),
            command="configure expiration",
            version="1",
        )
        await asyncio.sleep(0.05)
        payload = self.mock_nodes.update.call_args.kwargs["payload"]
        self.assertTrue(payload.facts_expiration.expire)

