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
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

from pyppetdb.crud.ca_authorities import CrudCAAuthoritiesCache
from pyppetdb.crud.ca_certificates import CertRevocationWatcher
from pyppetdb.crud.ca_spaces import CrudCASpacesCache
from pyppetdb.crud.hiera_key_models_dynamic import CrudHieraModelsDynamicAdapter
from pyppetdb.crud.hiera_keys import CrudHieraKeysAdapter
from pyppetdb.crud.hiera_levels import CrudHieraLevelsCache
from pyppetdb.crud.nodes_groups import CrudNodesGroupsCache
from pyppetdb.crud.nodes_secrets_redactor import CrudNodesSecretsRedactorCache
from pyppetdb.crud.watcher import CollectionWatcher
from pyppetdb.crud.watcher import WatcherCoordinator


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
        sleep = patch("pyppetdb.crud.watcher.asyncio.sleep")
        sleep.start()
        self.addCleanup(sleep.stop)

    async def run_watcher(self, watcher):
        with self.assertRaises(asyncio.CancelledError):
            await watcher._watch_changes()


class TestCollectionWatcher(_WatcherTestCase):
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
            await CollectionWatcher(
                coll=self.coll,
                log=self.log,
                name="test",
                handle_change=handle_change,
                resync=resync,
            ).run()

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
            await CollectionWatcher(
                coll=self.coll,
                log=self.log,
                name="test",
                handle_change=handle_change,
                resync=resync,
            ).run()
        self.assertEqual(len(attempts), 2)

    async def test_passes_pipeline(self):
        async def noop(*args):
            pass

        pipeline = [{"$project": {"operationType": 1}}]
        self.coll.watch.side_effect = [_ChangeStream()]
        with self.assertRaises(asyncio.CancelledError):
            await CollectionWatcher(
                coll=self.coll,
                log=self.log,
                name="test",
                handle_change=noop,
                resync=noop,
                pipeline=pipeline,
            ).run()
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
        self.coll.find_one = AsyncMock(return_value=None)

        await adapter._handle_change(
            {"operationType": "delete", "documentKey": {"_id": "d1"}}
        )

        adapter.model_unregister.assert_called_once_with("dynamic:a")
        self.assertEqual(adapter._doc_to_model_id, {})

    async def test_stale_delete_event_keeps_recreated_model(self):
        adapter = self._adapter()
        adapter._doc_to_model_id["old"] = "dynamic:a"
        self.coll.find_one = AsyncMock(return_value={"_id": "new"})

        await adapter._handle_change(
            {"operationType": "delete", "documentKey": {"_id": "old"}}
        )

        adapter.model_unregister.assert_not_called()
        self.coll.find_one.assert_called_once_with({"id": "dynamic:a"}, {"_id": 1})
        self.assertEqual(adapter._doc_to_model_id, {})

    async def test_change_stream_delivers_the_model(self):
        adapter = self._adapter()
        self.coll.find.side_effect = _cursors([])
        self.coll.watch.side_effect = [_ChangeStream()]

        await self.run_watcher(adapter)

        projection = self.coll.watch.call_args.kwargs["pipeline"][0]["$project"]
        self.assertEqual(projection["fullDocument.model"], 1)
        self.assertEqual(projection["fullDocument.description"], 1)


