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

import logging
import unittest
from unittest.mock import MagicMock

from pyppetdb.crud.ca_certificates import CertRevocationWatcher


class _RecordingListener:
    def __init__(self):
        self.serials = []
        self.object_ids = []

    def invalidate_serial(self, serial):
        self.serials.append(serial)

    def invalidate_object_id(self, object_id):
        self.object_ids.append(object_id)


def _make_watcher(log, listeners):
    watcher = CertRevocationWatcher(log=log, coll=MagicMock())
    for listener in listeners:
        watcher.add_listener(listener)
    return watcher


class TestCertRevocationWatcher(unittest.TestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.listener = _RecordingListener()
        self.watcher = _make_watcher(self.log, [self.listener])

    def test_update_to_revoked_invalidates_serial(self):
        self.watcher._handle_change(
            {
                "operationType": "update",
                "documentKey": {"_id": "objid-1"},
                "fullDocument": {"id": "serial-1", "status": "revoked"},
            }
        )
        self.assertEqual(self.listener.serials, ["serial-1"])
        self.assertEqual(self.listener.object_ids, [])

    def test_signed_update_does_not_invalidate(self):
        self.watcher._handle_change(
            {
                "operationType": "update",
                "documentKey": {"_id": "objid-1"},
                "fullDocument": {"id": "serial-1", "status": "signed"},
            }
        )
        self.assertEqual(self.listener.serials, [])
        self.assertEqual(self.listener.object_ids, [])

    def test_delete_invalidates_by_object_id(self):
        self.watcher._handle_change(
            {
                "operationType": "delete",
                "documentKey": {"_id": "objid-2"},
            }
        )
        self.assertEqual(self.listener.object_ids, ["objid-2"])
        self.assertEqual(self.listener.serials, [])

    def test_delete_object_id_is_stringified(self):
        oid = MagicMock()
        oid.__str__ = lambda self: "stringified-oid"
        self.watcher._handle_change(
            {
                "operationType": "delete",
                "documentKey": {"_id": oid},
            }
        )
        self.assertEqual(self.listener.object_ids, ["stringified-oid"])

    def test_update_without_full_document_is_ignored(self):
        self.watcher._handle_change(
            {
                "operationType": "update",
                "documentKey": {"_id": "objid-3"},
                "fullDocument": None,
            }
        )
        self.assertEqual(self.listener.serials, [])

    def test_serial_listener_error_does_not_break_dispatch(self):
        class Boom:
            def invalidate_serial(self, serial):
                raise RuntimeError("down")

            def invalidate_object_id(self, object_id):
                raise RuntimeError("down")

        watcher = _make_watcher(self.log, [Boom(), self.listener])
        watcher._handle_change(
            {
                "operationType": "update",
                "documentKey": {"_id": "objid-4"},
                "fullDocument": {"id": "serial-4", "status": "revoked"},
            }
        )
        self.assertEqual(self.listener.serials, ["serial-4"])

    def test_object_id_listener_error_does_not_break_dispatch(self):
        class Boom:
            def invalidate_serial(self, serial):
                raise RuntimeError("down")

            def invalidate_object_id(self, object_id):
                raise RuntimeError("down")

        watcher = _make_watcher(self.log, [Boom(), self.listener])
        watcher._handle_change(
            {
                "operationType": "delete",
                "documentKey": {"_id": "objid-5"},
            }
        )
        self.assertEqual(self.listener.object_ids, ["objid-5"])

    def test_dispatches_to_all_listeners(self):
        listener_a = _RecordingListener()
        listener_b = _RecordingListener()
        watcher = _make_watcher(self.log, [listener_a, listener_b])
        watcher._handle_change(
            {
                "operationType": "update",
                "documentKey": {"_id": "objid-6"},
                "fullDocument": {"id": "serial-6", "status": "revoked"},
            }
        )
        self.assertEqual(listener_a.serials, ["serial-6"])
        self.assertEqual(listener_b.serials, ["serial-6"])


if __name__ == "__main__":
    unittest.main()
