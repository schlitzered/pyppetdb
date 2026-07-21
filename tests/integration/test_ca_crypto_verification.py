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

import base64
import datetime
import textwrap
import uuid

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from tests.integration.base import IntegrationTestBase


class CACryptoVerificationTests(IntegrationTestBase):
    def _auth_headers(self):
        return {"x-secret-id": "test-cred", "x-secret": "test-secret"}

    def _csr_pem(self, cn):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        csr = (
            x509.CertificateSigningRequestBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)]))
            .sign(key, hashes.SHA256())
        )
        return csr.public_bytes(serialization.Encoding.PEM).decode()

    def _tampered_csr_pem(self, cn):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        csr = (
            x509.CertificateSigningRequestBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)]))
            .sign(key, hashes.SHA256())
        )
        der = bytearray(csr.public_bytes(serialization.Encoding.DER))
        der[-1] ^= 0xFF
        b64 = base64.b64encode(bytes(der)).decode()
        return (
            "-----BEGIN CERTIFICATE REQUEST-----\n"
            + "\n".join(textwrap.wrap(b64, 64))
            + "\n-----END CERTIFICATE REQUEST-----\n"
        )

    def _create_ca(self, cn="Crypto Test CA"):
        ca_id = f"ca-{uuid.uuid4().hex}"
        resp = self.client.post(
            f"/api/v1/ca/authorities/{ca_id}",
            headers=self._auth_headers(),
            json={"cn": cn},
        )
        self.assertEqual(resp.status_code, 201)
        self.addCleanup(self._db["ca_authorities"].delete_many, {"id": ca_id})
        return ca_id

    def _create_space(self, ca_id):
        space_id = f"space-{uuid.uuid4().hex}"
        resp = self.client.post(
            f"/api/v1/ca/spaces/{space_id}",
            headers=self._auth_headers(),
            json={"ca_id": ca_id},
        )
        self.assertEqual(resp.status_code, 201)
        self.addCleanup(self._db["ca_spaces"].delete_many, {"id": space_id})
        return space_id

    def _sign_cert(self, space_id, ca_id, cn):
        cert_id = str(uuid.uuid4().int)
        self._db["ca_certificates"].insert_one(
            {
                "id": cert_id,
                "space_id": space_id,
                "ca_id": ca_id,
                "cn": cn,
                "status": "requested",
                "csr": self._csr_pem(cn),
                "created": datetime.datetime.now(datetime.timezone.utc),
            }
        )
        self.addCleanup(
            self._db["ca_certificates"].delete_many, {"space_id": space_id, "cn": cn}
        )
        resp = self.client.put(
            f"/api/v1/ca/spaces/{space_id}/certs/{cert_id}",
            headers=self._auth_headers(),
            json={"status": "signed"},
        )
        self.assertEqual(resp.status_code, 200)
        return resp.json()

    def _ca_certificate(self, ca_id):
        resp = self.client.get(
            f"/api/v1/ca/authorities/{ca_id}", headers=self._auth_headers()
        )
        self.assertEqual(resp.status_code, 200)
        return resp.json()

    def test_invalid_csr_signature_is_rejected(self):
        nodename = f"node-{uuid.uuid4().hex}"
        resp = self.client.put(
            f"/puppet-ca/v1/certificate_request/{nodename}",
            content=self._tampered_csr_pem(nodename),
            headers={"Content-Type": "text/plain"},
        )
        self.assertEqual(resp.status_code, 400)
        status = self.client.get(
            f"/puppet-ca/v1/certificate_status/{nodename}"
        )
        self.assertEqual(status.status_code, 404)

    def test_csr_cn_mismatch_is_rejected(self):
        nodename = f"node-{uuid.uuid4().hex}"
        foreign_cn = f"foreign-{uuid.uuid4().hex}"
        resp = self.client.put(
            f"/puppet-ca/v1/certificate_request/{nodename}",
            content=self._csr_pem(foreign_cn),
            headers={"Content-Type": "text/plain"},
        )
        self.assertEqual(resp.status_code, 400)
        status = self.client.get(
            f"/puppet-ca/v1/certificate_status/{nodename}"
        )
        self.assertEqual(status.status_code, 404)

    def test_issued_certificate_is_signed_by_its_ca(self):
        ca_id = self._create_ca()
        space_id = self._create_space(ca_id)
        signed = self._sign_cert(space_id, ca_id, f"cn-{uuid.uuid4().hex}")

        issued = x509.load_pem_x509_certificate(signed["certificate"].encode())
        ca_cert = x509.load_pem_x509_certificate(
            self._ca_certificate(ca_id)["certificate"].encode()
        )
        issued.verify_directly_issued_by(ca_cert)

        foreign_ca = x509.load_pem_x509_certificate(
            self._ca_certificate(self._create_ca("Other CA"))["certificate"].encode()
        )
        with self.assertRaises(Exception):
            issued.verify_directly_issued_by(foreign_ca)

    def test_certificates_are_isolated_between_spaces(self):
        ca_id = self._create_ca()
        space_a = self._create_space(ca_id)
        space_b = self._create_space(ca_id)
        cn = f"shared-{uuid.uuid4().hex}"

        signed_a = self._sign_cert(space_a, ca_id, cn)
        signed_b = self._sign_cert(space_b, ca_id, cn)
        self.assertNotEqual(signed_a["id"], signed_b["id"])

        resp = self.client.get(
            f"/api/v1/ca/spaces/{space_b}/certs/{signed_a['id']}",
            headers=self._auth_headers(),
        )
        self.assertEqual(resp.status_code, 404)
