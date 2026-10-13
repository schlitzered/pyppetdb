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
import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

from pyppetdb.ca import crypto
from pyppetdb.errors import DuplicateResource
from pyppetdb.errors import QueryParamValidationError
from pyppetdb.main import cli_import_signed_certificates
from pyppetdb.model.ca_certificates import CACertificateGet
from pyppetdb.model.ca_validation import CAValidationConfig


class TestCliImportSignedCertificates(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.ca_cert, cls.ca_key = crypto.generate_ca(cn="puppet ca")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.signed = Path(self.tmp.name) / "signed"
        self.signed.mkdir()
        self.crl = Path(self.tmp.name) / "ca_crl.pem"
        self.container = MagicMock()
        self.container.ca_service.import_certificate = AsyncMock(
            side_effect=lambda **kwargs: CACertificateGet(id="1", cn="node")
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, cn):
        csr, _ = crypto.generate_csr(cn)
        cert = crypto.sign_csr(
            csr,
            self.ca_cert,
            self.ca_key,
            CAValidationConfig().get_key_usage_kwargs(),
            ["CLIENT_AUTH"],
        )
        (self.signed / f"{cn}.pem").write_bytes(cert)
        return int(crypto.get_cert_info(cert)["serial_number"])

    async def _run(self):
        return await cli_import_signed_certificates(
            container=self.container,
            log=logging.getLogger("test"),
            signed_dir=self.signed,
            crl_path=self.crl,
            ca_cert_pem=self.ca_cert,
        )

    async def test_imports_every_certificate_through_the_service(self):
        for cn in ("a", "b", "c"):
            self._write(cn)

        counts = await self._run()

        self.assertEqual(counts, {"imported": 3, "skipped": 0, "failed": 0})
        self.assertEqual(self.container.ca_service.import_certificate.await_count, 3)
        kwargs = self.container.ca_service.import_certificate.call_args.kwargs
        self.assertEqual(kwargs["space_id"], "puppet-ca")

    async def test_certificates_revoked_in_the_puppet_crl_are_not_loaded(self):
        revoked = self._write("revoked")
        self._write("valid")
        crl, _ = crypto.generate_crl(
            self.ca_cert,
            self.ca_key,
            [
                {
                    "serial_number": revoked,
                    "revocation_date": datetime.datetime.now(datetime.timezone.utc),
                }
            ],
        )
        self.crl.write_bytes(crl)

        counts = await self._run()

        self.assertEqual(counts, {"imported": 1, "skipped": 1, "failed": 0})
        imported = self.container.ca_service.import_certificate.call_args.kwargs
        self.assertNotEqual(
            int(crypto.get_cert_info(imported["certificate_pem"])["serial_number"]),
            revoked,
        )

    async def test_rejections_are_skipped_and_errors_are_failures(self):
        for cn in ("a", "b", "c"):
            self._write(cn)
        self.container.ca_service.import_certificate.side_effect = [
            DuplicateResource(),
            QueryParamValidationError(msg="expired"),
            RuntimeError("boom"),
        ]

        counts = await self._run()

        self.assertEqual(counts, {"imported": 0, "skipped": 2, "failed": 1})

    async def test_unreadable_file_is_a_failure(self):
        (self.signed / "broken.pem").write_bytes(b"not a certificate")

        counts = await self._run()

        self.assertEqual(counts, {"imported": 0, "skipped": 0, "failed": 1})


if __name__ == "__main__":
    unittest.main()
