import uuid
import datetime
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
                "cn": "Root CA",
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
                "cn": "Sub CA"
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
                "ca_id": ca_id
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
        self.assertIn("still a parent of", resp.json()["detail"])

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
            json={"ca_id": ca_id}
        )
        self.assertEqual(resp.status_code, 200)
        
        # Insert directly into DB for space deletion test
        self._db["ca_certificates"].insert_one({
            "id": cert_id,
            "space_id": space_id,
            "ca_id": ca_id,
            "cn": "test-node",
            "status": "requested",
            "csr": "DUMMY CSR",
            "created": datetime.datetime.now(datetime.timezone.utc)
        })

        # 8. Try to delete Space (should fail: has certificates)
        resp = self.client.delete(
            f"/api/v1/ca/spaces/{space_id}",
            headers=self._auth_headers()
        )
        self.assertEqual(resp.status_code, 422)
        self.assertIn("still contains certificates", resp.json()["detail"])

        # 9. Delete Certificate (Manual cleanup as there is no API endpoint for deletion)
        self._db["ca_certificates"].delete_one({"id": cert_id, "space_id": space_id})

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
        cert_pem, key_pem = CAUtils.generate_ca(cn="External CA")
        ca_id = f"external-ca-{uuid.uuid4().hex}"
        external_chain = ["DUMMY CHAIN CERT 1", "DUMMY CHAIN CERT 2"]

        resp = self.client.post(
            f"/api/v1/ca/authorities/{ca_id}",
            headers=self._auth_headers(),
            json={
                "cn": "External CA",
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

    def test_crl_integration(self):
        root_ca_id = f"root-{uuid.uuid4().hex}"
        sub_ca_id = f"sub-{uuid.uuid4().hex}"
        space_id = f"space-{uuid.uuid4().hex}"
        cert_cn = "test-node-cert"
        cert_id = str(uuid.uuid4().int)

        # 1. Setup Hierarchy
        self.client.post(f"/api/v1/ca/authorities/{root_ca_id}", headers=self._auth_headers(), json={"cn": "Root"})
        self.client.post(f"/api/v1/ca/authorities/{sub_ca_id}", headers=self._auth_headers(), json={"parent_id": root_ca_id, "cn": "Sub"})
        self.client.post(f"/api/v1/ca/spaces/{space_id}", headers=self._auth_headers(), json={"ca_id": sub_ca_id})

        # 2. Revoke Sub CA
        self.client.put(f"/api/v1/ca/authorities/{sub_ca_id}", headers=self._auth_headers(), json={"status": "revoked"})

        # 3. Create and Revoke a Certificate in the space
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
        
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        csr = x509.CertificateSigningRequestBuilder().subject_name(x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, cert_cn),
        ])).sign(key, hashes.SHA256())
        csr_pem = csr.public_bytes(serialization.Encoding.PEM).decode()

        self._db["ca_certificates"].insert_one({
            "id": cert_id,
            "space_id": space_id,
            "ca_id": sub_ca_id,
            "cn": cert_cn,
            "status": "requested",
            "csr": csr_pem,
            "created": datetime.datetime.now(datetime.timezone.utc)
        })
        
        # Sign the cert
        resp = self.client.put(f"/api/v1/ca/spaces/{space_id}/certs/{cert_id}", headers=self._auth_headers(), json={"status": "signed"})
        self.assertEqual(resp.status_code, 200)
        signed_cert = resp.json()
        serial = signed_cert["id"] # The serial number

        # Revoke the cert
        self.client.put(f"/api/v1/ca/spaces/{space_id}/certs/{serial}", headers=self._auth_headers(), json={"status": "revoked"})

        # 4. Check CRL in CA Authority
        resp = self.client.get(f"/api/v1/ca/authorities/{sub_ca_id}", headers=self._auth_headers())
        self.assertEqual(resp.status_code, 200)
        ca_data = resp.json()
        self.assertIsNotNone(ca_data.get("crl"))
        self.assertIn("BEGIN X509 CRL", ca_data["crl"]["crl_pem"])

    def test_authority_history(self):
        root1_id = f"root1-{uuid.uuid4().hex}"
        root2_id = f"root2-{uuid.uuid4().hex}"
        space_id = f"space-{uuid.uuid4().hex}"

        # 1. Create Space with root1
        self.client.post(f"/api/v1/ca/authorities/{root1_id}", headers=self._auth_headers(), json={"cn": "Root1"})
        self.client.post(f"/api/v1/ca/spaces/{space_id}", headers=self._auth_headers(), json={"ca_id": root1_id})

        # 2. Update Space to use root2
        self.client.post(f"/api/v1/ca/authorities/{root2_id}", headers=self._auth_headers(), json={"cn": "Root2"})
        resp = self.client.put(f"/api/v1/ca/spaces/{space_id}", headers=self._auth_headers(), json={"ca_id": root2_id})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["ca_id"], root2_id)
        self.assertEqual(resp.json()["ca_id_history"], [root1_id])

        # 3. Verify CRL exists for both CAs in their respective authority objects
        for ca_id in [root1_id, root2_id]:
            resp = self.client.get(f"/api/v1/ca/authorities/{ca_id}", headers=self._auth_headers())
            self.assertEqual(resp.status_code, 200)
            self.assertIsNotNone(resp.json().get("crl"))

    def test_authority_certs_and_crl(self):
        ca_id = f"ca-certs-test-{uuid.uuid4().hex}"
        space_id = f"space-certs-test-{uuid.uuid4().hex}"
        cert_cn = "test-cert-authority-endpoint"
        cert_id = str(uuid.uuid4().int)

        # 1. Create CA and Space
        self.client.post(f"/api/v1/ca/authorities/{ca_id}", headers=self._auth_headers(), json={"cn": "Test Auth Endpoints"})
        self.client.post(f"/api/v1/ca/spaces/{space_id}", headers=self._auth_headers(), json={"ca_id": ca_id})

        # 2. Submit and Sign Cert
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
        
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        csr = x509.CertificateSigningRequestBuilder().subject_name(x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, cert_cn),
        ])).sign(key, hashes.SHA256())
        csr_pem = csr.public_bytes(serialization.Encoding.PEM).decode()

        self._db["ca_certificates"].insert_one({
            "id": cert_id,
            "space_id": space_id,
            "ca_id": ca_id,
            "cn": cert_cn,
            "status": "requested",
            "csr": csr_pem,
            "created": datetime.datetime.now(datetime.timezone.utc)
        })
        resp = self.client.put(f"/api/v1/ca/spaces/{space_id}/certs/{cert_id}", headers=self._auth_headers(), json={"status": "signed"})
        self.assertEqual(resp.status_code, 200)
        serial = resp.json()["id"]

        # 3. Test /ca/authorities/{ca_id}/certs
        resp = self.client.get(f"/api/v1/ca/authorities/{ca_id}/certs", headers=self._auth_headers())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()["result"]), 1)
        self.assertEqual(resp.json()["result"][0]["id"], serial)

        # 4. Verify CRL in Authority object
        resp = self.client.get(f"/api/v1/ca/authorities/{ca_id}", headers=self._auth_headers())
        self.assertEqual(resp.status_code, 200)
        self.assertIsNotNone(resp.json().get("crl"))
        self.assertIn("BEGIN X509 CRL", resp.json()["crl"]["crl_pem"])

    def test_search_certs_by_cn(self):
        ca_id = f"ca-search-test-{uuid.uuid4().hex}"
        space_id = f"space-search-test-{uuid.uuid4().hex}"
        cert_cn = "test-cert-to-search"
        cert_id = str(uuid.uuid4().int)

        # 1. Setup
        self.client.post(f"/api/v1/ca/authorities/{ca_id}", headers=self._auth_headers(), json={"cn": "Search Test Auth"})
        self.client.post(f"/api/v1/ca/spaces/{space_id}", headers=self._auth_headers(), json={"ca_id": ca_id})

        # 2. Insert cert
        self._db["ca_certificates"].insert_one({
            "id": cert_id,
            "space_id": space_id,
            "ca_id": ca_id,
            "cn": cert_cn,
            "status": "signed",
            "created": datetime.datetime.now(datetime.timezone.utc)
        })

        # 3. Search by CN on spaces endpoint
        resp = self.client.get(f"/api/v1/ca/spaces/{space_id}/certs", headers=self._auth_headers(), params={"cn": cert_cn})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()["result"]), 1)
        self.assertEqual(resp.json()["result"][0]["cn"], cert_cn)

        # 4. Search by CN on authorities endpoint
        resp = self.client.get(f"/api/v1/ca/authorities/{ca_id}/certs", headers=self._auth_headers(), params={"cn": cert_cn})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()["result"]), 1)
        self.assertEqual(resp.json()["result"][0]["cn"], cert_cn)

        # 5. Search with regex
        resp = self.client.get(f"/api/v1/ca/spaces/{space_id}/certs", headers=self._auth_headers(), params={"cn": "test-cert-.*"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(len(resp.json()["result"]) >= 1)
