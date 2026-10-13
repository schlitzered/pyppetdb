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
import tempfile
import unittest
import uuid
from pathlib import Path

from pymongo import MongoClient

from pyppetdb.ca import crypto
from pyppetdb.model.ca_validation import CAValidationConfig


class CliImportPuppetCaTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        from pyppetdb.main import settings

        settings.mongodb.database = "pyppetdb_test"
        cls._mongo = MongoClient(settings.mongodb.url, serverSelectionTimeoutMS=3000)
        try:
            cls._mongo.admin.command("ping")
        except Exception as err:
            cls._mongo.close()
            raise unittest.SkipTest(f"MongoDB not reachable: {err}")
        cls._db = cls._mongo[settings.mongodb.database]

    @classmethod
    def tearDownClass(cls):
        cls._mongo.close()

    def _keep_puppet_ca_space(self):
        original = self._db["ca_spaces"].find_one({"id": "puppet-ca"})

        def restore():
            if original is None:
                self._db["ca_spaces"].delete_one({"id": "puppet-ca"})
            else:
                self._db["ca_spaces"].replace_one({"_id": original["_id"]}, original)

        self.addCleanup(restore)

    def _puppet_ca_dir(self, root: Path, cns, revoked_cn):
        ca_cert, ca_key = crypto.generate_ca(cn=f"Puppet CA {uuid.uuid4().hex}")
        (root / "ca_crt.pem").write_bytes(ca_cert)
        (root / "ca_key.pem").write_bytes(ca_key)
        (root / "signed").mkdir()
        revoked = []
        for cn in cns:
            csr, _ = crypto.generate_csr(cn, alt_names=[f"alias.{cn}"])
            cert = crypto.sign_csr(
                csr,
                ca_cert,
                ca_key,
                CAValidationConfig().get_key_usage_kwargs(),
                ["SERVER_AUTH", "CLIENT_AUTH"],
            )
            (root / "signed" / f"{cn}.pem").write_bytes(cert)
            if cn == revoked_cn:
                revoked.append(
                    {
                        "serial_number": int(crypto.get_cert_info(cert)["serial_number"]),
                        "revocation_date": datetime.datetime.now(datetime.timezone.utc),
                    }
                )
        crl, _ = crypto.generate_crl(ca_cert, ca_key, revoked)
        (root / "ca_crl.pem").write_bytes(crl)

    async def test_imports_all_valid_certificates_and_skips_revoked_ones(self):
        from pyppetdb.main import cli_import_puppet_ca

        ca_id = f"imported-{uuid.uuid4().hex}"
        suffix = uuid.uuid4().hex[:8]
        cns = [f"node{i}-{suffix}.example.com" for i in range(3)]
        self._keep_puppet_ca_space()
        self.addCleanup(self._db["ca_certificates"].delete_many, {"ca_id": ca_id})
        self.addCleanup(self._db["ca_authorities"].delete_many, {"id": ca_id})

        with tempfile.TemporaryDirectory() as tmp:
            self._puppet_ca_dir(Path(tmp), cns, revoked_cn=cns[1])
            await cli_import_puppet_ca(ca_dir=tmp, ca_id=ca_id)

        docs = {
            doc["cn"]: doc for doc in self._db["ca_certificates"].find({"ca_id": ca_id})
        }
        self.assertEqual(sorted(docs), sorted([cns[0], cns[2]]))
        for cn, doc in docs.items():
            self.assertEqual(doc["status"], "signed")
            self.assertEqual(doc["space_id"], "puppet-ca")
            self.assertEqual(doc["cert_uniqueness"], f"puppet-ca:{cn}")
            self.assertEqual(doc["serial_number"], doc["id"])
            self.assertEqual(doc["requested_sans"], [f"alias.{cn}"])
        authority = self._db["ca_authorities"].find_one({"id": ca_id})
        self.assertTrue(authority["internal"])
        self.assertEqual(authority["secret_refs"], [])


if __name__ == "__main__":
    unittest.main()
