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
import ssl
import statistics
import time
from typing import Optional

import httpx


class Target:
    def __init__(
        self,
        name: str,
        base_url: str,
        ca: Optional[str] = None,
        cert: Optional[str] = None,
        key: Optional[str] = None,
        timeout: float = 120.0,
        concurrency: int = 8,
    ):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.ca = ca
        self.cert = cert
        self.key = key
        self.timeout = timeout
        self.concurrency = concurrency
        self._client = None

    def _verify(self):
        if not self.base_url.startswith("https"):
            return None
        context = ssl.create_default_context(cafile=self.ca)
        if self.cert and self.key:
            context.load_cert_chain(certfile=self.cert, keyfile=self.key)
        return context

    async def __aenter__(self):
        verify = self._verify()
        limits = httpx.Limits(
            max_connections=self.concurrency * 2,
            max_keepalive_connections=self.concurrency * 2,
        )
        kwargs = {"timeout": self.timeout, "limits": limits}
        if verify is not None:
            kwargs["verify"] = verify
        self._client = httpx.AsyncClient(**kwargs)
        return self

    async def __aexit__(self, *exc):
        await self._client.aclose()
        self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("target is not open")
        return self._client

    def url(self, path: str) -> str:
        return f"{self.base_url}{path}"


class Timing:
    def __init__(self, name: str):
        self.name = name
        self.samples = []
        self.errors = 0
        self.rows = None
        self.status = None

    def add(self, seconds: float) -> None:
        self.samples.append(seconds * 1000.0)

    def summary(self) -> dict:
        if not self.samples:
            return {
                "name": self.name,
                "n": 0,
                "errors": self.errors,
                "rows": self.rows,
                "status": self.status,
            }
        ordered = sorted(self.samples)
        return {
            "name": self.name,
            "n": len(ordered),
            "errors": self.errors,
            "rows": self.rows,
            "status": self.status,
            "min": ordered[0],
            "p50": _percentile(ordered, 50),
            "p90": _percentile(ordered, 90),
            "p99": _percentile(ordered, 99),
            "max": ordered[-1],
            "mean": statistics.fmean(ordered),
        }


def _percentile(ordered: list, percentile: int) -> float:
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, int(round((percentile / 100.0) * len(ordered) + 0.5)) - 1)
    return ordered[index]


async def send_command(
    target: Target, certname: str, command: str, version: int, payload: dict
) -> httpx.Response:
    params = {
        "certname": certname,
        "command": command,
        "version": str(version),
        "producer-timestamp": payload.get("producer_timestamp", ""),
    }
    return await target.client.post(
        target.url("/pdb/cmd/v1"),
        params=params,
        json=payload,
        headers={"Content-Type": "application/json"},
    )


async def run_query(target: Target, spec: dict) -> httpx.Response:
    import json

    params = dict(spec.get("params") or {})
    if spec.get("ast") is not None:
        params["query"] = json.dumps(spec["ast"])
    return await target.client.get(target.url(spec["path"]), params=params)


async def measure(
    target: Target,
    spec: dict,
    iterations: int,
    concurrency: int,
    warmup: int = 2,
) -> Timing:
    timing = Timing(spec["name"])

    for _ in range(warmup):
        try:
            await run_query(target, spec)
        except Exception:
            pass

    semaphore = asyncio.Semaphore(concurrency)

    async def one():
        async with semaphore:
            started = time.perf_counter()
            try:
                response = await run_query(target, spec)
            except Exception:
                timing.errors += 1
                return
            elapsed = time.perf_counter() - started
            if response.status_code != 200:
                timing.errors += 1
                timing.status = response.status_code
                return
            timing.status = response.status_code
            if timing.rows is None:
                try:
                    body = response.json()
                    timing.rows = len(body) if isinstance(body, list) else 1
                except ValueError:
                    timing.rows = -1
            timing.add(elapsed)

    await asyncio.gather(*(one() for _ in range(iterations)))
    return timing


async def wait_for(target: Target, path: str, attempts: int = 120, delay: float = 2.0):
    for attempt in range(attempts):
        try:
            response = await target.client.get(target.url(path))
            if response.status_code == 200:
                return response
        except Exception:
            pass
        await asyncio.sleep(delay)
    raise RuntimeError(f"{target.name}: {path} did not become available")
