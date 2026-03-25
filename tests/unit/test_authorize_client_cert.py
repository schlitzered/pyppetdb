import unittest
from unittest.mock import MagicMock
import logging
from pyppetdb.authorize import AuthorizeClientCert
from pyppetdb.errors import ClientCertError


class TestAuthorizeClientCert(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.trusted_cns = ["admin.example.com", "puppet-master.example.com"]
        self.auth = AuthorizeClientCert(self.log, self.trusted_cns)

    def _create_mock_request(self, cert_dict=None):
        mock_request = MagicMock()
        mock_request.scope = {}
        if cert_dict:
            mock_request.scope["client_cert_dict"] = cert_dict
        return mock_request

    async def test_get_cn_from_request_success(self):
        cert_dict = {
            "subject": (
                (("commonName", "admin.example.com"),),
                (("organizationName", "PyppetDB"),),
            )
        }
        mock_request = self._create_mock_request(cert_dict)
        cn = self.auth.get_cert_info(mock_request)
        self.assertEqual(cn, "admin.example.com")

    async def test_get_cn_from_request_no_cert(self):
        mock_request = self._create_mock_request(None)
        cn = self.auth.get_cert_info(mock_request)
        self.assertIsNone(cn)

    async def test_require_cn(self):
        cert_dict = {"subject": ((("commonName", "any.example.com"),),)}
        mock_request = self._create_mock_request(cert_dict)
        cn = await self.auth.require_cn(mock_request)
        self.assertEqual(cn, "any.example.com")

    async def test_require_cn_trusted_success(self):
        cert_dict = {"subject": ((("commonName", "admin.example.com"),),)}
        mock_request = self._create_mock_request(cert_dict)
        cn = await self.auth.require_cn_trusted(mock_request)
        self.assertEqual(cn, "admin.example.com")

    async def test_require_cn_trusted_untrusted(self):
        cert_dict = {"subject": ((("commonName", "untrusted.example.com"),),)}
        mock_request = self._create_mock_request(cert_dict)
        with self.assertRaises(ClientCertError):
            await self.auth.require_cn_trusted(mock_request)

    async def test_require_cn_match_success(self):
        cert_dict = {"subject": ((("commonName", "match.example.com"),),)}
        mock_request = self._create_mock_request(cert_dict)
        cn = await self.auth.require_cn_match(mock_request, "match.example.com")
        self.assertEqual(cn, "match.example.com")

    async def test_require_cn_match_failure(self):
        cert_dict = {"subject": ((("commonName", "no-match.example.com"),),)}
        mock_request = self._create_mock_request(cert_dict)
        with self.assertRaises(ClientCertError):
            await self.auth.require_cn_match(mock_request, "match.example.com")
