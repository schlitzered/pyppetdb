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
        nodename = f"node-{uuid.uuid4().hex}"
        
        # 1. Generate CSR
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        csr = x509.CertificateSigningRequestBuilder().subject_name(x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, nodename),
        ])).sign(key, hashes.SHA256())
        csr_pem = csr.public_bytes(serialization.Encoding.PEM).decode()

        # 2. Submit CSR to puppet-ca
        resp = self.client.put(
            f"/puppet-ca/v1/certificate_request/{nodename}",
            content=csr_pem,
            headers={"Content-Type": "text/plain"}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.text, "CSR submitted")

        # 3. Check status - should be 'requested'
        resp = self.client.get(f"/puppet-ca/v1/certificate_status/{nodename}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["state"], "requested")

    def test_autosign_enabled(self):
        settings.ca.autoSign = True
        nodename = f"node-{uuid.uuid4().hex}"
        
        # 1. Generate CSR
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        csr = x509.CertificateSigningRequestBuilder().subject_name(x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, nodename),
        ])).sign(key, hashes.SHA256())
        csr_pem = csr.public_bytes(serialization.Encoding.PEM).decode()

        # 2. Submit CSR to puppet-ca
        resp = self.client.put(
            f"/puppet-ca/v1/certificate_request/{nodename}",
            content=csr_pem,
            headers={"Content-Type": "text/plain"}
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
        nodename = f"node-{uuid.uuid4().hex}"
        
        # 1. Generate CSR
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        csr = x509.CertificateSigningRequestBuilder().subject_name(x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, nodename),
        ])).sign(key, hashes.SHA256())
        csr_pem = csr.public_bytes(serialization.Encoding.PEM).decode()

        # 2. Submit CSR multiple times
        for _ in range(3):
            resp = self.client.put(
                f"/puppet-ca/v1/certificate_request/{nodename}",
                content=csr_pem,
                headers={"Content-Type": "text/plain"}
            )
            self.assertEqual(resp.status_code, 200)

        # 3. Count documents in DB - should be exactly 1
        count = self._db["ca_certificates"].count_documents({"cn": nodename, "space_id": "puppet-ca"})
        self.assertEqual(count, 1)

    def test_csr_ignored_if_signed(self):
        settings.ca.autoSign = True
        nodename = f"node-{uuid.uuid4().hex}"
        
        # 1. Generate first CSR
        key1 = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        csr1 = x509.CertificateSigningRequestBuilder().subject_name(x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, nodename),
        ])).sign(key1, hashes.SHA256())
        csr1_pem = csr1.public_bytes(serialization.Encoding.PEM).decode()

        # 2. Submit and auto-sign
        resp = self.client.put(
            f"/puppet-ca/v1/certificate_request/{nodename}",
            content=csr1_pem,
            headers={"Content-Type": "text/plain"}
        )
        self.assertEqual(resp.status_code, 200)

        # 3. Get first cert
        resp = self.client.get(f"/puppet-ca/v1/certificate/{nodename}")
        cert1_pem = resp.text

        # 4. Generate second CSR (different key)
        key2 = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        csr2 = x509.CertificateSigningRequestBuilder().subject_name(x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, nodename),
        ])).sign(key2, hashes.SHA256())
        csr2_pem = csr2.public_bytes(serialization.Encoding.PEM).decode()

        # 5. Submit second CSR - should be ignored (return 200 but keep old cert)
        resp = self.client.put(
            f"/puppet-ca/v1/certificate_request/{nodename}",
            content=csr2_pem,
            headers={"Content-Type": "text/plain"}
        )
        self.assertEqual(resp.status_code, 200)

        # 6. Verify certificate is still the first one
        resp = self.client.get(f"/puppet-ca/v1/certificate/{nodename}")
        self.assertEqual(resp.text, cert1_pem)
        
        # 7. Cleanup
        settings.ca.autoSign = False
