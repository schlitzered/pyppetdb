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
from unittest.mock import MagicMock
from unittest.mock import AsyncMock
import logging
from pyppetdb.authorize import AuthorizeClientCert
from pyppetdb.errors import ClientCertError


class TestAuthorizeClientCert(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.trusted_cns = ["admin.example.com", "puppet-master.example.com"]
        self.config = MagicMock()
        self.config.ca.verifyCertificateRegistration = True
        self.config.ca.verifyCertificateRegistrationCacheTtl = 300
        self.config.ca.verifyCertificateRegistrationCacheMaxsize = 1024
        self.crud_ca_certificates = MagicMock()
        self.crud_ca_certificates.get_internal_object_id = AsyncMock(
            return_value="000000000000000000000001"
        )
        self.auth = AuthorizeClientCert(
            log=self.log,
            config=self.config,
            trusted_cns=self.trusted_cns,
            crud_ca_certificates=self.crud_ca_certificates,
        )

    def _create_mock_request(self, cert_dict=None):
        mock_request = MagicMock()
        mock_request.scope = {}
        if cert_dict:
            mock_request.scope["client_cert_dict"] = cert_dict
        return mock_request

    def _setup_mock_cert(self, cn, status="signed", object_id="000000000000000000000001"):
        self.crud_ca_certificates.get_internal_object_id.return_value = object_id

    async def test_get_cn_from_request_success(self):
        cert_dict = {
            "subject": ((("commonName", "admin.example.com"),),),
            "serialNumber": "01",
        }
        self._setup_mock_cert("admin.example.com")
        mock_request = self._create_mock_request(cert_dict)
        cert_info = await self.auth.get_cert_info(mock_request)
        self.assertEqual(cert_info["cn"], "admin.example.com")
        self.assertEqual(cert_info["serial"], "1")
        self.crud_ca_certificates.get_internal_object_id.assert_called_once()

    async def test_registration_check_is_scoped_to_puppet_ca_space(self):
        cert_dict = {
            "subject": ((("commonName", "admin.example.com"),),),
            "serialNumber": "01",
        }
        self._setup_mock_cert("admin.example.com")
        mock_request = self._create_mock_request(cert_dict)

        await self.auth.get_cert_info(mock_request)

        _, kwargs = self.crud_ca_certificates.get_internal_object_id.call_args
        self.assertEqual(kwargs["space_id"], "puppet-ca")
        self.assertEqual(kwargs["cn"], "admin.example.com")
        self.assertEqual(kwargs["serial"], "1")

    async def test_get_cn_from_request_cache(self):
        cert_dict = {
            "subject": ((("commonName", "admin.example.com"),),),
            "serialNumber": "01",
        }
        self._setup_mock_cert("admin.example.com")
        mock_request = self._create_mock_request(cert_dict)

        # First call - should hit DB
        await self.auth.get_cert_info(mock_request)
        self.crud_ca_certificates.get_internal_object_id.assert_called_once()

        # Second call - should hit cache
        await self.auth.get_cert_info(mock_request)
        self.crud_ca_certificates.get_internal_object_id.assert_called_once()

    async def test_get_cn_from_request_bypass(self):
        self.config.ca.verifyCertificateRegistration = False
        cert_dict = {
            "subject": ((("commonName", "admin.example.com"),),),
            "serialNumber": "01",
        }
        mock_request = self._create_mock_request(cert_dict)
        await self.auth.get_cert_info(mock_request)
        self.crud_ca_certificates.get_internal_object_id.assert_not_called()

    async def test_get_cn_from_request_no_cert(self):
        mock_request = self._create_mock_request(None)
        with self.assertRaises(ClientCertError):
            await self.auth.get_cert_info(mock_request)

    async def test_require_cn_success(self):
        cert_dict = {
            "subject": ((("commonName", "any.example.com"),),),
            "serialNumber": "02",
        }
        self._setup_mock_cert("any.example.com")
        mock_request = self._create_mock_request(cert_dict)
        cn = await self.auth.require_cn(mock_request)
        self.assertEqual(cn, "any.example.com")

    async def test_require_cn_trusted_success(self):
        cert_dict = {
            "subject": ((("commonName", "admin.example.com"),),),
            "serialNumber": "03",
        }
        self._setup_mock_cert("admin.example.com")
        mock_request = self._create_mock_request(cert_dict)
        cn = await self.auth.require_cn_trusted(mock_request)
        self.assertEqual(cn, "admin.example.com")

    async def test_require_cn_trusted_failure(self):
        cert_dict = {
            "subject": ((("commonName", "untrusted.example.com"),),),
            "serialNumber": "04",
        }
        self._setup_mock_cert("untrusted.example.com")
        mock_request = self._create_mock_request(cert_dict)
        with self.assertRaises(ClientCertError):
            await self.auth.require_cn_trusted(mock_request)

    async def test_require_cn_match_success(self):
        cert_dict = {
            "subject": ((("commonName", "match.example.com"),),),
            "serialNumber": "05",
        }
        self._setup_mock_cert("match.example.com")
        mock_request = self._create_mock_request(cert_dict)
        cn = await self.auth.require_cn_match(mock_request, "match.example.com")
        self.assertEqual(cn, "match.example.com")

    async def test_require_cn_match_failure(self):
        cert_dict = {
            "subject": ((("commonName", "no-match.example.com"),),),
            "serialNumber": "06",
        }
        self._setup_mock_cert("no-match.example.com")
        mock_request = self._create_mock_request(cert_dict)
        with self.assertRaises(ClientCertError) as cm:
            await self.auth.require_cn_match(mock_request, "match.example.com")
        self.assertEqual(
            cm.exception.detail,
            "CN no-match.example.com does not match match.example.com",
        )

    async def test_invalidate_serial_forces_db_recheck(self):
        cert_dict = {
            "subject": ((("commonName", "admin.example.com"),),),
            "serialNumber": "01",
        }
        self._setup_mock_cert("admin.example.com")
        mock_request = self._create_mock_request(cert_dict)

        await self.auth.get_cert_info(mock_request)
        self.crud_ca_certificates.get_internal_object_id.assert_called_once()

        self.auth.invalidate_serial("1")

        await self.auth.get_cert_info(mock_request)
        self.assertEqual(
            self.crud_ca_certificates.get_internal_object_id.call_count, 2
        )

    async def test_invalidate_unknown_serial_is_noop(self):
        self.auth.invalidate_serial("does-not-exist")

    async def test_invalidate_object_id_evicts_matching_serial(self):
        cert_dict = {
            "subject": ((("commonName", "admin.example.com"),),),
            "serialNumber": "01",
        }
        self._setup_mock_cert("admin.example.com", object_id="deadbeefcafe")
        mock_request = self._create_mock_request(cert_dict)
        await self.auth.get_cert_info(mock_request)
        self.crud_ca_certificates.get_internal_object_id.assert_called_once()

        self.auth.invalidate_object_id("deadbeefcafe")

        await self.auth.get_cert_info(mock_request)
        self.assertEqual(
            self.crud_ca_certificates.get_internal_object_id.call_count, 2
        )

    async def test_invalidate_object_id_leaves_other_serials(self):
        self._setup_mock_cert("admin.example.com", object_id="aaa")
        await self.auth.get_cert_info(
            self._create_mock_request(
                {
                    "subject": ((("commonName", "admin.example.com"),),),
                    "serialNumber": "01",
                }
            )
        )
        self._setup_mock_cert("puppet-master.example.com", object_id="bbb")
        await self.auth.get_cert_info(
            self._create_mock_request(
                {
                    "subject": ((("commonName", "puppet-master.example.com"),),),
                    "serialNumber": "02",
                }
            )
        )
        self.assertEqual(
            self.crud_ca_certificates.get_internal_object_id.call_count, 2
        )

        self.auth.invalidate_object_id("aaa")

        await self.auth.get_cert_info(
            self._create_mock_request(
                {
                    "subject": ((("commonName", "puppet-master.example.com"),),),
                    "serialNumber": "02",
                }
            )
        )
        self.assertEqual(
            self.crud_ca_certificates.get_internal_object_id.call_count, 2
        )

    async def test_invalidate_unknown_object_id_is_noop(self):
        self.auth.invalidate_object_id("never-cached")

    async def test_verify_registration_cn_mismatch(self):
        from pyppetdb.errors import ResourceNotFound

        cert_dict = {
            "subject": ((("commonName", "cert-cn.example.com"),),),
            "serialNumber": "07",
        }
        # Mock database returning ResourceNotFound when CN is part of the query and doesn't match
        self.crud_ca_certificates.get_internal_object_id.side_effect = ResourceNotFound
        mock_request = self._create_mock_request(cert_dict)
        with self.assertRaises(ClientCertError) as cm:
            await self.auth.get_cert_info(mock_request)
        self.assertEqual(cm.exception.detail, "Certificate not found in database")
