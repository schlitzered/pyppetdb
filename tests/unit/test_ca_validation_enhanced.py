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
from unittest.mock import MagicMock, patch, AsyncMock
from pyppetdb.ca.service import CAService
from pyppetdb.model.ca_validation import (
    CAValidationConfig,
    CASANValidation,
    CAHTTPValidation,
    CAHTTPHeader,
)
from pyppetdb.model.ca_certificates import CACertificateGet
from pyppetdb.errors import QueryParamValidationError, ResourceNotFound
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


class TestCAServiceValidationEnhanced(unittest.IsolatedAsyncioTestCase):
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

    def _generate_csr(self, cn, san=None):
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
        return csr.public_bytes(serialization.Encoding.PEM).decode(), csr

    async def test_validate_subject_name_rfc1123_invalid(self):
        csr_pem, csr_obj = self._generate_csr("Test.Example.Com")
        ca_config = CAValidationConfig(enforce_rfc1123=True)
        with self.assertRaises(QueryParamValidationError) as cm:
            await self.service._validate_csr(
                csr=csr_obj,
                cn="Test.Example.Com",
                ca_config=ca_config,
                space_config=CAValidationConfig(),
                ca_id="ca1",
                space_id="space1",
            )
        self.assertIn("does not follow strict RFC 1123", str(cm.exception))

    async def test_validate_san_max_count_exceeded(self):
        csr_pem, csr_obj = self._generate_csr(
            "test.com", san=["a.com", "b.com", "c.com"]
        )
        ca_config = CAValidationConfig(san_validation=CASANValidation(max_san_count=2))
        with self.assertRaises(QueryParamValidationError) as cm:
            await self.service._validate_csr(
                csr=csr_obj,
                cn="test.com",
                ca_config=ca_config,
                space_config=CAValidationConfig(),
                ca_id="ca1",
                space_id="space1",
            )
        self.assertIn("exceeds maximum allowed", str(cm.exception))

    async def test_validate_san_regex_mismatch(self):
        csr_pem, csr_obj = self._generate_csr("test.com", san=["forbidden.com"])
        ca_config = CAValidationConfig(
            san_validation=CASANValidation(regex_list=[r".*\.example\.com$"])
        )
        with self.assertRaises(QueryParamValidationError) as cm:
            await self.service._validate_csr(
                csr=csr_obj,
                cn="test.com",
                ca_config=ca_config,
                space_config=CAValidationConfig(),
                ca_id="ca1",
                space_id="space1",
            )
        self.assertIn("does not match any allowed patterns", str(cm.exception))

    @patch("httpx.AsyncClient.request")
    async def test_validate_san_http_failure(self, mock_request):
        mock_request.return_value = MagicMock(is_error=True, status_code=403)
        csr_pem, csr_obj = self._generate_csr("test.com", san=["a.com"])
        ca_config = CAValidationConfig(
            san_validation=CASANValidation(
                http_checks=[CAHTTPValidation(url="http://validate.me")]
            )
        )
        with self.assertRaises(QueryParamValidationError) as cm:
            await self.service._validate_csr(
                csr=csr_obj,
                cn="test.com",
                ca_config=ca_config,
                space_config=CAValidationConfig(),
                ca_id="ca1",
                space_id="space1",
            )
        self.assertIn(
            "External HTTP validation failed with status 403", str(cm.exception)
        )

    @patch("httpx.AsyncClient.request")
    async def test_validate_san_http_placeholders(self, mock_request):
        mock_request.return_value = MagicMock(is_error=False, status_code=200)
        csr_pem, csr_obj = self._generate_csr("test.com", san=["a.com"])
        ca_config = CAValidationConfig(
            san_validation=CASANValidation(
                http_checks=[
                    CAHTTPValidation(
                        url="http://validate.me/{ca_id}/{space_id}/{cert_cn}",
                        method="PUT",
                    )
                ]
            )
        )
        await self.service._validate_csr(
            csr=csr_obj,
            cn="test.com",
            ca_config=ca_config,
            space_config=CAValidationConfig(),
            ca_id="ca1",
            space_id="space1",
        )
        args, kwargs = mock_request.call_args
        self.assertEqual(kwargs["url"], "http://validate.me/ca1/space1/test.com")
        self.assertEqual(kwargs["method"], "PUT")

    @patch("httpx.AsyncClient.request")
    async def test_validate_san_http_basic_auth(self, mock_request):
        mock_request.return_value = MagicMock(is_error=False, status_code=200)
        csr_pem, csr_obj = self._generate_csr("test.com", san=["a.com"])

        ca_config = CAValidationConfig(
            san_validation=CASANValidation(
                http_checks=[
                    CAHTTPValidation(
                        url="http://validate.me",
                        basic_auth_enabled=True,
                        username="user1",
                        password="pass1",
                        headers=[
                            CAHTTPHeader(name="X-Secret", value="secret")
                        ],
                    )
                ]
            )
        )
        await self.service._validate_csr(
            csr=csr_obj,
            cn="test.com",
            ca_config=ca_config,
            space_config=CAValidationConfig(),
            ca_id="myca",
            space_id="myspace",
        )
        args, kwargs = mock_request.call_args
        self.assertEqual(kwargs["auth"], ("user1", "pass1"))
        self.assertEqual(kwargs["headers"]["X-Secret"], "secret")

    @patch("asyncio.create_subprocess_exec")
    async def test_validate_san_script_failure(self, mock_exec):
        mock_proc = MagicMock()
        mock_proc.communicate = AsyncMock(return_value=(b"output", b"error"))
        mock_proc.returncode = 1
        mock_exec.return_value = mock_proc

        csr_pem, csr_obj = self._generate_csr("test.com", san=["a.com"])
        from pyppetdb.model.ca_validation import CAScriptValidation

        ca_config = CAValidationConfig(
            san_validation=CASANValidation(
                script_checks=[
                    CAScriptValidation(script_path="/bin/false", timeout_seconds=1)
                ]
            )
        )
        with self.assertRaises(QueryParamValidationError) as cm:
            await self.service._validate_csr(
                csr=csr_obj,
                cn="test.com",
                ca_config=ca_config,
                space_config=CAValidationConfig(),
                ca_id="ca1",
                space_id="space1",
            )
        self.assertIn("External script validation failed (exit 1)", str(cm.exception))

    async def test_validate_san_multiple_configs(self):
        csr_pem, csr_obj = self._generate_csr("test.com", san=["a.example.com"])

        # CA config allows anything
        ca_config = CAValidationConfig(
            san_validation=CASANValidation(regex_list=[r".*"])
        )
        # Space config restricts to example.com
        space_config = CAValidationConfig(
            san_validation=CASANValidation(regex_list=[r".*\.example\.com$"])
        )

        # Should pass
        await self.service._validate_csr(
            csr=csr_obj,
            cn="test.com",
            ca_config=ca_config,
            space_config=space_config,
            ca_id="ca1",
            space_id="space1",
        )

        # Now try with a non-matching SAN in space config
        csr_pem2, csr_obj2 = self._generate_csr("test.com", san=["a.other.com"])
        with self.assertRaises(QueryParamValidationError) as cm:
            await self.service._validate_csr(
                csr=csr_obj2,
                cn="test.com",
                ca_config=ca_config,
                space_config=space_config,
                ca_id="ca1",
                space_id="space1",
            )
        self.assertIn("does not match any allowed patterns", str(cm.exception))

    async def test_get_injected_sans_success(self):
        from pyppetdb.model.ca_validation import CASANInjection

        cn = "www-1.prod.fra.dc.example.com"
        configs = [
            CAValidationConfig(
                san_injection=[
                    CASANInjection(
                        pattern=r"^(?P<svc>www)-\d+\.(?P<domain>prod\.fra\.dc\.example\.com)$",
                        templates=["{svc}-svc.{domain}", "{1}-admin.{2}"],
                    )
                ]
            )
        ]
        injected = await self.service._get_injected_sans(cn, configs)
        self.assertIn("www-svc.prod.fra.dc.example.com", injected)
        self.assertIn("www-admin.prod.fra.dc.example.com", injected)
        self.assertEqual(len(injected), 2)

    @patch("pyppetdb.ca.utils.CAUtils.get_cert_info")
    @patch("pyppetdb.ca.utils.CAUtils.sign_csr")
    async def test_sign_certificate_with_injection(self, mock_sign_csr, mock_get_info):
        from pyppetdb.model.ca_validation import CASANInjection
        from pyppetdb.model.ca_authorities import CAAuthorityGet
        from pyppetdb.model.ca_spaces import CASpaceGet

        self.config.ca.autoSign = True
        self.crud_certificates.get_by_cn.side_effect = ResourceNotFound
        self.crud_certificates.create.return_value = MagicMock(id="123")
        self.crud_certificates.get.return_value = MagicMock(
            id="123", space_id="space1", cn="node-1", csr="PEM", status="requested"
        )
        mock_sign_csr.return_value = b"CERT_PEM"
        mock_get_info.return_value = {"cn": "node-1", "serial_number": "12345"}

        ca_config = CAValidationConfig(
            san_injection=[
                CASANInjection(pattern="node-(.*)", templates=["svc-{1}.com"])
            ]
        )

        self.crud_spaces.get.return_value = CASpaceGet(
            ca_id="ca1", validation_config=CAValidationConfig()
        )
        self.crud_authorities.get.return_value = CAAuthorityGet(
            id="ca1", validation_config=ca_config
        )
        # Mock resources loading
        self.service._get_ca_resources = AsyncMock(
            return_value=(MagicMock(), MagicMock())
        )

        csr_pem, _ = self._generate_csr("node-1")

        # Mock certificates crud
        cert_req = CACertificateGet(
            id="123", space_id="space1", cn="node-1", csr=csr_pem, status="requested"
        )

        async def get_by_cn_mock(space_id, cn, status=None, fields=None):
            if status == "signed":
                raise ResourceNotFound()
            return cert_req

        self.crud_certificates.get_by_cn.side_effect = get_by_cn_mock
        self.crud_certificates.get.return_value = cert_req
        self.crud_certificates.update.return_value = cert_req

        await self.service.submit_certificate_request(
            space_id="space1",
            csr_pem=csr_pem,
            cn="node-1",
            fields=[],
        )

        await self.service.sign_certificate(
            space_id="space1",
            cn="node-1",
            fields=[],
        )

        # Check if injected SAN was passed to sign_csr
        args, kwargs = mock_sign_csr.call_args
        # injected_sans is the 9th positional argument (index 8)
        self.assertIn("svc-1.com", args[8])
