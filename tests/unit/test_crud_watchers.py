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
import logging
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock
from unittest.mock import patch

from pyppetdb.crud.ca_authorities import CrudCAAuthoritiesCache
from pyppetdb.crud.ca_certificates import CertRevocationWatcher
from pyppetdb.crud.ca_spaces import CrudCASpacesCache
from pyppetdb.crud.common import watch_collection
from pyppetdb.crud.hiera_key_models_dynamic import CrudHieraModelsDynamicAdapter
from pyppetdb.crud.hiera_keys import CrudHieraKeysAdapter
from pyppetdb.crud.hiera_levels import CrudHieraLevelsCache
from pyppetdb.crud.nodes_groups import CrudNodesGroupsCache
from pyppetdb.crud.nodes_secrets_redactor import CrudNodesSecretsRedactorCache


class _ChangeStream:
    def __init__(self, changes=(), error=None, ends=False):
        self._changes = list(changes)
        self._error = error
        self._ends = ends

    async def __aenter__(self):
        if self._error:
            raise self._error
        return self

    async def __aexit__(self, *args):
        return False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._changes:
            if self._ends:
                raise StopAsyncIteration
            raise asyncio.CancelledError()
        return self._changes.pop(0)


class _Cursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._docs:
            raise StopAsyncIteration
        return self._docs.pop(0)


def _cursors(*batches):
    return [_Cursor(batch) for batch in batches]


def _streams_with_reconnect():
    return [_ChangeStream(error=RuntimeError("connection lost")), _ChangeStream()]


class _WatcherTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.coll = MagicMock()
        sleep = patch("pyppetdb.crud.common.asyncio.sleep")
        sleep.start()
        self.addCleanup(sleep.stop)

    async def run_watcher(self, watcher):
        with self.assertRaises(asyncio.CancelledError):
            await watcher._watch_changes()


class TestWatchCollection(_WatcherTestCase):
    async def test_resyncs_on_every_stream_start_and_restarts_after_errors(self):
        calls = []

        async def resync():
            calls.append("resync")

        async def handle_change(change):
            calls.append(change["n"])

        self.coll.watch.side_effect = [
            _ChangeStream([{"n": 1}], ends=True),
            _ChangeStream(error=RuntimeError("connection lost")),
            _ChangeStream([{"n": 2}]),
        ]

        with self.assertRaises(asyncio.CancelledError):
            await watch_collection(
                coll=self.coll,
                log=self.log,
                name="test",
                handle_change=handle_change,
                resync=resync,
            )

        self.assertEqual(calls, ["resync", 1, "resync", 2])
        self.assertEqual(self.coll.watch.call_count, 3)

    async def test_failed_resync_retries_with_new_stream(self):
        attempts = []

        async def resync():
            attempts.append(1)
            if len(attempts) == 1:
                raise RuntimeError("find failed")

        async def handle_change(change):
            pass

        self.coll.watch.side_effect = [_ChangeStream(), _ChangeStream()]
        with self.assertRaises(asyncio.CancelledError):
            await watch_collection(
                coll=self.coll,
                log=self.log,
                name="test",
                handle_change=handle_change,
                resync=resync,
            )
        self.assertEqual(len(attempts), 2)

    async def test_passes_pipeline(self):
        async def noop(*args):
            pass

        pipeline = [{"$project": {"operationType": 1}}]
        self.coll.watch.side_effect = [_ChangeStream()]
        with self.assertRaises(asyncio.CancelledError):
            await watch_collection(
                coll=self.coll,
                log=self.log,
                name="test",
                handle_change=noop,
                resync=noop,
                pipeline=pipeline,
            )
        self.coll.watch.assert_called_once_with(
            full_document="updateLookup", pipeline=pipeline
        )


class TestCASpacesCacheResync(_WatcherTestCase):
    async def test_reconnect_drops_spaces_deleted_meanwhile(self):
        cache = CrudCASpacesCache(log=self.log, coll=self.coll, protector=MagicMock())
        self.coll.find.side_effect = _cursors(
            [{"_id": "o1", "id": "space1", "ca_id": "ca1"}],
            [{"_id": "o2", "id": "space2", "ca_id": "ca2"}],
        )
        self.coll.watch.side_effect = _streams_with_reconnect()
        await cache._load_initial_data()
        self.assertIn("space1", cache.cache)

        await self.run_watcher(cache)

        self.assertEqual(list(cache.cache), ["space2"])
        self.assertEqual(cache._doc_to_id, {"o2": "space2"})


