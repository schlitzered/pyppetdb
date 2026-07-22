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
from unittest.mock import MagicMock, AsyncMock, patch

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from pyppetdb.ca.service import CAService
from pyppetdb.model.ca_certificates import CACertificateGet, CACertificatePut
from pyppetdb.model.ca_validation import (
    CAValidationConfig,
    CASANValidation,
    CAHTTPValidation,
)
from pyppetdb.errors import QueryParamValidationError, ResourceNotFound


def _generate_csr(cn, san=None):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    builder = x509.CertificateSigningRequestBuilder().subject_name(
        x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    )
    if san:
        builder = builder.add_extension(
            x509.SubjectAlternativeName([x509.DNSName(s) for s in san]),
            critical=False,
        )
    csr = builder.sign(private_key, hashes.SHA256())
    return csr


class _ServiceTestBase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = MagicMock()
        self.config = MagicMock()
        self.config.ca.concurrentWorkers = 2
        self.crud_authorities = AsyncMock()
        self.crud_spaces = AsyncMock()
        self.crud_certificates = AsyncMock()
        self.crud_pyppetdb_nodes = MagicMock()
        self.crud_secrets = AsyncMock()
        self.crud_secrets.get_values = AsyncMock(return_value={})
        self.service = CAService(
            log=self.log,
            config=self.config,
            crud_authorities=self.crud_authorities,
            crud_spaces=self.crud_spaces,
            crud_certificates=self.crud_certificates,
            crud_pyppetdb_nodes=self.crud_pyppetdb_nodes,
            crud_secrets=self.crud_secrets,
        )


class TestRevocationOwnership(_ServiceTestBase):
    async def test_revoke_by_ca_rejects_cert_of_other_ca(self):
        self.crud_certificates.get.return_value = CACertificateGet(
            id="99", ca_id="ca-b"
        )
        self.service.revoke_certificate = AsyncMock()

        with self.assertRaises(ResourceNotFound):
            await self.service.update_certificate_status_by_ca(
                ca_id="ca-a",
                cert_id="99",
                payload=CACertificatePut(status="revoked"),
                fields=[],
            )

        self.service.revoke_certificate.assert_not_called()

    async def test_revoke_by_ca_allows_cert_of_same_ca(self):
        self.crud_certificates.get.return_value = CACertificateGet(
            id="99", ca_id="ca-a"
        )
        revoked = CACertificateGet(id="99", ca_id="ca-a", status="revoked")
        self.service.revoke_certificate = AsyncMock(return_value=revoked)

        result = await self.service.update_certificate_status_by_ca(
            ca_id="ca-a",
            cert_id="99",
            payload=CACertificatePut(status="revoked"),
            fields=[],
        )

        self.assertIs(result, revoked)
        self.service.revoke_certificate.assert_called_once_with(_id="99")

    async def test_revoke_by_ca_missing_cert_raises_not_found(self):
        self.crud_certificates.get.side_effect = ResourceNotFound()
        self.service.revoke_certificate = AsyncMock()

        with self.assertRaises(ResourceNotFound):
            await self.service.update_certificate_status_by_ca(
                ca_id="ca-a",
                cert_id="missing",
                payload=CACertificatePut(status="revoked"),
                fields=[],
            )
        self.service.revoke_certificate.assert_not_called()

    async def test_revoke_by_ca_rejects_non_revoke_transition(self):
        with self.assertRaises(QueryParamValidationError):
            await self.service.update_certificate_status_by_ca(
                ca_id="ca-a",
                cert_id="1",
                payload=CACertificatePut(status="signed"),
                fields=[],
            )
        self.crud_certificates.get.assert_not_called()


class TestRevocationCacheInvalidation(_ServiceTestBase):
    async def test_revoke_notifies_listeners_with_serial(self):
        self.crud_certificates.update.return_value = CACertificateGet(
            id="serial-1", status="revoked"
        )
        seen = []
        self.service.add_revocation_listener(lambda serial: seen.append(serial))

        await self.service.revoke_certificate(_id="serial-1")

        self.assertEqual(seen, ["serial-1"])

    async def test_revoke_notifies_even_when_already_revoked(self):
        self.crud_certificates.update.side_effect = ResourceNotFound()
        self.crud_certificates.get.return_value = CACertificateGet(
            id="serial-2", status="revoked"
        )
        seen = []
        self.service.add_revocation_listener(lambda serial: seen.append(serial))

        await self.service.revoke_certificate(_id="serial-2")

        self.assertEqual(seen, ["serial-2"])

    async def test_listener_failure_does_not_break_revocation(self):
        self.crud_certificates.update.return_value = CACertificateGet(
            id="serial-3", status="revoked"
        )

        def boom(serial):
            raise RuntimeError("listener down")

        self.service.add_revocation_listener(boom)

        result = await self.service.revoke_certificate(_id="serial-3")
        self.assertEqual(result.status, "revoked")


