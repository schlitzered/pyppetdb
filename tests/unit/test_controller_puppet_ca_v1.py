import unittest
from unittest.mock import MagicMock, AsyncMock
import logging
from fastapi import HTTPException, Response
from pyppetdb.controller.puppet_ca.v1.ca import ControllerPuppetCaV1CA
from pyppetdb.errors import ResourceNotFound


class TestControllerPuppetCaV1CAUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_config = MagicMock()
        self.mock_crud_authorities = MagicMock()
        self.mock_crud_spaces = MagicMock()
        self.mock_crud_spaces.get = AsyncMock()
        self.mock_crud_certificates = MagicMock()
        self.mock_crud_certificates.coll = AsyncMock()
        self.mock_ca_service = MagicMock()
        self.mock_ca_service.get_certificate_chain = AsyncMock()
        self.mock_ca_service.get_crl_chain = AsyncMock()
        self.mock_ca_service.submit_certificate_request = AsyncMock()
        self.mock_ca_service.sign_certificate = AsyncMock()
        self.mock_ca_service.revoke_certificate = AsyncMock()
        self.mock_ca_service.update_certificate_status = AsyncMock()

        self.mock_auth_cert = MagicMock()
        self.mock_auth_cert.require_cn_trusted = AsyncMock()

        self.controller = ControllerPuppetCaV1CA(
            self.log,
            self.mock_config,
            self.mock_crud_authorities,
            self.mock_crud_spaces,
            self.mock_crud_certificates,
            self.mock_ca_service,
            self.mock_auth_cert,
        )

    async def test_get_certificate_ca(self):
        self.mock_ca_service.get_certificate_chain.return_value = b"CA_CHAIN"
        mock_request = MagicMock()

        response = await self.controller.get_certificate("ca", mock_request)
        self.assertIsInstance(response, Response)
        self.assertEqual(response.body, b"CA_CHAIN")

    async def test_get_certificate_node(self):
        self.mock_crud_certificates.coll.find_one.return_value = {
            "certificate": b"NODE_CERT",
            "status": "signed",
        }
        mock_request = MagicMock()

        response = await self.controller.get_certificate("node1", mock_request)
        self.assertEqual(response.body, b"NODE_CERT")

    async def test_get_certificate_not_found(self):
        self.mock_crud_certificates.coll.find_one.return_value = None
        mock_request = MagicMock()

        with self.assertRaises(HTTPException) as cm:
            await self.controller.get_certificate("node1", mock_request)
        self.assertEqual(cm.exception.status_code, 404)

    async def test_submit_certificate_request(self):
        from pyppetdb.ca.utils import CAUtils
        csr_pem, _ = CAUtils.generate_csr("node1")
        mock_request = MagicMock()
        mock_request.body = AsyncMock(return_value=csr_pem)
        self.mock_config.ca.autoSign = False

        response = await self.controller.submit_certificate_request(
            "node1", mock_request
        )
        self.assertEqual(response.body, b"CSR submitted")
        self.mock_ca_service.submit_certificate_request.assert_called_once_with(
            space_id="puppet-ca",
            csr_pem=csr_pem.decode(),
            fields=["id"],
            cn="node1",
        )

    async def test_submit_certificate_request_mismatch(self):
        from pyppetdb.errors import QueryParamValidationError
        from pyppetdb.ca.utils import CAUtils
        csr_pem, _ = CAUtils.generate_csr("attacker")
        mock_request = MagicMock()
        mock_request.body = AsyncMock(return_value=csr_pem)
        self.mock_config.ca.autoSign = False
        self.mock_ca_service.submit_certificate_request.side_effect = (
            QueryParamValidationError(msg="mismatch")
        )

        with self.assertRaises(HTTPException) as cm:
            await self.controller.submit_certificate_request("node1", mock_request)
        self.assertEqual(cm.exception.status_code, 400)
        self.assertEqual(cm.exception.detail, "mismatch")

    async def test_submit_certificate_request_invalid_csr(self):
        from pyppetdb.errors import QueryParamValidationError
        mock_request = MagicMock()
        mock_request.body = AsyncMock(return_value=b"INVALID_CSR")
        self.mock_config.ca.autoSign = False
        self.mock_ca_service.submit_certificate_request.side_effect = (
            QueryParamValidationError(msg="Invalid CSR")
        )

        with self.assertRaises(HTTPException) as cm:
            await self.controller.submit_certificate_request("node1", mock_request)
        self.assertEqual(cm.exception.status_code, 400)
        self.assertEqual(cm.exception.detail, "Invalid CSR")

    async def test_get_certificate_status(self):
        self.mock_crud_certificates.coll.find_one.return_value = {
            "cn": "node1",
            "status": "signed",
            "fingerprint": {"sha256": "f1"},
        }
        mock_request = MagicMock()

        result = await self.controller.get_certificate_status("node1", mock_request)
        self.assertEqual(result["name"], "node1")
        self.assertEqual(result["state"], "signed")

    async def test_get_crl(self):
        self.mock_ca_service.get_crl_chain.return_value = b"CRL_PEM"

        response = await self.controller.get_crl()
        self.assertEqual(response.body, b"CRL_PEM")

    async def test_get_certificate_status_not_found(self):
        self.mock_crud_certificates.coll.find_one.return_value = None
        mock_request = MagicMock()

        with self.assertRaises(HTTPException) as cm:
            await self.controller.get_certificate_status("node1", mock_request)
        self.assertEqual(cm.exception.status_code, 404)

    async def test_get_crl_not_found(self):
        self.mock_ca_service.get_crl_chain.side_effect = ResourceNotFound("CRL")

        with self.assertRaises(HTTPException) as cm:
            await self.controller.get_crl()
        self.assertEqual(cm.exception.status_code, 404)

    async def test_get_certificate_status_error(self):
        self.mock_crud_certificates.coll.find_one.side_effect = Exception("DB error")
        mock_request = MagicMock()

        with self.assertRaises(Exception) as cm:
            await self.controller.get_certificate_status("node1", mock_request)
        self.assertEqual(str(cm.exception), "DB error")

    async def test_get_certificate_ca_not_found(self):
        self.mock_ca_service.get_certificate_chain.side_effect = ResourceNotFound(
            "Space"
        )
        mock_request = MagicMock()
        with self.assertRaises(HTTPException) as cm:
            await self.controller.get_certificate("ca", mock_request)
        self.assertEqual(cm.exception.status_code, 404)

    async def test_get_certificate_request_success(self):
        self.mock_crud_certificates.coll.find_one.return_value = {
            "csr": b"CSR_DATA",
            "status": "requested",
        }
        mock_request = MagicMock()
        response = await self.controller.get_certificate_request("node1", mock_request)
        self.assertEqual(response.body, b"CSR_DATA")

    async def test_get_certificate_request_not_found(self):
        self.mock_crud_certificates.coll.find_one.return_value = None
        mock_request = MagicMock()
        with self.assertRaises(HTTPException) as cm:
            await self.controller.get_certificate_request("node1", mock_request)
        self.assertEqual(cm.exception.status_code, 404)

    async def test_submit_certificate_request_autosign_success(self):
        from pyppetdb.ca.utils import CAUtils
        csr_pem, _ = CAUtils.generate_csr("node1")
        mock_request = MagicMock()
        mock_request.body = AsyncMock(return_value=csr_pem)
        self.mock_config.ca.autoSign = True

        await self.controller.submit_certificate_request("node1", mock_request)
        self.mock_ca_service.sign_certificate.assert_called_once()

    async def test_submit_certificate_request_autosign_error(self):
        from pyppetdb.ca.utils import CAUtils
        csr_pem, _ = CAUtils.generate_csr("node1")
        mock_request = MagicMock()
        mock_request.body = AsyncMock(return_value=csr_pem)
        self.mock_config.ca.autoSign = True
        self.mock_ca_service.sign_certificate.side_effect = Exception("Autosign failed")

        # Should not raise HTTPException, just log error
        await self.controller.submit_certificate_request("node1", mock_request)
        self.mock_ca_service.sign_certificate.assert_called_once()

    async def test_update_certificate_status_signed(self):
        mock_request = MagicMock()
        mock_request.json = AsyncMock(return_value={"desired_state": "signed"})
        response = await self.controller.update_certificate_status(
            "node1", mock_request
        )
        self.assertEqual(response.status_code, 204)
        self.mock_ca_service.update_certificate_status.assert_called_once()

    async def test_update_certificate_status_revoked(self):
        mock_request = MagicMock()
        mock_request.json = AsyncMock(return_value={"desired_state": "revoked"})
        response = await self.controller.update_certificate_status(
            "node1", mock_request
        )
        self.assertEqual(response.status_code, 204)
        self.mock_ca_service.update_certificate_status.assert_called_once()

    async def test_update_certificate_status_invalid(self):
        mock_request = MagicMock()
        mock_request.json = AsyncMock(return_value={"desired_state": "invalid"})
        with self.assertRaises(HTTPException) as cm:
            await self.controller.update_certificate_status("node1", mock_request)
        self.assertEqual(cm.exception.status_code, 500)

    async def test_update_certificate_status_exception(self):
        mock_request = MagicMock()
        mock_request.json = AsyncMock(return_value={"desired_state": "signed"})
        self.mock_ca_service.update_certificate_status.side_effect = Exception("Failed")
        with self.assertRaises(HTTPException) as cm:
            await self.controller.update_certificate_status("node1", mock_request)
        self.assertEqual(cm.exception.status_code, 500)

    async def test_get_crl_exception(self):
        self.mock_ca_service.get_crl_chain.side_effect = Exception("Failed")
        with self.assertRaises(HTTPException) as cm:
            await self.controller.get_crl()
        self.assertEqual(cm.exception.status_code, 500)
