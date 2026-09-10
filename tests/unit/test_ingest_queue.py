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

from pyppetdb.ingest import IngestQueue


class TestIngestQueue(unittest.IsolatedAsyncioTestCase):
    def queue(self, size=10, workers=2):
        return IngestQueue(log=logging.getLogger("test"), size=size, workers=workers)

    async def test_runs_submitted_jobs(self):
        queue = self.queue()
        done = asyncio.Event()

        async def job():
            done.set()

        self.assertTrue(queue.submit(job))
        await asyncio.wait_for(done.wait(), timeout=2)
        await queue.stop()

    async def test_preserves_order_with_one_worker(self):
        queue = self.queue(workers=1)
        seen = []

        def make(value):
            async def job():
                seen.append(value)
            return job

        for value in range(5):
            queue.submit(make(value))
        for _ in range(50):
            if len(seen) == 5:
                break
            await asyncio.sleep(0.02)
        self.assertEqual(seen, [0, 1, 2, 3, 4])
        await queue.stop()

    async def test_rejects_when_full(self):
        queue = self.queue(size=2, workers=1)
        release = asyncio.Event()

        async def blocking():
            await release.wait()

        self.assertTrue(queue.submit(blocking))
        await asyncio.sleep(0.05)
        self.assertTrue(queue.submit(blocking))
        self.assertTrue(queue.submit(blocking))
        self.assertFalse(queue.submit(blocking))
        self.assertEqual(queue.stats["dropped"], 1)
        release.set()
        await queue.stop()

    async def test_a_failing_job_does_not_kill_the_worker(self):
        queue = self.queue(workers=1)
        survived = asyncio.Event()

        async def boom():
            raise RuntimeError("nope")

        async def after():
            survived.set()

        queue.submit(boom)
        queue.submit(after)
        await asyncio.wait_for(survived.wait(), timeout=2)
        self.assertEqual(queue.stats["failed"], 1)
        await queue.stop()

    async def test_stats(self):
        queue = self.queue(size=7, workers=3)
        queue.start()
        stats = queue.stats
        self.assertEqual(stats["size"], 7)
        self.assertEqual(stats["workers"], 3)
        self.assertEqual(stats["depth"], 0)
        self.assertEqual(stats["accepted"], 0)
        await queue.stop()

    async def test_start_is_idempotent(self):
        queue = self.queue()
        queue.start()
        queue.start()
        self.assertEqual(len(queue._tasks), queue.workers)
        await queue.stop()

    async def test_stop_is_safe_without_start(self):
        await self.queue().stop()

    async def test_submit_all_is_atomic_when_the_queue_is_almost_full(self):
        queue = self.queue(size=2, workers=1)
        release = asyncio.Event()
        seen = []

        async def blocking():
            await release.wait()

        async def job():
            seen.append(True)

        self.assertTrue(queue.submit(blocking))
        await asyncio.sleep(0.05)
        self.assertTrue(queue.submit(blocking))

        self.assertFalse(queue.submit_all([job, job]))
        self.assertEqual(queue.stats["dropped"], 2)
        self.assertEqual(queue.depth, 1)

        release.set()
        await queue.stop()
        self.assertEqual(seen, [])

    async def test_submit_all_queues_every_job_in_order(self):
        queue = self.queue(workers=1)
        seen = []

        def make(value):
            async def job():
                seen.append(value)

            return job

        self.assertTrue(queue.submit_all([make(1), make(2)]))
        self.assertEqual(queue.stats["accepted"], 2)
        await queue.stop()
        self.assertEqual(seen, [1, 2])

    async def test_submit_all_with_no_jobs_is_a_noop(self):
        queue = self.queue()
        self.assertTrue(queue.submit_all([]))
        self.assertEqual(queue.stats["accepted"], 0)
        self.assertEqual(queue.depth, 0)

    async def test_stop_waits_for_queued_and_running_jobs(self):
        queue = self.queue(workers=1)
        started = asyncio.Event()
        seen = []

        async def slow():
            started.set()
            await asyncio.sleep(0.2)
            seen.append("slow")

        async def later():
            seen.append("later")

        queue.submit(slow)
        queue.submit(later)
        await asyncio.wait_for(started.wait(), timeout=2)
        await queue.stop()
        self.assertEqual(seen, ["slow", "later"])

    async def test_stop_gives_up_after_the_drain_timeout(self):
        queue = IngestQueue(
            log=logging.getLogger("test"),
            size=10,
            workers=1,
            drain_timeout=0.1,
        )
        hanging = asyncio.Event()

        async def hang():
            await hanging.wait()

        async def never():
            hanging.set()

        queue.submit(hang)
        queue.submit(never)
        with self.assertLogs("test", level="ERROR") as logs:
            await queue.stop()
        self.assertIn("drain timed out", "\n".join(logs.output))
        self.assertFalse(hanging.is_set())

    async def test_submit_after_stop_is_rejected(self):
        queue = self.queue()
        await queue.stop()

        async def job():
            raise AssertionError("must not run")

        self.assertFalse(queue.submit(job))
        self.assertFalse(queue.submit_all([job, job]))
        self.assertEqual(queue.stats["dropped"], 3)
        self.assertEqual(queue.stats["accepted"], 0)
        self.assertIsNone(queue._queue)

    async def test_drain_timeout_default(self):
        self.assertEqual(self.queue().drain_timeout, 30.0)

    async def test_minimum_bounds(self):
        queue = IngestQueue(log=logging.getLogger("test"), size=0, workers=0)
        self.assertEqual(queue.size, 1)
        self.assertEqual(queue.workers, 1)


if __name__ == "__main__":
    unittest.main()
