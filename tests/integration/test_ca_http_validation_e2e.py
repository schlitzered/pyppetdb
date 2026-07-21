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

import json
import time
import uuid

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from pyppetdb.main import settings
from tests.integration.base import IntegrationTestBase
from tests.integration._dummy_http import CapturingServer


class CAHttpValidationE2ETests(IntegrationTestBase):
    def _auth_headers(self):
        return {"x-secret-id": "test-cred", "x-secret": "test-secret"}

    def _put_space_config(self, config):
        resp = self.client.put(
            "/api/v1/ca/spaces/puppet-ca",
            headers=self._auth_headers(),
            json={"validation_config": config},
        )
        self.assertEqual(resp.status_code, 200)

    def _wait_space_http_checks(self, present, timeout=20):
        deadline = time.time() + timeout
        while time.time() < deadline:
            resp = self.client.get(
                "/api/v1/ca/spaces/puppet-ca", headers=self._auth_headers()
            )
            cfg = resp.json().get("validation_config") or {}
            checks = (cfg.get("san_validation") or {}).get("http_checks")
            if bool(checks) == present:
                return
            time.sleep(0.25)
        self.fail(
            f"space validation_config did not propagate (present={present}) in time"
        )

    def _make_csr(self, cn, sans):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        builder = x509.CertificateSigningRequestBuilder().subject_name(
            x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
        )
        if sans:
            builder = builder.add_extension(
                x509.SubjectAlternativeName([x509.DNSName(s) for s in sans]),
                critical=False,
            )
        csr = builder.sign(key, hashes.SHA256())
        return csr.public_bytes(serialization.Encoding.PEM).decode()

    def _reset_space_and_secret(self, secret_id):
        self._put_space_config({})
        self._wait_space_http_checks(present=False)
        self.client.delete(
            f"/api/v1/ca/secrets/{secret_id}", headers=self._auth_headers()
        )

    def test_signing_fires_webhook_with_resolved_request(self):
        secret_id = f"E2E_{uuid.uuid4().hex}"
        nodename = f"node-{uuid.uuid4().hex}"

        with CapturingServer() as server:
            resp = self.client.post(
                f"/api/v1/ca/secrets/{secret_id}",
                headers=self._auth_headers(),
                json={"secret": "wire-secret"},
            )
            self.assertEqual(resp.status_code, 201)
            self.addCleanup(self._reset_space_and_secret, secret_id)

            self._put_space_config(
                {
                    "san_validation": {
                        "max_san_count": 10,
                        "http_checks": [
                            {
                                "url": f"http://127.0.0.1:{server.port}/validate",
                                "method": "POST",
                                "headers": [
                                    {
                                        "name": "Authorization",
                                        "value": f"Bearer $secrets[{secret_id}]",
                                    }
                                ],
                                "body_template": '{"node":"{{cn}}","sans":{{sans}}}',
                            }
                        ],
                    }
                }
            )
            self._wait_space_http_checks(present=True)

            settings.ca.autoSign = True
            self.addCleanup(setattr, settings.ca, "autoSign", False)

            csr_pem = self._make_csr(nodename, sans=[nodename])
            resp = self.client.put(
                f"/puppet-ca/v1/certificate_request/{nodename}",
                content=csr_pem,
                headers={"Content-Type": "text/plain"},
            )
            self.assertEqual(resp.status_code, 200)
            self.assertTrue(resp.text.startswith("-----BEGIN CERTIFICATE-----"))

            self.assertEqual(len(server.captured), 1)
            req = server.captured[0]
            self.assertEqual(req["method"], "POST")
            self.assertEqual(req["path"], "/validate")
            self.assertEqual(req["headers"]["Authorization"], "Bearer wire-secret")
            body = json.loads(req["body"])
            self.assertEqual(body["node"], nodename)
            self.assertEqual(body["sans"], [nodename])
