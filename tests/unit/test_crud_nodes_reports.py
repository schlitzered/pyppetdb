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
from unittest.mock import MagicMock, AsyncMock
import logging
from datetime import datetime, timedelta, UTC

import pymongo.errors

from pyppetdb.crud.nodes_reports import CrudNodesReports
from pyppetdb.crud.nodes_reports import LATEST_TRANSACTION_ATTEMPTS
from pyppetdb.model.nodes_reports import NodeReportPostInternal


class FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class TestCrudNodesReportsNodeState(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.coll = MagicMock()
        self.crud = CrudNodesReports(
            MagicMock(), logging.getLogger("test"), self.coll, MagicMock()
        )

    async def test_only_touches_reports_that_disagree(self):
        self.coll.update_many = AsyncMock(
            return_value=MagicMock(modified_count=3)
        )
        changed = await self.crud.set_node_disabled(node_id="n1", disabled=True)
        self.assertEqual(changed, 3)
        self.coll.update_many.assert_awaited_once_with(
            filter={"node_id": "n1", "disabled": {"$ne": True}},
            update={"$set": {"disabled": True}},
        )

    async def test_reactivation_uses_the_inverse_filter(self):
        self.coll.update_many = AsyncMock(
            return_value=MagicMock(modified_count=0)
        )
        await self.crud.set_node_disabled(node_id="n1", disabled=False)
        self.coll.update_many.assert_awaited_once_with(
            filter={"node_id": "n1", "disabled": {"$ne": False}},
            update={"$set": {"disabled": False}},
        )


class FakeSession:
    def __init__(self, error=None, errors=1):
        self.transactions = 0
        self._error = error
        self._errors = errors

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def start_transaction(self):
        self.transactions += 1
        if self._error and self.transactions <= self._errors:
            raise self._error
        return FakeTransaction()


class TestCrudNodesReportsUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_coll = MagicMock()
        self.mock_config = MagicMock()
        self.mock_redactor = MagicMock()
        self.crud = CrudNodesReports(
            self.mock_config, self.log, self.mock_coll, self.mock_redactor
        )

    async def test_delete(self):
        now = datetime.now()
        self.crud._delete = AsyncMock()
        await self.crud.delete(
            _id=now,
            node_id="node1",
            placement={},
        )
        self.crud._delete.assert_called_once_with(query={"id": now, "node_id": "node1"})

    async def test_delete_all_from_node(self):
        self.mock_coll.delete_many = AsyncMock()
        await self.crud.delete_all_from_node(
            node_id="node1",
            placement={},
        )
        self.mock_coll.delete_many.assert_called_once_with(filter={"node_id": "node1"})

    async def test_create(self):
        now = datetime.now()
        self.crud._create = AsyncMock(return_value={"id": now})
        self.mock_redactor.redact.side_effect = lambda x: x

        from pyppetdb.model.nodes_reports import NodeReportPostInternal

        payload = NodeReportPostInternal(report={"status": "changed"})

        result = await self.crud.create(
            _id=now, node_id="node1", payload=payload, fields=[]
        )
        self.assertEqual(result.id, now)
        self.mock_redactor.redact.assert_called_once()

    async def test_get(self):
        now = datetime.now()
        self.crud._get = AsyncMock(return_value={"id": now, "node_id": "node1"})
        await self.crud.get(
            _id=now,
            node_id="node1",
            placement={},
            fields=[],
        )
        self.crud._get.assert_called_once()

    async def test_resource_exists(self):
        now = datetime.now()
        self.crud._resource_exists = AsyncMock(return_value=True)
        await self.crud.resource_exists(
            _id=now,
            node_id="node1",
            placement={},
        )
        self.crud._resource_exists.assert_called_once()

    async def test_search(self):
        self.crud._search = AsyncMock(
            return_value={"result": [], "meta": {"result_size": 0}}
        )
        await self.crud.search(
            node_id="node1",
            placement={},
        )
        self.crud._search.assert_called_once()

    def _report_coll(self, stored=None):
        self.mock_coll.find_one = AsyncMock(return_value=stored)
        self.mock_coll.update_many = AsyncMock()
        self.mock_coll.insert_one = AsyncMock()
        self.mock_redactor.redact.side_effect = lambda x: x

    async def test_create_latest_flags_the_new_report(self):
        now = datetime.now(UTC)
        self._report_coll(
            stored={"report": {"end_time": now - timedelta(minutes=30)}},
        )
        session = FakeSession()
        self.mock_coll.database.client.start_session = AsyncMock(return_value=session)

        latest, _stored = await self.crud.create_latest(
            _id=now,
            node_id="node1",
            payload=NodeReportPostInternal(
                report={"status": "changed", "end_time": now, "latest": True}
            ),
        )

        self.assertTrue(latest)
        self.assertEqual(session.transactions, 1)
        self.mock_coll.update_many.assert_called_once_with(
            filter={"node_id": "node1", "report.latest": True},
            update={"$set": {"report.latest": False}},
            session=session,
        )
        document = self.mock_coll.insert_one.call_args.args[0]
        self.assertTrue(document["report"]["latest"])
        self.assertEqual(document["node_id"], "node1")
        self.assertEqual(document["id"], now)
        self.assertEqual(document["_version"], 1)
        self.assertEqual(
            self.mock_coll.insert_one.call_args.kwargs["session"], session
        )

    async def test_create_latest_keeps_a_newer_stored_report_as_latest(self):
        now = datetime.now(UTC)
        self._report_coll(
            stored={"report": {"end_time": now + timedelta(minutes=30)}},
        )
        session = FakeSession()
        self.mock_coll.database.client.start_session = AsyncMock(return_value=session)

        latest, _stored = await self.crud.create_latest(
            _id=now,
            node_id="node1",
            payload=NodeReportPostInternal(
                report={"status": "changed", "end_time": now, "latest": True}
            ),
        )

        self.assertFalse(latest)
        self.mock_coll.update_many.assert_not_called()
        document = self.mock_coll.insert_one.call_args.args[0]
        self.assertFalse(document["report"]["latest"])

    async def test_create_latest_compares_naive_stored_timestamps(self):
        now = datetime.now(UTC)
        naive_newer = (now + timedelta(minutes=30)).replace(tzinfo=None)
        self._report_coll(stored={"report": {"end_time": naive_newer}})
        self.mock_coll.database.client.start_session = AsyncMock(
            return_value=FakeSession()
        )

        latest, _stored = await self.crud.create_latest(
            _id=now,
            node_id="node1",
            payload=NodeReportPostInternal(
                report={"status": "changed", "end_time": now, "latest": True}
            ),
        )
        self.assertFalse(latest)

    async def test_create_latest_without_a_stored_report(self):
        now = datetime.now(UTC)
        self._report_coll(stored=None)
        self.mock_coll.database.client.start_session = AsyncMock(
            return_value=FakeSession()
        )

        latest, _stored = await self.crud.create_latest(
            _id=now,
            node_id="node1",
            payload=NodeReportPostInternal(
                report={"status": "changed", "end_time": now, "latest": True}
            ),
        )
        self.assertTrue(latest)
        self.mock_coll.update_many.assert_called_once()

    async def test_create_latest_falls_back_without_transactions(self):
        now = datetime.now(UTC)
        self._report_coll(stored=None)
        session = FakeSession(
            error=pymongo.errors.OperationFailure("no transactions", code=20)
        )
        self.mock_coll.database.client.start_session = AsyncMock(return_value=session)

        latest, _stored = await self.crud.create_latest(
            _id=now,
            node_id="node1",
            payload=NodeReportPostInternal(
                report={"status": "changed", "end_time": now, "latest": True}
            ),
        )

        self.assertTrue(latest)
        self.assertIsNone(self.mock_coll.insert_one.call_args.kwargs["session"])

    async def test_create_latest_raises_on_duplicates(self):
        from pyppetdb.errors import DuplicateResource

        now = datetime.now(UTC)
        self._report_coll(stored=None)
        self.mock_coll.insert_one = AsyncMock(
            side_effect=pymongo.errors.DuplicateKeyError("duplicate")
        )
        self.mock_coll.database.client.start_session = AsyncMock(
            return_value=FakeSession()
        )

        with self.assertRaises(DuplicateResource):
            await self.crud.create_latest(
                _id=now,
                node_id="node1",
                payload=NodeReportPostInternal(
                    report={"status": "changed", "end_time": now, "latest": True}
                ),
            )

    async def test_create_latest_retries_transient_transaction_errors(self):
        now = datetime.now(UTC)
        self._report_coll(stored=None)
        transient = pymongo.errors.OperationFailure(
            "write conflict",
            code=112,
            details={"errorLabels": ["TransientTransactionError"]},
        )
        sessions = [
            FakeSession(error=transient),
            FakeSession(),
        ]
        self.mock_coll.database.client.start_session = AsyncMock(
            side_effect=sessions
        )

        latest, _stored = await self.crud.create_latest(
            _id=now,
            node_id="node1",
            payload=NodeReportPostInternal(
                report={"status": "changed", "end_time": now, "latest": True}
            ),
        )

        self.assertTrue(latest)
        self.assertEqual([session.transactions for session in sessions], [1, 1])
        self.mock_coll.insert_one.assert_called_once()

    async def test_create_latest_gives_up_after_the_last_attempt(self):
        now = datetime.now(UTC)
        self._report_coll(stored=None)
        transient = pymongo.errors.OperationFailure(
            "write conflict",
            code=112,
            details={"errorLabels": ["TransientTransactionError"]},
        )
        self.mock_coll.database.client.start_session = AsyncMock(
            side_effect=lambda: FakeSession(error=transient)
        )

        with self.assertRaises(pymongo.errors.OperationFailure):
            await self.crud.create_latest(
                _id=now,
                node_id="node1",
                payload=NodeReportPostInternal(
                    report={"status": "changed", "end_time": now, "latest": True}
                ),
            )
        self.assertEqual(
            self.mock_coll.database.client.start_session.await_count,
            LATEST_TRANSACTION_ATTEMPTS,
        )
        self.mock_coll.insert_one.assert_not_called()
