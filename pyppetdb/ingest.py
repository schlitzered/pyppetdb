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
import time
from typing import Awaitable
from typing import Callable
from typing import Optional
from typing import Sequence

DEFAULT_DRAIN_TIMEOUT = 30.0


class IngestQueue:
    def __init__(
        self,
        log: logging.Logger,
        size: int,
        workers: int,
        drain_timeout: float = DEFAULT_DRAIN_TIMEOUT,
    ):
        self._log = log
        self._size = max(1, size)
        self._workers = max(1, workers)
        self._drain_timeout = drain_timeout
        self._queue: Optional[asyncio.Queue] = None
        self._tasks: list = []
        self._stopping = False
        self._dropped = 0
        self._accepted = 0
        self._failed = 0
        self._waited = 0
        self._room: Optional[asyncio.Event] = None

    @property
    def log(self):
        return self._log

    @property
    def size(self) -> int:
        return self._size

    @property
    def workers(self) -> int:
        return self._workers

    @property
    def drain_timeout(self) -> float:
        return self._drain_timeout

    @property
    def depth(self) -> int:
        return self._queue.qsize() if self._queue else 0

    @property
    def stats(self) -> dict:
        return {
            "size": self._size,
            "workers": self._workers,
            "depth": self.depth,
            "accepted": self._accepted,
            "dropped": self._dropped,
            "failed": self._failed,
            "waited": self._waited,
        }

    def start(self) -> None:
        if self._queue is not None:
            return
        self._queue = asyncio.Queue(maxsize=self._size)
        self._room = asyncio.Event()
        for number in range(self._workers):
            self._tasks.append(
                asyncio.create_task(self._worker(number), name=f"ingest-{number}")
            )
        self.log.info(
            f"Ingest queue started: size={self._size} workers={self._workers}"
        )

    async def stop(self) -> None:
        self._stopping = True
        queue = self._queue
        if queue is not None and self._tasks:
            await self._drain(queue)
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._tasks = []
        self._queue = None

    async def _drain(self, queue: asyncio.Queue) -> None:
        self.log.info(f"Draining ingest queue: depth={queue.qsize()}")
        try:
            await asyncio.wait_for(queue.join(), timeout=self._drain_timeout)
        except asyncio.TimeoutError:
            self.log.error(
                f"Ingest queue drain timed out after {self._drain_timeout}s, "
                f"discarding {queue.qsize()} queued jobs"
            )

    def submit(self, job: Callable[[], Awaitable[None]]) -> bool:
        return self.submit_all([job])

    def submit_all(self, jobs: Sequence[Callable[[], Awaitable[None]]]) -> bool:
        if not jobs:
            return True
        if self._stopping:
            self._reject(count=len(jobs), reason="stopping")
            return False
        self.start()
        if self._queue.qsize() + len(jobs) > self._queue.maxsize:
            self._reject(count=len(jobs), reason=f"full (size={self._size})")
            return False
        for job in jobs:
            self._queue.put_nowait(job)
        self._accepted += len(jobs)
        return True

    async def enqueue(
        self,
        jobs: Sequence[Callable[[], Awaitable[None]]],
        wait_timeout: float = 0.0,
    ) -> bool:
        if not jobs:
            return True
        if wait_timeout <= 0:
            return self.submit_all(jobs)
        if self._stopping:
            self._reject(count=len(jobs), reason="stopping")
            return False
        self.start()
        deadline = time.monotonic() + wait_timeout
        waited = False
        while True:
            if self._stopping:
                self._reject(count=len(jobs), reason="stopping")
                return False
            self._room.clear()
            if self._queue.qsize() + len(jobs) <= self._queue.maxsize:
                for job in jobs:
                    self._queue.put_nowait(job)
                self._accepted += len(jobs)
                if waited:
                    self._waited += 1
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._reject(
                    count=len(jobs),
                    reason=f"full for {wait_timeout:g}s (size={self._size})",
                )
                return False
            waited = True
            try:
                await asyncio.wait_for(self._room.wait(), timeout=remaining)
            except asyncio.TimeoutError:
                continue

    def _reject(self, count: int, reason: str) -> None:
        previous = self._dropped
        self._dropped += count
        if previous == 0 or previous // 100 != self._dropped // 100:
            self.log.warning(
                f"Ingest queue {reason}, rejecting work; "
                f"{self._dropped} rejected so far"
            )

    async def _worker(self, number: int) -> None:
        while True:
            queue = self._queue
            job = await queue.get()
            if self._room is not None:
                self._room.set()
            try:
                await job()
            except asyncio.CancelledError:
                raise
            except Exception as err:
                self._failed += 1
                self.log.error(f"Ingest job failed: {err}")
            finally:
                queue.task_done()
