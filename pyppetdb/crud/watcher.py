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
import typing
from datetime import UTC
from datetime import datetime
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorCollection

WATCH_RETRY_DELAY = 5

STATE_STARTING = "starting"
STATE_SYNCING = "syncing"
STATE_READY = "ready"
STATE_ERROR = "error"

EVENT_READY = "ready"
EVENT_CHANGED = "changed"
EVENT_ERROR = "error"

WatcherListener = typing.Callable[["CollectionWatcher", str], None]


class CollectionWatcher:
    def __init__(
        self,
        coll: AsyncIOMotorCollection,
        log: logging.Logger,
        name: str,
        handle_change: typing.Callable[[dict], typing.Awaitable[None]],
        resync: typing.Callable[[], typing.Awaitable[None]],
        pipeline: Optional[list] = None,
    ):
        self._coll = coll
        self._log = log
        self._name = name
        self._handle_change = handle_change
        self._resync = resync
        self._pipeline = pipeline
        self._state = STATE_STARTING
        self._last_error: Optional[str] = None
        self._last_sync: Optional[datetime] = None
        self._lock = asyncio.Lock()
        self._listeners: list[WatcherListener] = []
        self._task: Optional[asyncio.Task] = None

    @property
    def name(self) -> str:
        return self._name

    @property
    def state(self) -> str:
        return self._state

    @property
    def ready(self) -> bool:
        return self._state == STATE_READY

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error

    @property
    def last_sync(self) -> Optional[datetime]:
        return self._last_sync

    def add_listener(self, listener: WatcherListener) -> None:
        self._listeners.append(listener)

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self.run())

    async def resync(self) -> None:
        async with self._lock:
            await self._resync()
            self._last_sync = datetime.now(UTC)

    async def run(self) -> None:
        while True:
            try:
                async with self._coll.watch(
                    full_document="updateLookup", pipeline=self._pipeline
                ) as change_stream:
                    self._state = STATE_SYNCING
                    await self.resync()
                    self._last_error = None
                    self._state = STATE_READY
                    self._log.info(f"Change stream watcher started for {self._name}")
                    self._emit(EVENT_READY)
                    async for change in change_stream:
                        async with self._lock:
                            await self._handle_change(change)
                        self._emit(EVENT_CHANGED)
                self._fail("change stream closed")
            except Exception as err:
                self._fail(str(err) or type(err).__name__)
            await asyncio.sleep(WATCH_RETRY_DELAY)

    def _fail(self, reason: str) -> None:
        self._log.error(f"Error in {self._name} change stream: {reason}")
        self._state = STATE_ERROR
        self._last_error = reason
        self._emit(EVENT_ERROR)

    def _emit(self, event: str) -> None:
        for listener in self._listeners:
            try:
                listener(self, event)
            except Exception as err:
                self._log.error(
                    f"Watcher listener failed for {self._name} on '{event}': {err}"
                )


class _Rule:
    def __init__(
        self,
        name: str,
        source: CollectionWatcher,
        events: tuple,
        reaction: typing.Callable[[], typing.Awaitable[None]],
    ):
        self.name = name
        self.source = source
        self.events = events
        self.reaction = reaction
        self.running = False
        self.dirty = False


class WatcherCoordinator:
    def __init__(self, log: logging.Logger):
        self._log = log
        self._watchers: dict[str, CollectionWatcher] = {}
        self._rules: list[_Rule] = []
        self._tasks: set[asyncio.Task] = set()

    @property
    def watchers(self) -> list[CollectionWatcher]:
        return list(self._watchers.values())

    def register(self, watcher: CollectionWatcher) -> CollectionWatcher:
        if watcher.name not in self._watchers:
            self._watchers[watcher.name] = watcher
            watcher.add_listener(self._on_event)
        return watcher

    def on(
        self,
        source: CollectionWatcher,
        events: tuple,
        reaction: typing.Callable[[], typing.Awaitable[None]],
        name: str,
    ) -> None:
        self.register(source)
        self._rules.append(
            _Rule(name=name, source=source, events=tuple(events), reaction=reaction)
        )

    def status(self) -> list[dict]:
        return [
            {
                "name": watcher.name,
                "state": watcher.state,
                "last_sync": watcher.last_sync,
                "last_error": watcher.last_error,
            }
            for watcher in self._watchers.values()
        ]

    def _on_event(self, watcher: CollectionWatcher, event: str) -> None:
        for rule in self._rules:
            if rule.source is watcher and event in rule.events:
                self._trigger(rule)

    def _trigger(self, rule: _Rule) -> None:
        if rule.running:
            rule.dirty = True
            return
        rule.running = True
        task = asyncio.create_task(self._run(rule))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _run(self, rule: _Rule) -> None:
        try:
            while True:
                rule.dirty = False
                try:
                    await rule.reaction()
                except Exception as err:
                    self._log.error(f"Watcher rule '{rule.name}' failed: {err}")
                if not rule.dirty:
                    break
        finally:
            rule.running = False
