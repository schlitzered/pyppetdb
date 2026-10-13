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
import unittest

from cryptography import x509

from pyppetdb.ca import crypto
from pyppetdb.model.ca_validation import CAValidationConfig

KEY_USAGES = CAValidationConfig().get_key_usage_kwargs()


def _sans(cert_pem):
    cert = x509.load_pem_x509_certificate(cert_pem)
    return cert.extensions.get_extension_for_class(
        x509.SubjectAlternativeName
    ).value.get_values_for_type(x509.DNSName)


class TestCrypto(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ca_cert, cls.ca_key = crypto.generate_ca(cn="root")
        cls.other_cert, cls.other_key = crypto.generate_ca(cn="other")
        csr, _ = crypto.generate_csr("node1", alt_names=["alias.example"])
        cls.cert = crypto.sign_csr(
            csr, cls.ca_cert, cls.ca_key, KEY_USAGES, ["SERVER_AUTH"]
        )

    def test_root_ca_is_self_signed(self):
        cert = x509.load_pem_x509_certificate(self.ca_cert)

        self.assertEqual(cert.issuer, cert.subject)
        cert.verify_directly_issued_by(cert)

    def test_intermediate_is_issued_by_parent(self):
        child_pem, _ = crypto.sign_ca("sub", self.ca_cert, self.ca_key)
        parent = x509.load_pem_x509_certificate(self.ca_cert)
        child = x509.load_pem_x509_certificate(child_pem)

        self.assertEqual(child.issuer, parent.subject)
        child.verify_directly_issued_by(parent)

    def test_key_matches_certificate(self):
        self.assertTrue(crypto.key_matches_certificate(self.ca_cert, self.ca_key))
        self.assertFalse(
            crypto.key_matches_certificate(self.ca_cert, self.other_key)
        )

    def test_empty_extended_key_usages_omit_the_extension(self):
        csr, _ = crypto.generate_csr("node2")
        cert = x509.load_pem_x509_certificate(
            crypto.sign_csr(csr, self.ca_cert, self.ca_key, KEY_USAGES, [])
        )

        with self.assertRaises(x509.ExtensionNotFound):
            cert.extensions.get_extension_for_class(x509.ExtendedKeyUsage)
        self.assertEqual(crypto.common_name(cert.subject), "node2")

    def test_renew_keeps_sans_when_honored(self):
        renewed = crypto.renew_cert(
            self.cert, self.ca_cert, self.ca_key, KEY_USAGES, [], honor_cert_sans=True
        )

        self.assertEqual(sorted(_sans(renewed)), ["alias.example", "node1"])

    def test_renew_drops_old_sans_when_not_honored(self):
        renewed = crypto.renew_cert(
            self.cert,
            self.ca_cert,
            self.ca_key,
            KEY_USAGES,
            [],
            injected_sans=["svc.example"],
            honor_cert_sans=False,
        )

        self.assertEqual(_sans(renewed), ["node1", "svc.example"])

    def test_issued_by(self):
        self.assertTrue(crypto.issued_by(self.cert, self.ca_cert))
        self.assertFalse(crypto.issued_by(self.cert, self.other_cert))

    def test_revoked_serials_only_from_crls_of_the_issuer(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        own, _ = crypto.generate_crl(
            self.ca_cert, self.ca_key, [{"serial_number": 7, "revocation_date": now}]
        )
        foreign, _ = crypto.generate_crl(
            self.other_cert,
            self.other_key,
            [{"serial_number": 8, "revocation_date": now}],
        )

        serials = crypto.revoked_serials_from_crls(foreign + own, self.ca_cert)

        self.assertEqual(serials, {7})

    def test_renew_uses_given_requested_sans(self):
        renewed = crypto.renew_cert(
            self.cert,
            self.ca_cert,
            self.ca_key,
            KEY_USAGES,
            [],
            injected_sans=["svc.example"],
            requested_sans=["other.example"],
        )

        self.assertEqual(_sans(renewed), ["other.example", "node1", "svc.example"])


if __name__ == "__main__":
    unittest.main()
