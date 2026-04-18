import asyncio
import argparse
import signal
import socket
import os
import random
import string
import logging
import ssl
import httpx
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("stress-test")


class PuppetCAStressTest:
    def __init__(self, base_url, parallel, puppet_ssl_path):
        self.base_url = base_url.rstrip("/")
        self.parallel = parallel
        self.puppet_ssl_path = puppet_ssl_path
        self.running = True
        self.active_certs = set()
        self.fqdn = socket.getfqdn()
        self.client_cert = None
        self.client_key = None
        self.ca_cert = None
        self._load_puppet_certs()
        self.client = None
        self._lock = asyncio.Lock()

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

    async def stress_worker(self, worker_id):
        logger.info(f"Worker {worker_id} started")

        while self.running:
            random_part = "".join(
                random.choices(string.ascii_lowercase + string.digits, k=10)
            )
            cn = f"stress-test-{random_part}.example.com"

            try:
                # 1. Submit CSR
                logger.info(f"Worker {worker_id}: Submitting CSR for {cn}")
                csr_pem = self.generate_csr(cn)
                resp = await self.client.put(
                    f"{self.base_url}/puppet-ca/v1/certificate_request/{cn}",
                    content=csr_pem,
                    headers={"Content-Type": "text/plain"},
                )
                if resp.status_code not in (200, 201, 204):
                    logger.error(
                        f"Worker {worker_id}: Failed to submit CSR for {cn}: {resp.status_code} {resp.text}"
                    )
                    await asyncio.sleep(1)
                    continue

                async with self._lock:
                    self.active_certs.add(cn)

                # 2. Revoke immediately
                logger.info(f"Worker {worker_id}: Revoking {cn} immediately")
                resp = await self.client.put(
                    f"{self.base_url}/puppet-ca/v1/certificate_status/{cn}",
                    json={"desired_state": "revoked"},
                )
                if resp.status_code not in (200, 204):
                    logger.error(
                        f"Worker {worker_id}: Failed to revoke {cn}: {resp.status_code} {resp.text}"
                    )
                else:
                    logger.info(f"Worker {worker_id}: Successfully revoked {cn}")
                    async with self._lock:
                        self.active_certs.discard(cn)

                await asyncio.sleep(0.01)

            except Exception as e:
                logger.error(f"Worker {worker_id}: Unexpected error: {e}")
                await asyncio.sleep(1)

    async def run(self):
        ssl_context = ssl.create_default_context(cafile=self.ca_cert)
        ssl_context.load_cert_chain(certfile=self.client_cert, keyfile=self.client_key)

        async with httpx.AsyncClient(verify=ssl_context, timeout=60.0) as client:
            self.client = client
            workers = [self.stress_worker(i) for i in range(self.parallel)]
            await asyncio.gather(*workers)
            await self.cleanup()

    async def cleanup(self):
        async with self._lock:
            if not self.active_certs:
                return
            logger.info(
                f"Cleaning up {len(self.active_certs)} remaining active certificates..."
            )

            for cn in list(self.active_certs):
                try:
                    logger.info(f"Cleanup: Revoking {cn}")
                    resp = await self.client.put(
                        f"{self.base_url}/puppet-ca/v1/certificate_status/{cn}",
                        json={"desired_state": "revoked"},
                    )
                    if resp.status_code in (200, 204):
                        logger.info(f"Cleanup: Successfully revoked {cn}")
                        self.active_certs.discard(cn)
                    else:
                        logger.error(
                            f"Cleanup: Failed to revoke {cn}: {resp.status_code}"
                        )
                except Exception as e:
                    logger.error(f"Cleanup: Error revoking {cn}: {e}")

    def stop(self):
        self.running = False


async def main():
    parser = argparse.ArgumentParser(description="Puppet CA Stress Test")
    parser.add_argument(
        "--url",
        required=True,
        help="Base URL of PyppetDB (e.g. https://localhost:8000)",
    )
    parser.add_argument(
        "--parallel", type=int, default=5, help="Number of parallel workers"
    )
    parser.add_argument(
        "--ssl-path",
        default="/etc/puppetlabs/puppet/ssl",
        help="Path to Puppet SSL directory",
    )
    args = parser.parse_args()

    stress_test = PuppetCAStressTest(args.url, args.parallel, args.ssl_path)

    loop = asyncio.get_running_loop()

    def signal_handler():
        logger.info("Received stop signal, shutting down...")
        stress_test.stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)

    await stress_test.run()
    logger.info("Stress test finished")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