class TestSanRfc1123Validation(_ServiceTestBase):
    async def test_malformed_san_rejected_when_honored(self):
        csr = _generate_csr("node.example.com", san=["bad_underscore.example.com"])
        ca_config = CAValidationConfig(
            enforce_rfc1123=True,
            san_validation=CASANValidation(max_san_count=10),
        )
        with self.assertRaises(QueryParamValidationError) as cm:
            await self.service._validate_csr(
                csr=csr,
                cn="node.example.com",
                ca_config=ca_config,
                space_config=CAValidationConfig(enforce_rfc1123=True),
                ca_id="ca1",
                space_id="space1",
            )
        self.assertIn("does not follow strict RFC 1123", str(cm.exception))

    async def test_uppercase_san_rejected_when_honored(self):
        csr = _generate_csr("node.example.com", san=["Evil.Example.Com"])
        ca_config = CAValidationConfig(
            enforce_rfc1123=True,
            san_validation=CASANValidation(max_san_count=10),
        )
        with self.assertRaises(QueryParamValidationError):
            await self.service._validate_csr(
                csr=csr,
                cn="node.example.com",
                ca_config=ca_config,
                space_config=CAValidationConfig(enforce_rfc1123=True),
                ca_id="ca1",
                space_id="space1",
            )

    async def test_valid_san_accepted(self):
        csr = _generate_csr("node.example.com", san=["alt.example.com"])
        ca_config = CAValidationConfig(
            enforce_rfc1123=True,
            san_validation=CASANValidation(max_san_count=10),
        )
        await self.service._validate_csr(
            csr=csr,
            cn="node.example.com",
            ca_config=ca_config,
            space_config=CAValidationConfig(enforce_rfc1123=True),
            ca_id="ca1",
            space_id="space1",
        )

    async def test_malformed_san_ignored_when_not_honored(self):
        csr = _generate_csr("node.example.com", san=["bad_underscore.example.com"])
        await self.service._validate_csr(
            csr=csr,
            cn="node.example.com",
            ca_config=CAValidationConfig(enforce_rfc1123=True),
            space_config=CAValidationConfig(enforce_rfc1123=True),
            ca_id="ca1",
            space_id="space1",
        )

    async def test_malformed_san_allowed_when_rfc1123_disabled(self):
        csr = _generate_csr("node.example.com", san=["bad_underscore.example.com"])
        ca_config = CAValidationConfig(
            enforce_rfc1123=False,
            san_validation=CASANValidation(max_san_count=10),
        )
        await self.service._validate_csr(
            csr=csr,
            cn="node.example.com",
            ca_config=ca_config,
            space_config=CAValidationConfig(enforce_rfc1123=False),
            ca_id="ca1",
            space_id="space1",
        )


class TestHttpValidationInjection(_ServiceTestBase):
    @patch("httpx.AsyncClient.request")
    async def test_cn_is_url_encoded_in_validation_url(self, mock_request):
        mock_request.return_value = MagicMock(is_error=False, status_code=200)
        config = CAHTTPValidation(url="http://validate.me/check/{cert_cn}")

        await self.service._execute_http_validation(
            cn="evil/../../admin?x=1",
            sans=[],
            config=config,
            ca_id="ca1",
            space_id="space1",
        )

        _, kwargs = mock_request.call_args
        self.assertEqual(
            kwargs["url"],
            "http://validate.me/check/evil%2F..%2F..%2Fadmin%3Fx%3D1",
        )

    @patch("httpx.AsyncClient.request")
    async def test_cn_is_json_escaped_in_body_template(self, mock_request):
        mock_request.return_value = MagicMock(is_error=False, status_code=200)
        config = CAHTTPValidation(
            url="http://validate.me",
            method="POST",
            body_template='{"host": "{{cn}}", "trusted": false}',
        )

        await self.service._execute_http_validation(
            cn='x", "trusted": true, "y": "',
            sans=[],
            config=config,
            ca_id="ca1",
            space_id="space1",
        )

        _, kwargs = mock_request.call_args
        body = kwargs["json"]
        self.assertFalse(body["trusted"])
        self.assertEqual(body["host"], 'x", "trusted": true, "y": "')

    @patch("httpx.AsyncClient.request")
    async def test_plain_cn_url_unchanged(self, mock_request):
        mock_request.return_value = MagicMock(is_error=False, status_code=200)
        config = CAHTTPValidation(url="http://validate.me/{ca_id}/{space_id}/{cert_cn}")

        await self.service._execute_http_validation(
            cn="node1.example.com",
            sans=[],
            config=config,
            ca_id="ca1",
            space_id="space1",
        )

        _, kwargs = mock_request.call_args
        self.assertEqual(
            kwargs["url"], "http://validate.me/ca1/space1/node1.example.com"
        )


if __name__ == "__main__":
    unittest.main()
