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

import httpx
from fastapi import FastAPI
from fastapi.responses import StreamingResponse

from pyppetdb.middleware import ProcessTimeMiddleware


class TestProcessTimeMiddleware(unittest.IsolatedAsyncioTestCase):
    def app(self):
        app = FastAPI()

        @app.get("/small")
        async def small():
            return {"ok": True}

        @app.get("/stream")
        async def stream():
            async def body():
                for chunk in (b"a", b"b", b"c"):
                    yield chunk

            return StreamingResponse(body())

        app.add_middleware(ProcessTimeMiddleware)
        return app

    async def test_every_response_carries_the_process_time(self):
        transport = httpx.ASGITransport(app=self.app())
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            small = await client.get("/small")
            streamed = await client.get("/stream")
        self.assertEqual(small.json(), {"ok": True})
        self.assertGreaterEqual(float(small.headers["x-process-time"]), 0)
        self.assertEqual(streamed.content, b"abc")
        self.assertGreaterEqual(float(streamed.headers["x-process-time"]), 0)
