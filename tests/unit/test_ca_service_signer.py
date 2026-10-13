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

from concurrent.futures import ThreadPoolExecutor
import datetime
import logging
import unittest
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import padding

from pyppetdb.ca.signer import CASigners
from pyppetdb.ca.validation import CSRValidator
from pyppetdb.ca import crypto
from pyppetdb.ca.service import CAService
from pyppetdb.crud.ca_authorities import CrudCAAuthorities
from pyppetdb.crud.watcher import STATE_READY
from pyppetdb.crud.watcher import STATE_SYNCING
from pyppetdb.model.ca_authorities import CAAuthorityCacheEntry
from pyppetdb.errors import QueryParamValidationError
from pyppetdb.model.ca_authorities import CAAuthorityGet
from pyppetdb.model.ca_authorities import CAAuthorityPost
from pyppetdb.model.ca_certificates import CACertificateGet
from pyppetdb.model.ca_spaces import CASpaceGet
from pyppetdb.model.ca_validation import CAValidationConfig


class TestCAServiceSigner(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.cert_pem, cls.key_pem = crypto.generate_ca(cn="ca-one")
        cls.other_cert_pem, cls.other_key_pem = crypto.generate_ca(cn="ca-two")

    def setUp(self):
        config = MagicMock()
        config.ca.concurrentWorkers = 1
        config.ca.certificateRequestTtlDays = 30
        config.ca.crlValidityDays = 7
        config.ca.certificateValidityDays = 30
        self.protector = MagicMock()
        self.crud = CrudCAAuthorities(
            config=config,
            log=logging.getLogger("test"),
            coll=MagicMock(),
            protector=self.protector,
        )
        self.crud.cache.watcher._state = STATE_READY
        self.crud_spaces = AsyncMock()
        self.crud_spaces.get.return_value = CASpaceGet(id="space1", ca_id="ca1")
        self.crud_certificates = AsyncMock()
        executor = ThreadPoolExecutor(max_workers=1)
        self.service = CAService(
            log=logging.getLogger("test"),
            config=config,
            crud_authorities=self.crud,
            crud_spaces=self.crud_spaces,
            crud_certificates=self.crud_certificates,
            signers=CASigners(
                crud_authorities=self.crud, executor=executor
            ),
            validator=CSRValidator(
                log=logging.getLogger("test"), crud_secrets=AsyncMock()
            ),
            executor=executor,
        )

    def _cache(self, cert_pem, key_pem, status="active"):
        self.crud.cache.cache["ca1"] = CAAuthorityCacheEntry(
            authority=CAAuthorityGet(
                id="ca1", certificate=cert_pem.decode(), chain=[], status=status
            ),
            private_key=key_pem,
        )

    async def _resources(self, ca_id):
        signer = await self.service.signers.get(ca_id)
        return signer.certificate, signer.private_key

    def _cn(self, certificate):
        return certificate.subject.get_attributes_for_oid(
            x509.oid.NameOID.COMMON_NAME
        )[0].value

    async def test_decodes_once_and_reuses_signer(self):
        self._cache(self.cert_pem, self.key_pem)

        with patch.object(
            CASigners, "load", wraps=CASigners.load
        ) as load:
            first_cert, first_key = await self._resources("ca1")
            second_cert, second_key = await self._resources("ca1")

        self.assertEqual(load.call_count, 1)
        self.assertIs(first_cert, second_cert)
        self.assertIs(first_key, second_key)
        self.assertEqual(self._cn(first_cert), "ca-one")

    async def test_changed_authority_is_decoded_again(self):
        self._cache(self.cert_pem, self.key_pem)
        await self._resources("ca1")

        self._cache(self.other_cert_pem, self.other_key_pem)
        cert, key = await self._resources("ca1")

        self.assertEqual(self._cn(cert), "ca-two")
        self.assertEqual(
            key.public_key().public_numbers(), cert.public_key().public_numbers()
        )

    async def test_change_during_decode_is_not_stored(self):
        self._cache(self.cert_pem, self.key_pem)
        original = CASigners.load

        def load_while_changing(source):
            self._cache(self.other_cert_pem, self.other_key_pem)
            return original(source)

        with patch.object(CASigners, "load", side_effect=load_while_changing):
            cert, _ = await self._resources("ca1")

        self.assertEqual(self._cn(cert), "ca-one")
        self.assertIsNone(self.crud.cache.cache["ca1"].signer)
        cert, _ = await self._resources("ca1")
        self.assertEqual(self._cn(cert), "ca-two")

    async def test_not_ready_reads_backend_and_never_caches(self):
        self._cache(self.other_cert_pem, self.other_key_pem)
        self.crud.cache.watcher._state = STATE_SYNCING
        self.crud._get = AsyncMock(
            return_value={
                "certificate": self.cert_pem.decode(),
                "private_key_encrypted": "ENC",
            }
        )
        self.protector.decrypt_string.return_value = self.key_pem.decode()

        cert, _ = await self._resources("ca1")

        self.assertEqual(self._cn(cert), "ca-one")
        self.assertIsNone(self.crud.cache.cache["ca1"].signer)
        self.crud._get.assert_awaited_once()

    async def test_intermediate_is_signed_with_cached_parent_signer(self):
        self._cache(self.cert_pem, self.key_pem)
        self.crud._get = AsyncMock()
        self.protector.encrypt_string.return_value = "ENC"
        self.crud.create = AsyncMock(side_effect=lambda **kwargs: kwargs["payload"])

        created = await self.service.create_authority(
            _id="sub", payload=CAAuthorityPost(cn="sub", parent_id="ca1"), fields=[]
        )

        self.crud._get.assert_not_called()
        parent = x509.load_pem_x509_certificate(self.cert_pem)
        child = x509.load_pem_x509_certificate(created.certificate.encode())
        self.assertEqual(child.issuer, parent.subject)
        parent.public_key().verify(
            child.signature,
            child.tbs_certificate_bytes,
            padding.PKCS1v15(),
            child.signature_hash_algorithm,
        )
        self.assertEqual(created.chain, [self.cert_pem.decode()])
        self.assertIsNotNone(self.crud.cache.cache["ca1"].signer)

    async def test_revoked_parent_cannot_sign_intermediate(self):
        self._cache(self.cert_pem, self.key_pem, status="revoked")
        self.crud.create = AsyncMock()

        with patch.object(CASigners, "load") as load:
            with self.assertRaises(QueryParamValidationError):
                await self.service.create_authority(
                    _id="sub",
                    payload=CAAuthorityPost(cn="sub", parent_id="ca1"),
                    fields=[],
                )

        load.assert_not_called()
        self.crud.create.assert_not_called()

    async def test_revoked_authority_cannot_sign_requested_certificate(self):
        self._cache(self.cert_pem, self.key_pem, status="revoked")
        self.crud_certificates.get.return_value = CACertificateGet(
            id="1", space_id="space1", cn="node1", status="requested"
        )

        with patch.object(CASigners, "load") as load:
            with self.assertRaises(QueryParamValidationError) as ctx:
                await self.service.process_requested_certificate("1")

        self.assertIn("revoked", ctx.exception.detail)
        load.assert_not_called()
        self.crud_certificates.update.assert_not_called()

    async def test_revoked_authority_cannot_renew_certificate(self):
        self._cache(self.cert_pem, self.key_pem, status="revoked")
        self.crud_certificates.get_by_cn.return_value = CACertificateGet(
            id="1",
            space_id="space1",
            cn="node1",
            status="signed",
            certificate="CERT",
        )

        with patch.object(CASigners, "load") as load:
            with self.assertRaises(QueryParamValidationError):
                await self.service.renew_certificate("space1", "node1")

        load.assert_not_called()
        self.crud_certificates.revoke.assert_not_called()

    async def test_import_rejects_key_of_another_certificate(self):
        self.crud.create = AsyncMock()

        with self.assertRaises(QueryParamValidationError) as ctx:
            await self.service.import_authority(
                _id="imported",
                certificate_pem=self.cert_pem,
                private_key_pem=self.other_key_pem,
                internal=True,
                fields=[],
            )

        self.assertIn("does not belong", ctx.exception.detail)
        self.crud.create.assert_not_called()

    async def test_internal_import_gets_crl_external_does_not(self):
        self.protector.encrypt_string.return_value = "ENC"
        self.crud.create = AsyncMock(side_effect=lambda **kwargs: kwargs["payload"])

        internal = await self.service.import_authority(
            _id="a", certificate_pem=self.cert_pem, private_key_pem=self.key_pem,
            internal=True, fields=[],
        )
        external = await self.service.import_authority(
            _id="b", certificate_pem=self.cert_pem, private_key_pem=self.key_pem,
            internal=False, fields=[],
        )

        self.assertEqual(internal.cn, "ca-one")
        self.assertIn("BEGIN X509 CRL", internal.crl.crl_pem)
        self.assertIsNone(external.crl)
        self.assertEqual(internal.secret_refs, [])

    async def test_chain_cycle_is_rejected(self):
        self.crud.cache.cache["ca1"] = CAAuthorityCacheEntry(
            authority=CAAuthorityGet(id="ca1", parent_id="ca2", certificate="A")
        )
        self.crud.cache.cache["ca2"] = CAAuthorityCacheEntry(
            authority=CAAuthorityGet(id="ca2", parent_id="ca1", certificate="B")
        )

        with self.assertRaises(QueryParamValidationError):
            await self.service.get_certificate_chain("space1")

    async def test_chain_is_leaf_first(self):
        self.crud.cache.cache["ca1"] = CAAuthorityCacheEntry(
            authority=CAAuthorityGet(id="ca1", parent_id="root", certificate="LEAF")
        )
        self.crud.cache.cache["root"] = CAAuthorityCacheEntry(
            authority=CAAuthorityGet(id="root", certificate="ROOT")
        )

        self.assertEqual(await self.service.get_certificate_chain("space1"), b"LEAFROOT")

    async def test_renewal_follows_the_san_policy(self):
        self._cache(self.cert_pem, self.key_pem)
        csr, _ = crypto.generate_csr("node1", alt_names=["alias.example"])
        old = crypto.sign_csr(
            csr,
            self.cert_pem,
            self.key_pem,
            CAValidationConfig().get_key_usage_kwargs(),
            ["SERVER_AUTH"],
        )
        self.crud_certificates.get_by_cn.return_value = CACertificateGet(
            id="1", space_id="space1", cn="node1", status="signed",
            certificate=old.decode(),
        )
        self.crud_certificates.revoke.return_value = MagicMock()
        self.crud_certificates.create = AsyncMock(
            side_effect=lambda **kwargs: kwargs["payload"]
        )

        renewed = await self.service.renew_certificate("space1", "node1")

        self.assertEqual(renewed.sans, ["node1"])

    async def test_request_validation_gets_stored_refs_of_ca_and_space(self):
        self.crud.cache.cache["ca1"] = CAAuthorityCacheEntry(
            authority=CAAuthorityGet(id="ca1", secret_refs=["CA_TOKEN"])
        )
        self.crud_spaces.get.return_value = CASpaceGet(
            id="space1", ca_id="ca1", secret_refs=["SPACE_TOKEN"]
        )
        self.service.validator.validate = AsyncMock()
        csr_pem, _ = crypto.generate_csr("node1")

        await self.service.submit_certificate_request(
            space_id="space1", csr_pem=csr_pem.decode(), fields=[], cn="node1"
        )

        self.assertEqual(
            self.service.validator.validate.call_args.kwargs["secret_refs"],
            ["CA_TOKEN", "SPACE_TOKEN"],
        )

    async def test_chain_revoked_when_any_ancestor_is_revoked(self):
        self.crud.cache.cache["leaf"] = CAAuthorityCacheEntry(
            authority=CAAuthorityGet(id="leaf", parent_id="mid", status="active")
        )
        self.crud.cache.cache["mid"] = CAAuthorityCacheEntry(
            authority=CAAuthorityGet(id="mid", parent_id="root", status="active")
        )
        self.crud.cache.cache["root"] = CAAuthorityCacheEntry(
            authority=CAAuthorityGet(id="root", status="revoked")
        )

        self.assertTrue(await self.service.authority_chain_revoked("leaf"))
        self.crud.cache.cache["root"].authority.status = "active"
        self.assertFalse(await self.service.authority_chain_revoked("leaf"))

    async def test_request_expires_is_set_on_submit_and_removed_on_signing(self):
        self._cache(self.cert_pem, self.key_pem)
        csr_pem, _ = crypto.generate_csr("node1")
        self.crud_certificates.upsert_request = AsyncMock()

        await self.service.submit_certificate_request(
            space_id="space1", csr_pem=csr_pem.decode(), fields=[], cn="node1"
        )

        payload = self.crud_certificates.upsert_request.call_args.kwargs["payload"]
        self.assertEqual(
            (payload.request_expires - payload.created).days, 30
        )

        self.crud_certificates.get.return_value = CACertificateGet(
            id="req", space_id="space1", cn="node1", status="requested",
            csr=csr_pem.decode(),
        )
        self.crud_certificates.update = AsyncMock()

        await self.service.process_requested_certificate("req")

        self.assertEqual(
            self.crud_certificates.update.call_args.kwargs["unset"], ["request_expires"]
        )

    def _issued(self, cn, alt_names):
        csr, _ = crypto.generate_csr(cn, alt_names=alt_names)
        return crypto.sign_csr(
            csr,
            self.cert_pem,
            self.key_pem,
            CAValidationConfig().get_key_usage_kwargs(),
            ["SERVER_AUTH"],
            injected_sans=["svc.internal"],
        )

    async def test_renewal_validates_the_requested_sans_only(self):
        self._cache(self.cert_pem, self.key_pem)
        self.crud.cache.cache["ca1"].authority.validation_config = CAValidationConfig(
            san_injection=[{"pattern": "node1", "templates": ["svc.internal"]}]
        )
        old = self._issued("node1", ["alias.example"])
        self.crud_certificates.get_by_cn.return_value = CACertificateGet(
            id="1", space_id="space1", cn="node1", status="signed",
            certificate=old.decode(),
        )
        self.crud_certificates.create = AsyncMock(
            side_effect=lambda **kwargs: kwargs["payload"]
        )
        self.service.validator.validate_names = AsyncMock()

        await self.service.renew_certificate("space1", "node1")

        kwargs = self.service.validator.validate_names.call_args.kwargs
        self.assertEqual(kwargs["cn"], "node1")
        self.assertEqual(kwargs["sans"], ["alias.example"])

    async def test_renewal_rejected_by_current_validation(self):
        self._cache(self.cert_pem, self.key_pem)
        self.crud_spaces.get.return_value = CASpaceGet(
            id="space1",
            ca_id="ca1",
            validation_config=CAValidationConfig(
                san_validation={"regex_list": ["^allowed\\..*$"]}
            ),
        )
        old = self._issued("node1", ["alias.example"])
        self.crud_certificates.get_by_cn.return_value = CACertificateGet(
            id="1", space_id="space1", cn="node1", status="signed",
            certificate=old.decode(),
        )
        self.crud_certificates.create = AsyncMock()

        with self.assertRaises(QueryParamValidationError):
            await self.service.renew_certificate("space1", "node1")

        self.crud_certificates.revoke.assert_not_called()
        self.crud_certificates.create.assert_not_called()

    def _renewal_setup(self, old_cert, **cert_fields):
        self._cache(self.cert_pem, self.key_pem)
        self.crud_spaces.get.return_value = CASpaceGet(
            id="space1",
            ca_id="ca1",
            validation_config=CAValidationConfig(
                san_validation={},
                san_injection=[{"pattern": "node1", "templates": ["new.internal"]}],
            ),
        )
        self.crud_certificates.get_by_cn.return_value = CACertificateGet(
            id="1", space_id="space1", cn="node1", status="signed",
            certificate=old_cert.decode(), **cert_fields,
        )
        self.crud_certificates.create = AsyncMock(
            side_effect=lambda **kwargs: kwargs["payload"]
        )

    async def test_submit_stores_the_requested_sans(self):
        self._cache(self.cert_pem, self.key_pem)
        csr_pem, _ = crypto.generate_csr("node1", alt_names=["alias.example"])
        self.crud_certificates.upsert_request = AsyncMock()

        await self.service.submit_certificate_request(
            space_id="space1", csr_pem=csr_pem.decode(), fields=[], cn="node1"
        )

        payload = self.crud_certificates.upsert_request.call_args.kwargs["payload"]
        self.assertEqual(payload.requested_sans, ["alias.example"])

    async def test_renewal_drops_stale_injected_sans_and_keeps_requested(self):
        old = self._issued("node1", ["alias.example"])
        self._renewal_setup(old, requested_sans=["alias.example"])

        renewed = await self.service.renew_certificate("space1", "node1")

        self.assertEqual(
            sorted(renewed.sans), ["alias.example", "new.internal", "node1"]
        )
        self.assertEqual(renewed.requested_sans, ["alias.example"])

    async def test_renewal_falls_back_to_the_stored_csr(self):
        csr_pem, _ = crypto.generate_csr("node1", alt_names=["from-csr.example"])
        old = self._issued("node1", ["alias.example"])
        self._renewal_setup(old, csr=csr_pem.decode())

        renewed = await self.service.renew_certificate("space1", "node1")

        self.assertEqual(renewed.requested_sans, ["from-csr.example"])
        self.assertIn("from-csr.example", renewed.sans)
        self.assertNotIn("alias.example", renewed.sans)

    async def test_renewal_without_csr_uses_old_sans_without_cn(self):
        old = self._issued("node1", ["alias.example"])
        self._renewal_setup(old)

        renewed = await self.service.renew_certificate("space1", "node1")

        self.assertEqual(renewed.requested_sans, ["alias.example", "svc.internal"])

    async def test_import_certificate_creates_a_regular_signed_certificate(self):
        self.crud.cache.cache["ca1"] = CAAuthorityCacheEntry(
            authority=CAAuthorityGet(id="ca1", certificate=self.cert_pem.decode())
        )
        self.crud._get = AsyncMock(
            return_value={"id": "ca1", "certificate": self.cert_pem.decode()}
        )
        self.crud_certificates.create = AsyncMock(
            side_effect=lambda **kwargs: kwargs["payload"]
        )
        cert = self._issued("node9", ["alias.example"])

        created = await self.service.import_certificate("space1", cert, fields=[])

        self.assertEqual(created.cert_uniqueness, "space1:node9")
        self.assertEqual(created.status, "signed")
        self.assertEqual(created.ca_id, "ca1")
        self.assertEqual(created.id, created.serial_number)
        self.assertEqual(created.requested_sans, ["alias.example", "svc.internal"])

    async def test_import_rejects_certificates_of_another_ca(self):
        self.crud._get = AsyncMock(
            return_value={"id": "ca1", "certificate": self.other_cert_pem.decode()}
        )
        self.crud_certificates.create = AsyncMock()

        with self.assertRaises(QueryParamValidationError) as ctx:
            await self.service.import_certificate(
                "space1", self._issued("node9", []), fields=[]
            )

        self.assertIn("not issued by", ctx.exception.detail)
        self.crud_certificates.create.assert_not_called()

    async def test_import_rejects_expired_certificates(self):
        self.crud._get = AsyncMock(
            return_value={"id": "ca1", "certificate": self.cert_pem.decode()}
        )
        self.crud_certificates.create = AsyncMock()
        expired = {
            **crypto.get_cert_info(self._issued("node9", [])),
            "not_after": datetime.datetime(2020, 1, 1, tzinfo=datetime.timezone.utc),
        }

        with patch.object(crypto, "get_cert_info", return_value=expired):
            with self.assertRaises(QueryParamValidationError) as ctx:
                await self.service.import_certificate(
                    "space1", self._issued("node9", []), fields=[]
                )

        self.assertIn("expired", ctx.exception.detail)
        self.crud_certificates.create.assert_not_called()


if __name__ == "__main__":
    unittest.main()