def _authority_doc(object_id, ca_id):
    now = datetime.now(timezone.utc)
    return {
        "_id": object_id,
        "id": ca_id,
        "cn": ca_id,
        "issuer": ca_id,
        "serial_number": "1",
        "not_before": now,
        "not_after": now,
        "fingerprint": {"sha256": "abc", "sha1": "def", "md5": "ghi"},
        "certificate": "CERT",
        "private_key_encrypted": "ENC",
        "internal": True,
        "chain": [],
        "status": "active",
    }


class TestCAAuthoritiesCacheResync(_WatcherTestCase):
    async def test_reconnect_drops_authority_and_key_deleted_meanwhile(self):
        protector = MagicMock()
        protector.decrypt_string.return_value = "PEM"
        cache = CrudCAAuthoritiesCache(
            log=self.log, coll=self.coll, protector=protector
        )
        self.coll.find.side_effect = _cursors(
            [_authority_doc("o1", "ca1"), _authority_doc("o2", "ca2")],
            [_authority_doc("o2", "ca2")],
        )
        self.coll.watch.side_effect = _streams_with_reconnect()
        await cache._load_initial_data()
        self.assertEqual(set(cache.key_cache), {"ca1", "ca2"})

        await self.run_watcher(cache)

        self.assertEqual(list(cache.cache), ["ca2"])
        self.assertEqual(list(cache.key_cache), ["ca2"])
        self.assertEqual(cache._doc_to_id, {"o2": "ca2"})


class _ResetListener:
    def __init__(self):
        self.resets = 0
        self.serials = []

    def invalidate_all(self):
        self.resets += 1

    def invalidate_serial(self, serial):
        self.serials.append(serial)

    def invalidate_object_id(self, object_id):
        pass


class TestCertRevocationWatcherResync(_WatcherTestCase):
    async def test_every_stream_start_resets_listeners(self):
        listener = _ResetListener()
        watcher = CertRevocationWatcher(log=self.log, coll=self.coll)
        watcher.add_listener(listener)
        revoked = {
            "operationType": "update",
            "documentKey": {"_id": "objid-1"},
            "fullDocument": {"id": "serial-1", "status": "revoked"},
        }
        self.coll.watch.side_effect = [
            _ChangeStream([revoked], ends=True),
            _ChangeStream(error=RuntimeError("connection lost")),
            _ChangeStream(),
        ]

        await self.run_watcher(watcher)

        self.assertEqual(listener.resets, 2)
        self.assertEqual(listener.serials, ["serial-1"])

    async def test_reset_listener_error_does_not_stop_others(self):
        class Boom(_ResetListener):
            def invalidate_all(self):
                raise RuntimeError("down")

        listener = _ResetListener()
        watcher = CertRevocationWatcher(log=self.log, coll=self.coll)
        watcher.add_listener(Boom())
        watcher.add_listener(listener)
        self.coll.watch.side_effect = [_ChangeStream()]

        await self.run_watcher(watcher)

        self.assertEqual(listener.resets, 1)
        self.assertEqual(self.coll.watch.call_count, 1)


class TestNodesGroupsCacheResync(_WatcherTestCase):
    async def test_reconnect_updates_and_drops_groups(self):
        cache = CrudNodesGroupsCache(log=self.log, coll=self.coll)
        self.coll.find.side_effect = _cursors(
            [{"_id": "d1", "id": "g1"}, {"_id": "d2", "id": "g2"}],
            [{"_id": "d1", "id": "g1-renamed"}],
        )
        self.coll.watch.side_effect = _streams_with_reconnect()
        await cache._load_initial_data()
        cache_ref = cache.cache

        await self.run_watcher(cache)

        self.assertIs(cache.cache, cache_ref)
        self.assertEqual(list(cache.cache), ["d1"])
        self.assertEqual(cache.cache["d1"].id, "g1-renamed")


class TestHieraLevelsCacheResync(_WatcherTestCase):
    async def test_reconnect_keeps_list_identity_and_order(self):
        cache = CrudHieraLevelsCache(log=self.log, coll=self.coll)
        self.coll.find.side_effect = _cursors(
            [{"_id": "d1", "id": "a"}, {"_id": "d2", "id": "b"}],
            [{"_id": "d3", "id": "c"}, {"_id": "d2", "id": "b"}],
        )
        self.coll.watch.side_effect = _streams_with_reconnect()
        await cache._load_initial_data()
        level_ids = cache.level_ids
        self.assertEqual(level_ids, ["a", "b"])

        await self.run_watcher(cache)

        self.assertIs(cache.level_ids, level_ids)
        self.assertEqual(level_ids, ["b", "c"])
        self.assertEqual(set(cache.cache), {"d2", "d3"})


