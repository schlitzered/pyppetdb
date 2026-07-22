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

import unittest

from cryptography import x509

from pyppetdb.ca.utils import CAUtils


def _key_usage(cert_pem):
    cert = x509.load_pem_x509_certificate(cert_pem)
    return cert.extensions.get_extension_for_class(x509.KeyUsage)


class TestCACertKeyUsage(unittest.TestCase):
    def test_generate_ca_sets_cert_sign_and_crl_sign(self):
        cert_pem, _ = CAUtils.generate_ca(cn="Root CA")
        ext = _key_usage(cert_pem)

        self.assertTrue(ext.critical)
        self.assertTrue(ext.value.key_cert_sign)
        self.assertTrue(ext.value.crl_sign)
        self.assertFalse(ext.value.key_encipherment)

    def test_sign_ca_sets_cert_sign_and_crl_sign(self):
        root_cert, root_key = CAUtils.generate_ca(cn="Root CA")
        sub_cert, _ = CAUtils.sign_ca(
            cn="Intermediate CA",
            ca_cert_pem=root_cert,
            ca_key_pem=root_key,
        )
        ext = _key_usage(sub_cert)

        self.assertTrue(ext.critical)
        self.assertTrue(ext.value.key_cert_sign)
        self.assertTrue(ext.value.crl_sign)

    def test_ca_certs_are_still_basic_constraints_ca(self):
        cert_pem, _ = CAUtils.generate_ca(cn="Root CA")
        cert = x509.load_pem_x509_certificate(cert_pem)
        bc = cert.extensions.get_extension_for_class(x509.BasicConstraints)
        self.assertTrue(bc.value.ca)


if __name__ == "__main__":
    unittest.main()
