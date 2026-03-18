import uuid
from tests.integration.base import IntegrationTestBase

class ApiV1CAIntegrationTests(IntegrationTestBase):
    def _auth_headers(self):
        return {"x-secret-id": "test-cred", "x-secret": "test-secret"}

    def test_ca_lifecycle(self):
        ca_id = f"ca-{uuid.uuid4().hex}"
        sub_ca_id = f"subca-{uuid.uuid4().hex}"
        space_id = f"space-{uuid.uuid4().hex}"
        cert_id = f"cert-{uuid.uuid4().hex}"

        # 1. Create Root CA
        resp = self.client.post(
            f"/api/v1/ca/authorities/{ca_id}",
            headers=self._auth_headers(),
            json={
                "common_name": "Root CA",
                "organization": "Test Org"
            }
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["id"], ca_id)
        self.assertEqual(resp.json()["internal"], True)
        self.assertEqual(resp.json()["chain"], [])
        root_cert = resp.json()["certificate"]
        
        # Verify fingerprint structure
        fingerprint = resp.json()["fingerprint"]
        self.assertIn("sha256", fingerprint)
        self.assertIn("sha1", fingerprint)
        self.assertIn("md5", fingerprint)
        self.assertTrue(all(isinstance(v, str) for v in fingerprint.values()))

        # 2. Create Subordinate CA (signed by root)
        resp = self.client.post(
            f"/api/v1/ca/authorities/{sub_ca_id}",
            headers=self._auth_headers(),
            json={
                "parent_id": ca_id,
                "common_name": "Sub CA"
            }
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["internal"], True)
        self.assertEqual(resp.json()["chain"], [root_cert])

        # 3. Create Space using Root CA
        resp = self.client.post(
            f"/api/v1/ca/spaces/{space_id}",
            headers=self._auth_headers(),
            json={
                "authority_id": ca_id
            }
        )
        self.assertEqual(resp.status_code, 200)

        # 4. Try to delete Root CA (should fail: in use by space)
        resp = self.client.delete(
            f"/api/v1/ca/authorities/{ca_id}",
            headers=self._auth_headers()
        )
        self.assertEqual(resp.status_code, 422)
        self.assertIn("still in use by one or more spaces", resp.json()["detail"])

        # 5. Try to delete Root CA (should fail: is parent of sub CA)
        # Delete Space first
        resp = self.client.delete(
            f"/api/v1/ca/spaces/{space_id}",
            headers=self._auth_headers()
        )
        self.assertEqual(resp.status_code, 200)

        # Now try to delete Root CA again (should fail: is parent)
        resp = self.client.delete(
            f"/api/v1/ca/authorities/{ca_id}",
            headers=self._auth_headers()
        )
        self.assertEqual(resp.status_code, 422)
        self.assertIn("still a parent of one or more CA Authorities", resp.json()["detail"])

        # 6. Delete Sub CA
        resp = self.client.delete(
            f"/api/v1/ca/authorities/{sub_ca_id}",
            headers=self._auth_headers()
        )
        self.assertEqual(resp.status_code, 200)

        # 7. Re-create Space and Certificate to test space deletion logic
        resp = self.client.post(
            f"/api/v1/ca/spaces/{space_id}",
            headers=self._auth_headers(),
            json={"authority_id": ca_id}
        )
        self.assertEqual(resp.status_code, 200)
        
        # Insert directly into DB for space deletion test
        self._db["ca_certificates"].insert_one({
            "id": cert_id,
            "space_id": space_id,
            "status": "requested",
            "csr": "DUMMY CSR"
        })

        # 8. Try to delete Space (should fail: has certificates)
        resp = self.client.delete(
            f"/api/v1/ca/spaces/{space_id}",
            headers=self._auth_headers()
        )
        self.assertEqual(resp.status_code, 422)
        self.assertIn("still contains certificates", resp.json()["detail"])

        # 9. Delete Certificate
        resp = self.client.delete(
            f"/api/v1/ca/spaces/{space_id}/certs/{cert_id}",
            headers=self._auth_headers()
        )
        self.assertEqual(resp.status_code, 200)

        # 10. Delete Space
        resp = self.client.delete(
            f"/api/v1/ca/spaces/{space_id}",
            headers=self._auth_headers()
        )
        self.assertEqual(resp.status_code, 200)

        # 11. Delete Root CA
        resp = self.client.delete(
            f"/api/v1/ca/authorities/{ca_id}",
            headers=self._auth_headers()
        )
        self.assertEqual(resp.status_code, 200)

    def test_external_ca_upload(self):
        from pyppetdb.ca.utils import CAUtils
        cert_pem, key_pem = CAUtils.generate_ca(common_name="External CA")
        ca_id = f"external-ca-{uuid.uuid4().hex}"
        external_chain = ["DUMMY CHAIN CERT 1", "DUMMY CHAIN CERT 2"]

        resp = self.client.post(
            f"/api/v1/ca/authorities/{ca_id}",
            headers=self._auth_headers(),
            json={
                "certificate": cert_pem.decode(),
                "private_key": key_pem.decode(),
                "external_chain": external_chain
            }
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["id"], ca_id)
        self.assertEqual(resp.json()["internal"], False)
        self.assertEqual(resp.json()["chain"], external_chain)

        # Cleanup
        self.client.delete(f"/api/v1/ca/authorities/{ca_id}", headers=self._auth_headers())

    def test_crl_chain(self):
        root_ca_id = f"root-{uuid.uuid4().hex}"
        sub_ca_id = f"sub-{uuid.uuid4().hex}"
        space_id = f"space-{uuid.uuid4().hex}"
        cert_id = "test-node-cert"

        # 1. Setup Hierarchy
        self.client.post(f"/api/v1/ca/authorities/{root_ca_id}", headers=self._auth_headers(), json={"common_name": "Root"})
        self.client.post(f"/api/v1/ca/authorities/{sub_ca_id}", headers=self._auth_headers(), json={"parent_id": root_ca_id, "common_name": "Sub"})
        self.client.post(f"/api/v1/ca/spaces/{space_id}", headers=self._auth_headers(), json={"authority_id": sub_ca_id})

        # 2. Revoke Sub CA
        self.client.put(f"/api/v1/ca/authorities/{sub_ca_id}", headers=self._auth_headers(), json={"status": "revoked"})

        # 3. Create and Revoke a Certificate in the space
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
        
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        csr = x509.CertificateSigningRequestBuilder().subject_name(x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, cert_id),
        ])).sign(key, hashes.SHA256())
        csr_pem = csr.public_bytes(serialization.Encoding.PEM).decode()

        self._db["ca_certificates"].insert_one({
            "id": cert_id,
            "space_id": space_id,
            "status": "requested",
            "csr": csr_pem
        })
        
        self.client.put(f"/api/v1/ca/spaces/{space_id}/certs/{cert_id}", headers=self._auth_headers(), json={"status": "signed"})
        self.client.put(f"/api/v1/ca/spaces/{space_id}/certs/{cert_id}", headers=self._auth_headers(), json={"status": "revoked"})

        # 4. Get CRL
        resp = self.client.get(f"/api/v1/ca/spaces/{space_id}/crl", headers=self._auth_headers())
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"BEGIN X509 CRL", resp.content)

    def test_authority_history(self):
        root1_id = f"root1-{uuid.uuid4().hex}"
        root2_id = f"root2-{uuid.uuid4().hex}"
        space_id = f"space-{uuid.uuid4().hex}"

        # 1. Create Space with root1
        self.client.post(f"/api/v1/ca/authorities/{root1_id}", headers=self._auth_headers(), json={"common_name": "Root1"})
        self.client.post(f"/api/v1/ca/spaces/{space_id}", headers=self._auth_headers(), json={"authority_id": root1_id})

        # 2. Update Space to use root2
        self.client.post(f"/api/v1/ca/authorities/{root2_id}", headers=self._auth_headers(), json={"common_name": "Root2"})
        resp = self.client.put(f"/api/v1/ca/spaces/{space_id}", headers=self._auth_headers(), json={"authority_id": root2_id})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["authority_id"], root2_id)
        self.assertEqual(resp.json()["authority_id_history"], [root1_id])

        # 3. Get CRL - should contain CRLs for both root1 and root2
        resp = self.client.get(f"/api/v1/ca/spaces/{space_id}/crl", headers=self._auth_headers())
        self.assertEqual(resp.status_code, 200)

    def test_authority_certs_and_crl(self):
        ca_id = f"ca-certs-test-{uuid.uuid4().hex}"
        space_id = f"space-certs-test-{uuid.uuid4().hex}"
        cert_id = "test-cert-authority-endpoint"

        # 1. Create CA and Space
        self.client.post(f"/api/v1/ca/authorities/{ca_id}", headers=self._auth_headers(), json={"common_name": "Test Auth Endpoints"})
        self.client.post(f"/api/v1/ca/spaces/{space_id}", headers=self._auth_headers(), json={"authority_id": ca_id})

        # 2. Submit and Sign Cert
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
        
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        csr = x509.CertificateSigningRequestBuilder().subject_name(x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, cert_id),
        ])).sign(key, hashes.SHA256())
        csr_pem = csr.public_bytes(serialization.Encoding.PEM).decode()

        self._db["ca_certificates"].insert_one({
            "id": cert_id,
            "space_id": space_id,
            "status": "requested",
            "csr": csr_pem
        })
        self.client.put(f"/api/v1/ca/spaces/{space_id}/certs/{cert_id}", headers=self._auth_headers(), json={"status": "signed"})

        # 3. Test /ca/authorities/{ca_id}/certs
        resp = self.client.get(f"/api/v1/ca/authorities/{ca_id}/certs", headers=self._auth_headers())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()["result"]), 1)
        self.assertEqual(resp.json()["result"][0]["id"], cert_id)

        # 4. Test /ca/authorities/{ca_id}/crl
        resp = self.client.get(f"/api/v1/ca/authorities/{ca_id}/crl", headers=self._auth_headers())
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"BEGIN X509 CRL", resp.content)
