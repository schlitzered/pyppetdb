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
from pyppetdb.crud.ca_certificates import CrudCACertificates
from pyppetdb.errors import ResourceNotFound


class _RecordingListener:
    def __init__(self):
        self.serials = []
        self.object_ids = []

    def invalidate_serial(self, serial):
        self.serials.append(serial)

    def invalidate_object_id(self, object_id):
        self.object_ids.append(object_id)


class TestCrudCACertificatesUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_config = MagicMock()
        self.mock_coll = MagicMock()

        self.crud = CrudCACertificates(
            config=self.mock_config, log=self.log, coll=self.mock_coll
        )

    async def test_count(self):
        self.mock_coll.count_documents = AsyncMock(return_value=10)
        res = await self.crud.count({"status": "signed"})
        self.assertEqual(res, 10)
        self.mock_coll.count_documents.assert_called_once_with({"status": "signed"})

    def test_add_revocation_listener_is_wired_to_watcher(self):
        listener = _RecordingListener()
        self.crud.add_revocation_listener(listener)

        self.crud._revocation_watcher._handle_change(
            {
                "operationType": "update",
                "documentKey": {"_id": "objid"},
                "fullDocument": {"id": "serial-9", "status": "revoked"},
            }
        )
        self.assertEqual(listener.serials, ["serial-9"])

    async def test_get_internal_object_id_returns_stringified_id(self):
        oid = MagicMock()
        oid.__str__ = lambda self: "64f0c0ffee"
        self.mock_coll.find_one = AsyncMock(return_value={"_id": oid})

        result = await self.crud.get_internal_object_id(
            serial="123", cn="node1.example.com", space_id="puppet-ca"
        )

        self.assertEqual(result, "64f0c0ffee")
        self.mock_coll.find_one.assert_called_once_with(
            {
                "id": "123",
                "cn": "node1.example.com",
                "space_id": "puppet-ca",
                "status": "signed",
            },
            {"_id": 1},
        )

    async def test_get_internal_object_id_scopes_to_space(self):
        self.mock_coll.find_one = AsyncMock(return_value=None)

        with self.assertRaises(ResourceNotFound):
            await self.crud.get_internal_object_id(
                serial="123", cn="node1.example.com", space_id="other-space"
            )

        query, _ = self.mock_coll.find_one.call_args[0]
        self.assertEqual(query["space_id"], "other-space")

    async def test_get_internal_object_id_missing_raises_not_found(self):
        self.mock_coll.find_one = AsyncMock(return_value=None)
        with self.assertRaises(ResourceNotFound):
            await self.crud.get_internal_object_id(
                serial="404", cn="ghost", space_id="puppet-ca"
            )
