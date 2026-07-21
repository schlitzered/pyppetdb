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

import glob
import ssl
import tempfile
import unittest

from pyppetdb.ca.service import CAService
from pyppetdb.ca.utils import CAUtils
from pyppetdb.model.ca_validation import CAHTTPValidation


class TestBuildTlsVerify(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cert, key = CAUtils.generate_ca(cn="client")
        cls.client_cert = cert.decode()
        cls.client_key = key.decode()
        cacert, _ = CAUtils.generate_ca(cn="server-ca")
        cls.ca_cert = cacert.decode()

    def _check(self, **kwargs):
        kwargs.setdefault("url", "https://validate.example.com")
        return CAHTTPValidation(**kwargs)

    def test_no_tls_material_returns_bool(self):
        self.assertIs(self._build(verify_ssl=True), True)
        self.assertIs(self._build(verify_ssl=False), False)

    def _build(self, **kwargs):
        return CAService._build_tls_verify(self._check(**kwargs))

    def test_ca_cert_builds_context(self):
        verify = self._build(ca_cert=self.ca_cert)
        self.assertIsInstance(verify, ssl.SSLContext)
        self.assertTrue(verify.get_ca_certs())

    def test_client_cert_and_key_builds_context(self):
        verify = self._build(
            client_cert=self.client_cert, client_key=self.client_key
        )
        self.assertIsInstance(verify, ssl.SSLContext)

    def test_verify_false_with_client_cert(self):
        verify = self._build(
            verify_ssl=False,
            client_cert=self.client_cert,
            client_key=self.client_key,
        )
        self.assertIsInstance(verify, ssl.SSLContext)
        self.assertFalse(verify.check_hostname)
        self.assertEqual(verify.verify_mode, ssl.CERT_NONE)

    def test_client_cert_without_key_is_not_mtls(self):
        self.assertIs(
            self._build(client_cert=self.client_cert, verify_ssl=True), True
        )

    def test_client_key_tempfiles_are_removed(self):
        before = set(glob.glob(f"{tempfile.gettempdir()}/*.pem"))
        self._build(client_cert=self.client_cert, client_key=self.client_key)
        after = set(glob.glob(f"{tempfile.gettempdir()}/*.pem"))
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
