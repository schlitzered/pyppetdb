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
import argparse
import signal
import socket
import os
import time
import logging
import ssl
import httpx
import statistics
import math
from collections import Counter
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("ca-benchmark")


class PuppetCABenchmark:
    def __init__(
        self, base_url, max_requests, concurrency, puppet_ssl_path, forever=False
    ):
        self.base_url = base_url.rstrip("/")
        self.max_requests = max_requests
        self.concurrency = concurrency
        self.puppet_ssl_path = puppet_ssl_path
        self.forever = forever
        self.running = True
        self.fqdn = socket.getfqdn()
        self.client_cert = None
        self.client_key = None
        self.ca_cert = None
        self._load_puppet_certs()

        self.requests_completed = 0
        self.actual_completions = 0
        self.submission_times = []
        self.revocation_times = []
        self.deletion_times = []
        self.response_codes = Counter()
        self.retries = 0
        self.start_time = None
        self.end_time = None

        self._stats_lock = asyncio.Lock()

    def _load_puppet_certs(self):
        cert_path = os.path.join(self.puppet_ssl_path, "certs", f"{self.fqdn}.pem")
        key_path = os.path.join(
            self.puppet_ssl_path, "private_keys", f"{self.fqdn}.pem"
        )
        ca_path = os.path.join(self.puppet_ssl_path, "certs", "ca.pem")

        if not os.path.exists(cert_path):
            logger.error(f"Puppet cert not found at {cert_path}")
            exit(1)
        if not os.path.exists(key_path):
            logger.error(f"Puppet key not found at {key_path}")
            exit(1)
        if not os.path.exists(ca_path):
            logger.error(f"CA cert not found at {ca_path}")
            exit(1)

        self.client_cert = cert_path
        self.client_key = key_path
        self.ca_cert = ca_path

    def generate_csr(self, cn):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        csr = (
            x509.CertificateSigningRequestBuilder()
            .subject_name(
                x509.Name(
                    [
                        x509.NameAttribute(NameOID.COMMON_NAME, cn),
                    ]
                )
            )
            .sign(key, hashes.SHA256())
        )

        csr_pem = csr.public_bytes(serialization.Encoding.PEM).decode()
        return csr_pem

    async def _safe_request(self, client, method, url, **kwargs):
        while self.running:
            try:
                start = time.perf_counter()
                resp = await client.request(method, url, **kwargs)
                latency = time.perf_counter() - start

                async with self._stats_lock:
                    self.response_codes[resp.status_code] += 1

                if resp.status_code < 400:
                    return resp, latency

                logger.warning(
                    f"Request failed with {resp.status_code}: {resp.text[:100]}. Retrying..."
                )
                async with self._stats_lock:
                    self.retries += 1
                await asyncio.sleep(1)
            except Exception as e:
                logger.warning(f"Request error: {e}. Retrying...")
                async with self._stats_lock:
                    self.retries += 1
                await asyncio.sleep(1)
        return None, 0

    async def benchmark_worker(self, worker_id, csr_pem, cn, client):
        logger.info(f"Worker {worker_id} started for {cn}")

        while self.running:
            async with self._stats_lock:
                if not self.forever and self.requests_completed >= self.max_requests:
                    break
                # Reserve a request slot
                self.requests_completed += 1

            # 1. Submit CSR
            resp, sub_latency = await self._safe_request(
                client,
                "PUT",
                f"{self.base_url}/puppet-ca/v1/certificate_request/{cn}",
                content=csr_pem,
                headers={"Content-Type": "text/plain"},
            )
            if not resp:
                break

            # 2. Wait for it to be signed
            # We poll GET /puppet-ca/v1/certificate/{cn}
            while self.running:
                check_resp, _ = await self._safe_request(
                    client, "GET", f"{self.base_url}/puppet-ca/v1/certificate/{cn}"
                )
                if check_resp and check_resp.status_code == 200:
                    break
                await asyncio.sleep(0.5)

            # 3. Revoke
            rev_resp, rev_latency = await self._safe_request(
                client,
                "PUT",
                f"{self.base_url}/puppet-ca/v1/certificate_status/{cn}",
                json={"desired_state": "revoked"},
            )
            if not rev_resp:
                break

            # 4. Delete
            del_resp, del_latency = await self._safe_request(
                client,
                "DELETE",
                f"{self.base_url}/puppet-ca/v1/certificate_status/{cn}",
            )
            if not del_resp:
                break

            async with self._stats_lock:
                self.submission_times.append(sub_latency)
                self.revocation_times.append(rev_latency)
                self.deletion_times.append(del_latency)
                self.actual_completions += 1

                if self.actual_completions >= self.max_requests:
                    self.end_time = time.perf_counter()
                    self.print_summary()

                    if self.forever:
                        # Reset for next batch
                        self.actual_completions = 0
                        self.requests_completed = 0
                        self.submission_times = []
                        self.revocation_times = []
                        self.deletion_times = []
                        self.response_codes = Counter()
                        self.retries = 0
                        self.start_time = time.perf_counter()

    async def run(self):
        logger.info(f"Pre-creating {self.concurrency} CSRs...")
        worker_configs = []
        for i in range(self.concurrency):
            cn = f"bench-worker-{i}-{int(time.time())}.example.com"
            csr_pem = self.generate_csr(cn)
            worker_configs.append((i, csr_pem, cn))

        ssl_context = ssl.create_default_context(cafile=self.ca_cert)
        ssl_context.load_cert_chain(certfile=self.client_cert, keyfile=self.client_key)

        logger.info("Starting benchmark...")
        self.start_time = time.perf_counter()

        async with httpx.AsyncClient(verify=ssl_context, timeout=60.0) as client:
            workers = [
                self.benchmark_worker(wid, csr, cn, client)
                for wid, csr, cn in worker_configs
            ]
            await asyncio.gather(*workers)

        self.end_time = time.perf_counter()
        self.print_summary()

    def print_summary(self):
        total_duration = self.end_time - self.start_time

        def get_stats(data):
            if not data:
                return "N/A"
            avg = sum(data) / len(data)
            p50 = statistics.median(data)
            p95 = statistics.quantiles(data, n=20)[18] if len(data) >= 20 else max(data)
            p99 = statistics.quantiles(data, n=100)[98] if len(data) >= 100 else max(data)
            return {
                "avg": avg * 1000,
                "min": min(data) * 1000,
                "max": max(data) * 1000,
                "p50": p50 * 1000,
                "p95": p95 * 1000,
                "p99": p99 * 1000,
            }

        sub_stats = get_stats(self.submission_times)
        rev_stats = get_stats(self.revocation_times)
        del_stats = get_stats(self.deletion_times)

        print("\n" + "=" * 60)
        print("PUPPET CA BENCHMARK SUMMARY")
        print("=" * 60)
        print(f"Total Requests:      {self.max_requests}")
        print(f"Concurrency:         {self.concurrency}")
        print(f"Total Duration:      {total_duration:.2f} seconds")
        print(f"Requests Per Second: {self.max_requests / total_duration:.2f}")
        print("-" * 60)
        print(f"{'Operation':<15} | {'Avg':>8} | {'Min':>8} | {'Max':>8} | {'P95':>8} | {'P99':>8}")
        print("-" * 60)

        for label, stats in [
            ("Submission", sub_stats),
            ("Revocation", rev_stats),
            ("Deletion", del_stats),
        ]:
            if isinstance(stats, str):
                print(f"{label:<15} | {'N/A':>39}")
            else:
                print(
                    f"{label:<15} | {stats['avg']:8.2f} | {stats['min']:8.2f} | {stats['max']:8.2f} | {stats['p95']:8.2f} | {stats['p99']:8.2f} ms"
                )

        print("-" * 60)
        print("HTTP Status Codes:")
        for code, count in sorted(self.response_codes.items()):
            print(f"  {code}: {count}")
        print("-" * 60)
        print(f"Total Retries:       {self.retries}")
        print("=" * 60 + "\n")

    def stop(self):
        self.running = False


async def main():
    parser = argparse.ArgumentParser(description="Puppet CA Benchmark Tool")
    parser.add_argument(
        "--url",
        required=True,
        help="Base URL of PyppetDB (e.g. https://localhost:8000)",
    )
    parser.add_argument(
        "--requests", type=int, default=100, help="Total number of requests to execute"
    )
    parser.add_argument(
        "--concurrency", type=int, default=10, help="Max parallel requests"
    )
    parser.add_argument("--forever", action="store_true", help="Run benchmark forever")
    parser.add_argument(
        "--ssl-path",
        default="/etc/puppetlabs/puppet/ssl",
        help="Path to Puppet SSL directory",
    )
    args = parser.parse_args()

    benchmark = PuppetCABenchmark(
        args.url, args.requests, args.concurrency, args.ssl_path, args.forever
    )

    loop = asyncio.get_running_loop()

    def signal_handler():
        logger.info("Received stop signal, shutting down...")
        benchmark.stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)

    try:
        await benchmark.run()
    except Exception as e:
        logger.error(f"Benchmark failed: {e}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
