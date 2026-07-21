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

import ipaddress
import unittest
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from pyppetdb.ca.utils import CAUtils


def _csr_with_sans(cn, general_names):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    builder = x509.CertificateSigningRequestBuilder().subject_name(
        x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    )
    if general_names:
        builder = builder.add_extension(
            x509.SubjectAlternativeName(general_names), critical=False
        )
    csr = builder.sign(key, hashes.SHA256())
    return csr.public_bytes(serialization.Encoding.PEM)


class TestCAUtilsSANInjection(unittest.TestCase):
    def setUp(self):
        # Generate a CA for signing
        self.ca_cert_pem, self.ca_key_pem = CAUtils.generate_ca(cn="Test CA")

    def test_sign_csr_inject_san_no_original_san(self):
        cn = "test-node"
        csr_pem, _ = CAUtils.generate_csr(cn=cn)

        signed_cert_pem = CAUtils.sign_csr(
            csr=csr_pem,
            ca_cert=self.ca_cert_pem,
            ca_key=self.ca_key_pem,
            key_usages={
                "digital_signature": True,
                "content_commitment": False,
                "key_encipherment": True,
                "data_encipherment": False,
                "key_agreement": False,
                "key_cert_sign": False,
                "crl_sign": False,
                "encipher_only": False,
                "decipher_only": False,
            },
            extended_key_usages=[
                "SERVER_AUTH",
                "CLIENT_AUTH",
            ],
        )

        cert = x509.load_pem_x509_certificate(signed_cert_pem)
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        dns_names = san.get_values_for_type(x509.DNSName)

        self.assertIn(cn, dns_names)
        self.assertEqual(len(dns_names), 1)

    def test_sign_csr_inject_san_with_existing_san(self):
        cn = "test-node"
        alt_names = ["alt1.example.com", "alt2.example.com"]
        csr_pem, _ = CAUtils.generate_csr(cn=cn, alt_names=alt_names)

        signed_cert_pem = CAUtils.sign_csr(
            csr=csr_pem,
            ca_cert=self.ca_cert_pem,
            ca_key=self.ca_key_pem,
            key_usages={
                "digital_signature": True,
                "content_commitment": False,
                "key_encipherment": True,
                "data_encipherment": False,
                "key_agreement": False,
                "key_cert_sign": False,
                "crl_sign": False,
                "encipher_only": False,
                "decipher_only": False,
            },
            extended_key_usages=[
                "SERVER_AUTH",
                "CLIENT_AUTH",
            ],
        )

        cert = x509.load_pem_x509_certificate(signed_cert_pem)
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        dns_names = san.get_values_for_type(x509.DNSName)

        self.assertIn(cn, dns_names)
        self.assertIn("alt1.example.com", dns_names)
        self.assertIn("alt2.example.com", dns_names)
        self.assertEqual(len(dns_names), 3)

    def test_sign_csr_inject_san_cn_already_in_san(self):
        cn = "test-node"
        alt_names = ["test-node", "alt1.example.com"]
        csr_pem, _ = CAUtils.generate_csr(cn=cn, alt_names=alt_names)

        signed_cert_pem = CAUtils.sign_csr(
            csr=csr_pem,
            ca_cert=self.ca_cert_pem,
            ca_key=self.ca_key_pem,
            key_usages={
                "digital_signature": True,
                "content_commitment": False,
                "key_encipherment": True,
                "data_encipherment": False,
                "key_agreement": False,
                "key_cert_sign": False,
                "crl_sign": False,
                "encipher_only": False,
                "decipher_only": False,
            },
            extended_key_usages=[
                "SERVER_AUTH",
                "CLIENT_AUTH",
            ],
        )

        cert = x509.load_pem_x509_certificate(signed_cert_pem)
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        dns_names = san.get_values_for_type(x509.DNSName)

        self.assertIn(cn, dns_names)
        self.assertIn("alt1.example.com", dns_names)
        # Should not duplicate if it was already there
        self.assertEqual(len(dns_names), 2)

    def _sign(self, csr_pem, **kwargs):
        return CAUtils.sign_csr(
            csr=csr_pem,
            ca_cert=self.ca_cert_pem,
            ca_key=self.ca_key_pem,
            key_usages={
                "digital_signature": True,
                "content_commitment": False,
                "key_encipherment": True,
                "data_encipherment": False,
                "key_agreement": False,
                "key_cert_sign": False,
                "crl_sign": False,
                "encipher_only": False,
                "decipher_only": False,
            },
            extended_key_usages=[
                "SERVER_AUTH",
                "CLIENT_AUTH",
            ],
            **kwargs,
        )

    def _dns_names(self, signed_cert_pem):
        cert = x509.load_pem_x509_certificate(signed_cert_pem)
        san = cert.extensions.get_extension_for_class(
            x509.SubjectAlternativeName
        ).value
        return san.get_values_for_type(x509.DNSName)

    def test_sign_csr_ignores_csr_sans_when_disabled(self):
        cn = "test-node"
        alt_names = ["alt1.example.com", "alt2.example.com"]
        csr_pem, _ = CAUtils.generate_csr(cn=cn, alt_names=alt_names)

        signed_cert_pem = self._sign(csr_pem, honor_csr_sans=False)

        dns_names = self._dns_names(signed_cert_pem)
        self.assertIn(cn, dns_names)
        self.assertNotIn("alt1.example.com", dns_names)
        self.assertNotIn("alt2.example.com", dns_names)
        self.assertEqual(len(dns_names), 1)

    def test_sign_csr_ignores_csr_sans_but_keeps_injected(self):
        cn = "test-node"
        alt_names = ["attacker.example.com"]
        csr_pem, _ = CAUtils.generate_csr(cn=cn, alt_names=alt_names)

        signed_cert_pem = self._sign(
            csr_pem,
            honor_csr_sans=False,
            injected_sans=["trusted.example.com"],
        )

        dns_names = self._dns_names(signed_cert_pem)
        self.assertIn(cn, dns_names)
        self.assertIn("trusted.example.com", dns_names)
        self.assertNotIn("attacker.example.com", dns_names)
        self.assertEqual(len(dns_names), 2)

    def test_sign_csr_honors_csr_sans_when_enabled(self):
        cn = "test-node"
        alt_names = ["alt1.example.com", "alt2.example.com"]
        csr_pem, _ = CAUtils.generate_csr(cn=cn, alt_names=alt_names)

        signed_cert_pem = self._sign(csr_pem, honor_csr_sans=True)

        dns_names = self._dns_names(signed_cert_pem)
        self.assertIn(cn, dns_names)
        self.assertIn("alt1.example.com", dns_names)
        self.assertIn("alt2.example.com", dns_names)
        self.assertEqual(len(dns_names), 3)

    def test_get_cert_info_sans(self):
        cn = "test-node"
        alt_names = ["alt1.example.com", "alt2.example.com"]
        csr_pem, _ = CAUtils.generate_csr(cn=cn, alt_names=alt_names)

        signed_cert_pem = CAUtils.sign_csr(
            csr=csr_pem,
            ca_cert=self.ca_cert_pem,
            ca_key=self.ca_key_pem,
            key_usages={
                "digital_signature": True,
                "content_commitment": False,
                "key_encipherment": True,
                "data_encipherment": False,
                "key_agreement": False,
                "key_cert_sign": False,
                "crl_sign": False,
                "encipher_only": False,
                "decipher_only": False,
            },
            extended_key_usages=[
                "SERVER_AUTH",
                "CLIENT_AUTH",
            ],
        )

        info = CAUtils.get_cert_info(signed_cert_pem)
        self.assertIn("sans", info)
        self.assertIn(cn, info["sans"])
        self.assertIn("alt1.example.com", info["sans"])
        self.assertIn("alt2.example.com", info["sans"])
        self.assertEqual(len(info["sans"]), 3)

    def test_parse_and_extract_csr_sans(self):
        cn = "test-node"
        alt_names = ["alt1.example.com", "alt2.example.com"]
        csr_pem, _ = CAUtils.generate_csr(cn=cn, alt_names=alt_names)

        csr, info = CAUtils.parse_and_extract_csr(csr_pem)
        self.assertIn("sans", info)
        self.assertIn("alt1.example.com", info["sans"])
        self.assertIn("alt2.example.com", info["sans"])
        self.assertEqual(len(info["sans"]), 2)

    def test_sign_csr_drops_non_dns_san_types(self):
        cn = "test-node"
        csr_pem = _csr_with_sans(
            cn,
            [
                x509.DNSName("alt1.example.com"),
                x509.IPAddress(ipaddress.ip_address("10.0.0.5")),
                x509.UniformResourceIdentifier("https://evil.example.com"),
                x509.RFC822Name("admin@example.com"),
            ],
        )

        signed_cert_pem = self._sign(csr_pem, honor_csr_sans=True)

        cert = x509.load_pem_x509_certificate(signed_cert_pem)
        san = cert.extensions.get_extension_for_class(
            x509.SubjectAlternativeName
        ).value

        self.assertEqual(san.get_values_for_type(x509.IPAddress), [])
        self.assertEqual(san.get_values_for_type(x509.UniformResourceIdentifier), [])
        self.assertEqual(san.get_values_for_type(x509.RFC822Name), [])

        dns_names = san.get_values_for_type(x509.DNSName)
        self.assertIn(cn, dns_names)
        self.assertIn("alt1.example.com", dns_names)
        self.assertEqual(len(dns_names), 2)
