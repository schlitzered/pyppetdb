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

import time
import uuid
import datetime
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa


def micro_bench():
    print("=" * 50)
    print("PUPPET CA MICRO-BENCHMARK (RSA-4096)")
    print("=" * 50)

    # 1. Generate RSA-4096 Key
    start = time.perf_counter()
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=4096)
    duration_gen = time.perf_counter() - start
    print(f"1. Generate RSA-4096 Key:      {duration_gen*1000:8.2f} ms")

    # 2. Create self-signed CA
    start = time.perf_counter()
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Test CA")])
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(uuid.uuid4().int)
        .not_valid_before(datetime.datetime.now(datetime.timezone.utc))
        .not_valid_after(
            datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=365)
        )
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(private_key, hashes.SHA256())
    )
    ca_key_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    duration_ca = time.perf_counter() - start
    print(f"2. Create Self-Signed CA:      {duration_ca*1000:8.2f} ms")

    # 3. Load CA Key from PEM (This happens every request in the current implementation!)
    start = time.perf_counter()
    loaded_ca_key = serialization.load_pem_private_key(ca_key_pem, password=None)
    duration_load = time.perf_counter() - start
    print(f"3. Load CA Key from PEM:       {duration_load*1000:8.2f} ms")

    # 4. Generate a CSR (Simulate Client)
    csr_key = rsa.generate_private_key(public_exponent=65537, key_size=4096)
    csr = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test-node")]))
        .sign(csr_key, hashes.SHA256())
    )
    csr_pem = csr.public_bytes(serialization.Encoding.PEM)

    # 5. Sign the CSR
    start = time.perf_counter()
    csr_obj = x509.load_pem_x509_csr(csr_pem)
    cert = (
        x509.CertificateBuilder()
        .subject_name(csr_obj.subject)
        .issuer_name(ca_cert.subject)
        .public_key(csr_obj.public_key())
        .serial_number(uuid.uuid4().int)
        .not_valid_before(datetime.datetime.now(datetime.timezone.utc))
        .not_valid_after(
            datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=365)
        )
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(loaded_ca_key, hashes.SHA256())
    )
    _ = cert.public_bytes(serialization.Encoding.PEM)
    duration_sign = time.perf_counter() - start
    print(f"4. Sign CSR (Pure Math):       {duration_sign*1000:8.2f} ms")

    # 6. Calculate Fingerprints (MD5, SHA1, SHA256)
    start = time.perf_counter()
    _ = cert.fingerprint(hashes.SHA256()).hex()
    _ = cert.fingerprint(hashes.SHA1()).hex()
    _ = cert.fingerprint(hashes.MD5()).hex()
    duration_fp = time.perf_counter() - start
    print(f"5. Calculate 3 Fingerprints:   {duration_fp*1000:8.2f} ms")

    total_server_side = duration_load + duration_sign + duration_fp
    print("-" * 50)
    print(
        f"Total Server-Side Work:        {total_server_side*1000:8.2f} ms (estimated)"
    )
    print("=" * 50)


if __name__ == "__main__":
    micro_bench()
