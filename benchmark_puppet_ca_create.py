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
from collections import Counter
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("ca-create-bench")


class PuppetCACreateBenchmark:
    def __init__(self, base_url, max_certs, concurrency, puppet_ssl_path):
        self.base_url = base_url.rstrip("/")
        self.max_certs = max_certs
        self.concurrency = concurrency
        self.puppet_ssl_path = puppet_ssl_path
        self.running = True
        self.fqdn = socket.getfqdn()
        self.client_cert = None
        self.client_key = None
        self.ca_cert = None
        self._load_puppet_certs()

        self.certs_created = 0
        self.submission_times = []
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

    async def worker(self, client):
        while self.running:
            async with self._stats_lock:
                if self.certs_created >= self.max_certs:
                    break
                # Increment count
                self.certs_created += 1
                cert_idx = self.certs_created

            cn = f"stress-create-{cert_idx}-{int(time.time())}.example.com"
            csr_pem = self.generate_csr(cn)

            # Submit CSR
            resp, sub_latency = await self._safe_request(
                client,
                "PUT",
                f"{self.base_url}/puppet-ca/v1/certificate_request/{cn}",
                content=csr_pem,
                headers={"Content-Type": "text/plain"},
            )

            if resp:
                # Wait for it to be signed
                while self.running:
                    check_resp, _ = await self._safe_request(
                        client, "GET", f"{self.base_url}/puppet-ca/v1/certificate/{cn}"
                    )
                    if check_resp and check_resp.status_code == 200:
                        break
                    await asyncio.sleep(0.5)

                async with self._stats_lock:
                    self.submission_times.append(sub_latency)

    async def run(self):
        ssl_context = ssl.create_default_context(cafile=self.ca_cert)
        ssl_context.load_cert_chain(certfile=self.client_cert, keyfile=self.client_key)

        logger.info(f"Starting creation of {self.max_certs} certificates...")
        self.start_time = time.perf_counter()

        async with httpx.AsyncClient(verify=ssl_context, timeout=60.0) as client:
            workers = [self.worker(client) for _ in range(self.concurrency)]
            await asyncio.gather(*workers)

        self.end_time = time.perf_counter()
        self.print_summary()

    def print_summary(self):
        total_duration = self.end_time - self.start_time
        avg_sub = (
            sum(self.submission_times) / len(self.submission_times)
            if self.submission_times
            else 0
        )

        print("\n" + "=" * 40)
        print("PUPPET CA CREATE BENCHMARK SUMMARY")
        print("=" * 40)
        print(f"Total Certs:         {self.max_certs}")
        print(f"Concurrency:         {self.concurrency}")
        print(f"Total Duration:      {total_duration:.2f} seconds")
        print(f"Certs Per Second:    {len(self.submission_times) / total_duration:.2f}")
        print("-" * 40)
        print(f"Avg Submission Time: {avg_sub * 1000:.2f} ms")
        print("-" * 40)
        print("HTTP Status Codes:")
        for code, count in sorted(self.response_codes.items()):
            print(f"  {code}: {count}")
        print("-" * 40)
        print(f"Total Retries:       {self.retries}")
        print("=" * 40 + "\n")

    def stop(self):
        self.running = False


async def main():
    parser = argparse.ArgumentParser(description="Puppet CA Create Benchmark Tool")
    parser.add_argument(
        "--url",
        required=True,
        help="Base URL of PyppetDB (e.g. https://localhost:8000)",
    )
    parser.add_argument(
        "--certs", type=int, default=100, help="Total number of certificates to create"
    )
    parser.add_argument(
        "--concurrency", type=int, default=10, help="Max parallel requests"
    )
    parser.add_argument(
        "--ssl-path",
        default="/etc/puppetlabs/puppet/ssl",
        help="Path to Puppet SSL directory",
    )
    args = parser.parse_args()

    benchmark = PuppetCACreateBenchmark(
        args.url, args.certs, args.concurrency, args.ssl_path
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
