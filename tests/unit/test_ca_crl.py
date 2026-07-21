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

from pyppetdb.ca.utils import CAUtils


class TestCACrl(unittest.TestCase):
    def test_generate_crl_includes_revoked_serial_and_is_signed(self):
        ca_cert_pem, ca_key_pem = CAUtils.generate_ca(cn="CRL Test CA")
        ca_cert = x509.load_pem_x509_certificate(ca_cert_pem)
        serial = 0x1234567890ABCDEF
        now = datetime.datetime.now(datetime.timezone.utc)

        crl_pem, next_update = CAUtils.generate_crl(
            ca_cert_pem,
            ca_key_pem,
            [{"serial_number": serial, "revocation_date": now}],
            7,
        )

        crl = x509.load_pem_x509_crl(crl_pem)
        self.assertIn(serial, {entry.serial_number for entry in crl})
        self.assertTrue(crl.is_signature_valid(ca_cert.public_key()))
        self.assertGreater(next_update, now)

    def test_generate_crl_without_revocations_is_empty(self):
        ca_cert_pem, ca_key_pem = CAUtils.generate_ca(cn="CRL Test CA")
        crl_pem, _ = CAUtils.generate_crl(ca_cert_pem, ca_key_pem, [], 7)
        crl = x509.load_pem_x509_crl(crl_pem)
        self.assertEqual(len(list(crl)), 0)


if __name__ == "__main__":
    unittest.main()
