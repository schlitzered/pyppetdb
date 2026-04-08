import uuid
from pyppetdb.main import settings
from tests.integration.base import IntegrationTestBase
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


class PuppetCAIntegrationTests(IntegrationTestBase):
    def test_autosign_disabled(self):
        settings.ca.autoSign = False
        self.addCleanup(setattr, settings.ca, "autoSign", False)
        nodename = f"node-{uuid.uuid4().hex}"

        # 1. Generate CSR
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        csr = (
            x509.CertificateSigningRequestBuilder()
            .subject_name(
                x509.Name(
                    [
                        x509.NameAttribute(NameOID.COMMON_NAME, nodename),
                    ]
                )
            )
            .sign(key, hashes.SHA256())
        )
        csr_pem = csr.public_bytes(serialization.Encoding.PEM).decode()

        # 2. Submit CSR to puppet-ca
        resp = self.client.put(
            f"/puppet-ca/v1/certificate_request/{nodename}",
            content=csr_pem,
            headers={"Content-Type": "text/plain"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.text, "CSR submitted")

        # 3. Check status - should be 'requested'
        resp = self.client.get(f"/puppet-ca/v1/certificate_status/{nodename}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["state"], "requested")

    def test_autosign_enabled(self):
        settings.ca.autoSign = True
        self.addCleanup(setattr, settings.ca, "autoSign", False)
        nodename = f"node-{uuid.uuid4().hex}"

        # 1. Generate CSR
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        csr = (
            x509.CertificateSigningRequestBuilder()
            .subject_name(
                x509.Name(
                    [
                        x509.NameAttribute(NameOID.COMMON_NAME, nodename),
                    ]
                )
            )
            .sign(key, hashes.SHA256())
        )
        csr_pem = csr.public_bytes(serialization.Encoding.PEM).decode()

        # 2. Submit CSR to puppet-ca
        resp = self.client.put(
            f"/puppet-ca/v1/certificate_request/{nodename}",
            content=csr_pem,
            headers={"Content-Type": "text/plain"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.text, "CSR submitted")

        # 3. Check status - should be 'signed'
        resp = self.client.get(f"/puppet-ca/v1/certificate_status/{nodename}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["state"], "signed")

        # 4. Cleanup/Reset
        settings.ca.autoSign = False

    def test_csr_retry_deduplication(self):
        settings.ca.autoSign = False
        self.addCleanup(setattr, settings.ca, "autoSign", False)
        nodename = f"node-{uuid.uuid4().hex}"

        # 1. Generate CSR
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        csr = (
            x509.CertificateSigningRequestBuilder()
            .subject_name(
                x509.Name(
                    [
                        x509.NameAttribute(NameOID.COMMON_NAME, nodename),
                    ]
                )
            )
            .sign(key, hashes.SHA256())
        )
        csr_pem = csr.public_bytes(serialization.Encoding.PEM).decode()

        # 2. Submit CSR multiple times
        for _ in range(3):
            resp = self.client.put(
                f"/puppet-ca/v1/certificate_request/{nodename}",
                content=csr_pem,
                headers={"Content-Type": "text/plain"},
            )
            self.assertEqual(resp.status_code, 200)

        # 3. Count documents in DB - should be exactly 1
        count = self._db["ca_certificates"].count_documents(
            {"cn": nodename, "space_id": "puppet-ca"}
        )
        self.assertEqual(count, 1)

    def test_csr_ignored_if_signed(self):
        settings.ca.autoSign = True
        self.addCleanup(setattr, settings.ca, "autoSign", False)
        nodename = f"node-{uuid.uuid4().hex}"

        # 1. Generate first CSR
        key1 = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        csr1 = (
            x509.CertificateSigningRequestBuilder()
            .subject_name(
                x509.Name(
                    [
                        x509.NameAttribute(NameOID.COMMON_NAME, nodename),
                    ]
                )
            )
            .sign(key1, hashes.SHA256())
        )
        csr1_pem = csr1.public_bytes(serialization.Encoding.PEM).decode()

        # 2. Submit and auto-sign
        resp = self.client.put(
            f"/puppet-ca/v1/certificate_request/{nodename}",
            content=csr1_pem,
            headers={"Content-Type": "text/plain"},
        )
        self.assertEqual(resp.status_code, 200)

        # 3. Get first cert
        resp = self.client.get(f"/puppet-ca/v1/certificate/{nodename}")
        cert1_pem = resp.text

        # 4. Generate second CSR (different key)
        key2 = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        csr2 = (
            x509.CertificateSigningRequestBuilder()
            .subject_name(
                x509.Name(
                    [
                        x509.NameAttribute(NameOID.COMMON_NAME, nodename),
                    ]
                )
            )
            .sign(key2, hashes.SHA256())
        )
        csr2_pem = csr2.public_bytes(serialization.Encoding.PEM).decode()

        # 5. Submit second CSR - should be rejected with 400 Bad Request
        resp = self.client.put(
            f"/puppet-ca/v1/certificate_request/{nodename}",
            content=csr2_pem,
            headers={"Content-Type": "text/plain"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("A signed certificate already exists", resp.json()["detail"])

        # 6. Verify certificate is still the first one
        resp = self.client.get(f"/puppet-ca/v1/certificate/{nodename}")
        self.assertEqual(resp.text, cert1_pem)

        # 7. Cleanup
        settings.ca.autoSign = False

    def test_certificate_renewal(self):
        settings.ca.autoSign = True
        self.addCleanup(setattr, settings.ca, "autoSign", False)
        nodename = f"node-{uuid.uuid4().hex}"

        # 1. Create a signed certificate for the node
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        csr = (
            x509.CertificateSigningRequestBuilder()
            .subject_name(
                x509.Name(
                    [
                        x509.NameAttribute(NameOID.COMMON_NAME, nodename),
                    ]
                )
            )
            .sign(key, hashes.SHA256())
        )
        csr_pem = csr.public_bytes(serialization.Encoding.PEM).decode()

        self.client.put(
            f"/puppet-ca/v1/certificate_request/{nodename}",
            content=csr_pem,
            headers={"Content-Type": "text/plain"},
        )

        # Verify it exists and is signed
        resp = self.client.get(f"/puppet-ca/v1/certificate/{nodename}")
        self.assertEqual(resp.status_code, 200)
        old_cert_pem = resp.text
        old_cert = x509.load_pem_x509_certificate(old_cert_pem.encode())
        old_serial = str(old_cert.serial_number)

        # 2. Mock AuthorizeClientCert.get_cert_info to return this node's info
        from pyppetdb.authorize import AuthorizeClientCert
        from unittest.mock import patch, AsyncMock

        with patch.object(
            AuthorizeClientCert, "get_cert_info", new_callable=AsyncMock
        ) as mock_get_cert_info:
            mock_get_cert_info.return_value = {"cn": nodename, "serial": old_serial}

            # 3. Call renewal endpoint
            resp = self.client.post(
                "/puppet-ca/v1/certificate_renewal",
                headers={"Accept": "text/plain", "Content-Type": "text/plain"},
            )

            self.assertEqual(resp.status_code, 200)
            new_cert_pem = resp.text
            self.assertNotEqual(old_cert_pem, new_cert_pem)

            new_cert = x509.load_pem_x509_certificate(new_cert_pem.encode())
            self.assertEqual(new_cert.subject, old_cert.subject)
            self.assertNotEqual(new_cert.serial_number, old_cert.serial_number)

            # 4. Verify old cert is now revoked in DB
            old_cert_doc = self._db["ca_certificates"].find_one({"id": old_serial})
            self.assertEqual(old_cert_doc["status"], "revoked")

            # 5. Verify new cert is now the one returned by GET /certificate/{nodename}
            resp = self.client.get(f"/puppet-ca/v1/certificate/{nodename}")
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.text, new_cert_pem)

        # 6. Cleanup
        settings.ca.autoSign = False

    def test_autosign_node_if_exists_enabled_node_exists(self):
        settings.ca.autoSign = False
        self.addCleanup(setattr, settings.ca, "autoSign", False)
        settings.ca.autoSignNodeIfExists = True
        self.addCleanup(setattr, settings.ca, "autoSignNodeIfExists", False)
        nodename = f"node-{uuid.uuid4().hex}"

        # 0. Create node in DB
        self._db["nodes"].insert_one(
            {
                "id": nodename,
                "environment": "production",
                "disabled": False,
                "facts": {"os": "Linux", "hostname": nodename},
                "node_groups": [],
            }
        )

        # 1. Generate CSR
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        csr = (
            x509.CertificateSigningRequestBuilder()
            .subject_name(
                x509.Name(
                    [
                        x509.NameAttribute(NameOID.COMMON_NAME, nodename),
                    ]
                )
            )
            .sign(key, hashes.SHA256())
        )
        csr_pem = csr.public_bytes(serialization.Encoding.PEM).decode()

        # 2. Submit CSR to puppet-ca
        resp = self.client.put(
            f"/puppet-ca/v1/certificate_request/{nodename}",
            content=csr_pem,
            headers={"Content-Type": "text/plain"},
        )
        self.assertEqual(resp.status_code, 200)

        # 3. Check status - should be 'signed'
        resp = self.client.get(f"/puppet-ca/v1/certificate_status/{nodename}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["state"], "signed")

        # 4. Cleanup/Reset
        settings.ca.autoSignNodeIfExists = False

    def test_autosign_node_if_exists_enabled_node_not_exists(self):
        settings.ca.autoSign = False
        self.addCleanup(setattr, settings.ca, "autoSign", False)
        settings.ca.autoSignNodeIfExists = True
        self.addCleanup(setattr, settings.ca, "autoSignNodeIfExists", False)
        nodename = f"node-{uuid.uuid4().hex}"

        # 1. Generate CSR
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        csr = (
            x509.CertificateSigningRequestBuilder()
            .subject_name(
                x509.Name(
                    [
                        x509.NameAttribute(NameOID.COMMON_NAME, nodename),
                    ]
                )
            )
            .sign(key, hashes.SHA256())
        )
        csr_pem = csr.public_bytes(serialization.Encoding.PEM).decode()

        # 2. Submit CSR to puppet-ca
        resp = self.client.put(
            f"/puppet-ca/v1/certificate_request/{nodename}",
            content=csr_pem,
            headers={"Content-Type": "text/plain"},
        )
        self.assertEqual(resp.status_code, 200)

        # 3. Check status - should be 'requested'
        resp = self.client.get(f"/puppet-ca/v1/certificate_status/{nodename}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["state"], "requested")

        # 4. Cleanup/Reset
        settings.ca.autoSignNodeIfExists = False
