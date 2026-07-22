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
from pyppetdb.model.ca_validation import CAValidationConfig


def _ski(cert_pem):
    cert = x509.load_pem_x509_certificate(cert_pem)
    return cert.extensions.get_extension_for_class(x509.SubjectKeyIdentifier).value


def _aki(cert_pem):
    cert = x509.load_pem_x509_certificate(cert_pem)
    return cert.extensions.get_extension_for_class(x509.AuthorityKeyIdentifier).value


def _leaf_key_usages():
    return CAValidationConfig().get_key_usage_kwargs()


class TestCASkiAki(unittest.TestCase):
    def test_generate_ca_has_ski_and_self_aki(self):
        cert_pem, _ = CAUtils.generate_ca(cn="Root CA")
        ski = _ski(cert_pem)
        aki = _aki(cert_pem)
        self.assertIsNotNone(ski.digest)
        self.assertEqual(aki.key_identifier, ski.digest)

    def test_sign_ca_aki_points_to_parent_ski(self):
        root_cert, root_key = CAUtils.generate_ca(cn="Root CA")
        sub_cert, _ = CAUtils.sign_ca(
            cn="Sub CA", ca_cert_pem=root_cert, ca_key_pem=root_key
        )
        self.assertEqual(_aki(sub_cert).key_identifier, _ski(root_cert).digest)
        self.assertIsNotNone(_ski(sub_cert).digest)

    def test_signed_leaf_ski_and_aki(self):
        ca_cert, ca_key = CAUtils.generate_ca(cn="Root CA")
        csr_pem, _ = CAUtils.generate_csr("leaf.example.com")
        leaf = CAUtils.sign_csr(
            csr=csr_pem,
            ca_cert=ca_cert,
            ca_key=ca_key,
            key_usages=_leaf_key_usages(),
            extended_key_usages=["SERVER_AUTH"],
        )
        self.assertIsNotNone(_ski(leaf).digest)
        self.assertEqual(_aki(leaf).key_identifier, _ski(ca_cert).digest)

    def test_renewed_leaf_ski_and_aki(self):
        ca_cert, ca_key = CAUtils.generate_ca(cn="Root CA")
        csr_pem, _ = CAUtils.generate_csr("leaf.example.com")
        leaf = CAUtils.sign_csr(
            csr=csr_pem,
            ca_cert=ca_cert,
            ca_key=ca_key,
            key_usages=_leaf_key_usages(),
            extended_key_usages=["SERVER_AUTH"],
        )
        renewed = CAUtils.renew_cert(
            cert=leaf,
            ca_cert=ca_cert,
            ca_key=ca_key,
            key_usages=_leaf_key_usages(),
            extended_key_usages=["SERVER_AUTH"],
        )
        self.assertIsNotNone(_ski(renewed).digest)
        self.assertEqual(_aki(renewed).key_identifier, _ski(ca_cert).digest)

    def test_renew_does_not_duplicate_ski_aki_from_allowed_extensions(self):
        ca_cert, ca_key = CAUtils.generate_ca(cn="Root CA")
        csr_pem, _ = CAUtils.generate_csr("leaf.example.com")
        leaf = CAUtils.sign_csr(
            csr=csr_pem,
            ca_cert=ca_cert,
            ca_key=ca_key,
            key_usages=_leaf_key_usages(),
            extended_key_usages=["SERVER_AUTH"],
        )
        renewed = CAUtils.renew_cert(
            cert=leaf,
            ca_cert=ca_cert,
            ca_key=ca_key,
            key_usages=_leaf_key_usages(),
            extended_key_usages=["SERVER_AUTH"],
            allowed_extensions=["2.5.29.14", "2.5.29.35"],
        )
        cert = x509.load_pem_x509_certificate(renewed)
        ski_count = sum(
            1
            for ext in cert.extensions
            if isinstance(ext.value, x509.SubjectKeyIdentifier)
        )
        aki_count = sum(
            1
            for ext in cert.extensions
            if isinstance(ext.value, x509.AuthorityKeyIdentifier)
        )
        self.assertEqual(ski_count, 1)
        self.assertEqual(aki_count, 1)

    def test_generate_crl_aki_points_to_ca_ski(self):
        ca_cert, ca_key = CAUtils.generate_ca(cn="Root CA")
        crl_pem, _ = CAUtils.generate_crl(
            ca_cert=ca_cert, ca_key=ca_key, revoked_certs=[]
        )
        crl = x509.load_pem_x509_crl(crl_pem)
        crl_aki = crl.extensions.get_extension_for_class(
            x509.AuthorityKeyIdentifier
        ).value
        self.assertEqual(crl_aki.key_identifier, _ski(ca_cert).digest)


if __name__ == "__main__":
    unittest.main()
