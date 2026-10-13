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
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

from cryptography import x509

from pyppetdb.ca import crypto
from pyppetdb.ca.crl import CACrl
from pyppetdb.model.ca_authorities import CAAuthorityGet
from pyppetdb.model.ca_authorities import CAAuthorityGetMulti
from pyppetdb.model.ca_authorities import CASigner
from pyppetdb.model.ca_certificates import CACertificateGet
from pyppetdb.model.ca_certificates import CACertificateGetMulti


def _multi(model, items):
    return model(result=items, meta={"result_size": len(items)})


class TestCACrl(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.cert_pem, cls.key_pem = crypto.generate_ca(cn="crl-ca")

    def setUp(self):
        config = MagicMock()
        config.app.main.port = 8000
        config.ca.crlValidityDays = 7
        self.crud_authorities = AsyncMock()
        self.crud_authorities.search.return_value = _multi(CAAuthorityGetMulti, [])
        self.crud_certificates = AsyncMock()
        self.crud_certificates.search.return_value = _multi(CACertificateGetMulti, [])
        self.nodes = AsyncMock()
        self.signers = AsyncMock()
        self.signers.get.return_value = CASigner(
            certificate=crypto.load_certificate(self.cert_pem),
            private_key=crypto.load_private_key(self.key_pem),
            source=(self.cert_pem.decode(), self.key_pem),
        )
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.crl = CACrl(
            log=logging.getLogger("test"),
            config=config,
            crud_authorities=self.crud_authorities,
            crud_certificates=self.crud_certificates,
            crud_pyppetdb_nodes=self.nodes,
            signers=self.signers,
            executor=self.executor,
        )

    def tearDown(self):
        self.executor.shutdown()

    async def test_generate_signs_with_cached_signer_and_lists_revocations(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        self.crud_certificates.search.return_value = _multi(
            CACertificateGetMulti,
            [CACertificateGet(serial_number="42", revocation_date=now)],
        )

        await self.crl.generate("ca1")

        self.signers.get.assert_awaited_once_with("ca1")
        kwargs = self.crud_authorities.sync_crl_data.call_args.kwargs
        crl = x509.load_pem_x509_crl(kwargs["crl_pem"].encode())
        self.assertIsNotNone(crl.get_revoked_certificate_by_serial_number(42))
        self.assertTrue(
            crl.is_signature_valid(crypto.load_certificate(self.cert_pem).public_key())
        )

    async def test_refresh_skips_when_not_leader(self):
        self.nodes.get_leader.return_value = "someone-else:8000"

        await self.crl.refresh_all()

        self.crud_authorities.search.assert_not_called()
        self.crud_authorities.sync_crl_data.assert_not_called()

    async def test_refresh_continues_after_a_failing_authority(self):
        self.nodes.get_leader.return_value = self.crl._instance_id
        active = _multi(
            CAAuthorityGetMulti, [CAAuthorityGet(id="bad"), CAAuthorityGet(id="good")]
        )
        self.crud_authorities.search.side_effect = (
            lambda **kwargs: active
            if kwargs.get("internal")
            else _multi(CAAuthorityGetMulti, [])
        )
        self.signers.get.side_effect = [
            RuntimeError("broken"),
            self.signers.get.return_value,
        ]

        await self.crl.refresh_all()

        self.crud_authorities.search.assert_any_await(
            internal=True, status="active", fields=["id"]
        )
        self.assertEqual(
            self.crud_authorities.sync_crl_data.call_args.kwargs["ca_id"], "good"
        )

    async def test_revoked_serials_filter_children_exactly_by_parent(self):
        await self.crl.revoked_serials("ca.1")

        kwargs = self.crud_authorities.search.call_args.kwargs
        self.assertEqual(kwargs["parent_id"], "^ca\\.1$")
        self.assertEqual(kwargs["status"], "revoked")
        self.crud_certificates.search.assert_awaited_once_with(
            ca_id="ca.1", status="revoked", fields=["serial_number", "revocation_date"]
        )

    async def test_revoked_serials_fill_missing_revocation_dates(self):
        stored = datetime.datetime.now(datetime.timezone.utc)
        self.crud_authorities.search.return_value = _multi(
            CAAuthorityGetMulti,
            [CAAuthorityGet(serial_number="7", revocation_date=None)],
        )
        self.crud_certificates.search.return_value = _multi(
            CACertificateGetMulti,
            [CACertificateGet(serial_number="8", revocation_date=stored)],
        )

        revoked = await self.crl.revoked_serials("ca1")

        self.assertEqual([item["serial_number"] for item in revoked], [7, 8])
        self.assertIsNotNone(revoked[0]["revocation_date"])
        self.assertEqual(revoked[1]["revocation_date"], stored)


if __name__ == "__main__":
    unittest.main()