class TestSecretsRedactorCacheResync(_WatcherTestCase):
    async def test_reconnect_forgets_deleted_secret(self):
        redactor = MagicMock()
        redactor.decrypt.side_effect = lambda value: f"clear-{value}"
        cache = CrudNodesSecretsRedactorCache(
            log=self.log, coll=self.coll, redactor=redactor
        )
        self.coll.find.side_effect = _cursors(
            [{"_id": "d1", "value_encrypted": "s1"}, {"_id": "d2", "value_encrypted": "s2"}],
            [{"_id": "d2", "value_encrypted": "s2"}],
        )
        self.coll.watch.side_effect = _streams_with_reconnect()
        await cache._load_initial_data()

        await self.run_watcher(cache)

        self.assertEqual(cache._cache, {"d2": "clear-s2"})
        redactor.rebuild.assert_called_with(["clear-s2"])


class TestHieraKeysAdapterResync(_WatcherTestCase):
    async def test_reconnect_removes_deleted_keys_and_adds_new_ones(self):
        adapter = CrudHieraKeysAdapter(log=self.log, coll=self.coll, pyhiera=MagicMock())
        adapter._add_or_update_key = MagicMock()
        adapter._delete_key = MagicMock()
        self.coll.find.side_effect = _cursors(
            [{"_id": "d1", "id": "k1", "key_model_id": "m"}],
            [{"_id": "d2", "id": "k2", "key_model_id": "m"}],
        )
        self.coll.watch.side_effect = _streams_with_reconnect()
        await adapter._load_initial_data()

        await self.run_watcher(adapter)

        adapter._delete_key.assert_called_once_with("k1")
        adapter._add_or_update_key.assert_called_with("k2", "m")
        self.assertEqual(adapter._doc_to_key, {"d2": "k2"})


class TestHieraModelsDynamicAdapterResync(_WatcherTestCase):
    def _adapter(self):
        adapter = CrudHieraModelsDynamicAdapter(self.log, self.coll, MagicMock())
        adapter.model_register = MagicMock()
        adapter.model_unregister = MagicMock()
        return adapter

    async def test_reconnect_unregisters_deleted_models(self):
        adapter = self._adapter()
        self.coll.find.side_effect = _cursors(
            [{"_id": "d1", "id": "dynamic:a", "model": {}}],
            [{"_id": "d2", "id": "dynamic:b", "model": {}, "description": "b"}],
        )
        self.coll.watch.side_effect = _streams_with_reconnect()
        await adapter._load_initial_data()

        await self.run_watcher(adapter)

        adapter.model_unregister.assert_called_once_with("dynamic:a")
        adapter.model_register.assert_called_with("dynamic:b", {}, "b")
        self.assertEqual(adapter._doc_to_model_id, {"d2": "dynamic:b"})

    async def test_broken_model_does_not_block_the_others(self):
        adapter = self._adapter()
        adapter.model_register.side_effect = [ValueError("bad schema"), None]
        self.coll.find.side_effect = _cursors(
            [
                {"_id": "d1", "id": "dynamic:bad", "model": {}},
                {"_id": "d2", "id": "dynamic:good", "model": {}},
            ]
        )
        await adapter._load_initial_data()
        self.assertEqual(adapter.model_register.call_count, 2)

    async def test_delete_event_for_locally_removed_model_is_ignored(self):
        from pyhiera.errors import PyHieraError

        adapter = self._adapter()
        adapter.model_unregister.side_effect = PyHieraError("not found")
        adapter._doc_to_model_id["d1"] = "dynamic:a"

        await adapter._handle_change(
            {"operationType": "delete", "documentKey": {"_id": "d1"}}
        )

        adapter.model_unregister.assert_called_once_with("dynamic:a")
        self.assertEqual(adapter._doc_to_model_id, {})

    async def test_change_stream_delivers_the_model(self):
        adapter = self._adapter()
        self.coll.find.side_effect = _cursors([])
        self.coll.watch.side_effect = [_ChangeStream()]

        await self.run_watcher(adapter)

        projection = self.coll.watch.call_args.kwargs["pipeline"][0]["$project"]
        self.assertEqual(projection["fullDocument.model"], 1)
        self.assertEqual(projection["fullDocument.description"], 1)


if __name__ == "__main__":
    unittest.main()
