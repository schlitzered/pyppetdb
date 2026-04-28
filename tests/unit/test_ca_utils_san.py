import unittest
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.x509.oid import NameOID
from pyppetdb.ca.utils import CAUtils


class TestCAUtilsSANInjection(unittest.TestCase):
    def setUp(self):
        # Generate a CA for signing
        self.ca_cert_pem, self.ca_key_pem = CAUtils.generate_ca(cn="Test CA")

    def test_sign_csr_inject_san_no_original_san(self):
        cn = "test-node"
        csr_pem, _ = CAUtils.generate_csr(cn=cn)

        signed_cert_pem = CAUtils.sign_csr(
            csr_pem=csr_pem,
            ca_cert_pem=self.ca_cert_pem,
            ca_key_pem=self.ca_key_pem,
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
            csr_pem=csr_pem,
            ca_cert_pem=self.ca_cert_pem,
            ca_key_pem=self.ca_key_pem,
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
            csr_pem=csr_pem,
            ca_cert_pem=self.ca_cert_pem,
            ca_key_pem=self.ca_key_pem,
        )

        cert = x509.load_pem_x509_certificate(signed_cert_pem)
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        dns_names = san.get_values_for_type(x509.DNSName)

        self.assertIn(cn, dns_names)
        self.assertIn("alt1.example.com", dns_names)
        # Should not duplicate if it was already there
        self.assertEqual(len(dns_names), 2)

    def test_renew_cert_inject_san_no_original_san(self):
        cn = "test-node"
        csr_pem, _ = CAUtils.generate_csr(cn=cn)
        
        # Manually sign without SAN first to test renewal injection 
        # Actually CAUtils.sign_csr now ALWAYS injects SAN, so I have to test if it keeps it.
        
        signed_cert_pem = CAUtils.sign_csr(
            csr_pem=csr_pem,
            ca_cert_pem=self.ca_cert_pem,
            ca_key_pem=self.ca_key_pem,
        )
        
        renewed_cert_pem = CAUtils.renew_cert(
            cert_pem=signed_cert_pem,
            ca_cert_pem=self.ca_cert_pem,
            ca_key_pem=self.ca_key_pem,
        )

        cert = x509.load_pem_x509_certificate(renewed_cert_pem)
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        dns_names = san.get_values_for_type(x509.DNSName)

        self.assertIn(cn, dns_names)
        self.assertEqual(len(dns_names), 1)