class TestCollectionWatcherState(_WatcherTestCase):
    async def _noop(self, *args):
        pass

    def _watcher(self, handle_change=None, resync=None):
        return CollectionWatcher(
            coll=self.coll,
            log=self.log,
            name="test",
            handle_change=handle_change or self._noop,
            resync=resync or self._noop,
        )

    async def test_states_and_events_follow_the_stream(self):
        watcher = self._watcher()
        seen = []
        watcher.add_listener(
            lambda source, event: seen.append((event, source.state, source.last_error))
        )
        self.coll.watch.side_effect = [
            _ChangeStream([{"n": 1}], ends=True),
            _ChangeStream(error=RuntimeError("connection lost")),
            _ChangeStream(),
        ]
        self.assertEqual(watcher.state, "starting")
        self.assertFalse(watcher.ready)

        with self.assertRaises(asyncio.CancelledError):
            await watcher.run()

        self.assertEqual(
            seen,
            [
                ("ready", "ready", None),
                ("changed", "ready", None),
                ("error", "error", "change stream closed"),
                ("error", "error", "connection lost"),
                ("ready", "ready", None),
            ],
        )
        self.assertTrue(watcher.ready)
        self.assertIsNotNone(watcher.last_sync)

    async def test_a_failed_resync_is_an_error_state(self):
        async def resync():
            raise RuntimeError("find failed")

        watcher = self._watcher(resync=resync)
        self.coll.watch.side_effect = [_ChangeStream(), asyncio.CancelledError()]

        with self.assertRaises(asyncio.CancelledError):
            await watcher.run()

        self.assertEqual(watcher.state, "error")
        self.assertEqual(watcher.last_error, "find failed")
        self.assertIsNone(watcher.last_sync)

    async def test_a_failing_listener_does_not_stop_the_watcher(self):
        watcher = self._watcher()
        seen = []

        def boom(source, event):
            raise RuntimeError("listener down")

        watcher.add_listener(boom)
        watcher.add_listener(lambda source, event: seen.append(event))
        self.coll.watch.side_effect = [_ChangeStream([{"n": 1}])]

        with self.assertRaises(asyncio.CancelledError):
            await watcher.run()

        self.assertEqual(seen, ["ready", "changed"])

    async def test_external_resync_waits_for_the_running_change(self):
        order = []
        release = asyncio.Event()
        handling = asyncio.Event()

        async def handle_change(change):
            order.append("change start")
            handling.set()
            await release.wait()
            order.append("change end")

        async def resync():
            order.append("resync")

        watcher = self._watcher(handle_change=handle_change, resync=resync)
        self.coll.watch.side_effect = [_ChangeStream([{"n": 1}])]
        run = asyncio.create_task(watcher.run())
        await handling.wait()
        external = asyncio.create_task(watcher.resync())
        for _ in range(5):
            await asyncio.wait({external}, timeout=0)
        self.assertEqual(order, ["resync", "change start"])

        release.set()
        await external
        with self.assertRaises(asyncio.CancelledError):
            await run
        self.assertEqual(order, ["resync", "change start", "change end", "resync"])

    async def test_start_creates_one_task(self):
        watcher = self._watcher()
        self.coll.watch.side_effect = [_ChangeStream()]
        watcher.start()
        task = watcher._task
        watcher.start()
        self.assertIs(watcher._task, task)
        with self.assertRaises(asyncio.CancelledError):
            await task


class TestWatcherCoordinator(_WatcherTestCase):
    def _watcher(self, name="source"):
        async def noop(*args):
            pass

        return CollectionWatcher(
            coll=self.coll, log=self.log, name=name, handle_change=noop, resync=noop
        )

    async def _settle(self, coordinator):
        while coordinator._tasks:
            await asyncio.gather(*list(coordinator._tasks))

    async def test_rules_react_to_their_events_only(self):
        coordinator = WatcherCoordinator(log=self.log)
        source, other = self._watcher(), self._watcher("other")
        reaction = AsyncMock()
        coordinator.on(source, ("ready", "changed"), reaction, name="rule")
        coordinator.register(other)

        other._emit("ready")
        source._emit("error")
        await self._settle(coordinator)
        reaction.assert_not_awaited()

        source._emit("ready")
        await self._settle(coordinator)
        reaction.assert_awaited_once()

    async def test_triggers_during_a_running_reaction_collapse_into_one_more_run(self):
        coordinator = WatcherCoordinator(log=self.log)
        source = self._watcher()
        release = asyncio.Event()
        runs = []

        async def reaction():
            runs.append(1)
            await release.wait()

        coordinator.on(source, ("changed",), reaction, name="rule")
        source._emit("changed")
        await asyncio.wait(set(coordinator._tasks), timeout=0)
        for _ in range(3):
            source._emit("changed")
        self.assertEqual(len(coordinator._tasks), 1)

        release.set()
        await self._settle(coordinator)
        self.assertEqual(len(runs), 2)

    async def test_a_failing_reaction_is_logged_and_the_rule_stays_usable(self):
        coordinator = WatcherCoordinator(log=self.log)
        source = self._watcher()
        reaction = AsyncMock(side_effect=[RuntimeError("boom"), None])
        coordinator.on(source, ("ready",), reaction, name="rule")

        source._emit("ready")
        await self._settle(coordinator)
        source._emit("ready")
        await self._settle(coordinator)

        self.assertEqual(reaction.await_count, 2)

    async def test_status_lists_every_registered_watcher(self):
        coordinator = WatcherCoordinator(log=self.log)
        source = coordinator.register(self._watcher())
        coordinator.register(source)
        coordinator.register(self._watcher("other"))
        source._fail("connection lost")

        self.assertEqual(
            coordinator.status(),
            [
                {"name": "source", "state": "error", "last_sync": None, "last_error": "connection lost"},
                {"name": "other", "state": "starting", "last_sync": None, "last_error": None},
            ],
        )


