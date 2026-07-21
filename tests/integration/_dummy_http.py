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

import datetime
import http.server
import ipaddress
import os
import ssl
import tempfile
import threading

from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa


class _CaptureHandler(http.server.BaseHTTPRequestHandler):
    def _capture(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        peercert = None
        if isinstance(self.connection, ssl.SSLSocket):
            try:
                peercert = self.connection.getpeercert()
            except Exception:
                peercert = None
        self.server.captured.append(
            {
                "method": self.command,
                "path": self.path,
                "headers": {k: v for k, v in self.headers.items()},
                "body": body,
                "peercert": peercert,
            }
        )
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    do_GET = _capture
    do_POST = _capture
    do_PUT = _capture

    def log_message(self, *args):
        pass


class CapturingServer:
    def __init__(self, tls_ctx=None):
        self._server = http.server.ThreadingHTTPServer(
            ("127.0.0.1", 0), _CaptureHandler
        )
        self._server.captured = []
        if tls_ctx is not None:
            self._server.socket = tls_ctx.wrap_socket(
                self._server.socket, server_side=True
            )
        self._thread = threading.Thread(
            target=self._server.serve_forever, daemon=True
        )

    @property
    def port(self):
        return self._server.server_address[1]

    @property
    def captured(self):
        return self._server.captured

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._server.shutdown()
        self._server.server_close()
        return False


def self_signed_cert(cn, san_dns=None, san_ip=None):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    now = datetime.datetime.now(datetime.timezone.utc)
    builder = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=1))
    )
    sans = []
    if san_dns:
        sans.append(x509.DNSName(san_dns))
    if san_ip:
        sans.append(x509.IPAddress(ipaddress.ip_address(san_ip)))
    if sans:
        builder = builder.add_extension(
            x509.SubjectAlternativeName(sans), critical=False
        )
    cert = builder.sign(key, hashes.SHA256())
    cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode()
    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    ).decode()
    return cert_pem, key_pem


def server_tls_context(server_cert_pem, server_key_pem, client_ca_pem=None):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    cert_fd, cert_path = tempfile.mkstemp(suffix=".pem")
    key_fd, key_path = tempfile.mkstemp(suffix=".pem")
    try:
        with os.fdopen(cert_fd, "wb") as fh:
            fh.write(server_cert_pem.encode())
        with os.fdopen(key_fd, "wb") as fh:
            fh.write(server_key_pem.encode())
        ctx.load_cert_chain(certfile=cert_path, keyfile=key_path)
    finally:
        for path in (cert_path, key_path):
            try:
                os.unlink(path)
            except OSError:
                pass
    if client_ca_pem:
        ctx.verify_mode = ssl.CERT_REQUIRED
        ctx.load_verify_locations(cadata=client_ca_pem)
    return ctx
