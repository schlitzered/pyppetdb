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
        # Note: the check for space happens first in my implementation, 
        # but let's delete the space first to test the parent check.
        
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
        
        # We need a CSR to submit a cert request. Since we just want to test deletion, 
        # we can insert directly into DB or use a dummy CSR if the API allows.
        # Let's use the DB for simplicity in setup.
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

        # 12. Verify everything is gone
        resp = self.client.get(f"/api/v1/ca/authorities/{ca_id}", headers=self._auth_headers())
        self.assertEqual(resp.status_code, 404)
        resp = self.client.get(f"/api/v1/ca/spaces/{space_id}", headers=self._auth_headers())
        self.assertEqual(resp.status_code, 404)