class _Collection:
    def __init__(self):
        self.docs = []
        self.streams = []

    def find(self, *args, **kwargs):
        return _Cursor(self.docs)

    def watch(self, **kwargs):
        return self.streams.pop(0)


class TestHieraKeysFollowKeyModels(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        from types import SimpleNamespace

        from pyhiera.hiera import PyHieraAsync

        sleep = patch("pyppetdb.crud.watcher.asyncio.sleep")
        sleep.start()
        self.addCleanup(sleep.stop)
        logging.disable(logging.CRITICAL)
        self.addCleanup(logging.disable, logging.NOTSET)
        self.hiera = PyHieraAsync()
        pyhiera = SimpleNamespace(hiera=self.hiera)
        self.models_coll = _Collection()
        self.keys_coll = _Collection()
        log = logging.getLogger("test")
        self.models = CrudHieraModelsDynamicAdapter(log, self.models_coll, pyhiera)
        self.keys = CrudHieraKeysAdapter(log, self.keys_coll, pyhiera)
        self.coordinator = WatcherCoordinator(log=log)
        self.coordinator.register(self.keys.watcher)
        self.coordinator.on(
            source=self.models.watcher,
            events=("ready", "changed"),
            reaction=self.keys.watcher.resync,
            name="reload hiera keys after key model changes",
        )

    def _model(self, kind):
        return {
            "title": "Model",
            "type": "object",
            "required": ["data"],
            "properties": {"data": {"type": kind}},
        }

    async def _run(self, watcher):
        with self.assertRaises(asyncio.CancelledError):
            await watcher.run()
        while self.coordinator._tasks:
            await asyncio.gather(*list(self.coordinator._tasks))

    def _bound_to_current_model(self):
        return type(self.hiera._keys._keys["my::key"]) is self.hiera.key_models["dyn"]

    async def test_key_created_with_its_model_survives_keys_resyncing_first(self):
        self.models_coll.docs.append(
            {"_id": 1, "id": "dyn", "description": "d", "model": self._model("string")}
        )
        self.keys_coll.docs.append({"_id": 2, "id": "my::key", "key_model_id": "dyn"})
        self.keys_coll.streams.append(_ChangeStream())
        self.models_coll.streams.append(_ChangeStream())

        await self._run(self.keys.watcher)
        self.assertNotIn("my::key", self.hiera._keys._keys)

        await self._run(self.models.watcher)
        self.assertIn("my::key", self.hiera._keys._keys)

    async def test_a_changed_model_rebinds_its_keys(self):
        document = {"_id": 1, "id": "dyn", "description": "d", "model": self._model("string")}
        self.models_coll.docs.append(document)
        self.keys_coll.docs.append({"_id": 2, "id": "my::key", "key_model_id": "dyn"})
        await self.models.watcher.resync()
        await self.keys.watcher.resync()
        self.assertTrue(self._bound_to_current_model())

        changed = dict(document, model=self._model("integer"))
        self.models_coll.docs[0] = changed
        self.models_coll.streams.append(
            _ChangeStream(
                [
                    {
                        "operationType": "update",
                        "documentKey": {"_id": 1},
                        "fullDocument": changed,
                    }
                ]
            )
        )

        await self._run(self.models.watcher)

        self.assertTrue(self._bound_to_current_model())


if __name__ == "__main__":
    unittest.main()
